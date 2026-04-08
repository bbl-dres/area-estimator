# Tests

`pytest` suite covering the pure logic in [area.py](../area.py), [volume.py](../volume.py), [footprints.py](../footprints.py), and the aggregation reduce in [main.py](../main.py).

## Run

From the project root:

```bash
pip install -r python/requirements-dev.txt
pytest python/tests/
```

~200 tests, sub-second runtime. The suite includes one synthetic-GeoPackage integration test that needs `geopandas` + `pyogrio` GPKG write support — both are part of the standard `requirements.txt`.

## Files

| File | Covers |
|---|---|
| [test_area.py](test_area.py) | `_to_gwr_code` (incl. NaN/inf/overflow), `get_floor_height` priority + DEFAULT fallback, `determine_accuracy` decision tree (the 3 short-circuits + per-code dict lookups), `estimate_floor_area` happy path + every status branch + `gastw` cap + banker's-rounding fix + DEFAULT-warning regression + non-mutation, `_ACCURACY_BY_GKLAS`/`_ACCURACY_BY_GKAT` exhaustiveness against `FLOOR_HEIGHT_LOOKUP`, parametrized per-code coverage |
| [test_volume.py](test_volume.py) | `make_empty_volume_result` schema invariants (NaN-not-zero), `append_warning` semantics, `get_building_orientation` happy + degenerate cases, `create_aligned_grid_points` count/scaling/containment |
| [test_footprints.py](test_footprints.py) | `_parse_egid_cell` parametrized over 30+ input shapes (single/comma/slash/semicolon/whitespace/empty/garbage/zero/negative/inf/NaN), `_normalise_cell` whitespace collapse, `_read_input_csv` BOM stripping + delimiter auto-detect + cell cleanup, `load_footprints_from_av_with_coordinates` end-to-end against a synthetic GeoPackage fixture (including a spy test pinning down O(1) gpkg I/O) |
| [test_aggregate.py](test_aggregate.py) | `_format_sub_value` and `_demote_int_float` helpers; `aggregate_by_input_id` for empty/no-input_id/single-row/multi-polygon/multi-EGID/partial-match/all-failed cases; status_step3 rollup, warning deduplication, scalar-collapse-when-equal, integer-float demotion, column order preservation, geometry-column defensive guard, all three branches of the aggregation warning text |
| [conftest.py](conftest.py) | Adds `python/` to `sys.path` so test modules can `from area import …` without a package install |

## What's intentionally not unit-tested

- **Network paths** (`query_gwr_api`, `enrich_with_gwr` API mode, `tile_fetcher.ensure_tiles`) — would need request mocking. Covered by integration runs against `data/example.csv`.
- **Raster sampling** (`TileIndex.sample_heights`) — would need fake or mocked rasters. Covered by integration runs.
- **`enrich_with_gwr` CSV path** — currently uncovered, would need a synthetic GWR CSV fixture. Tracked as a follow-up.
- **`load_footprints_from_av_with_egids`** — the EGID-mode loader has no integration test mirroring the coordinate-mode synthetic-gpkg test. Tracked as a follow-up.

## Adding new tests

The test files use plain `pytest` with `parametrize`. No fancy fixtures other than `tmp_path` for the synthetic GeoPackage test. To add a test for a new behavior:

1. Add the test function to the appropriate `test_*.py` file (one per source module).
2. Use `pytest.mark.parametrize` for table-driven tests over input/expected pairs.
3. For tests that need real files, use `tmp_path` and write the file inline.
4. Run `pytest python/tests/test_<module>.py -v` to verify before committing.

For the public-API contract (`BuildingResult` TypedDict, output column schema, etc.) the convention is an **exhaustiveness test** — see `test_accuracy_dicts_cover_every_lookup_code` in `test_area.py` for the pattern.
