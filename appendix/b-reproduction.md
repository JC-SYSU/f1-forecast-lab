# Appendix B: Reproduction Guide

This appendix gives the minimal path for reproducing the scorecards. The commands run directly from the root of this repository, which mirrors the original research layout: `src/`, `scripts/`, `tests/`, `data/`, `docs/`. The archived scorecards themselves live in `predictions/` (see Appendix C).

## B.1 Environment and code

- Python 3.11; dependencies include LightGBM (needed by the LambdaMART slots), scikit-learn (elastic net / ridge regression), and the standard scientific computing stack.
- Code lives in `src/f1_big_predictor/`, split by target: `targets/qualifying/` (the qualifying line) and `targets/race/` (the race line).
- Frozen state: the qualifying scoring scale and the 31-candidate registry were frozen in July 2026 (commits `d7f7c44`, `9fcb0e8`); the race model formula was frozen at commit `606117e`. Reproduction should not modify these files.

## B.2 Data placement

Rerunning the evaluations requires the following minimal datasets (SHA-256 values are in each scorecard artifact's `input_snapshot` field; comparing them one by one confirms input identity):

| Path | Contents |
| --- | --- |
| `data/processed/season_2026_actuals/actuals.json` | Actuals for each round (qualifying/race results and standings) |
| `data/processed/circuit_history_2026_v1/` | Circuit history for R01–R13 (R14 Madrid is a new circuit; no file is expected) |
| `data/manual/` | Manually maintained files: season rosters, track profiles, pre-race evidence, and the like |
| `data/official_labels/` | Official qualifying label lists for R03–R09 (the scoring overlay layer) |
| `data/raw/` | Raw archives (required to rerun qualifying R03–R12; offline circuit-history generation depends on it) |

## B.3 Minimal example: scoring a single round with the frozen race model

```python
from pathlib import Path
from f1_big_predictor.targets.race.optimized_model import predict_top10, evaluate_model

root = Path("/path/to/repo")
top10 = predict_top10(root, target_round=12)          # race top-10 prediction for R12
metrics = evaluate_model(root, rounds=[12, 13, 14])   # multi-round scoring (including C0)
```

Prediction depends only on data from before the target round (`evaluate_model` truncates by round internally); the score is the single-race C0, and the reading rules are in 7.1.

## B.4 Full-volume rerun

```bash
# Official caliber (2026-09-20, seat-rotation policy, decision log entry 12)
# Qualifying: merged 31-candidate × R03–R14 scorecard (tens of minutes)
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 scripts/run_qualifying_c0_roster_r03_r14.py
# Race: baseline vs frozen model comparison over R03–R14
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 scripts/evaluate_race_c0_r03_r14.py

# Superseded caliber (2026-09-18) — reproduces the retained a90bf4ad / 615232a3 artifacts
# Qualifying: merged 31-candidate × R03–R12 scorecard
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 scripts/run_qualifying_c0_roster_r03_r12.py
# Qualifying: R13–R14 incremental
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 scripts/run_qualifying_c0_roster_r13_r14.py
# Race: baseline vs frozen model comparison over R03–R12
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 scripts/evaluate_race_c0_r03_r12.py
```

Artifacts are written to `outputs/experiments/<line>/<directory derived from the script name>/`; the directory name carries the first 8 characters of the code commit hash. Repeated runs under the same commit should produce bit-identical results. The copies under `predictions/` are the archived release view of exactly these artifacts (the scripts always write to `outputs/`; nothing reads or writes `predictions/`).

## B.5 Verification

After a rerun, compare three places against the official artifacts: the per-candidate means in `summary` (should match bit for bit), `candidate_registry` (31 entries and their configurations), and `input_snapshot.combined_sha256` (the overall check of input identity). Field meanings are in Appendix C.2.

## B.6 The practice-session experiments (September 20)

The practice-signal line (decision log, entries 13–14) ran as isolated, read-only experiments against the official scorecards. The scripts need the same data placement as B.2 plus the raw OpenF1 lap and session archives (`data/raw/openf1_laps_2026_round_*/`, `data/raw/openf1_sessions_2026_round_*/`). Artifacts are written under `outputs/experiments/` and are not distributed with this repository.

```bash
# Correlation audits (blocks A / A2 / C for qualifying; B' / C1' / C3'
# and the Block D gap test for the race line)
PYTHONPATH=src:scripts python3 scripts/analyze_fp_signal_correlation.py
PYTHONPATH=src:scripts python3 scripts/analyze_fp_race_line.py

# Replacement ablations (qualifying: 7 combinations of form / ctor /
# circuit_fit; race: GAP correction vs FP-DIRECT, lambda selected on
# dev R03-R09 only)
PYTHONPATH=src:scripts python3 scripts/ablation_fp_replace.py --replace form
PYTHONPATH=src:scripts python3 scripts/ablation_fp_race.py
```

The headline outcome, for checking a rerun against: every combination on either side stayed below the +0.010 bar (qualifying best +0.0072, inside the noise band; race GAP correction +0.0006, FP-DIRECT selecting λ*=0) — the evidence the line was closed on. The weekly coverage check behind B.2's collection list is `scripts/check_fp_sq_laps_coverage.py`.
