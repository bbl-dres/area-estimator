# Swiss floor height assumptions: validation across GWR building classes

**The floor height ranges in the Seiler & Seiler / ARE Canton Zurich table are broadly defensible but rest on professional estimation rather than large-scale empirical measurement.** No single Swiss source publishes a comprehensive table of measured Geschosshöhen (floor-to-floor heights) disaggregated by GWR building class. Instead, the assumed values derive from a convergence of regulatory minimums (cantonal building codes, ArGV4 workplace regulations), energy-norm standard heights (SIA 2024, SIA 380/1), and construction practice. The residential ranges are well-anchored in regulation; the non-residential ranges are plausible but carry higher uncertainty due to wide real-world variability. Notably, the GWR database itself contains no floor height attribute — making these assumptions critical infrastructure for any volume-to-area conversion in Swiss spatial planning.

---

## SIA norms define the measuring framework but prescribe no heights

The Swiss normative ecosystem separates *how* floor heights are measured from *what* they should be. **SIA 416** (2003) defines the calculation of building volume (Gebäudevolumen, GV) and floor area (Geschossfläche, GF), establishing that GV = GF × Geschosshöhe, where Geschosshöhe is measured from finished floor surface to finished floor surface (Oberkante fertiger Boden to Oberkante fertiger Boden). However, SIA 416 prescribes no specific heights for any building type. The **IVHB** (Interkantonale Vereinbarung über die Harmonisierung der Baubegriffe, 2010) harmonizes the definition of Geschosshöhe and lichte Höhe across cantons using the same measurement convention, but likewise sets no dimensional values.

**SIA 2024** (2021 edition, replacing 2015) is the closest thing to a normative floor-height table. It provides standard clear room heights (*lichte Raumhöhe*, hR) for **45 room types** used in energy and building-technology calculations. These are the approximate standard values with the corresponding Geschosshöhe (adding ~0.30m for typical slab construction):

| Room type (SIA 2024) | Lichte Raumhöhe (m) | ≈ Geschosshöhe (m) |
|---|---|---|
| Wohnen MFH / EFH | ~2.5 | ~2.8 |
| Einzel-/Gruppenbüro | ~2.7 | ~3.0 |
| Grossraumbüro | 2.7–3.0 | 3.0–3.3 |
| Schulzimmer | ~3.0 | ~3.3 |
| Verkauf Lebensmittel | ~3.5 | ~3.8 |
| Verkauf Fachgeschäft | ~3.0 | ~3.3 |
| Hotelzimmer | ~2.5 | ~2.8 |
| Restaurant | ~3.0 | ~3.3 |
| Spital Bettenzimmer | ~2.7 | ~3.0 |
| Lager | 3.0–6.0 | 3.3–6.3 |
| Industrie/Produktion | 3.5–5.0 | 3.8–5.3 |

These SIA 2024 values are *standard assumptions* for early-phase energy calculations, not empirically measured averages. The SIA harmonization report (2019) explicitly acknowledges that "neither the standard values from SIA 380/1 nor those from SIA 2024 are based on comprehensive statistical measurement data." **SIA 380/1** uses **3.0 m** as its correction threshold — buildings with floor-to-floor heights ≥3.0 m receive an energy-calculation correction factor, effectively treating heights below 3.0 m as the residential norm.

These SIA 2024 values generally align with the lower half of the Seiler & Seiler ranges for residential types (2.70–3.30m is consistent with ~2.8m typical) but suggest the table's upper bounds for offices (3.40–4.20m) and retail (3.40–5.00m) appropriately capture the range of practical variation beyond the SIA standard values.

---

## Regulatory minimums anchor the lower bounds convincingly

Swiss building regulations operate at three levels — federal workplace law, cantonal building codes, and municipal zoning ordinances — each contributing floor-height constraints.

**Federal workplace regulations (ArGV4, Art. 5)** set legally binding minimum clear room heights for industrial workplaces, scaled by room area. These are among the most important anchoring data points for non-residential floor heights:

