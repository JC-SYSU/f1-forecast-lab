#!/usr/bin/env python3
"""FP signal vs RACE prediction: correlation audit (fp-correlation-analysis-plan
race-line extension, kept open by the 2026-09-20 qualifying-line closure).

Read-only. Blocks:
  B'  univariate: rho(fp_rank_pct, race finish pos) per round + pooled;
      fleet version rho(fp_team_pct, constructor race order).
  C1' redundancy: rho(fp_rank_pct, racecraft_std) -- the only race feature
      not yet tested against fp.
  C3' residual: official race model (c0_race_r03_r14_d739e6e0,
      race_optimized_606117e) error vs fp_rank_pct / fp_team_pct, drivers in
      both predicted and actual top-10.

Frozen fp_score v1.0: fastest valid lap across FP(+SQ on sprint weekends),
pit-out excluded, 60 < lap_duration < 240; number map corrections
norris=3 / tsunoda=22.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import analyze_fp_signal_correlation as fpsig  # noqa: E402
from f1_big_predictor.targets.race.optimized_model import (  # noqa: E402
    _extract_racecraft_features,
)

DUR_MIN, DUR_MAX = 60.0, 240.0


def load_list(fp):
    try:
        d = json.load(open(fp))
        return d if isinstance(d, list) else None
    except Exception:
        return None


def session_keys(rn: int, name_filter: str) -> set[int]:
    keys = set()
    pat = ROOT / ("data/raw/openf1_sessions_2026_round_%02d/openf1/*sessions*.json" % rn)
    for f in glob.glob(str(pat)):
        if f.endswith(".meta.json"):
            continue
        d = load_list(f)
        if not d:
            continue
        for s in d:
            if isinstance(s, dict) and name_filter in str(s.get("session_name", "")):
                keys.add(s["session_key"])
    return keys


def best_by_keys(rn: int, keys: set[int], nummap) -> dict[str, float]:
    best: dict[str, float] = {}
    pat = ROOT / ("data/raw/openf1_laps_2026_round_%02d/openf1/*.json" % rn)
    for f in glob.glob(str(pat)):
        if f.endswith(".meta.json"):
            continue
        d = load_list(f)
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


def spearman(a, b) -> float:
    ra, rb = fpsig.rankdata(list(a)), fpsig.rankdata(list(b))
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb) if va and vb else float("nan")


def block_d_gap() -> dict:
    """Block D: fp_gap hypothesis (closure-report §5.1).

    gap = grid_pct - fp_pct  (positive = qualified far better than FP pace,
    i.e. suspected grid overperformance); dropback = race pos - grid pos.
    Hypothesis: rho(gap, dropback) > 0. Also: within-grid-quartile rho
    (does gap carry signal beyond grid position?) and fleet version.
    """
    nummap = fpsig.number_map()
    actuals = json.load(open(ROOT / "data/processed/season_2026_actuals/actuals.json"))
    rounds = {int(r["round"]): r for r in actuals["completed_rounds"]}
    d_rows, team_rows = [], []
    per_round = {}
    for rn in sorted(rounds):
        target = rounds[rn]
        race_recs = [x for x in target["race_results"]["records"]
                     if x.get("driver_id") and x.get("position") is not None]
        best = fpsig.best_by_session(rn, session_keys(rn, "Practice"), nummap)
        sqk = session_keys(rn, "Sprint Qualifying")
        if sqk:
            for d, t in best_by_keys(rn, sqk, nummap).items():
                if d not in best or t < best[d]:
                    best[d] = t
        if not best:
            continue
        rr = fpsig.rankdata(list(best.values()))
        fp_pct = {d: (r - 0.5) / len(best) for d, r in zip(best.keys(), rr)}
        rows = []
        for x in race_recs:
            g = x.get("grid")
            if not isinstance(g, int) or g <= 0:
                continue
            d = x["driver_id"]
            if d not in fp_pct:
                continue
            rows.append({
                "driver_id": d, "constructor_id": x["constructor_id"],
                "grid": g, "pos": int(x["position"]), "fp_pct": fp_pct[d],
            })
        if len(rows) < 10:
            continue
        gr = fpsig.rankdata([r["grid"] for r in rows])
        for r_, g_pct in zip(rows, gr):
            r_["grid_pct"] = (g_pct - 0.5) / len(rows)
            r_["gap"] = r_["grid_pct"] - r_["fp_pct"]
            r_["dropback"] = r_["pos"] - r_["grid"]
        rho = spearman([r["gap"] for r in rows], [float(r["dropback"]) for r in rows])
        pos_rate = sum(1 for r in rows if (r["gap"] > 0) == (r["dropback"] > 0))
        per_round[f"R{rn:02d}"] = {
            "race_name": target.get("race_name"),
            "rho_gap_vs_dropback": round(rho, 4), "n": len(rows),
            "sign_agreement": f"{pos_rate}/{len(rows)}",
        }
        d_rows.extend(rows)
        # fleet: ctor mean grid pct - ctor mean fp pct vs ctor mean dropback
        agg = {}
        for r_ in rows:
            a = agg.setdefault(r_["constructor_id"], {"g": [], "f": [], "d": []})
            a["g"].append(r_["grid_pct"]); a["f"].append(r_["fp_pct"]); a["d"].append(r_["dropback"])
        for c, a in agg.items():
            team_rows.append({
                "ctor": c,
                "gap_team": sum(a["g"]) / len(a["g"]) - sum(a["f"]) / len(a["f"]),
                "dropback_team": sum(a["d"]) / len(a["d"]),
            })

    # grid-quartile stratified rho (value beyond grid position)
    gr_all = fpsig.rankdata([r["grid_pct"] for r in d_rows])
    n = len(d_rows)
    strat = {}
    for tag, sel in (("q1_front", lambda p: p <= 0.25), ("q2", lambda p: 0.25 < p <= 0.5),
                     ("q3", lambda p: 0.5 < p <= 0.75), ("q4_back", lambda p: p > 0.75)):
        sub = [r for r, p in zip(d_rows, gr_all) if sel((p - 0.5) / n)]
        strat[tag] = {
            "n": len(sub),
            "rho_gap_vs_dropback": round(
                spearman([r["gap"] for r in sub], [float(r["dropback"]) for r in sub]), 4
            ) if len(sub) >= 10 else None,
        }

    buckets = {i: [] for i in range(5)}
    for r in d_rows:
        buckets[min(4, int((r["gap"] + 0.5) * 5))].append(r["dropback"])
    bucket_profile = {
        f"gap_bucket_{i}": {
            "n": len(buckets[i]),
            "median_dropback": sorted(buckets[i])[len(buckets[i]) // 2] if buckets[i] else None,
            "mean_dropback": round(sum(buckets[i]) / len(buckets[i]), 2) if buckets[i] else None,
        } for i in range(5)
    }
    return {
        "definition": "gap = grid_pct - fp_pct (positive = qualified better than FP pace); dropback = race_pos - grid_pos",
        "pooled_rho_gap_vs_dropback": round(
            spearman([r["gap"] for r in d_rows], [float(r["dropback"]) for r in d_rows]), 4),
        "n": len(d_rows),
        "per_round": per_round,
        "grid_quartile_stratified": strat,
        "bucket_profile": bucket_profile,
        "fleet": {
            "n": len(team_rows),
            "rho_gap_team_vs_dropback_team": round(
                spearman([r["gap_team"] for r in team_rows],
                         [float(r["dropback_team"]) for r in team_rows]), 4),
        },
    }


def main() -> None:
    nummap = fpsig.number_map()
    actuals = json.load(open(ROOT / "data/processed/season_2026_actuals/actuals.json"))
    rounds = {int(r["round"]): r for r in actuals["completed_rounds"]}
    completed = sorted(rounds.values(), key=lambda r: int(r["round"]))
    race_model = json.load(
        open(ROOT / "outputs/experiments/race/c0_race_r03_r14_d739e6e0/c0_results.json")
    )["results"]["race_optimized_606117e"]["per_round"]

    b_per, bf_per = {}, []
    c1_rows, c3_rows, c3f_rows = [], [], []
    pooled_b, pooled_bf = ([], []), ([], [])

    for rn in sorted(rounds):
        target = rounds[rn]
        race_recs = [x for x in target["race_results"]["records"]
                     if x.get("driver_id") and x.get("position") is not None]
        rpos = {x["driver_id"]: int(x["position"]) for x in race_recs}
        field = len(race_recs)

        fp_keys = session_keys(rn, "Practice")
        sq_keys = session_keys(rn, "Sprint Qualifying")
        best = best_by_keys(rn, fp_keys, nummap)
        if sq_keys:
            for d, t in best_by_keys(rn, sq_keys, nummap).items():
                if d not in best or t < best[d]:
                    best[d] = t
        if not best:
            continue
        rr = fpsig.rankdata(list(best.values()))
        fp_pct = {d: (r - 0.5) / len(best) for d, r in zip(best.keys(), rr)}

        # B' driver-level
        pairs = [(fp_pct[d], rpos[d]) for d in sorted(set(fp_pct) & set(rpos))]
        if len(pairs) >= 5:
            rho = spearman([p[0] for p in pairs], [float(p[1]) for p in pairs])
            b_per[f"R{rn:02d}"] = {"race_name": target.get("race_name"),
                                   "rho": round(rho, 4), "n": len(pairs)}
            pooled_b[0].extend(p[0] for p in pairs)
            pooled_b[1].extend(float(p[1]) for p in pairs)

        # B' fleet-level: constructor mean finish order vs fp_team_pct
        agg: dict[str, list[float]] = {}
        members: dict[str, list[str]] = {}
        for x in race_recs:
            agg.setdefault(x["constructor_id"], []).append(int(x["position"]))
            members.setdefault(x["constructor_id"], []).append(x["driver_id"])
        ctor_mean = {c: sum(v) / len(v) for c, v in agg.items()}
        ctor_rank = {c: i + 1 for i, c in enumerate(sorted(ctor_mean, key=lambda c: ctor_mean[c]))}
        fp_team = {}
        for c, ms in members.items():
            vals = [fp_pct[m] for m in ms if m in fp_pct]
            if len(vals) == len(ms) and vals:
                fp_team[c] = sum(vals) / len(vals)
        pairs_f = [(fp_team[c], ctor_rank[c]) for c in sorted(set(fp_team) & set(ctor_rank))]
        if len(pairs_f) >= 5:
            rho_f = spearman([p[0] for p in pairs_f], [float(p[1]) for p in pairs_f])
            bf_per.append({"rn": rn, "rho": round(rho_f, 4), "n": len(pairs_f)})
            pooled_bf[0].extend(p[0] for p in pairs_f)
            pooled_bf[1].extend(float(p[1]) for p in pairs_f)

        # C1' redundancy with racecraft
        racecraft = _extract_racecraft_features(completed, rn)
        for d in sorted(set(fp_pct) & set(racecraft) & set(rpos)):
            c1_rows.append({"fp_pct": fp_pct[d], "racecraft": racecraft[d]})

        # C3' residual vs official race model
        pm = race_model.get(str(rn))
        if not pm or pm.get("status") != "scored":
            continue
        pred_pos = {d: i + 1 for i, d in enumerate(pm["predicted_top10"])}
        for did in pred_pos:
            if did in rpos and rpos[did] <= 10 and did in fp_pct:
                c3_rows.append({"fp_pct": fp_pct[did],
                                "residual": rpos[did] - pred_pos[did]})
        for cid, ms in members.items():
            if cid not in ctor_rank or cid not in fp_team:
                continue
            preds = [pred_pos[m] for m in ms if m in pred_pos]
            if not preds:
                continue
            team_pred = min(preds)
            c3f_rows.append({"fp_team": fp_team[cid],
                             "residual": ctor_rank[cid] - team_pred})

    out = {
        "schema_version": "fp_corr_analysis.race_line.v1",
        "plan": "fp-correlation-analysis-plan race-line extension (kept open by the qualifying-line closure)",
        "b_per_round": b_per,
        "pooled_b_driver": round(spearman(*pooled_b), 4),
        "positive_round_rate_b": f"{sum(1 for v in b_per.values() if v['rho'] > 0)}/{len(b_per)}",
        "bf_per_round": bf_per,
        "pooled_bf_fleet": round(spearman(*pooled_bf), 4),
        "c1_redundancy_racecraft": round(
            spearman([r["fp_pct"] for r in c1_rows],
                     [r["racecraft"] for r in c1_rows]), 4) if len(c1_rows) > 5 else None,
        "c1_n": len(c1_rows),
        "c3_residual": {
            "n": len(c3_rows),
            "rho_fp_vs_residual": round(
                spearman([r["fp_pct"] for r in c3_rows],
                         [r["residual"] for r in c3_rows]), 4) if len(c3_rows) > 5 else None,
            "n_fleet": len(c3f_rows),
            "rho_fpteam_vs_residual": round(
                spearman([r["fp_team"] for r in c3f_rows],
                         [r["residual"] for r in c3f_rows]), 4) if len(c3f_rows) > 5 else None,
        },
    }
    dest = ROOT / "outputs/experiments/whatif_upgrade/fp_signal_corr_d739e6e0"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "fp_corr_stats_race.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=1))
    d = block_d_gap()
    (dest / "fp_gap_test_D.json").write_text(
        json.dumps({"schema_version": "fp_corr_analysis.blockD.v1", **d},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\nBlock D (fp_gap hypothesis):")
    print(json.dumps(d, ensure_ascii=False, indent=1))
    print(f"\nwrote {dest/'fp_gap_test_D.json'}")


if __name__ == "__main__":
    main()
