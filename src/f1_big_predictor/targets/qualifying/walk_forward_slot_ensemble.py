"""ST-6d slot-specialist ensemble runners (roster candidates #30 / #31).

Two C0 sub-specialist slot-assembly recipes, merged into the roster as formally
registered candidates:

  #30 slot_peak   (top_down)   #9 → P1; #28 → T3; circuit_T5 → T5; #13 → T10+order
  #31 slot_robust (set_first)  EN_new → P1+T3; circuit_T5 → T5; #13 → T10+order

circuit_T5 = explainable(interaction, circuit_fit upweighted); weak on the raw C0
metric but strong on T5 hits, found by the ST-6d knob grid.
EN_new = elastic_net(alpha=0.01, l1_ratio=0.7).

Assembly is decoupled from the C0 ruler: this module only produces a top10 (plus
a filled-in full-field order); scoring is still handled by the frozen
score_qualifying. Each donor contributes its walk-forward full-field ranking
(full_field), filling the slots with deduplication; this is identical in outcome
to the ST-6d scaffold (each donor contributing its top10) on R03-R09, because
every scaffold slot was already filled within the top10 — full_field is only a
robust extension of the same prefix.
"""
from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any, Callable

from .types import QualifyingFeatureConfig
from .walk_forward import run_walk_forward
from .walk_forward_elastic_net import run_walk_forward_elastic_net
from .walk_forward_lambdamart import run_walk_forward_lambdamart

# --- Donor configuration (matches the ST-6d scaffold) ----------------------
_EXP_TUNED_INDEPENDENT = {
    "form": 0.25, "constructor": 0.35, "circuit_fit": 0.20,
    "evidence": 0.05, "reliability": 0.05,
}
_CIRCUIT_T5_WEIGHTS = {
    "form": 0.20, "constructor": 0.30, "circuit_fit": 0.35,
    "evidence": 0.05, "reliability": 0.05,
}
_LTR_N100_PARAMS = {
    "n_estimators": 100, "num_leaves": 7, "learning_rate": 0.1,
    "min_child_samples": 5, "random_state": 42,
}


def _donor_p1_en_a001_l1_030(root: Path) -> dict[str, Any]:
    # Donor #9
    return run_walk_forward_elastic_net(root, alpha=0.01, l1_ratio=0.3)


def _donor_en_new(root: Path) -> dict[str, Any]:
    # EN_new
    return run_walk_forward_elastic_net(root, alpha=0.01, l1_ratio=0.7)


def _donor_t3_ltr_n100(root: Path) -> dict[str, Any]:
    # Donor #28
    return run_walk_forward_lambdamart(root, params=dict(_LTR_N100_PARAMS))


def _donor_circuit_t5(root: Path) -> dict[str, Any]:
    cfg = QualifyingFeatureConfig(
        track_profile_method="interaction",
        weights=dict(_CIRCUIT_T5_WEIGHTS),
        form_window=3,
    )
    return run_walk_forward(root, config=cfg)


def _donor_exp13(root: Path) -> dict[str, Any]:
    # Donor #13
    cfg = QualifyingFeatureConfig(
        track_profile_method="independent",
        weights=dict(_EXP_TUNED_INDEPENDENT),
    )
    return run_walk_forward(root, config=cfg)


# --- Assembly algorithm (verbatim from the ST-6d scaffold) -----------------
def _take_unique(src: list[str], n: int, used: set[str]) -> list[str]:
    out: list[str] = []
    for d in src:
        if d not in used:
            out.append(d)
            if len(out) == n:
                break
    return out


def _order_by(cands: list[str], order_src: list[str]) -> list[str]:
    pos = {d: i for i, d in enumerate(order_src)}
    return sorted(cands, key=lambda d: (pos.get(d, 999), d))


def _top_down(p1_src, t3_src, t5_src, t10_src, order_src) -> list[str]:
    used: set[str] = set()
    p1 = _take_unique(p1_src, 1, used); used.update(p1)
    t3 = _take_unique(t3_src, 2, used); used.update(t3)
    t5 = _take_unique(t5_src, 2, used); used.update(t5)
    t10 = _take_unique(t10_src, 5, used); used.update(t10)
    return (
        p1
        + _order_by(t3, order_src)
        + _order_by(t5, order_src)
        + _order_by(t10, order_src)
    )


def _set_first(p1_src, t3_src, t5_src, t10_src, order_src) -> list[str]:
    t10_set = _take_unique(t10_src, 10, set())
    t5: list[str] = []
    for d in t5_src:
        if d in t10_set and d not in t5:
            t5.append(d)
        if len(t5) == 5:
            break
    if len(t5) < 5:
        for d in t10_set:
            if d not in t5:
                t5.append(d)
            if len(t5) == 5:
                break
    t3: list[str] = []
    for d in t3_src:
        if d in t5 and d not in t3:
            t3.append(d)
        if len(t3) == 3:
            break
    if len(t3) < 3:
        for d in t5:
            if d not in t3:
                t3.append(d)
            if len(t3) == 3:
                break
    p1 = None
    for d in p1_src:
        if d in t3:
            p1 = d
            break
    if p1 is None:
        p1 = t3[0]
    return (
        [p1]
        + _order_by([d for d in t3 if d != p1], order_src)
        + _order_by([d for d in t5 if d not in t3], order_src)
        + _order_by([d for d in t10_set if d not in t5], order_src)
    )