| Room floor area | Min. lichte Höhe (m) | ≈ Min. Geschosshöhe (m) |
|---|---|---|
| ≤ 100 m² | **2.75** | ~3.05 |
| ≤ 250 m² | **3.00** | ~3.30 |
| ≤ 400 m² | **3.50** | ~3.80 |
| > 400 m² | **4.00** | ~4.30 |

Reductions of one step are permitted (but never below 2.50m clear height) for sedentary, low-exertion workplaces with adequate ventilation. These ArGV4 minimums directly validate the lower bounds for offices (3.40m is consistent with medium-sized office rooms ≥250 m² after adding HVAC installations), schools (~3.30m for classrooms of 50–100 m²), and industrial buildings (4.00m+ for large production halls).

**Cantonal residential minimums** have largely converged on **2.40 m lichte Höhe** (Zurich PBG §304, Aargau BauV §36a, Zug PBG §6, Bern BauV Art. 67), with Canton Luzern at **2.30 m**. Adding 0.25–0.30m slab thickness yields minimum Geschosshöhen of **~2.65–2.70m**, which aligns precisely with the **lower bound of 2.70m** in the residential building classes (1010, 1030, 1110, 1121, 1122, 1130). In practice, modern Swiss residential construction typically provides 2.50–2.60m lichte Höhe, producing floor-to-floor heights of **2.80–3.00m**.

**Cantonal maximum Geschosshöhe** regulations also corroborate the upper bounds. Canton Aargau BauV §22 sets a subsidiary maximum average Geschosshöhe of **3.20m** for Vollgeschosse in residential zones. Canton Luzern PBG §139 specifies **3.0m** as the standard average Geschosshöhe for Ausnützungsziffer calculations. The residential upper bound of **3.30m** in the table slightly exceeds these cantonal defaults, which is appropriate since some municipalities and older buildings permit or have higher ceilings (Altbau buildings routinely have lichte Höhen of 3.0–3.5m).

For commercial ground floors, municipal BZOs (Bau- und Zonenordnungen) commonly allow Geschosshöhen up to **4.50m**, supporting the differentiated ground-floor values in the table for mixed-use and non-residential categories (e.g., 1040 partially residential: GF 3.30–3.70m).

---

## The GWR contains no floor height data — making these assumptions indispensable

The Swiss GWR (Gebäude- und Wohnungsregister, version 4.2, BFS 2022) contains **no Gebäudehöhe or Geschosshöhe attribute**. The database records GAREA (footprint area), GVOL (building volume per SIA 416), and GASTW (number of above-ground storeys), but not building height or floor height. This stands in contrast to the Austrian AGWR, which explicitly requires "durchschnittliche Geschoßhöhe" per building.

A theoretical derivation via h_floor ≈ GVOL / (GAREA × GASTW) is possible but imprecise, because GVOL per SIA 416 includes the full building envelope (pitched roof volume, building shell), GAREA is the ground-floor footprint only (ignoring setbacks), and GASTW counting rules exclude certain floors. **No published BFS or GWR statistics cross-tabulate any height metric with building class (GKAT/GKLAS).** The BFS does publish buildings by number of storeys and category, but this is storey *count*, not storey *height*.

This data gap means the Seiler & Seiler floor height assumptions are not merely advisory — they are essential conversion factors for any Swiss spatial analysis that derives floor area from building volume or vice versa.

---

## Academic and energy-modeling studies reveal a consistent but shallow evidence base

No large-scale empirical measurement study of Swiss floor heights was identified in the published literature. The evidence base consists primarily of modeling assumptions and small samples.

**The Seiler & Seiler / ARE Canton Zurich methodology** (December 2020/2021) is the most sophisticated approach found. The model documentation (90 pages) distinguishes three height parameters — GHEG (ground floor), GHRG (standard upper floor), and GHDG (attic) — differentiated by building use type (Wohnen, Büro/Dienstleistung, Industrie/Gewerbe) and mapped to zoning categories. The model uses LiDAR-derived building heights combined with cadastral footprints and GWR floor counts, with empirically calibrated conversion factors (Section 6.3 of the documentation describes "Empirische Herleitung von Umrechnungsfaktoren"). The specific numeric values are embedded in figures (Abb. 37–39) of the PDF, which is the definitive source document for the table under validation.

