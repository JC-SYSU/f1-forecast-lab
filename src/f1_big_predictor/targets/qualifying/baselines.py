"""Four simple deterministic baseline predictors for qualifying top-10.

Each predictor is an independent model that uses only information available
before the target round (qualifying results, driver standings, constructor
standings from prior rounds).  They share no parameters with the v1
explainable-score model and are not allowed to read one another's outputs.

Public API
----------
predict_latest_prior         – rank by previous-round qualifying position
predict_season_to_date       – rank by season-average qualifying position
predict_constructor_only     – rank by constructor championship standing
predict_form_w3              – rank by mean qualifying position, last 3 rounds

Each function returns ``(prediction_dict, full_ranking_list)``.
``prediction_dict`` has the same top-level keys as QualifyingTargetPrediction.
``full_ranking_list`` is the complete 22-driver ranking (entries with
``driver_id``, ``position``, ``score``), parallel to ``score_qualifying_field``
in the v1 model.
"""
from __future__ import annotations

from typing import Any

TARGET_ID = "qualifying"
TOP10_SIZE = 10
FORM_WINDOW = 3
BASELINE_FALLBACK_POLICY = "driver_standings_then_alphabetical"

MODEL_ID_LATEST_PRIOR = "qualifying.model.baseline.latest_prior"
MODEL_ID_SEASON_TO_DATE = "qualifying.model.baseline.season_to_date"
MODEL_ID_CONSTRUCTOR_ONLY = "qualifying.model.baseline.constructor_only"
MODEL_ID_FORM_W3 = "qualifying.model.baseline.form_w3"

FEATURE_SET_ID_LATEST_PRIOR = "qualifying.features.baseline.latest_prior"
FEATURE_SET_ID_SEASON_TO_DATE = "qualifying.features.baseline.season_to_date"
FEATURE_SET_ID_CONSTRUCTOR_ONLY = "qualifying.features.baseline.constructor_only"
FEATURE_SET_ID_FORM_W3 = "qualifying.features.baseline.form_w3"

# Sentinel for unknown standings position (placed after known entries)
_UNKNOWN_POS = 9999


# ---------------------------------------------------------------------------
# Public predictors
# ---------------------------------------------------------------------------

