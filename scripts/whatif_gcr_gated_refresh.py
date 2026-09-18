#!/usr/bin/env python3
"""GCR experiment: gated constructor-strength refresh ("reassess constructors after time apart").

Protocol: EXP-WHATIF-UPGRADE-CORRECTION-001 §6 addendum (2026-09-05, user-approved).
Mainline untouched: every arm is an in-memory monkey-patch of the two constructor
feature paths; donors re-fit on transformed features; C0 yardstick frozen.

Locked design (user decisions):
  - event ledger = human news archive only (seat swaps excluded)
  - k = 3 (post = t - E >= 3; event round E counts as first evidence round)
  - no outlier-round exclusion
  - arms: A0 baseline, A1 full switch, A2 gradual m=3, A3 gradual m=6,
          A1f/A2f false-event stress (seeded random ledger, avoids real cells)
"""
from __future__ import annotations

import json
import random
from statistics import mean as _m
from pathlib import Path

import f1_big_predictor.targets.qualifying.features as F
import f1_big_predictor.targets.qualifying.feature_matrix as FM
from f1_big_predictor.targets._shared import driver_ids
from f1_big_predictor.targets.qualifying.official_labels import (
    load_officialized_actuals,
    official_records_for_round,
)
from f1_big_predictor.targets.qualifying.model import score_qualifying_field
from f1_big_predictor.targets.qualifying.types import QualifyingFeatureConfig
from f1_big_predictor.targets.qualifying.elastic_net_model import predict_elastic_net
from f1_big_predictor.targets.qualifying.lambdamart_model import predict_lambdamart
from f1_big_predictor.targets.qualifying.c0_scorer import score_qualifying
from f1_big_predictor.targets.qualifying.walk_forward_slot_ensemble import (
    _EXP_TUNED_INDEPENDENT, _CIRCUIT_T5_WEIGHTS, _LTR_N100_PARAMS,
    _set_first, _top_down,
)
from f1_big_predictor.targets.race.c0_score import c0_score
import f1_big_predictor.targets.race.optimized_model as OM

ROOT = Path(__file__).resolve().parents[1]
ROUNDS = list(range(3, 13))
K = 3  # confirmed rounds required before refresh engages

LEDGER = {  # news archive RES-CONSTRUCTOR-SHIFT-EVENTS (pace-affecting only)
    "mercedes": [5], "ferrari": [4, 7, 8], "mclaren": [4, 11],
    "red_bull": [4, 7], "aston_martin": [11, 12], "alpine": [12],
}

actuals = load_officialized_actuals(ROOT)
CUM: dict[str, dict[int, float]] = {}
for r in actuals["completed_rounds"]:
    rr = int(r["round"])
    for x in r["constructor_standings"]["records"]:
        CUM.setdefault(x["constructor_id"], {})[rr] = float(x["points"])
TEAMS = list(CUM)


def _cum(t, rr):
    table = CUM.get(t, {})
    rr = max(1, min(rr, 12))
    for probe in [rr, *[q for q in range(rr - 1, 0, -1)]]:
        if probe in table:
            return table[probe]
    return 0.0


def _inc(t, rr):
    return _cum(t, rr) - _cum(t, rr - 1)


def _norm(vals):
    mx = max(vals.values()) or 1.0
    return {t: v / mx for t, v in vals.items()}


def base_norm(rr):
    return _norm({t: _cum(t, rr) for t in TEAMS})


def regime_start(team, rr, ledger):
    """latest event E with post = (rr+1) - E >= K; None if none fired."""
    evs = [E for E in ledger.get(team, []) if (rr + 1) - E >= K]
    return max(evs) if evs else None


def make_gcr(ledger, mode, m):
    """Protocol §6: regime value = team's post-event point sum normalized by the
    max over ALL teams within that same window length (per-team window, fair scale)."""
    def variant(rr):
        out = base_norm(rr)
        for t in TEAMS:
            E = regime_start(t, rr, ledger)
            if E is None:
                continue
            post = (rr + 1) - E
            win = _norm({s: sum(_inc(s, q) for q in range(rr - post + 1, rr + 1))
                         for s in TEAMS})
            if mode == "full":
                out[t] = win[t]
            else:
                w = post / (post + m)
                out[t] = w * win[t] + (1 - w) * base_norm(rr)[t]
        return out
    return variant


