#!/usr/bin/env python3
"""WHAT-IF experiment series: upgrade-event handling / constructor-strength correction.

Isolated research run. Touches no mainline code/docs/state: all variant logic is
in-memory monkey-patching for the duration of each experiment arm.

Hypotheses under test (from RES-CONSTRUCTOR-SHIFT-EVENTS-R03-R13-001 §4):
  H1  cumulative constructor_score lags upgrade step-changes by ~2-4 rounds
  H2  a short-window increment (recent-3 normalized) fixes in-window error
      without side effects out of window
  H3  hybrid (cum x recent) blends dominate pure forms
  H4  event-conditioned windowed reset is sufficient (no permanent regime change)
  H5  EWMA decay is an alternative mechanism with lower design risk

Corrections are evaluated on:
  (a) qualifying #13 donor ranking C0 (deterministic scorer, no retraining)
  (b) frozen ensembles #30/#31 with corrected donor features (EN/LTR re-fit on
      corrected features per arm; C0 yardstick untouched)
  (c) race model (optimized_model formula with corrected constructor_raw)
  (d) estimator quality: Spearman(variant constructor strength, actual mean grid
      of the team's two drivers in the SAME target round)  <- the lag itself

Upgrade-event map (archive §1; pace-affecting only, seat swaps excluded by
user decision 2026-09-05):
  mer:[R05] fer:[R04,R07,R08] mcl:[R04,R11] rbr:[R04,R07] ast:[R11,R12] alp:[R12]
"""
from __future__ import annotations

import json
import statistics as st
from statistics import mean as _m, stdev as _s
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

ROOT = Path(__file__).resolve().parents[1]
ROUNDS = list(range(3, 13))
EVENTS = {  # team -> rounds where a pace-affecting upgrade landed (archive §1)
    "mercedes": [5], "ferrari": [4, 7, 8], "mclaren": [4, 11],
    "red_bull": [4, 7], "aston_martin": [11, 12], "alpine": [12],
}
WINDOW = 3  # rounds a correction is expected to matter after an event
EWMA_LAMBDA = 0.6

actuals = load_officialized_actuals(ROOT)
by_round = {int(r["round"]): r for r in actuals["completed_rounds"]}
CUM = {  # constructor -> {standings_as_of_round: points}
    t: {} for r in actuals["completed_rounds"]
    for t in [x["constructor_id"] for x in r["constructor_standings"]["records"]]
}
for r in actuals["completed_rounds"]:
    rr = int(r["round"])
    for x in r["constructor_standings"]["records"]:
        CUM[x["constructor_id"]][rr] = float(x["points"])
TEAMS = list(CUM)


def _cum(t, rr):
    """cumulative points of team t as recorded in standings snapshot of round rr (clamped)."""
    table = CUM.get(t, {})
    rr = max(1, min(rr, 12))
    for probe in (rr, *[q for q in range(rr - 1, 0, -1)]):
        if probe in table:
            return table[probe]
    return 0.0


def _per_round_pts(t, rr):
    return _cum(t, rr) - _cum(t, rr - 1)


def base_norm(rr):
    """V0 values: cumulative through standings-of-(rr) normalized by max."""
    vals = {t: _cum(t, rr) for t in TEAMS}
    mx = max(vals.values()) or 1.0
    return {t: v / mx for t, v in vals.items()}


def recent_norm(rr, k=3):
    vals = {t: sum(_per_round_pts(t, q) for q in range(rr - k + 1, rr + 1)) for t in TEAMS}
    mx = max(vals.values()) or 1.0
    return {t: v / mx for t, v in vals.items()}


def ewma_norm(rr):
    vals = {}
    for t in TEAMS:
        acc, w = 0.0, 1.0
        for back in range(0, rr):  # rounds rr, rr-1, ... 1
            acc += w * _per_round_pts(t, rr - back)
            w *= EWMA_LAMBDA
        vals[t] = acc
    mx = max(vals.values()) or 1.0
    return {t: v / mx for t, v in vals.items()}