**CESAR (Empa)** and **TEP Energy's Gebäudeparkmodell** both derive floor height implicitly from building height divided by number of floors, rather than assuming fixed values. The **EPFL DISCS database** (2025) documents 102 Swiss buildings with detailed structural data that likely includes measured floor heights, but the per-building statistics are not published in aggregate form. The **SwissRes model** (Drouilles et al.) is based on **25,000+ GEAK Plus certificates** that contain measured floor heights — potentially the richest empirical dataset on Swiss building floor heights — but these statistics are not publicly disaggregated.

The **EUBUCCO database** (v0.1, 2023) covers 202+ million European buildings including Switzerland, with building height available for ~74% of records. Combined with GWR floor counts via EGID, this could enable empirical floor-height-by-building-type analysis at scale, but no such published analysis exists.

---

## 3D building models now enable empirical validation for the first time

**swissBUILDINGS3D 3.0 Beta** (swisstopo, November 2025) represents a breakthrough: for the first time, building heights with **±30–50 cm accuracy** are available per EGID for 16 cantons. With EGID integration, these heights can be joined to GWR data to compute average floor-to-floor heights by building class. However, critical methodological challenges remain. Academic research (Roy et al., 2023, TU Delft) demonstrates that dividing building height by floor count using a fixed 3.0m assumption achieves only **~70% accuracy** for residential buildings ≤5 floors. Swiss buildings with steep pitched roofs are particularly problematic, as ridge height includes uninhabitable roof volume. **Eave height (Traufhöhe)** is a better proxy, but swissBUILDINGS3D attributes focus on maximum roof height.

The Munich Building Floor Dataset study (2025) explicitly warns that "assumptions of using a fixed floor height to convert building height to floor number are invalid due to variability in ceiling heights, roof structures, and construction practices." The **M4Heights benchmark** (2025, Scientific Data) includes Switzerland as a study country and confirms that "urban areas in Switzerland exhibit higher densities and wider ranges of building heights" than comparable European cities.

---

## Confidence assessment by building class

The following table synthesizes all sources to assess confidence in each floor height range. "High" confidence means multiple independent sources corroborate the range. "Medium" means the range is plausible from regulation and practice but lacks direct empirical validation. "Low" means significant uncertainty exists.

