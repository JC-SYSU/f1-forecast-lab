"""C0 single-event qualifying scorer (ALG-QUALIFYING-001 v0.26).

All parameters are frozen candidates as of 2026-07-17 ("Approval A").

Frozen parameter bundle
-----------------------
position_exponent       = 1.25
membership_weights      = 0.10 / 0.20 / 0.70  (Top3 / Top5 / Top10)
b                       = 1.5
q                       = (2/3)^(1/3)  ≈ 0.8735804647362989
x_combo                 = 0.20
k_distance              = 1 / (25 * (1 + x_combo))  = 1/30
DSQ uncertainty cap     = 2 distance units (sqrt mirror-depth curve)
branch weights          = 0.45 / 0.35 / 0.20  (Exact / Membership / InternalOrder)

Usage
-----
    from f1_big_predictor.targets.qualifying.c0_scorer import score_qualifying
    result = score_qualifying(predicted_top10, official_records, field_size=22)

Inputs
------
predicted_top10   : list[str]          exactly 10 driver_ids, best first (P1→P10)
official_records  : list[dict]         frozen official driver universe; each entry
                                       must have "driver_id" (str) and "position"
                                       (int | None).  position=None also requires
                                       "classification_status" or "status".
field_size        : int                N — number of starters at cutoff (typically 22)

Output
------
A dict matching the field names in spec section 9.  All active nodes, sub-nodes,
and diagnostics are present.  overall_candidate_score can be negative; it is
never clipped.
"""
from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Frozen parameters (ALG-QUALIFYING-001 v0.26)
# ---------------------------------------------------------------------------

_POSITION_EXPONENT = 1.25

_W_TOP3 = 0.10
_W_TOP5 = 0.20
_W_TOP10 = 0.70

_B = 1.5
_Q = (2.0 / 3.0) ** (1.0 / 3.0)    # ≈ 0.8735804647362989

_X_COMBO = 0.20
_K_DISTANCE = 1.0 / (25.0 * (1.0 + _X_COMBO))   # = 1/30

_DSQ_U_MAX = 2.0   # distance units cap

_W_EXACT = 0.45
_W_MEMBERSHIP = 0.35
_W_INTERNAL_ORDER = 0.20

