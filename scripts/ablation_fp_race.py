#!/usr/bin/env python3
"""Race-line ablation: GAP correction vs FP-DIRECT weighting (v1.2 §7).

Baseline: race_optimized_606117e full order (c0_race_r03_r14_d739e6e0).
Variants re-rank the baseline full order by
  GAP:      key = pred_pos - lambda * (grid_pct - fp_pct)
  FPDIRECT: key = pred_pos - lambda * fp_pct
(C3'/Block D direction: fp-fast and grid-over-fp drivers underperform grid
expectation in the race, so the correction pushes them BACK.)

lambda* is selected on dev R03-R09 only; full R03-R14 and prospective
R10-R14 are reported with lambda*. Read-only except its own output JSON.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import analyze_fp_race_line as RL  # noqa: E402
from evaluate_race_c0_r03_r12 import _model_order  # noqa: E402
from f1_big_predictor.targets.race.c0_score import c0_score  # noqa: E402

DEVD = list(range(3, 10))
PROS = list(range(10, 15))
ALLR = list(range(3, 15))
LAMBDAS = [0, 0.5, 1, 2, 3, 5, 8, 12, 20]


def main() -> None:
    nummap = RL.fpsig.number_map()
    actuals = json.load(open(ROOT / "data/processed/season_2026_actuals/actuals.json"))
    rounds = {int(r["round"]): r for r in actuals["completed_rounds"]}
    race_model = json.load(
        open(ROOT / "outputs/experiments/race/c0_race_r03_r14_d739e6e0/c0_results.json")
    )["results"]["race_optimized_606117e"]["per_round"]

    per_round = {}
    for rn in ALLR:
        target = rounds[rn]
        race_recs = [x for x in target["race_results"]["records"]
                     if x.get("driver_id") and x.get("position") is not None]
        rpos = {x["driver_id"]: int(x["position"]) for x in race_recs}
        actual_order = [x["driver_id"] for x in
                        sorted(race_recs, key=lambda x: int(x["position"]))]
        base_order = _model_order(ROOT, actuals, rn)
        if not base_order:
            continue
        pred_pos = {d: i + 1 for i, d in enumerate(base_order)}
                # grid_pct from actual grid values (not pred order)
        grids = {}
        for x in race_recs:
            g = x.get("grid")
            if isinstance(g, int) and g > 0:
                grids[x["driver_id"]] = g
        gvals = sorted(grids.values())
        g_rank = {d: i + 1 for i, d in enumerate(sorted(grids, key=lambda d: grids[d]))}
        n_grid = len(gvals)
        grid_pct = {d: (g_rank[d] - 0.5) / n_grid for d in grids}

        fp_keys = RL.session_keys(rn, "Practice")
        sq_keys = RL.session_keys(rn, "Sprint Qualifying")
        best = RL.best_by_keys(rn, fp_keys, nummap)
        if sq_keys:
            for d, t in RL.best_by_keys(rn, sq_keys, nummap).items():
                if d not in best or t < best[d]:
                    best[d] = t
        rr = RL.fpsig.rankdata(list(best.values()))
        fp_pct = {d: (r - 0.5) / len(best) for d, r in zip(best.keys(), rr)}

        per_round[rn] = {
            "actual_order": actual_order,
            "pred_pos": pred_pos,
            "grid_pct": grid_pct,
            "fp_pct": fp_pct,
            "base_c0": round(c0_score(base_order, actual_order), 6),
            "race_name": target.get("race_name"),
        }

    def variant_mean(kind: str, lam: float, rounds_sel) -> float:
        vals = []
        for rn in rounds_sel:
            d = per_round[rn]
            keys = []
            for dd in sorted(d["pred_pos"], key=lambda x: d["pred_pos"][x]):
                pp = d["pred_pos"][dd]
                fpv = d["fp_pct"].get(dd, 0.5)
                gv = d["grid_pct"].get(dd, 0.5)
                if kind == "gap":
                    keys.append((pp - lam * (gv - fpv), dd))
                else:
                    keys.append((pp - lam * fpv, dd))
            order = [dd for _, dd in sorted(keys)]
            vals.append(c0_score(order, d["actual_order"]))
        return sum(vals) / len(vals) if vals else float("nan")

    curves = {}
    for kind in ("gap", "fpdirect"):
        curves[kind] = {str(l): round(variant_mean(kind, l, DEVD), 6) for l in LAMBDAS}
    chosen = {}
    for kind in ("gap", "fpdirect"):
        best_l = max(LAMBDAS, key=lambda l: curves[kind][str(l)])
        chosen[kind] = best_l
        full = round(variant_mean(kind, best_l, ALLR), 6)
        pros = round(variant_mean(kind, best_l, PROS), 6)
        base_full = round(sum(per_round[rn]["base_c0"] for rn in ALLR) / len(ALLR), 6)
        base_pros = round(sum(per_round[rn]["base_c0"] for rn in PROS) / len(PROS), 6)
        print(f"{kind:>9}: lambda*={best_l} (dev {curves[kind][str(best_l)]}) | "
              f"R03-R14 {full} (base {base_full}, d={full-base_full:+.4f}) | "
              f"R10-R14 {pros} (base {base_pros}, d={pros-base_pros:+.4f})")
        curves[kind + "_full"] = full
        curves[kind + "_pros"] = pros
        curves["base_full"] = base_full
        curves["base_pros"] = base_pros

    detail = {}
    for kind, lam in chosen.items():
        per = {}
        for rn in ALLR:
            d = per_round[rn]
            keys = []
            for dd in sorted(d["pred_pos"], key=lambda x: d["pred_pos"][x]):
                pp = d["pred_pos"][dd]
                if kind == "gap":
                    keys.append((pp - lam * (d["grid_pct"].get(dd, 0.5) - d["fp_pct"].get(dd, 0.5)), dd))
                else:
                    keys.append((pp - lam * d["fp_pct"].get(dd, 0.5), dd))
            order = [dd for _, dd in sorted(keys)]
            per[rn] = {"c0": round(c0_score(order, d["actual_order"]), 6),
                       "top10": order[:10], "race_name": d["race_name"]}
        detail[kind] = per

    payload = {
        "schema_version": "race.fp_ablation.v1",
        "plan": "fp-race-line report §7 (v1.2)",
        "lambda_grid": LAMBDAS,
        "dev_curves": {k: v for k, v in curves.items() if k in ("gap", "fpdirect")},
        "chosen_lambda": chosen,
        "headline": {k: v for k, v in curves.items() if "full" in k or "pros" in k},
        "per_round_detail": {k: {str(rn): v for rn, v in d.items()} for k, d in detail.items()},
    }
    dest = ROOT / "outputs/experiments/whatif_upgrade/fp_signal_corr_d739e6e0"
    (dest / "race_ablation_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {dest/'race_ablation_results.json'}")


if __name__ == "__main__":
    main()