| Code | Building type | GF (m) | UF (m) | Confidence | Key evidence | Notes |
|---|---|---|---|---|---|---|
| 1010 | Provisional shelter | 2.70–3.30 | 2.70–3.30 | **Medium** | Residential defaults applied | Minimal data; reasonable proxy |
| 1030 | Residential w/ secondary use | 2.70–3.30 | 2.70–3.30 | **High** | Cantonal min. 2.40m lichte → ~2.70m GH; SIA 2024 ~2.8m; AG max avg 3.20m | Well-anchored in regulation |
| 1040 | Partially residential | 3.30–3.70 (GF) | 2.70–3.70 (UF) | **Medium-High** | GF commercial use → ArGV4 / municipal BZO allows ≤4.50m; UF residential floors | GF/UF differentiation well-justified |
| 1060 | Non-residential | 3.30–5.00 | 3.00–5.00 | **Medium** | ArGV4 min. 2.75–4.00m lichte by room size; wide variation by actual use | Very broad category; range necessarily wide |
| 1080 | Special-purpose | 3.00–4.00 | 3.00–4.00 | **Low-Medium** | Heterogeneous category; no specific data | Reasonable central estimate |
| 1110 | Single-family house | 2.70–3.30 | 2.70–3.30 | **High** | Cantonal minimums + SIA 2024 + typical practice ~2.8–3.0m | Very well-established range |
| 1121 | Two-family house | 2.70–3.30 | 2.70–3.30 | **High** | Same as EFH | Identical construction practice |
| 1122 | Multi-family house | 2.70–3.30 | 2.70–3.30 | **High** | Cantonal min + SIA 2024 Wohnen MFH + AG max 3.20m + LU PBG 3.0m standard | Best-supported category |
| 1130 | Community residential | 2.70–3.30 | 2.70–3.30 | **Medium-High** | Similar to residential; SIA 2024 Hotel/Heim subcategory | May have slightly higher ceilings for institutional use |
| 1211 | Hotel | 3.30–3.70 (GF) | 3.00–3.50 (UF) | **Medium** | SIA 2024 Hotelzimmer hR ~2.5m → GH ~2.8m; GF lobby/restaurant higher | **UF upper bound may be high** — typical hotel GH closer to 2.8–3.2m; GF plausible with lobby |
| 1212 | Short-term accommodation | 3.00–3.50 | 3.00–3.50 | **Medium** | Similar to hotel UF; less data available | Reasonable proxy |
| 1220 | Office building | 3.40–4.20 | 3.40–4.20 | **Medium-High** | ArGV4 min. 3.00m lichte for ≤250m² → ~3.30m GH; with HVAC 3.40–3.80m typical; SIA 2024 Büro ~3.0m GH | Modern offices with raised floors and suspended ceilings commonly 3.5–4.0m; **lower bound well-supported** |
| 1230 | Wholesale and retail | 3.40–5.00 | 3.40–5.00 | **Medium** | ArGV4 min. 3.50–4.00m for large retail (>250m²); SIA 2024 Lebensmittel ~3.8m GH | Wide range appropriate given hypermarkets vs. small shops |
| 1231 | Restaurants and bars | 3.30–4.00 | 3.30–4.00 | **Medium** | SIA 2024 Restaurant hR ~3.0m → GH ~3.3m; ArGV4 for medium rooms | Well-aligned with SIA 2024 |
| 1241 | Stations and terminals | 4.00–6.00 | 4.00–6.00 | **Low-Medium** | Very limited data; large public spaces require high ceilings | Plausible but unvalidated |
| 1242 | Parking garages | 2.80–3.20 | 2.80–3.20 | **Medium** | Swiss standard ~2.50m clear height for parking + ~0.30m slab; fire protection norm requires min. 2.40m clear | **Range may be slightly high** — many garages have 2.60–2.80m GH; 3.20m upper bound generous |
| 1251 | Industrial building | 4.00–7.00 | 4.00–7.00 | **Medium-High** | ArGV4 min. 4.00m lichte for >400m² → GH ~4.30m minimum; production halls 5–7m typical | Lower bound well-supported by regulation |
| 1252 | Tanks, silos, warehouses | 3.50–6.00 | 3.50–6.00 | **Low-Medium** | Highly variable by function; warehouse floors ~4–6m; silos may be single-volume | Heterogeneous category |
| 1261 | Culture and leisure | 3.50–5.00 | 3.50–5.00 | **Low-Medium** | Large gathering spaces require high ceilings; ArGV4 for >400m² | Plausible but highly variable |
| 1262 | Museums and libraries | 3.50–5.00 | 3.50–5.00 | **Low-Medium** | Exhibition and stack rooms vary widely; 3.5–5.0m reasonable for modern institutions | Historic buildings may exceed 5.0m |
| 1263 | Schools and universities | 3.30–4.00 | 3.30–4.00 | **High** | SIA 2024 Schulzimmer hR ~3.0m → GH ~3.3m; cantonal Richtraumprogramme (Schwyz) specify 3.0m min. lichte Höhe; ArGV4 for classroom sizes | **Well-supported** across multiple sources |
| 1264 | Hospitals and clinics | 3.30–4.00 | 3.30–4.00 | **Medium-High** | SIA 2024 Spital hR ~2.7m → GH ~3.0m; HVAC/medical installations add 0.3–0.5m; SWKI norms for medical facilities | **Lower bound may be slightly low** — modern hospitals often 3.60–4.20m due to technical installations |
| 1265 | Sports halls | 3.00–6.00 | 3.00–6.00 | **Medium** | Auxiliary rooms ~3.0m; main halls 5.5–7.0m (competition norms); wide range justified | **Upper bound may be low** for competition halls (7.0m+ common) |
| 1271 | Agricultural buildings | 3.50–5.00 | 3.50–5.00 | **Low-Medium** | Minimal normative data; barn/stable heights vary by use and era | Reasonable estimate |
| 1272 | Churches and religious | 3.00–6.00 | 3.00–6.00 | **Low** | Extremely variable; nave heights far exceed 6.0m; side rooms may be 3.0m | **Upper bound too low** for main worship spaces |
| 1273 | Monuments and protected | 3.00–4.00 | 3.00–4.00 | **Low** | Heterogeneous by definition; no standard heights | Rough central estimate only |
| 1274 | Other structures | 3.00–4.00 | 3.00–4.00 | **Low** | Catch-all category | Default assumption |
| — | Default (unknown) | 2.70–3.30 | 2.70–3.30 | **Medium** | Majority of Swiss buildings are residential (MFH/EFH); residential default is appropriate | Sensible fallback |