def _in_window(t, rr):
    return any(e <= rr <= e + WINDOW - 1 for e in EVENTS.get(t, []))


def hybrid(a, b, w):
    return {t: w * a[t] + (1 - w) * b[t] for t in a}


def event_reset(rr):
    """V3: teams inside their post-event window use recent3; everyone else cum."""
    out = dict(base_norm(rr))
    for t in TEAMS:
        if _in_window(t, rr):
            out[t] = recent_norm(rr)[t]
    return out


VARIANTS = {
    "V0_cumulative": lambda rr: base_norm(rr),
    "V1_recent3": lambda rr: recent_norm(rr),
    "V2a_blend50": lambda rr: hybrid(base_norm(rr), recent_norm(rr), 0.5),
    "V2b_blend25": lambda rr: hybrid(base_norm(rr), recent_norm(rr), 0.25),
    "V3_event_reset": event_reset,
    "V4_ewma": lambda rr: ewma_norm(rr),
}

# ---------------------------------------------------------------- patching
_orig_F = F._constructor_scores
_orig_FM = FM._constructor_standings_pts


def _install(variant):
    def f_scores(payload):
        rr = int(payload["round"])
        vals = variant(rr)
        return {t: vals.get(t, 0.0) for t in (x["constructor_id"] for x in payload["constructor_standings"]["records"])}

    def fm_pts(completed_rounds, after_round):
        orig = _orig_FM(completed_rounds, after_round)
        vals = variant(int(after_round))
        return {t: vals.get(t, 0.0) * 400.0 for t in orig}  # rescale to point-ish magnitude

    F._constructor_scores = f_scores
    FM._constructor_standings_pts = fm_pts


def _uninstall():
    F._constructor_scores = _orig_F
    FM._constructor_standings_pts = _orig_FM


# ---------------------------------------------------------------- ground truth
def _labels():
    out = {}
    raw = json.loads((ROOT / "data/processed/season_2026_actuals/actuals.json").read_text())
    raw_by = {int(r["round"]): r for r in raw["completed_rounds"]}
    for rn in ROUNDS:
        if rn <= 9:
            recs, fs = official_records_for_round(ROOT, rn)
        else:
            recs = [
                {"driver_id": x["driver_id"], "position": x.get("position"),
                 "classification_status": x.get("status") or "Classified"}
                for x in raw_by[rn]["qualifying_results"]["records"]
            ]
            fs = len(recs)
        out[rn] = (recs, fs)
    race = {}
    for rn in ROUNDS:
        recs = [x for x in raw_by[rn]["race_results"]["records"] if x.get("position") is not None]
        recs.sort(key=lambda x: int(x["position"]))
        race[rn] = {
            "order": [x["driver_id"] for x in recs],
            "grid": {x["driver_id"]: (x["race_results_records"] if False else x["grid"]) for x in recs},
            "team": {x["driver_id"]: x["constructor_id"] for x in recs},
        }
    return out, race


LABELS, RACE = _labels()


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
    en_rows = sorted(actuals["completed_rounds"], key=lambda r: int(r["round"]))
    _, enr = predict_elastic_net(rn, en_rows, 0.01, 0.7)
    _, ltr = predict_lambdamart(rn, en_rows, params=dict(_LTR_N100_PARAMS))
    return rank13, rank5, driver_ids(enr), driver_ids(ltr), fp13


def c0_of(pred, rn):
    recs, fs = LABELS[rn]
    try:
        return score_qualifying(pred, recs, fs)["overall_candidate"]["overall_candidate_score"]
    except ValueError as exc:
        # seat-swap universe drift (deferred by user decision 2026-09-05):
        # record the round as unscoreable and continue; averages skip None.
        if "absent from" in str(exc):
            return None
        raise


