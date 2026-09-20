#!/usr/bin/env python3
"""Ablation runner: replace form/constructor/circuit_fit with fp_score.

fp-replacement-ablation-plan. What-if isolation only -- src/ is untouched; the three
feature scorers on the features module are patched the same way the 2026-09-05
GCR what-if patched F._constructor_scores. target_round is inferred from the
prior rounds (max prior round + 1) for form/ctor, passed through for
circuit_fit. Scoring pipeline (registry, walk-forward limit, C0 scorer,
labels) is identical to run_qualifying_c0_roster_r03_r14.py.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import analyze_fp_signal_correlation as fpsig  # noqa: E402

from f1_big_predictor.targets.qualifying import features as F  # noqa: E402
from f1_big_predictor.targets.qualifying.c0_roster import (  # noqa: E402
    build_input_snapshot,
    candidate_registry,
)
from f1_big_predictor.targets.qualifying.c0_scorer import score_qualifying  # noqa: E402
from f1_big_predictor.targets.qualifying.r10_c0_replay import (  # noqa: E402
    extended_walk_forward_round_limit,
)
from run_qualifying_c0_roster_r03_r14 import _git_commit, _label_source, _labels_for_round  # noqa: E402

ROUNDS = list(range(3, 15))
ALL_FEATURES = ("form", "ctor", "circuit_fit")


def build_fp_tables() -> dict[int, dict[str, float]]:
    """Frozen fp_score v1.0 (with SQ pooling), R03-R14: driver -> 0-1 score."""
    nummap = fpsig.number_map()
    actuals = json.load(open(ROOT / "data/processed/season_2026_actuals/actuals.json"))
    rounds = {int(r["round"]): r for r in actuals["completed_rounds"]}
    tables: dict[int, dict[str, float]] = {}
    for rn in sorted(rounds):
        best = fpsig.best_by_session(rn, fpsig.fp_keys(rn), nummap)
        sq = fpsig.sq_keys(rn)
        if sq:
            for d, t in fpsig.best_by_session(rn, sq, nummap).items():
                if d not in best or t < best[d]:
                    best[d] = t
        if not best:
            continue
        field = int(rounds[rn]["race_results"]["row_count"])
        rr = fpsig.rankdata(list(best.values()))
        tables[rn] = {
            d: (field + 1 - r) / field for d, r in zip(best.keys(), rr)
        }
    return tables


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace", required=True,
                        help="comma list from: form,ctor,circuit_fit")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    combo = tuple(sorted(x.strip() for x in args.replace.split(",") if x.strip()))
    assert set(combo) <= set(ALL_FEATURES) and combo, f"bad --replace: {combo}"
    tag = "+".join(combo)

    root = ROOT
    fp_tables = build_fp_tables()
    actuals = json.load(open(root / "data/processed/season_2026_actuals/actuals.json"))
    rounds = {int(r["round"]): r for r in actuals["completed_rounds"]}
    ctor_members: dict[int, dict[str, list[str]]] = {
        rn: {} for rn in rounds
    }
    for rn, r in rounds.items():
        for x in r["qualifying_results"]["records"]:
            if x.get("driver_id") and x.get("constructor_id"):
                ctor_members[rn].setdefault(x["constructor_id"], []).append(x["driver_id"])

    def target_of_prior(prior_rounds) -> int:
        return max(int(r["round"]) for r in prior_rounds) + 1

    orig_form = F._form_scores
    orig_ctor = F._constructor_scores
    orig_cfit = F._circuit_fit_scores

    def patched_form(prior_rounds, drivers, evidence_gaps):
        if "form" not in combo or not prior_rounds:
            return orig_form(prior_rounds, drivers, evidence_gaps)
        tgt = target_of_prior(prior_rounds)
        table = fp_tables.get(tgt, {})
        return {str(d["driver_id"]): table.get(str(d["driver_id"])) for d in drivers}

    def patched_ctor(round_payload):
        if "ctor" not in combo or round_payload is None:
            return orig_ctor(round_payload)
        tgt = int(round_payload["round"]) + 1
        table = fp_tables.get(tgt, {})
        out = {}
        for cid, members in ctor_members.get(tgt, {}).items():
            vals = [table.get(m) for m in members]
            vals = [v for v in vals if v is not None]
            out[cid] = sum(vals) / len(vals) if vals else None
        return out

    def patched_cfit(project_root, target_round, evidence_gaps):
        if "circuit_fit" not in combo:
            return orig_cfit(project_root, target_round, evidence_gaps)
        table = fp_tables.get(target_round, {})
        return dict(table)

    F._form_scores = patched_form
    F._constructor_scores = patched_ctor
    F._circuit_fit_scores = patched_cfit

    commit = _git_commit()
    out = args.output_dir or (
        root / "outputs/experiments/qualifying" / f"fp_ablation_{tag}_{commit[:8]}"
    )
    out.mkdir(parents=True, exist_ok=True)

    registry = candidate_registry()
    targets: dict[int, tuple[list, int, str]] = {}
    for rn in ROUNDS:
        recs, fs = _labels_for_round(actuals, rn)
        targets[rn] = (recs, fs, _label_source(rn))

    candidates = []
    for spec in registry:
        entry = {"spec": spec.public_record(), "rounds": {}, "failures": {}}
        try:
            with extended_walk_forward_round_limit(max(ROUNDS)):
                history = spec.runner(root)
            by_round = {int(i["round"]): i for i in history.get("per_round", [])}
            for rn in ROUNDS:
                if rn < spec.first_scoring_round:
                    entry["rounds"][rn] = {"status": "expected_exclusion"}
                    continue
                item = by_round.get(rn)
                if item is None:
                    entry["failures"][rn] = "missing_per_round_result"
                    continue
                pred = list(item.get("top10_predicted_driver_ids") or [])
                recs, fs, src = targets[rn]
                try:
                    c0_full = score_qualifying(pred, recs, fs)
                except ValueError as exc:
                    if "absent from" in str(exc):
                        entry["rounds"][rn] = {
                            "status": "unscoreable_field_mismatch",
                            "prediction_top10": pred, "label_source": src,
                            "reason": str(exc),
                        }
                        continue
                    raise
                entry["rounds"][rn] = {
                    "status": "scored", "prediction_top10": pred,
                    "label_source": src,
                    "c0": c0_full["overall_candidate"]["overall_candidate_score"],
                }
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        candidates.append(entry)
        done = sum(1 for v in entry["rounds"].values() if v.get("status") == "scored")
        print(f"#{spec.ordinal:>2} {spec.candidate_id:<44} scored {done}/{len(ROUNDS)}"
              + (f"  ERROR {entry['error'][:60]}" if "error" in entry else ""))

    summary = []
    for entry in candidates:
        sp = entry["spec"]
        scores = {int(k): float(v["c0"]) for k, v in entry["rounds"].items()
                  if v.get("status") == "scored" and isinstance(v.get("c0"), (int, float))}
        summary.append({
            "candidate_id": sp["candidate_id"], "ordinal": sp["ordinal"],
            "n_rounds": len(scores),
            "mean_c0_r03_r14": round(sum(scores.values()) / len(scores), 6) if scores else None,
            "per_round": {str(k): round(v, 6) for k, v in sorted(scores.items())},
        })
    summary.sort(key=lambda r: -(r["mean_c0_r03_r14"] or -1))

    payload = {
        "schema_version": "qualifying.fp_ablation.v1",
        "season": 2026,
        "replaced_features": list(combo),
        "evaluation_rounds": ROUNDS,
        "baseline_artifact": "c0_roster_r03_r14_92076830",
        "cutoff_semantics": {
            "plan": "fp-replacement-ablation-plan",
            "note": "replaced feature scorers patched at module level (9-05 GCR what-if precedent); weights untouched",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_commit": commit,
        "summary": summary,
        "candidates": candidates,
    }
    (out / "c0_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {(out / 'c0_results.json').relative_to(root)}")
    for row in summary[:5]:
        print(f"  #{row['ordinal']:>2} {row['candidate_id']:<40} {row['mean_c0_r03_r14']}")


if __name__ == "__main__":
    main()