---

## Notable refinements and challenges to the table

Several specific findings merit attention for anyone using or refining these assumptions.

**Hotels may warrant lower upper-floor values.** SIA 2024 places hotel room clear heights at ~2.5m (comparable to residential), yielding Geschosshöhe of ~2.8m. The table's UF range of 3.00–3.50m appears generous for standard hotel room floors. The GF range (3.30–3.70m) is more defensible given lobbies and restaurants.

**Parking garage heights may be slightly high.** Swiss parking structures commonly have clear heights of 2.30–2.50m (minimum 2.10m under beams per cantonal fire protection norms), producing Geschosshöhen of ~2.60–2.80m rather than the table's 2.80–3.20m. Multi-storey parking garages typically aim for minimum structural height to minimize construction volume.

**Hospital floor heights in modern construction often exceed the table range.** Contemporary Swiss hospital buildings (e.g., those following SWKI VA105-01 HVAC norms for medical facilities) commonly have Geschosshöhen of **3.60–4.50m** due to intensive above-ceiling technical installations, clean-room requirements, and vertical services distribution. The table's range of 3.30–4.00m captures typical ward floors but may underestimate operating theaters and diagnostic floors.

**Church and religious building heights are not meaningfully captured by the range.** Nave heights of Swiss churches routinely exceed 10–15m, while ancillary rooms may be 3.0m. The 3.00–6.00m range is a compromise that may mislead volume calculations.

**Ground floor vs. upper floor differentiation is underutilized.** Only three categories in the table (1040, 1211, and implicitly 1060) differentiate between GF and UF heights. In practice, most mixed-use and commercial buildings have distinctly taller ground floors. Applying this differentiation more broadly — particularly for retail (1230), restaurants (1231), and office buildings (1220) — would improve accuracy.

---

## Conclusion: defensible defaults with known limitations

The Seiler & Seiler floor height assumptions represent **the best available systematic treatment** of Swiss building floor heights by GWR class. They are anchored in a coherent framework of regulatory minimums (ArGV4, cantonal PBG), energy-norm standards (SIA 2024, SIA 380/1), and professional construction knowledge. The residential categories (1110–1130) have the strongest evidentiary support, with multiple converging regulatory and normative sources. Non-residential categories are plausible but carry wider uncertainty bands — particularly for heterogeneous classes like special-purpose buildings, religious buildings, and transport infrastructure.

The most significant finding from this validation is not that the values are wrong, but that **no large-scale empirical dataset of Swiss floor heights by building type currently exists in the public domain**. The combination of swissBUILDINGS3D 3.0 (with EGID-linked building heights for 16 cantons) and GWR class data now makes such validation technically feasible for the first time. A systematic analysis dividing eave heights by above-ground floor counts, disaggregated by GKLAS, would either confirm these assumptions or produce empirically grounded replacements. Until such a study is published, the Seiler & Seiler values remain the standard reference — used by Canton Zurich for its Geschossflächenreserven model and implicitly adopted whenever Swiss spatial planners convert between building volume and floor area.