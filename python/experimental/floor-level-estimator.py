#!/usr/bin/env python 3
"""
Floor level estimator — experimental

Standalone exploration of floor-count estimation that adds a
construction-period (gbaup) factor on top of the GWR floor-height table.
Lives outside the active pipeline (../area.py is what main.py uses), but
kept here as reference because the gbaup factor captures real-world
intuition about how floor heights have shifted across construction eras
(representative pre-1919 buildings, post-war rationalisation, modern
Minergie comfort, etc.) — a refinement the documented Seiler & Seiler 2020
methodology doesn't model.

If the gbaup factors prove themselves on real data, the next step would be
to fold them into ../area.py as an optional refinement. Until then this
file is intentionally not imported anywhere.

Original description:
Calculates number of floors of a building using buidling volumes (generated from area footprints and swissBuildings3D measurements)
while using different floor heights for different building types. Building types (gkat and gklas) and construction periods (gbaup) are
obtained from the GWR classifictaion
"""


import requests
import pandas as pd
import json

# Floor height lookup table (pandas dataframe for better understanding)
# GH_EG_MIN: Ground floor min. height, GH_EG_MAX: Ground floor max. height
# GH_RG_MIN: Upper floor min. height, GH_RG_MAX: Upper floor max. height
lookup_table_height_raw = [
    {"GWR_GKAT": 1010, "TEXT": "Provisorische Unterkunft", "GH_EG_MIN": 2.7, "GH_EG_MAX": 3.3, "GH_RG_MIN": 2.7, "GH_RG_MAX": 3.3},
    {"GWR_GKAT": 1020, "TEXT": "Gebäude Einzelhaus", "GH_EG_MIN": 2.7, "GH_EG_MAX": 3.3, "GH_RG_MIN": 2.7, "GH_RG_MAX": 3.3},
    {"GWR_GKAT": 1021, "TEXT": "Einfamilienhaus", "GH_EG_MIN": 2.7, "GH_EG_MAX": 3.3, "GH_RG_MIN": 2.7, "GH_RG_MAX": 3.3},
    {"GWR_GKAT": 1025, "TEXT": "Mehrfamilienhaus", "GH_EG_MIN": 2.7, "GH_EG_MAX": 3.3, "GH_RG_MIN": 2.7, "GH_RG_MAX": 3.3},
    {"GWR_GKAT": 1030, "TEXT": "Wohngebäude mit Nebennutzung", "GH_EG_MIN": 2.7, "GH_EG_MAX": 3.3, "GH_RG_MIN": 2.7, "GH_RG_MAX": 3.3},
    {"GWR_GKAT": 1040, "TEXT": "Gebäude mit teilweiser Wohnnutzung", "GH_EG_MIN": 3.3, "GH_EG_MAX": 3.7, "GH_RG_MIN": 2.7, "GH_RG_MAX": 3.7},
    {"GWR_GKAT": 1060, "TEXT": "Gebäude ohne Wohnnutzung", "GH_EG_MIN": 3.3, "GH_EG_MAX": 5.0, "GH_RG_MIN": 3.3, "GH_RG_MAX": 5.0},
    {"GWR_GKAT": 1080, "TEXT": "Sonderbau", "GH_EG_MIN": 2.7, "GH_EG_MAX": 5.0, "GH_RG_MIN": 2.7, "GH_RG_MAX": 5.0},
    {"GWR_GKAT": 1110, "TEXT": "Gebäude mit einer Wohnung", "GH_EG_MIN": 2.7, "GH_EG_MAX": 3.3, "GH_RG_MIN": 2.7, "GH_RG_MAX": 3.3},
    {"GWR_GKAT": 1121, "TEXT": "Gebäude mit zwei Wohnungen", "GH_EG_MIN": 2.7, "GH_EG_MAX": 3.3, "GH_RG_MIN": 2.7, "GH_RG_MAX": 3.3},
    {"GWR_GKAT": 1122, "TEXT": "Gebäude mit drei oder mehr Wohnungen", "GH_EG_MIN": 2.7, "GH_EG_MAX": 3.3, "GH_RG_MIN": 2.7, "GH_RG_MAX": 3.3},
    {"GWR_GKAT": 1130, "TEXT": "Wohngebäude für Gemeinschaften", "GH_EG_MIN": 2.7, "GH_EG_MAX": 3.7, "GH_RG_MIN": 2.7, "GH_RG_MAX": 3.3},
    {"GWR_GKAT": 1211, "TEXT": "Hotelgebäude", "GH_EG_MIN": 2.7, "GH_EG_MAX": 3.7, "GH_RG_MIN": 2.7, "GH_RG_MAX": 3.7},
    {"GWR_GKAT": 1212, "TEXT": "Andere Gebäude für kurzfristige Beherbergung", "GH_EG_MIN": 2.7, "GH_EG_MAX": 3.3, "GH_RG_MIN": 2.7, "GH_RG_MAX": 3.3},
    {"GWR_GKAT": 1220, "TEXT": "Bürogebäude", "GH_EG_MIN": 3.4, "GH_EG_MAX": 4.2, "GH_RG_MIN": 3.4, "GH_RG_MAX": 4.2},
    {"GWR_GKAT": 1230, "TEXT": "Gross-und Einzelhandelsgebäude", "GH_EG_MIN": 3.4, "GH_EG_MAX": 5.0, "GH_RG_MIN": 3.4, "GH_RG_MAX": 5.0},
    {"GWR_GKAT": 1241, "TEXT": "Gebäude des Verkehrs- und Nachrichtenwesens ohne Garagen", "GH_EG_MIN": 3.4, "GH_EG_MAX": 3.7, "GH_RG_MIN": 3.4, "GH_RG_MAX": 3.7},
    {"GWR_GKAT": 1242, "TEXT": "Garagengebäude", "GH_EG_MIN": 2.7, "GH_EG_MAX": 3.3, "GH_RG_MIN": 2.7, "GH_RG_MAX": 3.3},
    {"GWR_GKAT": 1251, "TEXT": "Industriegebäude", "GH_EG_MIN": 4.0, "GH_EG_MAX": 7.0, "GH_RG_MIN": 4.0, "GH_RG_MAX": 7.0},
    {"GWR_GKAT": 1252, "TEXT": "Behälter, Silos und Lagergebäude", "GH_EG_MIN": 2.7, "GH_EG_MAX": 4.0, "GH_RG_MIN": 2.7, "GH_RG_MAX": 4.0},
    {"GWR_GKAT": 1261, "TEXT": "Gebäude für Kultur- und Freizeitzwecke", "GH_EG_MIN": 3.7, "GH_EG_MAX": 4.2, "GH_RG_MIN": 3.7, "GH_RG_MAX": 4.2},
    {"GWR_GKAT": 1262, "TEXT": "Museen und Bibliotheken", "GH_EG_MIN": 3.4, "GH_EG_MAX": 6.0, "GH_RG_MIN": 3.4, "GH_RG_MAX": 6.0},
    {"GWR_GKAT": 1263, "TEXT": "Schul- und Hochschulgebäude, Forschungseinrichtungen", "GH_EG_MIN": 3.0, "GH_EG_MAX": 3.7, "GH_RG_MIN": 3.0, "GH_RG_MAX": 3.7},
    {"GWR_GKAT": 1264, "TEXT": "Krankenhäuser und Facheinrichtungen des Gesundheitswesens", "GH_EG_MIN": 3.4, "GH_EG_MAX": 5.0, "GH_RG_MIN": 3.4, "GH_RG_MAX": 5.0},
    {"GWR_GKAT": 1265, "TEXT": "Sporthallen", "GH_EG_MIN": 3.0, "GH_EG_MAX": 6.0, "GH_RG_MIN": 3.0, "GH_RG_MAX": 6.0},
    {"GWR_GKAT": 1271, "TEXT": "Landwirtschaftliche Betriebsgebäude", "GH_EG_MIN": 2.7, "GH_EG_MAX": 4.0, "GH_RG_MIN": 2.7, "GH_RG_MAX": 4.0},
    {"GWR_GKAT": 1272, "TEXT": "Kirchen und sonstige Kultgebäude", "GH_EG_MIN": 3.0, "GH_EG_MAX": 6.0, "GH_RG_MIN": 3.0, "GH_RG_MAX": 6.0},
    {"GWR_GKAT": 1273, "TEXT": "Denkmäler oder unter Denkmalschutz stehende Bauwerke", "GH_EG_MIN": 2.7, "GH_EG_MAX": 3.3, "GH_RG_MIN": 2.7, "GH_RG_MAX": 3.3},
    {"GWR_GKAT": 1274, "TEXT": "Sonstige Hochbauten, anderweitig nicht genannt", "GH_EG_MIN": 2.7, "GH_EG_MAX": 3.3, "GH_RG_MIN": 2.7, "GH_RG_MAX": 3.3},
    {"GWR_GKAT": 9999, "TEXT": None, "GH_EG_MIN": 3.4, "GH_EG_MAX": 4.2, "GH_RG_MIN": None, "GH_RG_MAX": None},
    {"GWR_GKAT": None, "TEXT": "Nicht bekannt", "GH_EG_MIN": 2.7, "GH_EG_MAX": 5.0, "GH_RG_MIN": 2.7, "GH_RG_MAX": 5.0},
]

