# data/ — cleaned data (final version)

The single data layer read by the pipeline. Layout matches the paths hard-coded in the scoring contract, so reproduction works without reconfiguration.

## Layout

| Path | Content |
| --- | --- |
| `processed/season_2026_actuals/actuals.json` | Season actuals: per-round race / qualifying / sprint results and standings (R01–R14). |
| `processed/circuit_history_2026_v1/` | Circuit history per round, R01–R13 (R14 Madrid is a new circuit — no history by fact, not by omission). |
| `manual/` | Curated inputs: season entry list (`2026_grid.json`), circuit profiles (`track_profile_2026_v1.json`), pre-race evidence snapshots (`agent_evidence_2026_v1.json`, R02–R08, each entry with source URL / retrieval time / direction / confidence), manual rating residuals (R02–R08), and registration templates. |
| `official_labels/` | Official qualifying-label overlay (R01–R09) and the R10/R11 FIA audit manifests — the inputs that make a prediction scoreable. |
| `README.md` | This file. |

## Note on paths

The label manifests were moved here from `docs/` on 2026-09-20; the scoring contract's path constants were updated with them. Everything under this directory is an input to scoring — there are no derived outputs here (those live in `predictions/`).

## Weekly collection hard check

`scripts/check_fp_sq_laps_coverage.py` verifies, for every completed round, that practice (FP) and sprint-qualifying lap archives are present and non-empty before the week is considered closed. It runs as part of the weekly collection checklist; a missing batch blocks the week's closure rather than failing silently.
