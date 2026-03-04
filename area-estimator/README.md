# Swiss Building Floor Area Estimator

A tool for estimating building gross floor areas (Geschossflächen) using LIDAR-derived volumes, building footprints, and GWR building classifications.

## Table of Contents

- [Overview](#overview)
- [Quick Start](#quick-start)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Command-Line Reference](#command-line-reference)
- [Methodology](#methodology)
- [Data Sources](#data-sources)
- [GWR Building Classification](#gwr-building-classification)
- [Floor Height Assumptions](#floor-height-assumptions)
- [Output Format](#output-format)
- [Accuracy & Limitations](#accuracy--limitations)
- [References](#references)
- [Version History](#version-history)
- [License](#license)
- [Contributing](#contributing)
- [Acknowledgments](#acknowledgments)

---

## Overview

This estimator calculates approximate gross floor areas for Swiss buildings by combining:

- **Building footprints** from cadastral data (PostGIS/swissBUILDINGS3D)
- **Building volumes** from LIDAR point clouds (swissSURFACE3D / swissBUILDINGS3D 3.0)
- **Building classifications** from GWR (Gebäude- und Wohnungsregister)

The methodology is based on the Canton Zurich approach documented in ["Modell zur Berechnung der bestehenden Geschossfläche pro Grundstück im Kanton Zürich"](https://are.zh.ch/) (SEILER & SEILER GmbH, December 2020).

**Prerequisites:** This tool requires buildings to have volume data calculated by the [Volume Estimator](../volume-estimator/).

---

## Quick Start

### Estimate floor areas for 10 buildings (CSV output)

```bash
python python/main.py \
    "postgresql://user:password@host:5432/database" \
    --limit 10 \
    -o results.csv
```

### Update database with floor area estimates

```bash
python python/main.py \
    "postgresql://user:password@host:5432/database" \
    --limit 100 \
    --write-to-db
```

### Process specific buildings

```bash
python python/main.py \
    "postgresql://user:password@host:5432/database" \
    --building-ids 6767 8921 12345 \
    -o specific_buildings.csv
```

---

## Requirements

### Python Dependencies

```bash
pip install psycopg2-binary pandas numpy
```

### Database Requirements

Buildings must have the following data populated (typically by the [Volume Estimator](../volume-estimator/)):

| Column | Required | Description |
|--------|----------|-------------|
| `area_footprint_m2` | Yes | Building footprint area |
| `volume_above_ground_m3` | Yes | LIDAR-derived building volume |
| `height_mean_m` | Optional | Mean building height (calculated from volume/footprint if missing) |
| `category` | Recommended | GWR GKAT code |
| `class` | Recommended | GWR GKLAS code |

---

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/davras5/OpenBuildings.git
cd OpenBuildings/tools/area-estimator
```

### 2. Install Dependencies

```bash
pip install psycopg2-binary pandas numpy
```

### 3. Ensure Volume Data Exists

Run the [Volume Estimator](../volume-estimator/) first to populate `volume_above_ground_m3` and `area_footprint_m2` for buildings.

---

## Usage

### Export to CSV Only

```bash
python python/main.py \
    "postgresql://user:password@host:5432/database" \
    --limit 100 \
    -o output.csv
```

### Update Database Only

```bash
python python/main.py \
    "postgresql://user:password@host:5432/database" \
    --limit 100 \
    --write-to-db
```

### Both CSV and Database

```bash
python python/main.py \
    "postgresql://user:password@host:5432/database" \
    --limit 100 \
    -o output.csv \
    --write-to-db
```

### Process Buildings in Bounding Box

```bash
python python/main.py \
    "postgresql://user:password@host:5432/database" \
    --bbox 7.5 47.5 8.0 48.0 \
    --write-to-db
```

---

## Command-Line Reference

### Required Arguments

| Argument | Description |
|----------|-------------|
| `db_connection` | PostgreSQL connection string<br>Format: `postgresql://user:password@host:port/database` |

### Optional Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `-o, --output` | string | - | CSV output file path |
| `--write-to-db` | flag | false | Write results to database |
| `-l, --limit` | int | - | Limit number of buildings to process |
| `--building-ids` | int list | - | Process specific building IDs (space-separated) |
| `-b, --bbox` | 4 floats | - | Bounding box in WGS84: `MINLON MINLAT MAXLON MAXLAT` |
| `--table-name` | string | `public.buildings` | Database table name |
| `--include-missing-volume` | flag | false | Include buildings without volume data |

**Important:** You must specify at least one of `--output` or `--write-to-db`.

---

## Methodology

### Core Calculation

1. **Calculate mean building height**
   ```
   mean_height = building_volume / footprint_area
   ```

2. **Derive floor count** using building-type-specific floor heights
   ```
   floor_count = mean_height / floor_height
   ```

3. **Calculate gross floor area**
   ```
   gross_floor_area = footprint_area × floor_count
   ```

### Why LIDAR Volumes Instead of GWR Floor Counts?

The GWR provides floor counts via the `GASTW` attribute ("Anzahl Geschosse"), but this field has significant limitations:

- Ambiguity about inclusion of basement/underground floors
- Inconsistent data quality across municipalities
- Often missing or outdated values

Using LIDAR-derived volumes provides a more consistent and verifiable approach, as the volume data is measured directly from the building geometry.

## Data Sources

| Data | Source | Description |
|------|--------|-------------|
| Building footprints | swissBUILDINGS3D / Cadastral survey | 2D polygon geometries |
| Building volumes | swissSURFACE3D / swissBUILDINGS3D 3.0 | LIDAR-derived 3D volumes |
| Building classification | GWR (Merkmalskatalog v4.2/4.3) | GKAT and GKLAS codes |
| Roof type | GWR or swissBUILDINGS3D | For attic estimation |

## GWR Building Classification

The GWR uses a hierarchical classification system with two key attributes:

- **GKAT** (Gebäudekategorie): Broad building category
- **GKLAS** (Gebäudeklasse): Detailed building class within category

### GKAT Codes (Building Categories)

| Code | Description (DE) | Description (EN) |
|------|------------------|------------------|
| 1010 | Provisorische Unterkunft | Provisional accommodation |
| 1020 | Gebäude mit ausschliesslicher Wohnnutzung | Residential buildings only |
| 1030 | Wohngebäude mit Nebennutzung | Residential with secondary use |
| 1040 | Gebäude mit teilweiser Wohnnutzung | Partial residential use |
| 1060 | Gebäude ohne Wohnnutzung | Non-residential buildings |
| 1080 | Sonderbauten | Special structures |

### GKLAS Codes (Building Classes)

The GKLAS provides more detailed classification, particularly for buildings in GKAT 1020, 1030, and 1040:

#### Residential (within GKAT 1020)

| Code | Description (DE) | Description (EN) |
|------|------------------|------------------|
| 1110 | Gebäude mit einer Wohnung | Single-dwelling building (EFH) |
| 1121 | Gebäude mit zwei Wohnungen | Two-dwelling building |
| 1122 | Gebäude mit drei oder mehr Wohnungen | Multi-dwelling building (MFH) |
| 1130 | Wohngebäude für Gemeinschaften | Communal housing |

#### Hotels and Tourism (within GKAT 1040)

| Code | Description (DE) | Description (EN) |
|------|------------------|------------------|
| 1211 | Hotelgebäude | Hotel buildings |
| 1212 | Andere Gebäude für kurzfristige Beherbergung | Other short-term accommodation |

#### Commercial and Industrial (within GKAT 1060)

| Code | Description (DE) | Description (EN) |
|------|------------------|------------------|
| 1220 | Bürogebäude | Office buildings |
| 1230 | Gross- und Einzelhandelsgebäude | Retail buildings |
| 1231 | Restaurants und Bars | Restaurants and bars |
| 1241 | Bahnhöfe, Terminals | Stations, terminals |
| 1242 | Parkhäuser | Parking structures |
| 1251 | Industriegebäude | Industrial buildings |
| 1252 | Behälter, Silos, Lagergebäude | Containers, silos, warehouses |
| 1261 | Gebäude für Kultur und Freizeit | Culture and leisure buildings |
| 1262 | Museen und Bibliotheken | Museums and libraries |
| 1263 | Schulen und Hochschulen | Schools and universities |
| 1264 | Spitäler und Kliniken | Hospitals and clinics |
| 1265 | Sporthallen | Sports halls |
| 1271 | Landwirtschaftliche Betriebsgebäude | Agricultural buildings |
| 1272 | Kirchen und Sakralbauten | Churches and religious buildings |
| 1273 | Denkmäler und unter Schutz stehende Gebäude | Monuments and protected buildings |
| 1274 | Andere Hochbauten | Other buildings |

## Floor Height Assumptions

Floor heights vary by building type. The estimator uses differentiated heights for:
- **EG** (Erdgeschoss): Ground floor
- **RG** (Regelgeschoss): Regular/upper floors

To account for uncertainty, the model provides **minimum** and **maximum** estimates based on floor height ranges.

### Floor Height Lookup Table

Based on Canton Zurich methodology (Tab. 14, Modelldokumentation December 2020):

| Code | Building Type | Schema | EG Min | EG Max | RG Min | RG Max |
|------|---------------|--------|--------|--------|--------|--------|
| 1010 | Provisorische Unterkunft | GKAT | 2.70 | 3.30 | 2.70 | 3.30 |
| 1110 | Einfamilienhaus | GKLAS | 2.70 | 3.30 | 2.70 | 3.30 |
| 1121 | Zweifamilienhaus | GKLAS | 2.70 | 3.30 | 2.70 | 3.30 |
| 1122 | Mehrfamilienhaus | GKLAS | 2.70 | 3.30 | 2.70 | 3.30 |
| 1130 | Wohngebäude für Gemeinschaften | GKLAS | 2.70 | 3.30 | 2.70 | 3.30 |
| 1030 | Wohngebäude mit Nebennutzung | GKAT | 2.70 | 3.30 | 2.70 | 3.30 |
| 1040 | Geb. mit teilweiser Wohnnutzung | GKAT | 3.30 | 3.70 | 2.70 | 3.70 |
| 1211 | Hotelgebäude | GKLAS | 3.30 | 3.70 | 3.00 | 3.50 |
| 1212 | Kurzfristige Beherbergung | GKLAS | 3.00 | 3.50 | 3.00 | 3.50 |
| 1220 | Bürogebäude | GKLAS | 3.40 | 4.20 | 3.40 | 4.20 |
| 1230 | Gross- und Einzelhandel | GKLAS | 3.40 | 5.00 | 3.40 | 5.00 |
| 1231 | Restaurants und Bars | GKLAS | 3.30 | 4.00 | 3.30 | 4.00 |
| 1241 | Bahnhöfe, Terminals | GKLAS | 4.00 | 6.00 | 4.00 | 6.00 |
| 1242 | Parkhäuser | GKLAS | 2.80 | 3.20 | 2.80 | 3.20 |
| 1251 | Industriegebäude | GKLAS | 4.00 | 7.00 | 4.00 | 7.00 |
| 1252 | Behälter, Silos, Lager | GKLAS | 3.50 | 6.00 | 3.50 | 6.00 |
| 1261 | Kultur und Freizeit | GKLAS | 3.50 | 5.00 | 3.50 | 5.00 |
| 1262 | Museen und Bibliotheken | GKLAS | 3.50 | 5.00 | 3.50 | 5.00 |
| 1263 | Schulen und Hochschulen | GKLAS | 3.30 | 4.00 | 3.30 | 4.00 |
| 1264 | Spitäler und Kliniken | GKLAS | 3.30 | 4.00 | 3.30 | 4.00 |
| 1265 | Sporthallen | GKLAS | 3.00 | 6.00 | 3.00 | 6.00 |
| 1271 | Landwirtschaft. Betriebsgeb. | GKLAS | 3.50 | 5.00 | 3.50 | 5.00 |
| 1272 | Kirchen und Sakralbauten | GKLAS | 3.00 | 6.00 | 3.00 | 6.00 |
| 1273 | Denkmäler, geschützte Geb. | GKLAS | 3.00 | 4.00 | 3.00 | 4.00 |
| 1274 | Andere Hochbauten | GKLAS | 3.00 | 4.00 | 3.00 | 4.00 |
| 1060 | Gebäude ohne Wohnnutzung | GKAT | 3.30 | 5.00 | 3.00 | 5.00 |
| 1080 | Sonderbauten | GKAT | 3.00 | 4.00 | 3.00 | 4.00 |
| — | Fallback (unknown) | — | 2.70 | 3.30 | 2.70 | 3.30 |

**Note:** Some building types (marked with H16 in original documentation) have heterogeneous uses with wide height ranges. These include sports halls (1265), churches (1272), and industrial buildings (1251).

### Lookup Priority

When determining floor height:

1. First, check if a specific **GKLAS** code exists in the lookup table
2. If not found, fall back to the **GKAT** category
3. If neither is found, use the default residential values (2.70–3.30m)

## Output Format

### Database Output

When using `--write-to-db`, the following columns are updated:

| Column | Type | Description |
|--------|------|-------------|
| `area_floor_total_m2` | numeric | Total gross floor area estimate |
| `area_floor_above_ground_m2` | numeric | Above-ground floor area (same as total) |
| `area_accuracy` | text | Accuracy level: `high`, `medium`, or `low` |
| `floors_total` | integer | Estimated total floor count |
| `floors_above` | integer | Above-ground floors (same as total) |
| `floors_accuracy` | text | Accuracy level for floor count |

### CSV Output

When using `--output`, additional debug columns are included:

| Column | Description |
|--------|-------------|
| `id` | Building ID |
| `area_floor_total_m2` | Total gross floor area estimate |
| `area_floor_above_ground_m2` | Above-ground floor area |
| `area_accuracy` | Accuracy level |
| `floors_total` | Estimated floor count |
| `floors_above` | Above-ground floors |
| `floors_accuracy` | Accuracy level |
| `status` | Processing status (`success` or `error`) |
| `error_message` | Error description if failed |
| `_height_mean_m` | Mean building height used |
| `_floor_height_used` | Floor height assumption applied |
| `_schema_used` | Classification schema (`GKLAS`, `GKAT`, or `DEFAULT`) |
| `_building_type` | Building type description |

### Accuracy Levels

| Level | Expected Accuracy | Building Types |
|-------|-------------------|----------------|
| `high` | ±10–15% | Residential buildings (GKAT 1020, GKLAS 11xx) |
| `medium` | ±15–25% | Commercial, office, schools, hospitals |
| `low` | ±25–40% | Industrial, special use, or missing classification |

## Accuracy & Limitations

### Expected Accuracy

Based on validation against reference data (Canton Zurich study), the estimator achieves:

- **±10–15%** for residential buildings (GKAT 1020)
- **±15–25%** for commercial/office buildings
- **±25–40%** for industrial and special-use buildings

### Known Limitations

1. **Complex building shapes**: Buildings with irregular footprints or multiple wings may have inaccurate volume calculations

2. **Mixed-use buildings**: Buildings with multiple uses (GKAT 1040) have higher uncertainty due to varying floor heights within the same structure

3. **Historical buildings**: Older buildings may have non-standard floor heights not captured in the lookup table

4. **Basement floors**: Underground floors are generally not included in LIDAR volume calculations

5. **Recent construction**: New buildings may not yet have accurate GWR classifications

## References

- **GWR Merkmalskatalog v4.2** (2022): [housing-stat.ch](https://www.housing-stat.ch/files/881-2200.pdf)
- **Canton Zurich Methodology** (December 2020): "Modell zur Berechnung der bestehenden Geschossfläche pro Grundstück im Kanton Zürich" — SEILER & SEILER GmbH for Amt für Raumentwicklung
- **swissBUILDINGS3D 3.0**: [swisstopo.ch](https://www.swisstopo.ch/swissbuildings3d)
- **swissSURFACE3D**: [swisstopo.ch](https://www.swisstopo.ch/swisssurface3d)

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2024-XX | Initial release |
| 1.1 | 2025-01 | Updated to GWR v4.2/4.3 codes; removed wall thickness deduction |

## License

MIT License — See LICENSE file for details.

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

**Areas for improvement:**
- Validation against additional reference datasets
- Support for additional building classification systems
- Integration with other cantonal methodologies

---

## Acknowledgments

- Canton Zurich / Amt für Raumentwicklung for the methodology documentation
- SEILER & SEILER GmbH for the original study
- Federal Office of Topography swisstopo for elevation and building data
- Swiss Federal Statistical Office for GWR data and documentation

---

*This tool is provided for estimation purposes only. For official floor area calculations, consult the relevant cantonal authorities or certified surveyors.*
