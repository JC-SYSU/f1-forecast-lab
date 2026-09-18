#!/usr/bin/env python3
"""Merged qualifying C0 roster scorecard over R03-R12 (31 candidates).

Replaces the R03-R09-only official scorecard plus the two single-round
replays (r10/r11) with one integrated artifact.

Label policy per round:
- R03-R09: official overlay manifest (FIA-tracked, unchanged semantics).
- R10-R11: raw actuals qualifying results. Verified identical in order to
  the FIA audit used by the single-round replays (checked 2026-09-05),
  so no information is lost versus those artifacts.
- R12: raw actuals (FIA final classification PDF archived today; no
  official label entry yet — flagged `pending_fia_overlay`).

Walk-forward causality per round is preserved via
`extended_walk_forward_round_limit` (the mechanism the r10/r11 replays
already use, patched-then-restored on every donor module).
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from f1_big_predictor.targets.qualifying.c0_roster import (
    build_input_snapshot,
    candidate_registry,
)
from f1_big_predictor.targets.qualifying.c0_scorer import score_qualifying
from f1_big_predictor.targets.qualifying.official_labels import (
    official_records_for_round,
)
from f1_big_predictor.targets.qualifying.r10_c0_replay import (
    extended_walk_forward_round_limit,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROUNDS = list(range(3, 13))


def _git_commit() -> str:
    return subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _labels_for_round(actuals: dict, round_number: int):
    for item in actuals["completed_rounds"]:
        if int(item["round"]) != round_number:
            continue
        recs = item["qualifying_results"]["records"]
        official = [
            {
                "driver_id": r["driver_id"],
                "position": r.get("position"),
                "classification_status": r.get("status") or "Classified",
            }
            for r in recs
        ]
        return official, len(official)
    raise ValueError(f"round {round_number} missing from actuals")


def _label_source(round_number: int) -> str:
    if round_number <= 9:
        return "official_overlay_manifest"
    if round_number in (10, 11):
        return "raw_actuals_verified_equal_to_fia_replay_audit"
    return "raw_actuals_pending_fia_overlay"


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
        root
        / "outputs/experiments/qualifying"
        / f"c0_roster_r03_r12_{commit[:8]}"
    )
    out.mkdir(parents=True, exist_ok=True)

    # Precompute official records/field per round (official for <=9, raw for >=10)
    targets: dict[int, tuple[list, int, str]] = {}
    for rn in ROUNDS:
        if rn <= 9:
            recs, fs = official_records_for_round(root, rn)
            targets[rn] = (recs, fs, _label_source(rn))
        else:
            recs, fs = _labels_for_round(actuals, rn)
            targets[rn] = (recs, fs, _label_source(rn))

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

    def _score_of(r: dict):
        c0 = r.get("c0")
        return float(c0) if isinstance(c0, (int, float)) else None

    summary_rows = []
    for entry in candidates:
        sp = entry["spec"]
        scores: dict[int, float] = {}
        for rn, rnd in entry["rounds"].items():
            if rnd.get("status") != "scored":
                continue
            s = _score_of(rnd)
            if s is None:
                continue
            scores[int(rn)] = s
        r39 = [v for k, v in scores.items() if k <= 9]
        r1012 = [v for k, v in scores.items() if k >= 10]
        allv = list(scores.values())
        summary_rows.append({
            "candidate_id": sp["candidate_id"],
            "ordinal": sp["ordinal"],
            "model_id": sp["model_id"],
            "variant": sp["variant"],
            "n_rounds": len(allv),
            "mean_c0_r03_r12": round(sum(allv) / len(allv), 6) if allv else None,
            "mean_c0_r03_r09": round(sum(r39) / len(r39), 6) if r39 else None,
            "mean_c0_r10_r12": round(sum(r1012) / len(r1012), 6) if r1012 else None,
            "per_round": {str(k): v for k, v in scores.items()},
        })
    summary_rows.sort(key=lambda r: -(r["mean_c0_r03_r12"] or -1))

    payload = {
        "schema_version": "qualifying.c0_roster.v2_merged",
        "season": 2026,
        "candidate_registry": [s.public_record() for s in registry],
        "evaluation_rounds": ROUNDS,
        "label_provenance": {str(rn): targets[rn][2] for rn in ROUNDS},
        "cutoff_semantics": {
            "merge_note": (
                "Integrated development (R03-R09) + prospective rounds (R10-R12) "
                "post-hoc; all rounds here are after-the-fact evidence, not "
                "pre-frozen prospective claims."
            ),
            "training": "only rounds strictly before each target round",
            "labels": "see label_provenance per round",
        },
        "run_purpose": "merged_full_coverage_scorecard_supersedes_r03_r09_and_single_round_replays",
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
    lines = ["rank,ordinal,candidate_id,model_id,variant,mean_c0_r03_r12,mean_c0_r03_r09,mean_c0_r10_r12"]
    for i, row in enumerate(summary_rows, 1):
        lines.append(
            f"{i},{row['ordinal']},{row['candidate_id']},{row['model_id']},"
            f"\"{row['variant']}\",{row['mean_c0_r03_r12']},{row['mean_c0_r03_r09']},{row['mean_c0_r10_r12']}"
        )
    (out / "c0_ranking.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {results_path.relative_to(root)}")
    print("top of merged ranking:")
    for row in summary_rows[:5]:
        print(
            f"  #{row['ordinal']:>2} {row['candidate_id']:<40} "
            f"r03-12 {row['mean_c0_r03_r12']}  (dev {row['mean_c0_r03_r09']} | late {row['mean_c0_r10_r12']})"
        )


if __name__ == "__main__":
    main()
