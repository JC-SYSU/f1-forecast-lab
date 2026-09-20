"""Feature matrix builder for the single-factor diagnosis stage.

Builds one feature row per driver for a given target round, using only
information available before that round (rounds 1..N-1).  All missing
values are returned as None so the diagnosis layer can measure coverage.

Available features
------------------
drv_standings_pos          driver championship position (after round N-1)
drv_standings_pts          driver championship points
ctor_standings_pos         constructor championship position
ctor_standings_pts         constructor championship points
qual_pos_prev              qualifying position in round N-1
qual_pos_mean3             mean qualifying position, last 3 rounds
qual_pos_season            mean qualifying position, all prior rounds
race_pos_prev              race finishing position in round N-1
race_pos_mean3             mean race finishing position, last 3 rounds
race_pos_season            mean race finishing position, all prior rounds
qual_same_circuit_mean     mean qualifying position at same circuit_id (prior rounds)
qual_teammate_delta_prev   qual_pos_prev minus teammate's qual_pos_prev in round N-1
                           (negative = outqualified teammate; None if either absent)
"""
from __future__ import annotations

from typing import Any

FEATURE_NAMES: tuple[str, ...] = (
    "drv_standings_pos",
    "drv_standings_pts",
    "ctor_standings_pos",
    "ctor_standings_pts",
    "qual_pos_prev",
    "qual_pos_mean3",
    "qual_pos_season",
    "race_pos_prev",
    "race_pos_mean3",
    "race_pos_season",
    "qual_same_circuit_mean",
    "qual_teammate_delta_prev",
)

# Direction: "lower_better" means a lower feature value predicts a better
# (lower-numbered) qualifying position.
FEATURE_DIRECTION: dict[str, str] = {
    "drv_standings_pos": "lower_better",
    "drv_standings_pts": "higher_better",
    "ctor_standings_pos": "lower_better",
    "ctor_standings_pts": "higher_better",
    "qual_pos_prev": "lower_better",
    "qual_pos_mean3": "lower_better",
    "qual_pos_season": "lower_better",
    "race_pos_prev": "lower_better",
    "race_pos_mean3": "lower_better",
    "race_pos_season": "lower_better",
    "qual_same_circuit_mean": "lower_better",
    "qual_teammate_delta_prev": "lower_better",  # negative = beat teammate
}