def mean_grid_strength_corr(vals_fn):
    """(d): Spearman between variant constructor strength and actual mean grid in target round."""
    def spearman(a, b):
        ra = {v: i for i, v in enumerate(sorted(range(len(a)), key=lambda i: a[i]))}
        rb = {v: i for i, v in enumerate(sorted(range(len(b)), key=lambda i: b[i]))}
        n = len(a)
        d2 = sum((ra[i] - rb[i]) ** 2 for i in range(n))
        return 1 - 6 * d2 / (n * (n * n - 1))
    out = {}
    for rn in ROUNDS:
        strengths = vals_fn(rn - 1)
        agg = {}
        for did, t in RACE[rn]["team"].items():
            agg.setdefault(t, []).append(RACE[rn]["grid"][did])
        keys = [t for t in agg if t in strengths and len(agg[t]) >= 1]
        x = [strengths[t] for t in keys]
        y = [-st.mean(agg[t]) for t in keys]
        if len(keys) >= 5:
            out[rn] = round(spearman(x, y), 3)
    return out


def main():
    results = {}
    for name, fn in VARIANTS.items():
        _install(fn)
        per = {"q13": [], "q31": [], "q30": [], "race": [], "gridcorr": fn}
        try:
            for rn in ROUNDS:
                r13, r5, enn, ltr, fp = donors_for_round(rn)
                q31 = _set_first(enn[:10], enn[:10], r5[:10], r13[:10], r13[:10])
                q30 = _top_down(enn[:10], ltr[:10], r5[:10], r13[:10], r13[:10])
                per["q13"].append((rn, c0_of(r13[:10], rn)))
                per["q31"].append((rn, c0_of(q31[:10], rn)))
                per["q30"].append((rn, c0_of(q30[:10], rn)))
                # race arm
                qual = {row["driver_id"]: (row.get("form_score") or 0.0,
                                           row.get("constructor_score") or 0.0)
                        for row in fp["rows"]}
                import f1_big_predictor.targets.race.optimized_model as OM
                rc = OM._extract_racecraft_features(
                    sorted(actuals["completed_rounds"], key=lambda r: int(r["round"])), rn)
                feats = {}
                for did, g in RACE[rn]["grid"].items():
                    f_, c_ = qual.get(did, (0.0, 0.0))
                    feats[did] = {"grid": g, "form_raw": f_, "constructor_raw": c_,
                                  "racecraft_raw": rc.get(did, 0.5)}
                if feats:
                    fv = [x["form_raw"] for x in feats.values()]
                    rvv = [x["racecraft_raw"] for x in feats.values()]
                    fm_, fs_ = _m(fv), (_s(fv) if len(fv) > 1 else 1.0)
                    rm_, rs_ = _m(rvv), (_s(rvv) if len(rvv) > 1 else 1.0)
                    scored = []
                    for did, x in feats.items():
                        boost = max(0, x["grid"] - 10) * x["constructor_raw"]
                        pos = (x["grid"]
                               - 3.0 * ((x["form_raw"] - fm_) / fs_ if fs_ > 0 else 0)
                               - 2.0 * ((x["racecraft_raw"] - rm_) / rs_ if rs_ > 0 else 0)
                               - 3.0 * boost)
                        scored.append((did, pos))
                    scored.sort(key=lambda z: z[1])
                    order = [d for d, _ in scored]
                    per["race"].append((rn, round(c0_score(order, RACE[rn]["order"]), 4)))
        finally:
            _uninstall()
        per["gridcorr"] = mean_grid_strength_corr(fn)
        results[name] = per
        def _mean_of(key):
            vals = [v for _, v in per[key] if v is not None]
            return round(_m(vals), 4) if vals else None
        print(name, "q31 mean", _mean_of("q31"),
              "race mean", _mean_of("race"),
              "corr mean", round(_m(list(per["gridcorr"].values())), 3))
    outdir = ROOT / "outputs/experiments/whatif_upgrade"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "whatif_upgrade_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", outdir / "whatif_upgrade_results.json")


if __name__ == "__main__":
    main()