lookup_table_height = pd.DataFrame(lookup_table_height_raw)

# Construction Period lookup table (pandas dataframe for better understanding)
# Factors for different building styles (floor heights) according to construction period
# eg: ground floor factor, rg:upper floor factor
baup_lookup = [
    {"gbaup": 8011, "text": "vor 1919", "eg": 1.3, "rg": 1.25, "reasoning": "Repräsentative Altbauten, hohe Räume"},
    {"gbaup": 8012, "text": "1919-1945", "eg": 1.15, "rg": 1.10, "reasoning": "Noch großzügige Bauweise"},
    {"gbaup": 8013, "text": "1946-1960", "eg": 0.95, "rg": 0.95, "reasoning": "Nachkriegszeit, sparsame Bauweise"},
    {"gbaup": 8014, "text": "1961-1970", "eg": 0.90, "rg": 0.90, "reasoning": "Rationalisierte Bauweise"},
    {"gbaup": 8015, "text": "1971-1980", "eg": 0.90, "rg": 0.90, "reasoning": "Ölkrise, minimale Standards"},
    {"gbaup": 8016, "text": "1981-1985", "eg": 0.95, "rg": 0.95, "reasoning": "Leichte Verbesserung"},
    {"gbaup": 8017, "text": "1986-1990", "eg": 1.00, "rg": 1.00, "reasoning": "Standard-Referenz"},
    {"gbaup": 8018, "text": "1991-1995", "eg": 1.05, "rg": 1.05, "reasoning": "Höhere Komfortansprüche"},
    {"gbaup": 8019, "text": "1996-2000", "eg": 1.05, "rg": 1.05, "reasoning": "Weitere Verbesserungen"},
    {"gbaup": 8020, "text": "2001-2005", "eg": 1.10, "rg": 1.10, "reasoning": "Moderne Standards"},
    {"gbaup": 8021, "text": "2006-2010", "eg": 1.15, "rg": 1.12, "reasoning": "Energieeffizienz + Komfort"},
    {"gbaup": 8022, "text": "2011-2015", "eg": 1.15, "rg": 1.12, "reasoning": "Minergie-Standards"},
    {"gbaup": 8023, "text": "nach 2015", "eg": 1.20, "rg": 1.15, "reasoning": "Aktuelle hohe Standards"},
]

