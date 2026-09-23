"""Borda-count heuristic aggregation model for qualifying prediction.

Aggregates the four simple deterministic baselines via weighted Borda scores:
  - latest_prior      (previous round's qualifying order)
  - season_to_date    (season-to-date mean)
  - constructor_only  (constructor standings)
  - form_w3           (mean of the last three rounds)

Each baseline produces a full 22-driver ranking.  A Borda score is assigned to
each driver from each ranking (position P → n+1-P, where n = field size), then
weighted-summed.  Drivers ranked higher by more baselines accumulate more points.

This is a different normalisation paradigm from both the single-signal baselines
(ordinal aggregation vs. single ordinal signal) and the explainable-score models
(rank-based vs. value-based component normalisation).

Confirmed candidate configurations:
  EQUAL_WEIGHTS    – equal weight for all four baselines (plain Borda)
  CTOR_UP_WEIGHTS  – constructor_only receives 2× weight (strongest single signal
                     per Stage-1 diagnosis: Spearman ρ=0.869, std=0.046)
"""
from __future__ import annotations

from typing import Any

from .baselines import (
    predict_constructor_only,
    predict_form_w3,
    predict_latest_prior,
    predict_season_to_date,
)

TARGET_ID = "qualifying"
MODEL_ID = "qualifying.model.heuristic.borda"
FEATURE_SET_ID = "qualifying.features.heuristic.baseline_rankings_v1"
FALLBACK_POLICY = "worst_borda_for_unranked"
TOP10_SIZE = 10

# Candidate configurations (#14 and #15 in the confirmed roster)
EQUAL_WEIGHTS: dict[str, float] = {
    "latest_prior": 1.0,
    "season_to_date": 1.0,
    "constructor_only": 1.0,
    "form_w3": 1.0,
}

CTOR_UP_WEIGHTS: dict[str, float] = {
    "latest_prior": 1.0,
    "season_to_date": 1.0,
    "constructor_only": 2.0,   # ctor is most stable single signal (Stage-1 diagnosis)
    "form_w3": 1.0,
}


def predict_borda(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
    weights: dict[str, float] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Aggregate four baseline rankings via weighted Borda count.

    Returns (prediction_dict, full_ranking_list).
    """
    w = weights or EQUAL_WEIGHTS
    evidence_gaps: list[str] = []

    # --- Collect full rankings from each baseline ----------------------------
    _, lp_full = predict_latest_prior(target_round, completed_rounds)
    _, std_full = predict_season_to_date(target_round, completed_rounds)
    _, co_full = predict_constructor_only(target_round, completed_rounds)
    _, fw_full = predict_form_w3(target_round, completed_rounds)

    baseline_rankings: list[tuple[str, float, list[dict[str, Any]]]] = [
        ("latest_prior",    w.get("latest_prior",    1.0), lp_full),
        ("season_to_date",  w.get("season_to_date",  1.0), std_full),
        ("constructor_only", w.get("constructor_only", 1.0), co_full),
        ("form_w3",         w.get("form_w3",         1.0), fw_full),
    ]

    # --- Collect all drivers in the target round field ----------------------
    # Use the union of all four baseline fields (should be identical in practice)
    all_drivers: set[str] = set()
    for _, _, ranking in baseline_rankings:
        for entry in ranking:
            all_drivers.add(str(entry["driver_id"]))

    if not all_drivers:
        pred = {
            "target_id": TARGET_ID, "model_id": MODEL_ID,
            "feature_set_id": FEATURE_SET_ID, "fallback_policy": FALLBACK_POLICY,
            "status": "evidence_issue", "entries": [],
            "evidence_gaps": ["target_round_field_missing"],
        }
        return pred, []

    n = len(all_drivers)
    total_weight = sum(weight for _, weight, _ in baseline_rankings)

    # --- Compute weighted Borda scores --------------------------------------
    borda: dict[str, float] = {did: 0.0 for did in all_drivers}
    for name, weight, ranking in baseline_rankings:
        pos_map = {str(e["driver_id"]): int(e["position"]) for e in ranking}
        # Propagate cold-start gaps from constituent baselines
        _, base_pred = _baseline_prediction(name, target_round, completed_rounds)
        for gap in base_pred.get("evidence_gaps", []):
            annotated = f"{name}:{gap}"
            if annotated not in evidence_gaps:
                evidence_gaps.append(annotated)
        for did in all_drivers:
            pos = pos_map.get(did, n)   # unranked → worst position
            borda[did] += weight * float(n + 1 - pos)

    # --- Sort by Borda score (desc), break ties alphabetically -------------
    ordered = sorted(all_drivers, key=lambda d: (-borda[d], d))
    full_ranking = [
        {
            "driver_id": did,
            "position": pos,
            "score": round(borda[did] / total_weight, 6),  # normalised average
        }
        for pos, did in enumerate(ordered, start=1)
    ]

    if n >= TOP10_SIZE:
        entries, status = full_ranking[:TOP10_SIZE], "ok"
    else:
        entries, status = [], "evidence_issue"
        evidence_gaps.append("insufficient_drivers_for_top10")

    prediction: dict[str, Any] = {
        "target_id": TARGET_ID,
        "model_id": MODEL_ID,
        "feature_set_id": FEATURE_SET_ID,
        "fallback_policy": FALLBACK_POLICY,
        "status": status,
        "entries": entries,
        "evidence_gaps": evidence_gaps,
    }
    return prediction, full_ranking


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------

def _baseline_prediction(
    name: str,
    target_round: int,
    completed_rounds: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (full_ranking, prediction_dict) for a named baseline."""
    if name == "latest_prior":
        pred, full = predict_latest_prior(target_round, completed_rounds)
    elif name == "season_to_date":
        pred, full = predict_season_to_date(target_round, completed_rounds)
    elif name == "constructor_only":
        pred, full = predict_constructor_only(target_round, completed_rounds)
    else:
        pred, full = predict_form_w3(target_round, completed_rounds)
    return full, pred
