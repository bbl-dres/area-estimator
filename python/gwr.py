#!/usr/bin/env python3
"""
GWR Classification Lookup

Retrieves building classification data (GKAT, GKLAS, GBAUJ, GASTW) from the
Federal Register of Buildings and Dwellings (GWR) using EGID as the link key.

Two data access methods:
1. CSV bulk download from housing-stat.ch (for processing all of Switzerland)
2. swisstopo REST API for individual building lookups

The CSV method is preferred for batch processing. The API is a fallback for
small numbers of buildings or when no CSV is available.
"""

import sys
import json
import time
import urllib.request
import urllib.error
import pandas as pd


# Columns we need from the GWR CSV
GWR_COLUMNS = {
    'EGID': 'egid',
    'GKAT': 'gkat',
    'GKLAS': 'gklas',
    'GBAUJ': 'gbauj',
    'GASTW': 'gastw',
}


def load_gwr_from_csv(csv_path):
    """
    Load GWR building data from a bulk CSV download.

    The CSV can be downloaded from:
    https://www.housing-stat.ch/de/data/supply/public.html

    Args:
        csv_path: Path to the GWR CSV file

    Returns:
        DataFrame indexed by EGID with columns: gkat, gklas, gbauj, gastw
    """
    print(f"Loading GWR data from {csv_path}...")

    df = pd.read_csv(csv_path, sep=';', dtype=str, low_memory=False)

    # Find and rename the columns we need
    available = {}
    for src_col, dst_col in GWR_COLUMNS.items():
        if src_col in df.columns:
            available[src_col] = dst_col

    if 'EGID' not in available:
        raise ValueError(f"CSV does not contain EGID column. Found: {list(df.columns[:20])}")

    df = df[list(available.keys())].rename(columns=available)

    # Convert types
    for col in ['egid', 'gkat', 'gklas', 'gbauj', 'gastw']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df = df.dropna(subset=['egid'])
    df['egid'] = df['egid'].astype(int)
    df = df.set_index('egid')

    print(f"  Loaded {len(df)} buildings from GWR CSV")
    return df


def query_gwr_api(egid):
    """
    Query a single building's GWR data via the swisstopo REST API.

    Uses the ch.bfs.gebaeude_wohnungs_register layer:
    1. Search for the building by EGID
    2. Fetch full attributes by feature ID

    Args:
        egid: Federal building identifier (integer)

    Returns:
        Dict with keys: gkat, gklas, gbauj, gastw (or None values if not found)
    """
    result = {'gkat': None, 'gklas': None, 'gbauj': None, 'gastw': None}

    try:
        # Step 1: Search for building by EGID
        search_url = (
            f"https://api3.geo.admin.ch/rest/services/ech/SearchServer"
            f"?searchText={egid}&type=locations&origins=address"
        )
        req = urllib.request.Request(search_url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            search_data = json.loads(resp.read().decode('utf-8'))

        if not search_data.get('results'):
            return result

        # Find a result that links to the GWR layer
        feature_id = None
        for search_result in search_data['results']:
            attrs = search_result.get('attrs', {})
            for link in attrs.get('links', []):
                if 'ch.bfs.gebaeude_wohnungs_register' in link:
                    # Extract feature ID from the link
                    feature_id = link.split('/')[-1]
                    break
            if feature_id:
                break

        if not feature_id:
            return result

        # Step 2: Fetch full building attributes
        detail_url = (
            f"https://api3.geo.admin.ch/rest/services/ech/MapServer"
            f"/ch.bfs.gebaeude_wohnungs_register/{feature_id}"
        )
        req = urllib.request.Request(detail_url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            detail_data = json.loads(resp.read().decode('utf-8'))

        feature_attrs = detail_data.get('feature', {}).get('attributes', {})

        result['gkat'] = feature_attrs.get('gkat')
        result['gklas'] = feature_attrs.get('gklas')
        result['gbauj'] = feature_attrs.get('gbauj')
        result['gastw'] = feature_attrs.get('gastw')

    except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
        print(f"Warning: GWR API query failed for EGID {egid}: {e}", file=sys.stderr)

    return result


def enrich_with_gwr(buildings_df, gwr_csv_path=None):
    """
    Add GWR classification columns to a buildings DataFrame.

    If gwr_csv_path is provided, uses bulk CSV lookup.
    Otherwise, falls back to individual API queries for buildings with EGID.

    Args:
        buildings_df: DataFrame with 'egid' column
        gwr_csv_path: Optional path to GWR CSV file

    Returns:
        DataFrame with added columns: gkat, gklas, gbauj, gastw
    """
    df = buildings_df.copy()

    # Initialize columns
    for col in ['gkat', 'gklas', 'gbauj', 'gastw']:
        if col not in df.columns:
            df[col] = None

    if 'egid' not in df.columns:
        print("Warning: No EGID column — skipping GWR enrichment", file=sys.stderr)
        return df

    egids_available = df['egid'].notna()

    if gwr_csv_path:
        # Bulk CSV lookup via vectorized merge
        gwr_df = load_gwr_from_csv(gwr_csv_path)
        gwr_cols = [c for c in ['gkat', 'gklas', 'gbauj', 'gastw'] if c in gwr_df.columns]

        # Merge on EGID — only update rows that have an EGID
        df['_egid_int'] = df.loc[egids_available, 'egid'].astype(int)
        merged = df[['_egid_int']].merge(
            gwr_df[gwr_cols], left_on='_egid_int', right_index=True, how='left'
        )
        for col in gwr_cols:
            df.loc[merged.index, col] = merged[col].values
        df.drop(columns=['_egid_int'], inplace=True)

        matched = df.loc[egids_available, 'gkat'].notna().sum()
        print(f"  GWR CSV: matched {matched}/{egids_available.sum()} buildings")

    else:
        # API fallback — query individually with rate limiting
        api_count = egids_available.sum()
        if api_count > 100:
            print(f"Warning: Querying {api_count} buildings via API. "
                  f"Consider using --gwr-csv for bulk processing.", file=sys.stderr)

        matched = 0
        for i, idx in enumerate(df.index[egids_available]):
            egid = int(df.at[idx, 'egid'])
            print(f"  GWR API: querying {i + 1}/{api_count} (EGID {egid})",
                  end='\r', flush=True)
            result = query_gwr_api(egid)
            for col in ['gkat', 'gklas', 'gbauj', 'gastw']:
                if result[col] is not None:
                    df.at[idx, col] = result[col]
            if result['gkat'] is not None:
                matched += 1
            time.sleep(0.1)

        print(f"\n  GWR API: matched {matched}/{api_count} buildings")

    return df
