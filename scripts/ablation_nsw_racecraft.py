#!/usr/bin/env python3
"""ST-2: NSW racecraft-source scan at the 606117e formula slot (race-nsw plan).

For each round, call compute_grid_delta_features ONCE to get all 208 variant
columns; for each variant, build the race prediction with the formula
  pred = grid - 3*form_z - 2*variant_z - 3*max(0,grid-10)*ctor_raw
(z-scores within the round's field, same as _model_order), score C0 against
the actual order, and compare with the official baseline (racecraft source =
optimized_model._extract_racecraft_features, i.e. N2f6_S0_Wexp semantics).

Drivers with a None variant value fall back to the official racecraft source.
Read-only except its own output JSON.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from evaluate_race_c0_r03_r12 import _model_order  # noqa: E402
from f1_big_predictor.targets.race.c0_score import c0_score  # noqa: E402
from f1_big_predictor.targets.race.grid_delta_features import (  # noqa: E402
    compute_grid_delta_features,
)
from f1_big_predictor.targets.qualifying.features import (  # noqa: E402
    build_qualifying_features,
)
from f1_big_predictor.targets.race.optimized_model import (  # noqa: E402
    _extract_racecraft_features,
)

ALLR = list(range(3, 15))
PROS = list(range(10, 15))


def zscore_map(values: dict[str, float]) -> dict[str, float]:
    vs = list(values.values())
    if len(vs) < 2:
        return {k: 0.0 for k in values}
    m = mean(vs)
    sd = stdev(vs)
    return {k: ((v - m) / sd if sd > 0 else 0.0) for k, v in values.items()}


def main() -> None:
    actuals = json.load(open(ROOT / "data/processed/season_2026_actuals/actuals.json"))
    rounds = {int(r["round"]): r for r in actuals["completed_rounds"]}

    per_round = {}
    for rn in ALLR:
        target = rounds[rn]
        race_recs = [x for x in target["race_results"]["records"]
                     if x.get("driver_id") and x.get("position") is not None]
        actual_order = [x["driver_id"] for x in
                        sorted(race_recs, key=lambda x: int(x["position"]))]

        base_order = _model_order(ROOT, actuals, rn)
        official_rc = _extract_racecraft_features(actuals["completed_rounds"], rn)

        qual = build_qualifying_features(
            project_root=ROOT, target_round=rn, officialize_actuals=False
        )
        qfeat = {
            r["driver_id"]: {
                "form": r.get("form_score") or 0.0,
                "ctor": r.get("constructor_score") or 0.0,
            }
            for r in qual.get("rows", [])
        }
        gd_rows = compute_grid_delta_features(rn, actuals["completed_rounds"])
        variant_vals: dict[str, dict[str, float]] = {}
        for row in gd_rows:
            did = row["driver_id"]
            for v in row:
                if v in ("driver_id", "grid_position", "actual_finish"):
                    continue
                val = row[v]
                if isinstance(val, (int, float)):
                    variant_vals.setdefault(v, {})[did] = float(val)

        # prediction inputs per driver (formula consumers need grid+form+ctor)
        inputs = {}
        for rec in race_recs:
            did = rec["driver_id"]
            g = rec.get("grid")
            if not isinstance(g, int) or g <= 0 or did not in qfeat:
                continue
            inputs[did] = {"grid": g,
                           "form_raw": qfeat[did]["form"],
                           "ctor_raw": qfeat[did]["ctor"]}

        fv = [v["form_raw"] for v in inputs.values()]
        fm, fs = mean(fv), (stdev(fv) if len(fv) > 1 else 1.0)
        form_z = {d: ((v["form_raw"] - fm) / fs if fs > 0 else 0.0)
                  for d, v in inputs.items()}

        # official racecraft z (baseline source)
        off_map = {d: official_rc.get(d, official_rc.get(d, 0.5)) for d in inputs}
        off_map = {d: official_rc.get(d, 0.5) for d in inputs}
        off_z = zscore_map(off_map)

        per_round[rn] = {
            "actual_order": actual_order,
            "inputs": inputs,
            "form_z": form_z,
            "official_rc_z": off_z,
            "variants": variant_vals,
            "race_name": target.get("race_name"),
        }

    # baseline (official source) — verify against d739e6e0 per-round c0
    base_model = json.load(
        open(ROOT / "outputs/experiments/race/c0_race_r03_r14_d739e6e0/c0_results.json")
    )["results"]["race_optimized_606117e"]["per_round"]

    def eval_variant(source_getter) -> dict:
        per, vals_all, vals_pros = {}, [], []
        for rn in ALLR:
            d = per_round[rn]
            scored = []
            for did, inp in d["inputs"].items():
                rc_off = d["official_rc_z"].get(did, 0.0)
                rc = source_getter(did, d, rc_off)
                boost = max(0, inp["grid"] - 10) * inp["ctor_raw"]
                pred = (inp["grid"] - 3.0 * d["form_z"].get(did, 0.0)
                        - 2.0 * rc - 3.0 * boost)
                scored.append((pred, did))
            scored.sort(key=lambda x: x[0])
            order = [d_ for _, d_ in scored]
            c0 = c0_score(order, d["actual_order"])
            per[rn] = {"c0": round(c0, 6), "top10": order[:10]}
            vals_all.append(c0)
            if rn in PROS:
                vals_pros.append(c0)
        return {
            "mean_r03_r14": round(sum(vals_all) / len(vals_all), 6),
            "mean_r10_r14": round(sum(vals_pros) / len(vals_pros), 6),
            "per_round": per,
        }

    base = eval_variant(lambda did, d, rc_off: rc_off)
    scan = {"official_baseline": base}
    for vname in sorted(next(iter(per_round.values()))["variants"].keys()):
        res = eval_variant(
            lambda did, d, rc_off, _v=vname: zscore_map(
                {k2: v2 for k2, v2 in d["variants"][_v].items()}
            ).get(did, rc_off)
        )
        res["delta_full_vs_base"] = round(res["mean_r03_r14"] - base["mean_r03_r14"], 6)
        res["delta_pros_vs_base"] = round(res["mean_r10_r14"] - base["mean_r10_r14"], 6)
        scan[vname] = res

    base_chk = [abs(base["per_round"][rn]["c0"] - base_model[str(rn)]["c0"])
                for rn in ALLR]
    assert max(base_chk) < 1e-6, f"baseline mismatch: {max(base_chk)}"

    ranked = sorted(
        ((v, r["mean_r03_r14"], r["delta_full_vs_base"], r["delta_pros_vs_base"])
         for v, r in scan.items() if v != "official_baseline"),
        key=lambda x: -x[1],
    )
    print(f"baseline (official source): full {base['mean_r03_r14']} | pros {base['mean_r10_r14']}")
    print(f"top 15 variants (of {len(ranked)}):")
    for v, m, df, dp in ranked[:15]:
        print(f"  {v:<18} full {m:.6f}  d_full {df:+.4f}  d_pros {dp:+.4f}")
    winners = [v for v, m, df, dp in ranked if dp >= 0.010]
    print(f"prospective gate (d_pros>=+0.010) winners: {winners or 'NONE'}")

    dest = ROOT / "outputs/experiments/race/nsw_racecraft_scan_035117f2"
    dest.mkdir(parents=True, exist_ok=True)
    slim = {v: {k: r.get(k, 0.0 if "delta" in k else r.get(k))
                for k in ("mean_r03_r14", "mean_r10_r14",
                          "delta_full_vs_base", "delta_pros_vs_base")}
            for v, r in scan.items()}
    (dest / "nsw_scan.json").write_text(
        json.dumps({"schema_version": "race.nsw_scan.v1",
                    "plan": "race-nsw plan ST-2",
                    "n_variants": len(ranked),
                    "scan": slim,
                    "baseline_verification_max_abs_diff": max(base_chk)},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {dest/'nsw_scan.json'}")


if __name__ == "__main__":
    main()