# --- Runner assembly -------------------------------------------------------
def _seat_exit_filter(root: Path) -> dict[int, set[str]]:
    """round -> set of drivers that have exited by that round (manual registry).

    Defense-in-depth for the slot assembly: feature-row overrides already
    remove exited drivers from donor candidate pools, but the assembly layer
    refuses to slot them in even if a donor ranking still carries one.
    Fail-closed on a missing registry (DEC-CONTROL-SEAT-ROTATION-UNLOCK-001).
    """
    path = root / "data/manual/seat_changes_2026_v1.json"
    if not path.exists():
        raise FileNotFoundError(f"seat registry missing: {path}")
    registry = json.loads(path.read_text(encoding="utf-8"))
    exits: dict[int, set[str]] = {}
    for event in registry.get("events", []):
        if str(event["type"]) != "exit":
            continue
        rn = int(event["round"])
        for round_number in range(rn, 99):
            exits.setdefault(round_number, set()).add(str(event["driver_id"]))
    return exits


def _rankings_top10(runner: Callable[[Path], dict[str, Any]], root: Path) -> dict[int, list[str]]:
    """Take the top 10 of each donor per-round full_field ranking (same convention as the ST-6d scaffold)."""
    out: dict[int, list[str]] = {}
    meta: dict[int, dict[str, Any]] = {}
    res = runner(root)
    for pr in res["per_round"]:
        rn = int(pr["round"])
        out[rn] = list(pr["full_field_predicted_driver_ids"])[:10]
        meta[rn] = pr
    return out, meta


def _run_slot_ensemble(
    root: Path,
    *,
    method: str,
    p1_runner: Callable[[Path], dict[str, Any]],
    t3_runner: Callable[[Path], dict[str, Any]],
    t5_runner: Callable[[Path], dict[str, Any]],
    t10_runner: Callable[[Path], dict[str, Any]],
    order_runner: Callable[[Path], dict[str, Any]],
) -> dict[str, Any]:
    p1_rk, meta = _rankings_top10(p1_runner, root)
    t3_rk, _ = _rankings_top10(t3_runner, root)
    t5_rk, _ = _rankings_top10(t5_runner, root)
    t10_rk, _ = _rankings_top10(t10_runner, root)
    ord_rk, _ = _rankings_top10(order_runner, root)

    assemble = _top_down if method == "top_down" else _set_first

    per_round: list[dict[str, Any]] = []
    rounds = sorted(set(p1_rk) & set(t3_rk) & set(t5_rk) & set(t10_rk) & set(ord_rk))
    seat_filter = _seat_exit_filter(root)
    for rn in rounds:
        excluded = seat_filter.get(rn, set())

        def _strip(src: list[str]) -> list[str]:
            return [d for d in src if d not in excluded]

        top10 = assemble(
            _strip(p1_rk[rn]),
            _strip(t3_rk[rn]),
            _strip(t5_rk[rn]),
            _strip(t10_rk[rn]),
            _strip(ord_rk[rn]),
        )
        src_meta = meta.get(rn, {})
        per_round.append(
            {
                "round": rn,
                "race_name": src_meta.get("race_name"),
                "top10_predicted_driver_ids": top10[:10],
                "full_field_predicted_driver_ids": top10,
                "training_rounds": src_meta.get("training_rounds"),
                "prediction_status": "predicted",
                "prediction_evidence_gaps": [],
            }
        )
    return {"per_round": per_round, "evidence_gaps": []}


def run_walk_forward_slot_peak(project_root: Path) -> dict[str, Any]:
    """#30 ST-6d peak: #9→P1; #28→T3; circuit_T5→T5; #13→T10+order (top_down)."""
    return _run_slot_ensemble(
        project_root,
        method="top_down",
        p1_runner=_donor_p1_en_a001_l1_030,
        t3_runner=_donor_t3_ltr_n100,
        t5_runner=_donor_circuit_t5,
        t10_runner=_donor_exp13,
        order_runner=_donor_exp13,
    )


def run_walk_forward_slot_robust(project_root: Path) -> dict[str, Any]:
    """#31 ST-6d robust: EN_new→P1+T3; circuit_T5→T5; #13→T10+order (set_first)."""
    return _run_slot_ensemble(
        project_root,
        method="set_first",
        p1_runner=_donor_en_new,
        t3_runner=_donor_en_new,
        t5_runner=_donor_circuit_t5,
        t10_runner=_donor_exp13,
        order_runner=_donor_exp13,
    )