lookup_table_baup = pd.DataFrame(baup_lookup)

# Make sure that factors and categories are in right format
lookup_table_height["GWR_GKAT"] = lookup_table_height["GWR_GKAT"].astype(float)
lookup_table_baup["gbaup"] = lookup_table_baup["gbaup"].astype(float)

lookup_table_height = lookup_table_height.set_index("GWR_GKAT")
lookup_table_baup = lookup_table_baup.set_index("gbaup")

# Obtain building category (gkat), building class(gklas) and construction period (gbaup) from GWR database
# EGID-Number is used as identifier
FIND_URL = "https://api3.geo.admin.ch/rest/services/ech/MapServer/find"

EMPTY = {
    "gkat": None,
    "gklas": None,
    "gbaup": None
}

def fetch_egid_attributes(egid):
    # Filter missing egid-entries
    if pd.isna(egid):
        return EMPTY.copy()

    # Make sure egid-numbers are in right format
    try:
        egid_int = int(float(str(egid).strip()))
    except Exception:
        return EMPTY.copy()

    # Define parameters for API-request
    params = {
        "layer": "ch.bfs.gebaeude_wohnungs_register",
        "searchField": "egid",
        "searchText": str(egid_int),
        "contains": "false",
        "returnGeometry": "true",
        "geometryFormat": "geojson",
        "sr": "4326"
    }

    try:
        r = requests.get(FIND_URL, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return EMPTY.copy()

    results = data.get("results", [])
    if not results:
        return EMPTY.copy()

    feature = results[0]
    props = feature.get("properties", {}) or {}
    geom = feature.get("geometry", {}) or {}

    # Obtain factors for every egid-entry
    return {
        "gkat": props.get("gkat"),
        "gklas": props.get("gklas"),
        "gbaup": props.get("gbaup"),

    }


# Save obtained information from api-request in provided csv-file
def add_egid_attributes(df, egid_col, lookup):

    new_cols = (
        df[egid_col]
        .map(lookup)
        .apply(lambda x: x if isinstance(x, dict) else {})
        .apply(pd.Series)
    )

    return pd.concat([df.reset_index(drop=True),
                      new_cols.reset_index(drop=True)], axis=1)


# Calculate floor heights according to building category or class (gkat, gklas) and construction period (gbaup)
def get_floor_heights(GWR_GKAT, gbaup):

    GWR_GKAT = float(GWR_GKAT)

    base_eg_min = lookup_table_height.loc[GWR_GKAT, "GH_EG_MIN"]
    base_eg_max = lookup_table_height.loc[GWR_GKAT, "GH_EG_MAX"]
    base_rg_min = lookup_table_height.loc[GWR_GKAT, "GH_RG_MIN"]
    base_rg_max = lookup_table_height.loc[GWR_GKAT, "GH_RG_MAX"]

    # Default factor for ground floor and upper floor
    factor_eg = 1
    factor_rg = 1

    # Adjust factor according to construction period if gbaup is not NA
    if pd.notna(gbaup):
        gbaup = float(gbaup)

        if gbaup in lookup_table_baup.index:
            factor_eg = lookup_table_baup.loc[gbaup, "eg"]
            factor_rg = lookup_table_baup.loc[gbaup, "rg"]
    # Calculate effective floor height according to factors
    eg_min = base_eg_min * factor_eg
    eg_max = base_eg_max * factor_eg
    rg_min = base_rg_min * factor_rg
    rg_max = base_rg_max * factor_rg

    return eg_min, eg_max, rg_min, rg_max

# Estimate floor count according to factors, building categories and construction year (using factors from get_floor_heights)
def estimate_floors_detailed(height_mean_m, GWR_GKAT, gbaup):

    eg_min, eg_max, rg_min, rg_max = get_floor_heights(GWR_GKAT, gbaup)

    if pd.isna(rg_min) or pd.isna(rg_max) or rg_min == 0 or rg_max == 0:
        return None

    floors_conservative = max(1, 1 + (height_mean_m - eg_max) / rg_max)
    floors_optimistic = max(1, 1 + (height_mean_m - eg_min) / rg_min)

    floors_estimate = (floors_conservative + floors_optimistic) / 2

    return round(floors_estimate * 2) / 2

# Use input dats from csv file and calculate
def estimate_row(row):

    # Determine building class (gklas). If gklas is NA, building category (gkat) is used
    gkat_used = row["gklas"] if pd.notna(row["gklas"]) else row["gkat"]

    if pd.isna(row["height_mean_m"]) or pd.isna(gkat_used):
        return pd.Series({
            "eg_min_adj": None,
            "eg_max_adj": None,
            "rg_min_adj": None,
            "rg_max_adj": None,
            "floors_estimated": None
        })

    eg_min, eg_max, rg_min, rg_max = get_floor_heights(gkat_used, row["gbaup"])

    floors = estimate_floors_detailed(
        row["height_mean_m"],
        gkat_used,
        row["gbaup"]
    )

    return pd.Series({
        "eg_min_adj": eg_min,
        "eg_max_adj": eg_max,
        "rg_min_adj": rg_min,
        "rg_max_adj": rg_max,
        "floors_estimated": floors
    })