_TOP10_SIZE = 10
_INTERNAL_ORDER_DENOM = 45   # = 10 * 9 / 2  (max pair count for m=10)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_qualifying(
    predicted_top10: list[str],
    official_records: list[dict[str, Any]],
    field_size: int,
) -> dict[str, Any]:
    """Score one qualifying prediction against the official result.

    Returns the full output dict (section 9 field names).
    Raises ValueError for malformed inputs that violate the scoring contract.
    """
    official_pos, official_status = _validate_and_parse_inputs(
        predicted_top10,
        official_records,
        field_size,
    )

    # Official top-N sets (DSQ drivers excluded from ranked positions)
    official_ranked = sorted(
        [(did, p) for did, p in official_pos.items() if p is not None],
        key=lambda t: t[1],
    )
    official_top3_set  = {did for did, p in official_ranked if p <= 3}
    official_top5_set  = {did for did, p in official_ranked if p <= 5}
    official_top10_set = {did for did, p in official_ranked if p <= 10}

    # Reverse lookup: official_position_of[driver] = ranked position (1-based)
    official_position_of: dict[str, int] = {did: p for did, p in official_ranked}

    # ---- 1. M-POOL-MEMBERSHIP ---------------------------------------------
    membership = _compute_membership(
        predicted_top10, official_top3_set, official_top5_set, official_top10_set
    )

    # ---- 2 & 3. Exact vector → S_exact ------------------------------------
    exact_vec, exact_result = _compute_exact(predicted_top10, official_position_of)

    # ---- 4. Combo ----------------------------------------------------------
    combo = _compute_combo(exact_vec)

    # ---- 5. Distance -------------------------------------------------------
    distance = _compute_distance(
        predicted_top10,
        official_pos,
        official_status,
        field_size,
    )

    # ---- 6. Internal order -------------------------------------------------
    internal_order = _compute_internal_order(
        predicted_top10, official_top10_set, official_position_of
    )

    # ---- 7. Exact branch synthesis ----------------------------------------
    exact_positive_raw = exact_result["exact_position_score"] + combo["combo_bonus_candidate"]
    exact_positive_score = exact_positive_raw / (1.0 + _X_COMBO)
    distance_penalty = _K_DISTANCE * distance["mean_rank_distance"]
    exact_branch_score = exact_positive_score - distance_penalty   # signed, never clipped

    # ---- 8. Overall candidate ---------------------------------------------
    overall = (
        _W_EXACT * exact_branch_score
        + _W_MEMBERSHIP * membership["pool_candidate_score"]
        + _W_INTERNAL_ORDER * internal_order["internal_order_score"]
    )

    return {
        "membership": {
            "top3_set_score": membership["top3_set_score"],
            "top5_set_score": membership["top5_set_score"],
            "top10_set_score": membership["top10_set_score"],
            "pool_candidate_score": membership["pool_candidate_score"],
        },
        "exact": {
            "exact_hit_vector": exact_vec,
            "exact_hit_count": sum(exact_vec),
            "exact_hit_positions": [i + 1 for i, v in enumerate(exact_vec) if v],
            "exact_position_score": exact_result["exact_position_score"],
            "exact_positive_raw": round(exact_positive_raw, 10),
            "exact_positive_normalization_denominator": round(1.0 + _X_COMBO, 10),
            "exact_positive_score": round(exact_positive_score, 10),
        },
        "combo": {
            "maximal_runs": combo["maximal_runs"],
            "per_run_start_value": combo["per_run_start_value"],
            "per_run_length_value": combo["per_run_length_value"],
            "combo_shape": round(combo["combo_shape"], 10),
            "combo_bonus_candidate": round(combo["combo_bonus_candidate"], 10),
        },
        "distance": {
            "distance_vector": distance["distance_vector"],
            "distance_sum": round(distance["distance_sum"], 10),
            "mean_rank_distance": round(distance["mean_rank_distance"], 10),
            "max_rank_distance": round(distance["max_rank_distance"], 10),
            "k_distance_candidate": _K_DISTANCE,
            "distance_penalty_candidate": round(distance_penalty, 10),
            "status_branch_trace": distance["status_branch_trace"],
        },
        "exact_branch": {
            "exact_positive_score": round(exact_positive_score, 10),
            "distance_penalty": round(distance_penalty, 10),
            "exact_branch_score": round(exact_branch_score, 10),
        },
        "internal_order": {
            "common_driver_count": internal_order["common_driver_count"],
            "observed_pair_count": internal_order["observed_pair_count"],
            "inversion_count": internal_order["inversion_count"],
            "conditional_order_accuracy": internal_order["conditional_order_accuracy"],
            "signed_internal_order_skill": round(internal_order["signed_internal_order_skill"], 10),
            "internal_order_score": round(internal_order["internal_order_score"], 10),
        },
        "overall_candidate": {
            "w_exact": _W_EXACT,
            "w_membership": _W_MEMBERSHIP,
            "w_internal_order": _W_INTERNAL_ORDER,
            "overall_candidate_score": round(overall, 10),
        },
    }


