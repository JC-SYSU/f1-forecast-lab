#!/usr/bin/env python3
"""Race Top-10 C0 incremental evaluation for R13-R14 only.

Continuation of scripts/evaluate_race_c0_r03_r12.py (artifact
c0_race_r03_r12_615232a3), which stays untouched. Per the user decision of
2026-09-14: already-persisted round scores are NOT refreshed (R06 keeps its
pre-ICA labels in that artifact); R01/R02 remain excluded; this run scores
only the two prospective rounds R13 (Monza) and R14 (Madring).

Scoring logic is imported from the donor module verbatim:
  - race_optimized_606117e via `_model_order` (frozen formula, no refit);
  - race_grid_only reimplemented here in one-to-one form because the donor
    defines it inside main() (identical code path, same actuals source).

Feature inputs are read from the CURRENT actuals.json, whose R06 block was
merged with post-ICA ground truth on 2026-09-13 — walk-forward features for
R13/R14 therefore use the corrected history (prospective semantics, intended).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate_race_c0_r03_r12 import PROJECT_ROOT, _git_commit, _model_order  # noqa: E402

from f1_big_predictor.targets.race.c0_score import c0_score  # noqa: E402

ROUNDS = [13, 14]


def _grid_only(by_round: dict, rn: int) -> list[str]:
    starters = [
        (rec["driver_id"], int(rec["grid"]))
        for rec in by_round[rn]["race_results"]["records"]
        if rec.get("grid") is not None
    ]
    starters.sort(key=lambda x: x[1])
    return [d for d, _ in starters]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = PROJECT_ROOT
    commit = _git_commit()
    out = args.output_dir or (
        root / "outputs/experiments/race" / f"c0_race_r13_r14_{commit[:8]}"
    )
    out.mkdir(parents=True, exist_ok=True)

    actuals = json.loads(
        (root / "data/processed/season_2026_actuals/actuals.json").read_text()
    )
    by_round = {int(r["round"]): r for r in actuals["completed_rounds"]}

    candidates = {
        "race_grid_only": lambda rn: _grid_only(by_round, rn),
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
            "mean_c0_r13_r14": round(sum(scored) / len(scored), 6) if scored else None,
            "n_rounds": len(scored),
        }
        print(f"{name:<24} mean {results[name]['mean_c0_r13_r14']}  rounds {len(scored)}")
        for rn, v in per_round.items():
            if v.get("status") == "scored":
                print(f"   R{rn:02d} {v['race_name']:<28} C0={v['c0']:.4f}")

    payload = {
        "schema_version": "race.c0_evaluation.v1",
        "season": 2026,
        "evaluation_rounds": ROUNDS,
        "continuation_of": "c0_race_r03_r12_615232a3",
        "cutoff_semantics": {
            "weights": (
                "optimized model weights frozen at commit 606117e; R13/R14 are "
                "the second/third rounds scored after the weights freeze"
            ),
            "training": "form/constructor/racecraft features use only rounds < target",
            "labels": "race_results finish order from actuals.json as of 2026-09-14 (R13/R14 merged this week)",
            "r06_policy": "persisted R03-R12 artifact not refreshed; this run's features include post-ICA R06 (prospective only)",
        },
        "run_purpose": "incremental_prospective_c0_r13_r14_user_directive_20260914",
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
