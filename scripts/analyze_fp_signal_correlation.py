#!/usr/bin/env python3
"""FP fastest-lap signal correlation audit -- block A (driver-level, R01-R14).

PLAN-FP-CORR-ANALYSIS-001. Read-only: openf1_laps/sessions archives +
actuals.json. No modelling, no src changes.

Signal: fp_best(d,N) = fastest valid lap across FP1/FP2/FP3 (is_pit_out_lap
false, 60 < lap_duration < 240); fp_rank = field order by fp_best.

Driver-number mapping (verified 2026-09-20):
  grid.json racing_number table, with two OpenF1-side corrections:
  norris carries #3 on OpenF1 (R01 FP1 has no #4; #3 present every round),
  tsunoda carries #22 (first appears R12, matching the seat entry).
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DUR_MIN, DUR_MAX = 60.0, 240.0


def load_list(fp: str):
    try:
        d = json.load(open(fp))
        return d if isinstance(d, list) else None
    except Exception:
        return None


def number_map() -> dict[int, str]:
    grid = json.load(open(ROOT / "data/manual/2026_grid.json"))
    m = {x["racing_number"]: x["driver_id"] for x in grid["drivers"]}
    del m[4]
    m[3] = "norris"
    m[22] = "tsunoda"
    return m


def fp_keys(rn: int) -> set[int]:
    keys = set()
    for f in glob.glob(str(ROOT / f"data/raw/openf1_sessions_2026_round_{rn:02d}/openf1/*sessions*.json")):
        if f.endswith(".meta.json"):
            continue
        d = load_list(f)
        if not d:
            continue
        for s in d:
            if isinstance(s, dict) and "Practice" in str(s.get("session_name", "")):
                keys.add(s["session_key"])
    return keys


def fp_best_by_driver(rn: int, nummap: dict[int, str]) -> dict[str, float]:
    keys = fp_keys(rn)
    best: dict[str, float] = {}
    pat = ROOT / ("data/raw/openf1_laps_2026_round_%02d/openf1/*.json" % rn)
    for fp in glob.glob(str(pat)):
        if fp.endswith(".meta.json"):
            continue
        d = load_list(fp)
        if not d or d[0].get("session_key") not in keys:
            continue
        for x in d:
            if x.get("is_pit_out_lap"):
                continue
            t = x.get("lap_duration")
            if not isinstance(t, (int, float)) or not (DUR_MIN < t < DUR_MAX):
                continue
            did = nummap.get(x.get("driver_number"))
            if did is None:
                continue
            if did not in best or t < best[did]:
                best[did] = float(t)
    return best


def rankdata(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float:
    ra, rb = rankdata(a), rankdata(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb) if va and vb else float("nan")


def sq_keys(rn: int) -> set[int]:
    keys = set()
    pat = ROOT / ("data/raw/openf1_sessions_2026_round_%02d/openf1/*sessions*.json" % rn)
    for f in glob.glob(str(pat)):
        if f.endswith(".meta.json"):
            continue
        d = load_list(f)
        if not d:
            continue
        for s in d:
            if isinstance(s, dict) and s.get("session_name") == "Sprint Qualifying":
                keys.add(s["session_key"])
    return keys


def best_by_session(rn: int, keys: set[int], nummap: dict[int, str]) -> dict[str, float]:
    best: dict[str, float] = {}
    pat = ROOT / ("data/raw/openf1_laps_2026_round_%02d/openf1/*.json" % rn)
    for fp in glob.glob(str(pat)):
        if fp.endswith(".meta.json"):
            continue
        d = load_list(fp)
        if not d or d[0].get("session_key") not in keys:
            continue
        for x in d:
            if x.get("is_pit_out_lap"):
                continue
            t = x.get("lap_duration")
            if not isinstance(t, (int, float)) or not (DUR_MIN < t < DUR_MAX):
                continue
            did = nummap.get(x.get("driver_number"))
            if did is None:
                continue
            if did not in best or t < best[did]:
                best[did] = float(t)
    return best


def block_a2_sprint() -> dict:
    """Sprint weekends: FP1-only signal vs FP1+SQ pooled signal (user idea:
    SQ counts as a second practice session). Causal: SQ precedes Q."""
    nummap = number_map()
    actuals = json.load(open(ROOT / "data/processed/season_2026_actuals/actuals.json"))
    rounds = {int(r["round"]): r for r in actuals["completed_rounds"]}
    out = {}
    for rn in sorted(rounds):
        sq = sq_keys(rn)
        if not sq:
            continue
        target = rounds[rn]
        qpos = {
            x["driver_id"]: int(x["position"])
            for x in target["qualifying_results"]["records"]
            if x.get("driver_id") and x.get("position") is not None
        }
        fp_best = best_by_session(rn, fp_keys(rn), nummap)
        sq_best = best_by_session(rn, sq, nummap)
        combo = {d: min(fp_best.get(d, 1e9), sq_best.get(d, 1e9)) for d in set(fp_best) | set(sq_best)}
        combo = {d: t for d, t in combo.items() if t < 1e9}
        def rho(sig: dict[str, float]) -> float | None:
            pairs = [(sig[d], qpos[d]) for d in sorted(set(sig) & set(qpos))]
            if len(pairs) < 5:
                return None
            return spearman([p[0] for p in pairs], [p[1] for p in pairs])
        out[rn] = {
            "race_name": target.get("race_name"),
            "rho_fp_only": round(rho(fp_best), 4),
            "rho_fp_plus_sq": round(rho(combo), 4),
            "n_sq_drivers": len(sq_best),
            "n_fp_drivers": len(fp_best),
        }
    pooled_fp_f, pooled_fp_q, pooled_c_f, pooled_c_q = [], [], [], []
    for rn, v in out.items():
        pass
    # pooled over sprint rounds using within-round rank percentiles
    # (raw lap seconds are NOT comparable across circuits of different length)
    for sig_tag, with_sq in (("fp_only", False), ("fp_plus_sq", True)):
        f_all, q_all = [], []
        for rn in [k for k in out if isinstance(k, int)]:
            keys = fp_keys(rn) | (sq_keys(rn) if with_sq else set())
            sig = best_by_session(rn, keys, nummap)
            qpos = {
                x["driver_id"]: int(x["position"])
                for x in rounds[rn]["qualifying_results"]["records"]
                if x.get("driver_id") and x.get("position") is not None
            }
            pairs = [(sig[d], qpos[d]) for d in sorted(set(sig) & set(qpos))]
            if len(pairs) < 5:
                continue
            rr = rankdata([p[0] for p in pairs])
            n = len(pairs)
            f_all.extend((r - 0.5) / n for r in rr)
            q_all.extend((p[1] - 0.5) / n for p in pairs)
        out[f"pooled_{sig_tag}"] = round(spearman(f_all, q_all), 4)
    return out


def block_c_incremental() -> dict:
    """Block C: is the FP signal worth anything beyond existing features?

    C1 redundancy: Spearman(fp_rank_pct, form/constructor/circuit_fit scores).
    C2 conditional correlation: within form terciles, rho(fp_rank_pct, qpos).
    C3 residual correlation: official #31 (caliber 92076830) prediction error
       vs fp_rank_pct, for drivers present in both the predicted and actual
       top-10.
    """
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from f1_big_predictor.targets.qualifying.features import build_qualifying_features

    nummap = number_map()
    actuals = json.load(open(ROOT / "data/processed/season_2026_actuals/actuals.json"))
    rounds = {int(r["round"]): r for r in actuals["completed_rounds"]}

    scorecard = json.load(
        open(
            glob.glob(
                str(ROOT / "outputs/experiments/qualifying/c0_roster_r03_r14_*/c0_results.json")
            )[0]
        )
    )
    c31 = next(c for c in scorecard["candidates"] if c["spec"]["ordinal"] == 31)

    rows_c1 = []
    resid_rows = []
    form_terciles: dict[str, list] = {"low": [], "mid": [], "high": []}
    for rn in sorted(rounds):
        best = fp_best_by_driver(rn, nummap)
        if not best:
            continue
        fp_keys_n = fp_keys(rn)
        if sq_keys(rn):
            sq_best = best_by_session(rn, sq_keys(rn), nummap)
            for d, t in sq_best.items():
                if d not in best or t < best[d]:
                    best[d] = t
        rr = rankdata(list(best.values()))
        fp_pct = {d: (r - 0.5) / len(best) for d, r in zip(best.keys(), rr)}

        feat = build_qualifying_features(
            project_root=ROOT, target_round=rn, officialize_actuals=False
        )
        frows = {
            r["driver_id"]: r
            for r in feat.get("rows", [])
            if r.get("driver_id") in fp_pct
        }
        qpos = {
            x["driver_id"]: int(x["position"])
            for x in rounds[rn]["qualifying_results"]["records"]
            if x.get("driver_id") and x.get("position") is not None
        }
        for did, fr in frows.items():
            if did not in qpos or did not in fp_pct:
                continue
            rows_c1.append(
                {
                    "rn": rn,
                    "driver_id": did,
                    "fp_pct": fp_pct[did],
                    "qpos": qpos[did],
                    "form": fr.get("form_score"),
                    "ctor": fr.get("constructor_score"),
                    "circuit_fit": fr.get("circuit_fit_score"),
                }
            )

        pred_top10 = (c31["rounds"].get(str(rn)) or {}).get("prediction_top10")
        if pred_top10:
            pred_pos = {d: i + 1 for i, d in enumerate(pred_top10)}
            for did in pred_top10:
                if did in qpos and qpos[did] <= 10 and did in fp_pct:
                    resid_rows.append(
                        {
                            "rn": rn,
                            "fp_pct": fp_pct[did],
                            "residual": qpos[did] - pred_pos[did],
                        }
                    )

    def _pair(rows, key_a, key_b):
        a = [r[key_a] for r in rows if r.get(key_a) is not None and r.get(key_b) is not None]
        b = [r[key_b] for r in rows if r.get(key_a) is not None and r.get(key_b) is not None]
        return (a, b)

    c1 = {}
    for tag in ("form", "ctor", "circuit_fit"):
        a, b = _pair(rows_c1, "fp_pct", tag)
        c1[f"fp_vs_{tag}"] = round(spearman(a, b), 4) if len(a) > 5 else None
        c1[f"n_{tag}"] = len(a)

    forms = sorted(r["form"] for r in rows_c1 if r.get("form") is not None)
    t1, t2 = forms[len(forms) // 3], forms[2 * len(forms) // 3]
    c2 = {}
    for tag, sel in (
        ("low", lambda v: v is not None and v <= t1),
        ("mid", lambda v: v is not None and t1 < v <= t2),
        ("high", lambda v: v is not None and v > t2),
    ):
        sub = [r for r in rows_c1 if sel(r.get("form"))]
        a = [r["fp_pct"] for r in sub]
        b = [float(r["qpos"]) for r in sub]
        c2[f"form_{tag}"] = (
            {"n": len(sub), "rho_fp_vs_qpos": round(spearman(a, b), 4)}
            if len(sub) > 5
            else {"n": len(sub), "rho_fp_vs_qpos": None}
        )

    a = [r["fp_pct"] for r in resid_rows]
    b = [float(r["residual"]) for r in resid_rows]
    c3 = {"n": len(resid_rows), "rho_fp_vs_residual": round(spearman(a, b), 4) if len(a) > 5 else None}

    return {"c1_redundancy": c1, "c2_conditional": c2, "c3_residual": c3, "form_cutpoints": [t1, t2]}


def main() -> None:
    nummap = number_map()
    actuals = json.load(open(ROOT / "data/processed/season_2026_actuals/actuals.json"))
    rounds = {int(r["round"]): r for r in actuals["completed_rounds"]}

    per_round = {}
    for rn in sorted(rounds):
        best = fp_best_by_driver(rn, nummap)
        target = rounds[rn]
        qpos = {
            x["driver_id"]: int(x["position"])
            for x in target["qualifying_results"]["records"]
            if x.get("driver_id") and x.get("position") is not None
        }
        field_size = len(target["race_results"]["records"])
        pairs = [(best[d], qpos[d]) for d in sorted(set(best) & set(qpos))]
        no_fp = sorted(set(qpos) - set(best))
        if len(pairs) < 5:
            per_round[rn] = {"status": "insufficient_overlap", "n_pairs": len(pairs)}
            continue
        fbest = [p[0] for p in pairs]
        qposv = [p[1] for p in pairs]
        rho = spearman(fbest, qposv)
        # in-round rank percentile of fp for bucketing
        rr = rankdata(fbest)
        n = len(fbest)
        perc = [(r - 0.5) / n for r in rr]
        per_round[rn] = {
            "status": "ok",
            "race_name": target.get("race_name"),
            "n_pairs": n,
            "field_size": field_size,
            "spearman_rho": round(rho, 4),
            "fp_percentile": perc,
            "qpos_percentile": [ (p - 0.5) / field_size for p in qposv ],
            "drivers_without_fp": no_fp,
        }

    ok = {rn: v for rn, v in per_round.items() if v.get("status") == "ok"}
    all_fp, all_q = [], []
    for rn, v in ok.items():
        all_fp.extend(v["fp_percentile"])
        all_q.extend(v["qpos_percentile"])
    pooled = spearman(all_fp, all_q)
    pos_rate = sum(1 for v in ok.values() if v["spearman_rho"] > 0)

    seg1 = [rn for rn in ok if 3 <= rn <= 9]
    seg2 = [rn for rn in ok if rn >= 10]
    seg = {}
    for tag, sel in (("r03_r09", seg1), ("r10_r14", seg2)):
        f = [x for rn in sel for x in ok[rn]["fp_percentile"]]
        q = [x for rn in sel for x in ok[rn]["qpos_percentile"]]
        seg[tag] = {"n_rounds": len(sel), "spearman_rho": round(spearman(f, q), 4)} if sel else None

    buckets = {i: [] for i in range(5)}
    for v in ok.values():
        for p, q in zip(v["fp_percentile"], v["qpos_percentile"]):
            buckets[min(4, int(p * 5))].append(q)
    bucket_profile = {
        f"fp_pct_bucket_{i}_{lo:.0f}-{hi:.0f}": {
            "n": len(buckets[i]),
            "mean_qpos_pct": round(sum(buckets[i]) / len(buckets[i]), 4) if buckets[i] else None,
        }
        for i, (lo, hi) in enumerate([(0, 20), (20, 40), (40, 60), (60, 80), (80, 100)])
    }

    out = {
        "schema_version": "fp_corr_analysis.blockA.v1",
        "plan": "PLAN-FP-CORR-ANALYSIS-001",
        "signal": "fp_best = fastest valid lap across FP1/2/3 (pit-out excluded, 60<lap_duration<240); fp_rank per round",
        "number_map_corrections": {"3": "norris (OpenF1 side; R01 FP1 has no #4, #3 all season)", "22": "tsunoda (first appears R12)"},
        "rounds": {str(k): v for k, v in per_round.items()},
        "pooled_spearman": round(pooled, 4),
        "positive_round_rate": f"{pos_rate}/{len(ok)}",
        "segments": seg,
        "bucket_profile": bucket_profile,
    }
    dest = ROOT / "outputs/experiments/whatif_upgrade/fp_signal_corr_d739e6e0"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "fp_corr_stats_A.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in out.items() if k != "rounds"}, ensure_ascii=False, indent=1))
    print("\nper-round rho:")
    for rn, v in ok.items():
        print(f"  R{rn:02d} {v['race_name']:<26} rho={v['spearman_rho']:+.4f} n={v['n_pairs']} noFP={v['drivers_without_fp'] or '-'}")
    print(f"\nwrote {dest/'fp_corr_stats_A.json'}")
    a2 = block_a2_sprint()
    (dest / "fp_corr_stats_A2_sprint.json").write_text(
        json.dumps({"schema_version": "fp_corr_analysis.blockA2.v1",
                    "idea": "sprint weekends: SQ fastest lap counts as a second FP session (causal: SQ precedes Q)",
                    "sprint_rounds": {str(k): v for k, v in a2.items()}}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("\nA2 sprint-weekend comparison:")
    for rn, v in a2.items():
        if isinstance(v, dict):
            print(f"  R{rn:02d} {v['race_name']:<24} FP-only {v['rho_fp_only']:+.4f} -> FP+SQ {v['rho_fp_plus_sq']:+.4f}  (sq drv {v['n_sq_drivers']}, fp drv {v['n_fp_drivers']})")
        else:
            print(f"  {rn}: {v}")
    print(f"\nwrote {dest/'fp_corr_stats_A2_sprint.json'}")
    c = block_c_incremental()
    (dest / "fp_corr_stats_C.json").write_text(
        json.dumps({"schema_version": "fp_corr_analysis.blockC.v1", **c},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\nBlock C:")
    print(json.dumps(c, ensure_ascii=False, indent=1))
    print(f"\nwrote {dest/'fp_corr_stats_C.json'}")


if __name__ == "__main__":
    main()