def build_feature_matrix(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a feature row for every driver in the target round's field.

    Each row contains ``driver_id``, ``constructor_id``, and one key per
    feature in FEATURE_NAMES (value is float or None for missing).
    """
    target_circuit = _circuit_id(completed_rounds, target_round)
    target_drivers, constructor_map = _target_round_field(completed_rounds, target_round)
    if not target_drivers:
        return []

    prior_rounds = sorted(
        [r for r in completed_rounds if int(r["round"]) < target_round],
        key=lambda r: int(r["round"]),
    )
    prior_round_nums = [int(r["round"]) for r in prior_rounds]
    last_prior = prior_round_nums[-1] if prior_round_nums else target_round - 1

    drv_pos_map = _driver_standings(completed_rounds, last_prior)
    drv_pts_map = _driver_standings_pts(completed_rounds, last_prior)
    ctor_pos_map = _constructor_standings(completed_rounds, last_prior)
    ctor_pts_map = _constructor_standings_pts(completed_rounds, last_prior)

    qual_history: dict[str, list[int]] = {}   # driver_id -> [pos, ...]  all prior rounds
    race_history: dict[str, list[int]] = {}
    same_circuit_history: dict[str, list[int]] = {}
    prev_qual: dict[str, int] = {}
    prev_race: dict[str, int] = {}

    for rnd in prior_rounds:
        rn = int(rnd["round"])
        circuit = rnd.get("circuit_id") or ""
        for rec in _qual_records(rnd):
            did = rec["driver_id"]
            pos = int(rec["position"])
            qual_history.setdefault(did, []).append(pos)
            if rn == last_prior:
                prev_qual[did] = pos
        for rec in _race_records(rnd):
            did = rec["driver_id"]
            pos = int(rec["position"])
            race_history.setdefault(did, []).append(pos)
            if rn == last_prior:
                prev_race[did] = pos
        if circuit and circuit == target_circuit:
            for rec in _qual_records(rnd):
                same_circuit_history.setdefault(rec["driver_id"], []).append(int(rec["position"]))
    # Teammate lookup: constructor → list of drivers in target round
    ctor_to_drivers: dict[str, list[str]] = {}
    for did, cid in constructor_map.items():
        ctor_to_drivers.setdefault(cid, []).append(did)

    rows: list[dict[str, Any]] = []
    for did in target_drivers:
        cid = constructor_map.get(did, "")
        teammates = [t for t in ctor_to_drivers.get(cid, []) if t != did]
        teammate_id = teammates[0] if len(teammates) == 1 else None

        q_all = qual_history.get(did, [])
        q3 = q_all[-3:] if q_all else []
        r_all = race_history.get(did, [])
        r3 = r_all[-3:] if r_all else []
        sc = same_circuit_history.get(did, [])

        prev_q = prev_qual.get(did)
        tm_prev_q = prev_qual.get(teammate_id) if teammate_id else None

        row: dict[str, Any] = {
            "driver_id": did,
            "constructor_id": cid,
            # Audit-only field (not in FEATURE_NAMES): which teammate the
            # delta is computed against at the target round. Seat-rotation
            # semantics (DEC-CONTROL-SEAT-ROTATION-UNLOCK-001): the delta is
            # always relative to the current-team teammate.
            "qual_teammate_id": teammate_id,
            "drv_standings_pos": _opt(drv_pos_map.get(did)),
            "drv_standings_pts": _opt(drv_pts_map.get(did)),
            "ctor_standings_pos": _opt(ctor_pos_map.get(cid)),
            "ctor_standings_pts": _opt(ctor_pts_map.get(cid)),
            "qual_pos_prev": _opt(prev_q),
            "qual_pos_mean3": _mean(q3),
            "qual_pos_season": _mean(q_all),
            "race_pos_prev": _opt(prev_race.get(did)),
            "race_pos_mean3": _mean(r3),
            "race_pos_season": _mean(r_all),
            "qual_same_circuit_mean": _mean(sc),
            "qual_teammate_delta_prev": (
                float(prev_q - tm_prev_q)
                if prev_q is not None and tm_prev_q is not None
                else None
            ),
        }
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _target_round_field(
    completed_rounds: list[dict[str, Any]], target_round: int
) -> tuple[list[str], dict[str, str]]:
    for rnd in completed_rounds:
        if int(rnd["round"]) == target_round:
            records = rnd.get("qualifying_results", {}).get("records") or []
            drivers = [str(r["driver_id"]) for r in records if r.get("driver_id")]
            ctor_map = {str(r["driver_id"]): str(r.get("constructor_id", "")) for r in records if r.get("driver_id")}
            return drivers, ctor_map
    return [], {}


def _circuit_id(completed_rounds: list[dict[str, Any]], target_round: int) -> str:
    for rnd in completed_rounds:
        if int(rnd["round"]) == target_round:
            return str(rnd.get("circuit_id") or "")
    return ""


def _qual_records(rnd: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        r for r in (rnd.get("qualifying_results", {}).get("records") or [])
        if r.get("driver_id") and r.get("position") is not None
    ]


def _race_records(rnd: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        r for r in (rnd.get("race_results", {}).get("records") or [])
        if r.get("driver_id") and r.get("position") is not None
    ]


def _driver_standings(completed_rounds: list[dict[str, Any]], after_round: int) -> dict[str, int]:
    for rnd in completed_rounds:
        if int(rnd["round"]) == after_round:
            return {str(r["driver_id"]): int(r["position"]) for r in (rnd.get("driver_standings", {}).get("records") or []) if r.get("driver_id") and r.get("position") is not None}
    return {}


def _driver_standings_pts(completed_rounds: list[dict[str, Any]], after_round: int) -> dict[str, float]:
    for rnd in completed_rounds:
        if int(rnd["round"]) == after_round:
            return {str(r["driver_id"]): float(r["points"]) for r in (rnd.get("driver_standings", {}).get("records") or []) if r.get("driver_id") and r.get("points") is not None}
    return {}


def _constructor_standings(completed_rounds: list[dict[str, Any]], after_round: int) -> dict[str, int]:
    for rnd in completed_rounds:
        if int(rnd["round"]) == after_round:
            return {str(r["constructor_id"]): int(r["position"]) for r in (rnd.get("constructor_standings", {}).get("records") or []) if r.get("constructor_id") and r.get("position") is not None}
    return {}


def _constructor_standings_pts(completed_rounds: list[dict[str, Any]], after_round: int) -> dict[str, float]:
    for rnd in completed_rounds:
        if int(rnd["round"]) == after_round:
            return {str(r["constructor_id"]): float(r["points"]) for r in (rnd.get("constructor_standings", {}).get("records") or []) if r.get("constructor_id") and r.get("points") is not None}
    return {}


def _mean(values: list[int | float]) -> float | None:
    return sum(values) / len(values) if values else None


def _opt(value: int | float | None) -> float | None:
    return float(value) if value is not None else None
