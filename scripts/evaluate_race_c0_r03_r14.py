#!/usr/bin/env python3
"""Race Top-10 C0 evaluation R03-R14 with persisted artifacts.

Full recompute under the seat-rotation policy implementation
(the seat-rotation implementation plan, the seat-rotation unlock decision):
constructor attribution now follows the manual seat registry from R12 on
(lawson -> red_bull), so constructor_raw for R12-R14 uses the new team.
Supersedes c0_race_r03_r12_615232a3 and c0_race_r13_r14_6a01fdaa.

Candidates (both walk-forward: features train only on rounds < target):
  1. race_grid_only          — finish order assumed = grid order.
  2. race_optimized_606117e  — frozen formula
        pos = grid - 3*form_std - 2*racecraft_std - 3*max(0, grid-10)*constructor_raw
     Weights are NOT refit here; note that R03-R09 was the weight-training
     window and R10-R11 the original test window, so those rounds are
     in-sample/post-hoc; R12 is the first genuinely unseen round.

Ground truth: race_results finish order (position ascending).
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev

from f1_big_predictor.targets.qualifying.features import build_qualifying_features
from f1_big_predictor.targets.race.c0_score import c0_score
from f1_big_predictor.targets.race.optimized_model import _extract_racecraft_features

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROUNDS = list(range(3, 15))


def _git_commit() -> str:
    return subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _model_order(root: Path, actuals: dict, target_round: int) -> list[str]:
    completed = sorted(actuals["completed_rounds"], key=lambda r: int(r["round"]))
    qual_data = build_qualifying_features(
        project_root=root, target_round=target_round, season=2026,
        officialize_actuals=False,
    )
    qual_features = {
        row["driver_id"]: {
            "form": row.get("form_score") or 0.0,
            "constructor": row.get("constructor_score") or 0.0,
        }
        for row in qual_data.get("rows", [])
    }
    racecraft = _extract_racecraft_features(completed, target_round)
    target = next(r for r in completed if int(r["round"]) == target_round)
    features = {}
    for rec in target["race_results"]["records"]:
        did = rec["driver_id"]
        grid = rec.get("grid")
        if grid is None:
            continue
        qual = qual_features.get(did, {})
        features[did] = {
            "grid": grid,
            "form_raw": qual.get("form", 0.0),
            "constructor_raw": qual.get("constructor", 0.0),
            "racecraft_raw": racecraft.get(did, 0.5),
        }
    if not features:
        return []
    fv = [f["form_raw"] for f in features.values()]
    rv = [f["racecraft_raw"] for f in features.values()]
    fm, fs = mean(fv), (stdev(fv) if len(fv) > 1 else 1.0)
    rm, rs = mean(rv), (stdev(rv) if len(rv) > 1 else 1.0)
    scored = []
    for did, f in features.items():
        boost = max(0, f["grid"] - 10) * f["constructor_raw"]
        pred_pos = (
            f["grid"]
            - 3.0 * ((f["form_raw"] - fm) / fs if fs > 0 else 0.0)
            - 2.0 * ((f["racecraft_raw"] - rm) / rs if rs > 0 else 0.0)
            - 3.0 * boost
        )
        scored.append((did, pred_pos))
    scored.sort(key=lambda x: x[1])
    return [d for d, _ in scored]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = PROJECT_ROOT
    commit = _git_commit()
    out = args.output_dir or (
        root / "outputs/experiments/race" / f"c0_race_r03_r14_{commit[:8]}"
    )
    out.mkdir(parents=True, exist_ok=True)

    actuals = json.loads(
        (root / "data/processed/season_2026_actuals/actuals.json").read_text()
    )
    by_round = {int(r["round"]): r for r in actuals["completed_rounds"]}

    def _grid_only(rn: int) -> list[str]:
        starters = [
            (rec["driver_id"], int(rec["grid"]))
            for rec in by_round[rn]["race_results"]["records"]
            if rec.get("grid") is not None
        ]
        starters.sort(key=lambda x: x[1])
        return [d for d, _ in starters]

    candidates = {
        "race_grid_only": _grid_only,
        "race_optimized_606117e": lambda rn: _model_order(root, actuals, rn),
    }

    results: dict[str, dict] = {}
    for name, fn in candidates.items():
        per_round = {}
        for rn in ROUNDS:
            target = by_round.get(rn)
            if target is None:
                per_round[rn] = {"status": "missing_round"}
                continue
            actual_order = [
                rec["driver_id"]
                for rec in sorted(
                    (r for r in target["race_results"]["records"]
                     if r.get("position") is not None),
                    key=lambda r: int(r["position"]),
                )
            ]
            predicted = fn(rn)
            if not predicted:
                per_round[rn] = {"status": "no_prediction"}
                continue
            c0 = c0_score(predicted, actual_order)
            per_round[rn] = {
                "status": "scored",
                "race_name": target.get("race_name"),
                "c0": round(c0, 6),
                "predicted_top10": predicted[:10],
                "actual_top10": actual_order[:10],
            }
        scored = [v["c0"] for v in per_round.values() if v.get("status") == "scored"]
        results[name] = {
            "per_round": per_round,
            "mean_c0_r03_r14": round(mean(scored), 6) if scored else None,
            "n_rounds": len(scored),
        }
        print(f"{name:<24} mean {results[name]['mean_c0_r03_r14']}  rounds {len(scored)}")
        for rn, v in per_round.items():
            if v.get("status") == "scored":
                print(f"   R{rn:02d} {v['race_name']:<28} C0={v['c0']:.4f}")

    payload = {
        "schema_version": "race.c0_evaluation.v1",
        "season": 2026,
        "evaluation_rounds": ROUNDS,
        "cutoff_semantics": {
            "weights": (
                "optimized model weights frozen at commit 606117e (selected on "
                "R03-R09 dev / R10-R11 test); rounds R03-R11 are post-hoc, "
                "R12 is the first round scored after the weights were frozen"
            ),
            "training": "form/constructor/racecraft features use only rounds < target",
            "labels": "race_results finish order from actuals.json as of 2026-09-20 (R01-R14)",
            "seat_policy": (
                "constructor attribution follows the manual seat registry "
                "from R12 on; weights remain frozen at 606117e"
            ),
        },
        "run_purpose": "seat_rotation_impl_race_full_recompute_r03_r14_supersedes_615232a3",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_commit": commit,
        "results": results,
    }
    (out / "c0_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {(out / 'c0_results.json').relative_to(root)}")


if __name__ == "__main__":
    main()