def predict_latest_prior(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Rank the target-round field by the previous round's qualifying order."""
    prior_round = target_round - 1
    prior_records = _qualifying_records(completed_rounds, prior_round)
    drv_standings = _driver_standings(completed_rounds, prior_round)
    target_drivers, _ = _target_round_field(completed_rounds, target_round)

    evidence_gaps: list[str] = []
    if not prior_records:
        evidence_gaps.append(f"round_{prior_round:02d}_qualifying_results_missing")

    prior_pos: dict[str, int] = {r["driver_id"]: int(r["position"]) for r in prior_records}
    cold_start = [d for d in target_drivers if d not in prior_pos]
    if cold_start:
        evidence_gaps.append(f"cold_start_drivers_{len(cold_start)}")

    def _key(driver_id: str) -> tuple:
        pos = prior_pos.get(driver_id)
        if pos is not None:
            return (0, float(pos), drv_standings.get(driver_id, _UNKNOWN_POS), driver_id)
        return (1, float(_UNKNOWN_POS), drv_standings.get(driver_id, _UNKNOWN_POS), driver_id)

    ordered = sorted(target_drivers, key=_key)
    return _make_result(MODEL_ID_LATEST_PRIOR, FEATURE_SET_ID_LATEST_PRIOR, ordered, evidence_gaps)


def predict_season_to_date(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Rank by mean qualifying position across all rounds before target_round.

    Only rounds where the driver actually participated count; absent rounds
    are not penalised.  When two drivers share the same mean, the one with
    more rounds of evidence ranks higher.  Cold-start drivers (zero prior
    appearances) fall back to driver standings then alphabetical.
    """
    prior_rounds = sorted(
        [r for r in completed_rounds if int(r["round"]) < target_round],
        key=lambda r: int(r["round"]),
    )
    last_prior = int(prior_rounds[-1]["round"]) if prior_rounds else target_round - 1
    drv_standings = _driver_standings(completed_rounds, last_prior)
    target_drivers, _ = _target_round_field(completed_rounds, target_round)

    evidence_gaps: list[str] = []
    pos_history: dict[str, list[int]] = {}
    for rnd in prior_rounds:
        for rec in _qualifying_records(completed_rounds, int(rnd["round"])):
            pos_history.setdefault(rec["driver_id"], []).append(int(rec["position"]))

    cold_start = [d for d in target_drivers if d not in pos_history]
    if cold_start:
        evidence_gaps.append(f"cold_start_drivers_{len(cold_start)}")

    def _key(driver_id: str) -> tuple:
        positions = pos_history.get(driver_id)
        if positions:
            mean_pos = sum(positions) / len(positions)
            # more rounds → better evidence → sort earlier (negate count)
            return (0, mean_pos, -len(positions), drv_standings.get(driver_id, _UNKNOWN_POS), driver_id)
        return (1, float(_UNKNOWN_POS), 0, drv_standings.get(driver_id, _UNKNOWN_POS), driver_id)

    ordered = sorted(target_drivers, key=_key)
    return _make_result(MODEL_ID_SEASON_TO_DATE, FEATURE_SET_ID_SEASON_TO_DATE, ordered, evidence_gaps)


def predict_constructor_only(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Rank by constructor championship standing after the previous round.

    Teammates are split by driver championship standing, then alphabetically.
    """
    prior_round = target_round - 1
    ctor_standings = _constructor_standings(completed_rounds, prior_round)
    drv_standings = _driver_standings(completed_rounds, prior_round)
    target_drivers, constructor_map = _target_round_field(completed_rounds, target_round)

    evidence_gaps: list[str] = []
    missing_ctor = [
        d for d in target_drivers
        if constructor_map.get(d, "") not in ctor_standings
    ]
    if missing_ctor:
        evidence_gaps.append(f"constructor_not_in_standings_{len(missing_ctor)}")

    def _key(driver_id: str) -> tuple:
        ctor_id = constructor_map.get(driver_id, "")
        ctor_pos = ctor_standings.get(ctor_id, _UNKNOWN_POS)
        drv_pos = drv_standings.get(driver_id, _UNKNOWN_POS)
        return (ctor_pos, drv_pos, driver_id)

    ordered = sorted(target_drivers, key=_key)
    return _make_result(MODEL_ID_CONSTRUCTOR_ONLY, FEATURE_SET_ID_CONSTRUCTOR_ONLY, ordered, evidence_gaps)


def predict_form_w3(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
    window: int = FORM_WINDOW,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Rank by mean qualifying position over the last ``window`` rounds.

    Only rounds where the driver actually participated count.  When the
    available history is shorter than the window, all available rounds are
    used (no penalty for the shorter window).
    """
    all_prior = sorted(
        [r for r in completed_rounds if int(r["round"]) < target_round],
        key=lambda r: int(r["round"]),
    )
    window_rounds = all_prior[-window:]  # last W rounds, or fewer if not enough
    last_prior = int(all_prior[-1]["round"]) if all_prior else target_round - 1
    drv_standings = _driver_standings(completed_rounds, last_prior)
    target_drivers, _ = _target_round_field(completed_rounds, target_round)

    evidence_gaps: list[str] = []
    pos_history: dict[str, list[int]] = {}
    for rnd in window_rounds:
        for rec in _qualifying_records(completed_rounds, int(rnd["round"])):
            pos_history.setdefault(rec["driver_id"], []).append(int(rec["position"]))

    cold_start = [d for d in target_drivers if d not in pos_history]
    if cold_start:
        evidence_gaps.append(f"cold_start_drivers_{len(cold_start)}")

    def _key(driver_id: str) -> tuple:
        positions = pos_history.get(driver_id)
        if positions:
            mean_pos = sum(positions) / len(positions)
            return (0, mean_pos, -len(positions), drv_standings.get(driver_id, _UNKNOWN_POS), driver_id)
        return (1, float(_UNKNOWN_POS), 0, drv_standings.get(driver_id, _UNKNOWN_POS), driver_id)

    ordered = sorted(target_drivers, key=_key)
    return _make_result(MODEL_ID_FORM_W3, FEATURE_SET_ID_FORM_W3, ordered, evidence_gaps)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _qualifying_records(
    completed_rounds: list[dict[str, Any]],
    round_num: int,
) -> list[dict[str, Any]]:
    """Return qualifying records for a given round, sorted by position."""
    for rnd in completed_rounds:
        if int(rnd["round"]) == round_num:
            records = rnd.get("qualifying_results", {}).get("records") or []
            return sorted(
                [r for r in records if r.get("driver_id") and r.get("position") is not None],
                key=lambda r: (int(r["position"]), str(r["driver_id"])),
            )
    return []


def _driver_standings(
    completed_rounds: list[dict[str, Any]],
    after_round: int,
) -> dict[str, int]:
    """Map driver_id → championship position after a given round."""
    for rnd in completed_rounds:
        if int(rnd["round"]) == after_round:
            records = rnd.get("driver_standings", {}).get("records") or []
            return {
                str(r["driver_id"]): int(r["position"])
                for r in records
                if r.get("driver_id") and r.get("position") is not None
            }
    return {}


def _constructor_standings(
    completed_rounds: list[dict[str, Any]],
    after_round: int,
) -> dict[str, int]:
    """Map constructor_id → championship position after a given round."""
    for rnd in completed_rounds:
        if int(rnd["round"]) == after_round:
            records = rnd.get("constructor_standings", {}).get("records") or []
            return {
                str(r["constructor_id"]): int(r["position"])
                for r in records
                if r.get("constructor_id") and r.get("position") is not None
            }
    return {}


def _target_round_field(
    completed_rounds: list[dict[str, Any]],
    target_round: int,
) -> tuple[list[str], dict[str, str]]:
    """Return (driver_ids_list, driver_to_constructor_map) for the target round."""
    for rnd in completed_rounds:
        if int(rnd["round"]) == target_round:
            records = rnd.get("qualifying_results", {}).get("records") or []
            drivers = [str(r["driver_id"]) for r in records if r.get("driver_id")]
            ctor_map = {
                str(r["driver_id"]): str(r.get("constructor_id", ""))
                for r in records if r.get("driver_id")
            }
            return drivers, ctor_map
    return [], {}


def _make_result(
    model_id: str,
    feature_set_id: str,
    ordered_drivers: list[str],
    evidence_gaps: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build (prediction_dict, full_ranking_list) from a sorted driver list."""
    n = len(ordered_drivers)
    full_ranking = [
        {
            "driver_id": did,
            "position": pos,
            # score: higher = better (mirrors explainable-score model convention)
            "score": float(n + 1 - pos),
        }
        for pos, did in enumerate(ordered_drivers, start=1)
    ]
    if n >= TOP10_SIZE:
        entries = full_ranking[:TOP10_SIZE]
        status = "ok"
        gaps = list(evidence_gaps)
    else:
        entries = []
        status = "evidence_issue"
        gaps = list(evidence_gaps) + ["insufficient_drivers_for_top10"]

    prediction: dict[str, Any] = {
        "target_id": TARGET_ID,
        "model_id": model_id,
        "feature_set_id": feature_set_id,
        "fallback_policy": BASELINE_FALLBACK_POLICY,
        "status": status,
        "entries": entries,
        "evidence_gaps": gaps,
    }
    return prediction, full_ranking
