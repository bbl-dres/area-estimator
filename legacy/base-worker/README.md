# Base Worker

The main worker for updating and aggregating official Swiss cadastral survey data (Amtliche Vermessung) for buildings and parcels.

> Documentation in progress

## Table of Contents

- [Overview](#overview)
- [Data Sources](#data-sources)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Output Format](#output-format)
- [Accuracy & Limitations](#accuracy--limitations)
- [References](#references)
- [Version History](#version-history)
- [License](#license)
- [Contributing](#contributing)

---

## Overview

This tool aggregates data from official Swiss cadastral surveys and the Federal Register of Buildings and Dwellings (GWR) to create a unified dataset of buildings and parcels. It combines:

- **Building footprints** (polygons) from Amtliche Vermessung
- **Parcel geometries** (polygons) from Amtliche Vermessung
- **Landcover information** (polygons) from Amtliche Vermessung
- **Building attributes** from GWR using EGID identifiers

---

## Data Sources

### Amtliche Vermessung (Official Cadastral Survey)

Source: [geodienste.ch/services/av](https://www.geodienste.ch/services/av)

| Layer | Content | Key Identifiers |
|-------|---------|-----------------|
| **Bodenbedeckung** | Land cover including building footprints (`BBArt = Gebaeude`) | EGID |
| **Liegenschaften** | Parcel geometries | EGRID |

Data model documentation:
- [Cadastre Manual - Data Model DM.01-AV-CH](https://www.cadastre-manual.admin.ch/de/datenmodell-der-amtlichen-vermessung-dm01-av-ch)
- [INTERLIS Model Definition](https://models.geo.admin.ch/V_D/DM.01-AV-CH_LV95_24d_ili1.ili)
- [models.geo.admin.ch/V_D](https://models.geo.admin.ch/V_D/)

### GWR (Gebäude- und Wohnungsregister)

Source: [housing-stat.ch](https://www.housing-stat.ch/de/index.html)

Building attributes are retrieved using EGID identifiers from the official AV building polygons.

- [GWR Documentation (v4.3)](https://www.housing-stat.ch/catalog/en/4.3/final)

---

## Requirements

- FME Desktop (2020 or newer recommended)

---

## Installation

1. Open the FME workbench file in FME Desktop: `fme/Base Worker FME.fmw`
2. Configure input/output parameters as needed
3. Run the workbench

---

## Usage

*Documentation pending.*

---

## Output Format

*Documentation pending.*

---

## Accuracy & Limitations

*Documentation pending.*

---

## References

- [geodienste.ch - Amtliche Vermessung](https://www.geodienste.ch/services/av)
- [housing-stat.ch - GWR](https://www.housing-stat.ch/de/index.html)
- [GWR Catalog v4.3](https://www.housing-stat.ch/catalog/en/4.3/final)
- [Cadastre Manual - DM.01-AV-CH](https://www.cadastre-manual.admin.ch/de/datenmodell-der-amtlichen-vermessung-dm01-av-ch)
- [INTERLIS Model Definition](https://models.geo.admin.ch/V_D/DM.01-AV-CH_LV95_24d_ili1.ili)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | TBD | Initial release |

---

## License

MIT License — See LICENSE file for details.

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
