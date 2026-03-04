# Workers

Overview of all workers in the OpenBuildings pipeline.

| Worker | Description | Status | Implementation | Data Sources |
|--------|-------------|--------|----------------|--------------|
| [base-worker](base-worker/) | Aggregates Swiss cadastral data (Amtliche Vermessung) with GWR building attributes | Active | FME | geodienste.ch, housing-stat.ch |
| [volume-estimator](volume-estimator/) | Estimates building volumes using swissALTI3D/swissSURFACE3D elevation models | Active | Python | swissALTI3D, swissSURFACE3D |
| [area-estimator](area-estimator/) | Calculates gross floor areas from volumes using GWR building classifications | Active | Python | housing-stat.ch |
| [roof-estimator](roof-estimator/) | Estimates roof characteristics of buildings | In Development | - | TBD |
| [biodoversity-estimator](biodoversity-estimator/) | Estimates biodiversity metrics for buildings and surroundings | In Development | - | TBD |
| [volume-estimator_DEPRACATED](volume-estimator_DEPRACATED/) | Original volume estimator using swissBUILDINGS3D mesh data | Deprecated | FME, Python | swissBUILDINGS3D |