def _validate_and_parse_inputs(
    predicted_top10: list[str],
    official_records: list[dict[str, Any]],
    field_size: int,
) -> tuple[dict[str, int | None], dict[str, str | None]]:
    """Validate the public scoring contract and parse official records."""
    if len(predicted_top10) != _TOP10_SIZE:
        raise ValueError(
            f"predicted_top10 must have exactly 10 entries, got {len(predicted_top10)}"
        )
    if any(not isinstance(driver, str) or not driver.strip() for driver in predicted_top10):
        raise ValueError("predicted_top10 driver_id values must be non-empty strings")
    if len(set(predicted_top10)) != len(predicted_top10):
        raise ValueError("predicted_top10 must not contain duplicate driver_id values")
    if isinstance(field_size, bool) or not isinstance(field_size, int):
        raise ValueError("field_size must be an integer")
    if field_size < _TOP10_SIZE:
        raise ValueError(f"field_size must be >= 10, got {field_size}")
    if len(official_records) != field_size:
        raise ValueError(
            "official_records must cover the frozen field_size universe: "
            f"expected {field_size}, got {len(official_records)}"
        )

    official_pos: dict[str, int | None] = {}
    official_status: dict[str, str | None] = {}
    seen_positions: set[int] = set()

    for index, rec in enumerate(official_records):
        if not isinstance(rec, dict):
            raise ValueError(f"official_records[{index}] must be an object")
        did = rec.get("driver_id")
        if not isinstance(did, str) or not did.strip():
            raise ValueError(
                f"official_records[{index}].driver_id must be a non-empty string"
            )
        if did in official_pos:
            raise ValueError(f"duplicate official driver_id: {did}")

        pos = rec.get("position")
        raw_status = rec.get("classification_status", rec.get("status"))
        status = raw_status.strip() if isinstance(raw_status, str) and raw_status.strip() else None

        if pos is None:
            if status is None:
                raise ValueError(
                    f"official driver {did} with position=None requires a non-empty status"
                )
            parsed_pos = None
        else:
            if isinstance(pos, bool) or not isinstance(pos, int):
                raise ValueError(f"official position for {did} must be an integer or null")
            if not 1 <= pos <= field_size:
                raise ValueError(
                    f"official position for {did} must be within 1..{field_size}, got {pos}"
                )
            if pos in seen_positions:
                raise ValueError(f"duplicate official numeric position: {pos}")
            seen_positions.add(pos)
            parsed_pos = pos

        official_pos[did] = parsed_pos
        official_status[did] = status

    missing = [driver for driver in predicted_top10 if driver not in official_pos]
    if missing:
        raise ValueError(
            "predicted driver_id values are absent from the frozen official universe: "
            + ", ".join(missing)
        )

    return official_pos, official_status


# ---------------------------------------------------------------------------
# M-POOL-MEMBERSHIP
# ---------------------------------------------------------------------------

def _compute_membership(
    predicted: list[str],
    official_top3: set[str],
    official_top5: set[str],
    official_top10: set[str],
) -> dict[str, float]:
    s_top3  = len(set(predicted[:3]) & official_top3)  / 3.0
    s_top5  = len(set(predicted[:5]) & official_top5)  / 5.0
    s_top10 = len(set(predicted)     & official_top10) / 10.0
    s_pool  = _W_TOP3 * s_top3 + _W_TOP5 * s_top5 + _W_TOP10 * s_top10
    return {
        "top3_set_score":       round(s_top3,  10),
        "top5_set_score":       round(s_top5,  10),
        "top10_set_score":      round(s_top10, 10),
        "pool_candidate_score": round(s_pool,  10),
    }


# ---------------------------------------------------------------------------
# M-EXACT-POSITION-HIT
# ---------------------------------------------------------------------------

def _position_value(i: int) -> float:
    """i is 1-based slot position (1..10)."""
    x = (i - 1) / 9.0
    return 1.0 - 0.4 * x ** _POSITION_EXPONENT


_POS_VALUES = [_position_value(i) for i in range(1, 11)]
_POS_VALUES_SUM = sum(_POS_VALUES)


def _compute_exact(
    predicted: list[str],
    official_position_of: dict[str, int],
) -> tuple[list[int], dict[str, float]]:
    # Build official_driver_at_slot: slot_position → driver_id (ranked drivers only)
    driver_at_slot: dict[int, str] = {p: d for d, p in official_position_of.items()}

    exact_vec = [
        1 if predicted[i] == driver_at_slot.get(i + 1) else 0
        for i in range(_TOP10_SIZE)
    ]
    s_exact = (
        sum(_POS_VALUES[i] * exact_vec[i] for i in range(_TOP10_SIZE))
        / _POS_VALUES_SUM
    )
    return exact_vec, {"exact_position_score": round(s_exact, 10)}


# ---------------------------------------------------------------------------
# M-EXACT-COMBO
# ---------------------------------------------------------------------------

def _start_value(s: int) -> float:
    """s is 1-based start position (1..9)."""
    return _Q ** (s - 1)


def _length_value(L: int) -> float:
    """L >= 2."""
    return _B ** (L - 10)