def fake_ledger(seed=20260905):
    rng = random.Random(seed)
    teams = rng.sample(TEAMS, 6)
    led = {}
    for t in teams:
        real = set(LEDGER.get(t, []))
        opts = [r for r in range(3, 11) if r not in real]
        led[t] = [rng.choice(opts)]
    return led


ARMS = {
    "A0_baseline": lambda rr: base_norm(rr),
    "A1_full_switch": make_gcr(LEDGER, "full", 0),
    "A2_gradual_m3": make_gcr(LEDGER, "gradual", 3),
    "A3_gradual_m6": make_gcr(LEDGER, "gradual", 6),
    "A1f_false_full": make_gcr(fake_ledger(), "full", 0),
    "A2f_false_gradual_m3": make_gcr(fake_ledger(), "gradual", 3),
}

_orig_F = F._constructor_scores
_orig_FM = FM._constructor_standings_pts


def _install(variant):
    def f_scores(payload):
        rr = int(payload["round"])
        vals = variant(rr)
        return {x["constructor_id"]: vals.get(x["constructor_id"], 0.0)
                for x in payload["constructor_standings"]["records"]}

    def fm_pts(completed_rounds, after_round):
        orig = _orig_FM(completed_rounds, after_round)
        vals = variant(int(after_round))
        return {t: vals.get(t, 0.0) * 400.0 for t in orig}

    F._constructor_scores = f_scores
    FM._constructor_standings_pts = fm_pts


def _uninstall():
    F._constructor_scores = _orig_F
    FM._constructor_standings_pts = _orig_FM


# ------------------------------------------------------------- ground truth
raw = json.loads((ROOT / "data/processed/season_2026_actuals/actuals.json").read_text())
raw_by = {int(r["round"]): r for r in raw["completed_rounds"]}
LABELS = {}
Q_TRUTH = {}
RACE = {}
for rn in ROUNDS:
    if rn <= 9:
        recs, fs = official_records_for_round(ROOT, rn)
    else:
        recs = [{"driver_id": x["driver_id"], "position": x.get("position"),
                 "classification_status": x.get("status") or "Classified"}
                for x in raw_by[rn]["qualifying_results"]["records"]]
        fs = len(recs)
    LABELS[rn] = (recs, fs)
    Q_TRUTH[rn] = {r["driver_id"]: r["position"] for r in recs if r.get("position")}
    rrecs = sorted((x for x in raw_by[rn]["race_results"]["records"]
                    if x.get("position") is not None), key=lambda x: int(x["position"]))
    RACE[rn] = {"order": [x["driver_id"] for x in rrecs],
                "grid": {x["driver_id"]: x["grid"] for x in rrecs},
                "team": {x["driver_id"]: x["constructor_id"] for x in rrecs}}


def c0_of(pred, rn):
    recs, fs = LABELS[rn]
    try:
        return score_qualifying(pred, recs, fs)["overall_candidate"]["overall_candidate_score"]
    except ValueError as exc:
        if "absent from" in str(exc):
            return None
        raise


def donors_for_round(rn):
    cfg13 = QualifyingFeatureConfig(track_profile_method="independent",
                                    weights=dict(_EXP_TUNED_INDEPENDENT))
    cfg5 = QualifyingFeatureConfig(track_profile_method="interaction",
                                   weights=dict(_CIRCUIT_T5_WEIGHTS), form_window=3)
    fp13 = F.build_qualifying_features(project_root=ROOT, target_round=rn, season=2026,
                                       config=cfg13, officialize_actuals=True)
    fp5 = F.build_qualifying_features(project_root=ROOT, target_round=rn, season=2026,
                                      config=cfg5, officialize_actuals=True)
    rank13 = driver_ids(score_qualifying_field(driver_features=fp13["rows"]))
    rank5 = driver_ids(score_qualifying_field(driver_features=fp5["rows"]))
    _, enr = predict_elastic_net(rn, actuals["completed_rounds"], 0.01, 0.7)
    _, ltr = predict_lambdamart(rn, actuals["completed_rounds"], params=dict(_LTR_N100_PARAMS))
    return rank13, rank5, driver_ids(enr), driver_ids(ltr), fp13


