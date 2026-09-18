#!/usr/bin/env python3
"""Qualifying C0 roster incremental scorecard for R13-R14 only (31 candidates).

Continuation of scripts/run_qualifying_c0_roster_r03_r12.py (artifact
c0_roster_r03_r12_615232a3), which stays untouched. User decision
2026-09-14: R06 persisted scores are NOT refreshed; R01/R02 stay excluded;
this run scores only R13 (Monza) and R14 (Madring).

Label policy identical to donor R10+ branch: raw actuals qualifying results
(`raw_actuals_pending_fia_overlay`); `_labels_for_round` / `_label_source`
imported from the donor module so the extraction path is byte-identical.

Known upstream quirks recorded honestly (scoring contract, no repair):
- R14 jolpica qualifying returned 20 rows while the race had 22 cars;
- seat-swap field changes surface as `unscoreable_field_mismatch`
  (deferred mechanism per user ruling; see memory seat-swap-mechanism-deferred).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_qualifying_c0_roster_r03_r12 import (  # noqa: E402
    PROJECT_ROOT,
    _git_commit,
    _label_source,
    _labels_for_round,
)

from f1_big_predictor.targets.qualifying.c0_roster import (  # noqa: E402
    build_input_snapshot,
    candidate_registry,
)
from f1_big_predictor.targets.qualifying.c0_scorer import score_qualifying  # noqa: E402
from f1_big_predictor.targets.qualifying.r10_c0_replay import (  # noqa: E402
    extended_walk_forward_round_limit,
)

ROUNDS = [13, 14]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = PROJECT_ROOT
    actuals = json.loads(
        (root / "data/processed/season_2026_actuals/actuals.json").read_text()
    )
    registry = candidate_registry()
    commit = _git_commit()
    out = args.output_dir or (
        root / "outputs/experiments/qualifying" / f"c0_roster_r13_r14_{commit[:8]}"
    )
    out.mkdir(parents=True, exist_ok=True)

    targets: dict[int, tuple[list, int, str]] = {}
    for rn in ROUNDS:
        recs, fs = _labels_for_round(actuals, rn)
        targets[rn] = (recs, fs, _label_source(rn))
    print("label rows:", {rn: targets[rn][1] for rn in ROUNDS})

    candidates: list[dict] = []
    for spec in registry:
        entry: dict = {"spec": spec.public_record(), "rounds": {}, "failures": {}}
        try:
            with extended_walk_forward_round_limit(max(ROUNDS)):
                history = spec.runner(root)
            by_round = {
                int(item["round"]): item for item in history.get("per_round", [])
            }
            for rn in ROUNDS:
                if rn < spec.first_scoring_round:
                    entry["rounds"][rn] = {"status": "expected_exclusion"}
                    continue
                item = by_round.get(rn)
                if item is None:
                    entry["failures"][rn] = "missing_per_round_result"
                    continue
                prediction = list(item.get("top10_predicted_driver_ids") or [])
                recs, fs, src = targets[rn]
                try:
                    c0_full = score_qualifying(prediction, recs, fs)
                except ValueError as exc:
                    if "absent from" in str(exc):
                        entry["rounds"][rn] = {
                            "status": "unscoreable_field_mismatch",
                            "prediction_top10": prediction,
                            "label_source": src,
                            "reason": str(exc),
                        }
                        continue
                    raise
                entry["rounds"][rn] = {
                    "status": "scored",
                    "prediction_top10": prediction,
                    "label_source": src,
                    "c0": c0_full["overall_candidate"]["overall_candidate_score"],
                    "c0_full": c0_full,
                }
        except Exception as exc:  # keep artifact honest
            entry["error"] = f"{type(exc).__name__}: {exc}"
        candidates.append(entry)
        done = sum(1 for v in entry["rounds"].values() if v.get("status") == "scored")
        print(
            f"#{spec.ordinal:>2} {spec.candidate_id:<44} scored {done}/{len(ROUNDS)}"
            + (f"  ERROR {entry['error'][:60]}" if "error" in entry else "")
        )

    summary_rows = []
    for entry in candidates:
        sp = entry["spec"]
        scores: dict[int, float] = {}
        for rn, rnd in entry["rounds"].items():
            if rnd.get("status") != "scored":
                continue
            c0 = rnd.get("c0")
            if isinstance(c0, (int, float)):
                scores[int(rn)] = float(c0)
        allv = list(scores.values())
        summary_rows.append({
            "candidate_id": sp["candidate_id"],
            "ordinal": sp["ordinal"],
            "model_id": sp["model_id"],
            "variant": sp["variant"],
            "n_rounds": len(allv),
            "mean_c0_r13_r14": round(sum(allv) / len(allv), 6) if allv else None,
            "per_round": {str(k): v for k, v in scores.items()},
        })
    summary_rows.sort(key=lambda r: -(r["mean_c0_r13_r14"] or -1))

    payload = {
        "schema_version": "qualifying.c0_roster.v2_incremental_r13_r14",
        "season": 2026,
        "candidate_registry": [s.public_record() for s in registry],
        "evaluation_rounds": ROUNDS,
        "continuation_of": "c0_roster_r03_r12_615232a3",
        "label_provenance": {str(rn): targets[rn][2] for rn in ROUNDS},
        "cutoff_semantics": {
            "merge_note": (
                "Incremental prospective continuation after the c0 iteration "
                "freeze (d7f7c44): same frozen 31-candidate registry and scorer "
                "contract; R03-R12 artifact untouched (R06 NOT refreshed per "
                "user directive 2026-09-14)."
            ),
            "training": "only rounds strictly before each target round",
            "labels": "see label_provenance per round",
        },
        "run_purpose": "incremental_prospective_c0_roster_r13_r14_user_directive_20260914",
        "input_snapshot": build_input_snapshot(root),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_commit": commit,
        "summary": summary_rows,
        "candidates": candidates,
    }
    results_path = out / "c0_results.json"
    results_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = ["rank,ordinal,candidate_id,model_id,variant,mean_c0_r13_r14"]
    for i, row in enumerate(summary_rows, 1):
        lines.append(
            f"{i},{row['ordinal']},{row['candidate_id']},{row['model_id']},"
            f"\"{row['variant']}\",{row['mean_c0_r13_r14']}"
        )
    (out / "c0_ranking.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {results_path.relative_to(root)}")
    print("top of incremental ranking:")
    for row in summary_rows[:6]:
        print(
            f"  #{row['ordinal']:>2} {row['candidate_id']:<40} "
            f"r13-14 {row['mean_c0_r13_r14']}  per_round {row['per_round']}"
        )


if __name__ == "__main__":
    main()