def _compute_combo(exact_vec: list[int]) -> dict[str, Any]:
    # Find all maximal contiguous runs of length >= 2
    runs: list[tuple[int, int]] = []   # (start_pos_1based, length)
    i = 0
    while i < _TOP10_SIZE:
        if exact_vec[i]:
            length = 1
            j = i + 1
            while j < _TOP10_SIZE and exact_vec[j]:
                length += 1
                j += 1
            if length >= 2:
                runs.append((i + 1, length))  # 1-based start
            i = j
        else:
            i += 1

    sv = [_start_value(r[0]) for r in runs]
    lv = [_length_value(r[1]) for r in runs]
    combo_shape = sum(sv[k] * lv[k] for k in range(len(runs)))
    combo_bonus = _X_COMBO * combo_shape

    return {
        "maximal_runs": [{"start": r[0], "length": r[1]} for r in runs],
        "per_run_start_value": [round(v, 10) for v in sv],
        "per_run_length_value": [round(v, 10) for v in lv],
        "combo_shape": combo_shape,
        "combo_bonus_candidate": combo_bonus,
    }


# ---------------------------------------------------------------------------
# M-PREDICTED-TOP10-RANK-DISTANCE
# ---------------------------------------------------------------------------

def _dsq_distance(slot: int, N: int) -> float:
    """Distance for a predicted-slot driver who turned out DSQ.

    slot : 1-based predicted position (1..10)
    N    : field size
    """
    base = abs(slot - 11)
    mirror_proxy = N + 1 - slot
    mirror_depth = max(1, mirror_proxy - 10)
    normalized_severity = mirror_depth / max(1, N - 10)
    uncertainty = _DSQ_U_MAX * math.sqrt(normalized_severity)
    return base + uncertainty


def _compute_distance(
    predicted: list[str],
    official_pos: dict[str, int | None],
    official_status: dict[str, str | None],
    field_size: int,
) -> dict[str, Any]:
    dist_vec: list[float] = []
    trace: list[str] = []

    for slot, driver in enumerate(predicted, start=1):
        off_pos = official_pos[driver]
        if off_pos is None:
            d = _dsq_distance(slot, field_size)
            trace.append(f"slot_{slot}:{driver}={official_status[driver]}")
        else:
            d = abs(slot - off_pos)
            trace.append(f"slot_{slot}:{driver}=P{off_pos}→dist{d}")
        dist_vec.append(round(d, 10))

    dist_sum = sum(dist_vec)
    mean_dist = dist_sum / 10.0

    return {
        "distance_vector": dist_vec,
        "distance_sum": dist_sum,
        "mean_rank_distance": mean_dist,
        "max_rank_distance": max(dist_vec),
        "status_branch_trace": trace,
    }


# ---------------------------------------------------------------------------
# M-DRIVER-INTERNAL-ORDER
# ---------------------------------------------------------------------------

def _compute_internal_order(
    predicted: list[str],
    official_top10_set: set[str],
    official_position_of: dict[str, int],
) -> dict[str, Any]:
    common = [d for d in predicted if d in official_top10_set]
    m = len(common)

    if m < 2:
        return {
            "common_driver_count": m,
            "observed_pair_count": 0,
            "inversion_count": 0,
            "conditional_order_accuracy": None,
            "signed_internal_order_skill": 0.0,
            "internal_order_score": 0.0,
            "scoring_status": "insufficient_common_drivers",
        }

    pred_rank = {d: predicted.index(d) for d in common}   # lower = better
    off_rank  = {d: official_position_of[d] for d in common}

    T = m * (m - 1) // 2
    concordant = inversions = 0
    for j in range(len(common)):
        for k in range(j + 1, len(common)):
            d1, d2 = common[j], common[k]
            pred_ahead = pred_rank[d1] < pred_rank[d2]   # d1 ranked better in prediction
            off_ahead  = off_rank[d1]  < off_rank[d2]    # d1 ranked better officially
            if pred_ahead == off_ahead:
                concordant += 1
            else:
                inversions += 1

    cond_acc = concordant / T if T > 0 else None

    return {
        "common_driver_count": m,
        "observed_pair_count": T,
        "inversion_count": inversions,
        "conditional_order_accuracy": round(cond_acc, 10) if cond_acc is not None else None,
        "signed_internal_order_skill": round(
            (concordant - inversions) / _INTERNAL_ORDER_DENOM,
            10,
        ),
        "internal_order_score": round(concordant / _INTERNAL_ORDER_DENOM, 10),
    }