def race_c0(rn, fp13):
    import statistics as _st
    qual = {row["driver_id"]: (row.get("form_score") or 0.0,
                                row.get("constructor_score") or 0.0) for row in fp13["rows"]}
    rc = OM._extract_racecraft_features(
        sorted(actuals["completed_rounds"], key=lambda r: int(r["round"])), rn)
    feats = {}
    for did, g in RACE[rn]["grid"].items():
        f_, c_ = qual.get(did, (0.0, 0.0))
        feats[did] = {"grid": g, "form": f_, "ctor": c_, "rc": rc.get(did, 0.5)}
    fv = [x["form"] for x in feats.values()]
    rv = [x["rc"] for x in feats.values()]
    fm_, fs_ = _m(fv), (_st.stdev(fv) if len(fv) > 1 else 1.0) or 1.0
    rm_, rs_ = _m(rv), (_st.stdev(rv) if len(rv) > 1 else 1.0) or 1.0
    scored = []
    for did, x in feats.items():
        boost = max(0, x["grid"] - 10) * x["ctor"]
        pos = (x["grid"] - 3.0 * (x["form"] - fm_) / fs_
               - 2.0 * (x["rc"] - rm_) / rs_ - 3.0 * boost)
        scored.append((did, pos))
    scored.sort(key=lambda z: z[1])
    return c0_score([d for d, _ in scored], RACE[rn]["order"])


def spearman(a, b):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        return {order[i]: i + 1 for i in range(len(v))}
    ra, rb = ranks(a), ranks(b)
    n = len(a)
    d2 = sum((ra[i] - rb[i]) ** 2 for i in range(n))
    return 1 - 6 * d2 / (n * (n * n - 1))


def main():
    results = {}
    for name, variant in ARMS.items():
        _install(variant)
        per = {"q13": [], "q31": [], "q30": [], "race": [], "gridcorr": {}, "fired": {}}
        try:
            for rn in ROUNDS:
                r13, r5, enn, ltr, fp13 = donors_for_round(rn)
                q31 = _set_first(enn[:10], enn[:10], r5[:10], r13[:10], r13[:10])
                q30 = _top_down(enn[:10], ltr[:10], r5[:10], r13[:10], r13[:10])
                per["q13"].append((rn, c0_of(r13[:10], rn)))
                per["q31"].append((rn, c0_of(q31[:10], rn)))
                per["q30"].append((rn, c0_of(q30[:10], rn)))
                per["race"].append((rn, round(race_c0(rn, fp13), 4)))
                strengths = variant(rn - 1)
                agg: dict[str, list] = {}
                for did, t in RACE[rn]["team"].items():
                    agg.setdefault(t, []).append(RACE[rn]["grid"][did])
                keys = [t for t in agg if t in strengths]
                if len(keys) >= 5:
                    per["gridcorr"][str(rn)] = round(spearman(
                        [strengths[t] for t in keys],
                        [-_m(agg[t]) for t in keys]), 3)
                # fired-team top10 membership detail (qualifying truth)
                actual_q10 = {d for d, p in Q_TRUTH[rn].items() if p is not None and int(p) <= 10}
                led = fake_ledger() if name in ("A1f_false_full", "A2f_false_gradual_m3") else LEDGER
                for t in TEAMS:
                    E = regime_start(t, rn - 1, led)
                    if E is None:
                        continue
                    preds = {d for d in q31[:10] if RACE[rn]["team"].get(d) == t}
                    hits = len(preds & actual_q10)
                    false = len(preds - actual_q10)
                    per["fired"][f"R{rn:02d}:{t}"] = {
                        "E": E, "post": rn - E,
                        "pred_q_top10_drivers": sorted(preds),
                        "hits_vs_q_truth": hits, "false_alarm": false,
                    }
        finally:
            _uninstall()
        results[name] = per
        print(name, "q31", round(_m([v for _, v in per["q31"] if v is not None]), 4),
              "race", round(_m([v for _, v in per["race"] if v is not None]), 4))
    outdir = ROOT / "outputs/experiments/whatif_upgrade"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "gcr_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", outdir / "gcr_results.json")


if __name__ == "__main__":
    main()
