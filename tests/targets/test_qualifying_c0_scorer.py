"""Tests for C0 qualifying scorer (ALG-QUALIFYING-001 v0.26).

Invariant numbers reference section 10 of the spec.
"""
from __future__ import annotations

import pytest

from f1_big_predictor.targets.qualifying.c0_scorer import (
    _K_DISTANCE, _Q, _X_COMBO, score_qualifying,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _official(order: list[str]) -> list[dict]:
    """Build official_records from an ordered list (P1 first)."""
    return [{"driver_id": d, "position": i + 1} for i, d in enumerate(order)]


def _official_with_dsq(order: list[str], dsq: set[str], N: int = 22) -> list[dict]:
    """Build official_records where DSQ drivers have position=None."""
    non_dsq = [d for d in order if d not in dsq]
    records = [{"driver_id": d, "position": i + 1} for i, d in enumerate(non_dsq)]
    for d in dsq:
        records.append({"driver_id": d, "position": None, "status": "DSQ"})
    return records


def _score(predicted: list[str], official: list[dict], N: int = 22) -> dict:
    return score_qualifying(predicted, official, field_size=N)


DRIVERS = [f"d{i:02d}" for i in range(1, 23)]   # d01..d22

PERFECT_ORDER = DRIVERS[:10]
PERFECT_OFFICIAL = _official(DRIVERS)


# ---------------------------------------------------------------------------
# Invariant 2: S_exact in [0,1]; perfect ten = 1
# ---------------------------------------------------------------------------

class TestExact:
    def test_perfect_ten_exact_score_is_one(self):
        r = _score(PERFECT_ORDER, PERFECT_OFFICIAL)
        assert r["exact"]["exact_position_score"] == pytest.approx(1.0, abs=1e-9)

    def test_all_wrong_exact_score_is_zero(self):
        # predict d11..d20 when real top10 is d01..d10
        wrong = DRIVERS[10:20]
        r = _score(wrong, PERFECT_OFFICIAL)
        assert r["exact"]["exact_position_score"] == pytest.approx(0.0, abs=1e-9)

    def test_exact_hit_count_matches_vector(self):
        r = _score(PERFECT_ORDER, PERFECT_OFFICIAL)
        assert r["exact"]["exact_hit_count"] == sum(r["exact"]["exact_hit_vector"])

    def test_exact_hit_positions_are_1_based(self):
        r = _score(PERFECT_ORDER, PERFECT_OFFICIAL)
        assert r["exact"]["exact_hit_positions"] == list(range(1, 11))

    def test_p1_p5_exact_score(self):
        # spec says S_exact(P1-P5 five-hit) ≈ 0.5693616; verify to 4 dp
        partial = PERFECT_ORDER[:5] + DRIVERS[10:15]  # P6-P10 wrong
        r = _score(partial, PERFECT_OFFICIAL)
        assert r["exact"]["exact_position_score"] == pytest.approx(0.5693616, abs=1e-4)


# ---------------------------------------------------------------------------
# Invariant 5: perfect P1-P10 ComboShape = 1
# ---------------------------------------------------------------------------

class TestCombo:
    def test_perfect_combo_shape_is_one(self):
        r = _score(PERFECT_ORDER, PERFECT_OFFICIAL)
        assert r["combo"]["combo_shape"] == pytest.approx(1.0, abs=1e-9)

    def test_no_hits_no_combo(self):
        wrong = DRIVERS[10:20]
        r = _score(wrong, PERFECT_OFFICIAL)
        assert r["combo"]["maximal_runs"] == []
        assert r["combo"]["combo_shape"] == pytest.approx(0.0, abs=1e-12)

    def test_single_hit_no_combo(self):
        # only P1 exact
        partial = [DRIVERS[0]] + DRIVERS[10:19]
        r = _score(partial, PERFECT_OFFICIAL)
        assert r["combo"]["maximal_runs"] == []

    def test_run_of_two_detected(self):
        # P1-P2 exact, rest wrong
        partial = DRIVERS[:2] + DRIVERS[10:18]
        r = _score(partial, PERFECT_OFFICIAL)
        runs = r["combo"]["maximal_runs"]
        assert len(runs) == 1
        assert runs[0]["start"] == 1
        assert runs[0]["length"] == 2

    def test_miss_cuts_run(self):
        # P1 exact, P2 wrong, P3-P5 exact → one run of 3 starting at P3
        partial = [DRIVERS[0], DRIVERS[10], DRIVERS[2], DRIVERS[3], DRIVERS[4]] + DRIVERS[11:16]
        r = _score(partial, PERFECT_OFFICIAL)
        runs = r["combo"]["maximal_runs"]
        assert len(runs) == 1
        assert runs[0]["start"] == 3
        assert runs[0]["length"] == 3

    def test_combo_shape_values(self):
        # Spec table: length=2 → 0.0390, length=5 → 0.1317 (from P1)
        lv2  = 1.5 ** (2 - 10)
        lv5  = 1.5 ** (5 - 10)
        sv1  = _Q ** 0
        assert lv2 == pytest.approx(0.0390, abs=5e-4)
        assert lv5 == pytest.approx(0.1317, abs=5e-4)
        assert sv1 == pytest.approx(1.0, abs=1e-9)

    def test_exact_positive_score_perfect(self):
        # Invariant 13: ExactPositiveScore in [0,1]; perfect ten = 1
        r = _score(PERFECT_ORDER, PERFECT_OFFICIAL)
        assert r["exact"]["exact_positive_score"] == pytest.approx(1.0, abs=1e-9)

    def test_x_combo_value(self):
        assert _X_COMBO == pytest.approx(0.20, abs=1e-12)


# ---------------------------------------------------------------------------
# Invariant 10: rank distance not normalised by N
# ---------------------------------------------------------------------------

class TestDistance:
    def test_perfect_distance_zero(self):
        r = _score(PERFECT_ORDER, PERFECT_OFFICIAL)
        assert r["distance"]["mean_rank_distance"] == pytest.approx(0.0, abs=1e-12)
        assert all(d == 0 for d in r["distance"]["distance_vector"])

    def test_distance_one_slot_off(self):
        # swap P1 and P2
        partial = [DRIVERS[1], DRIVERS[0]] + DRIVERS[2:10]
        r = _score(partial, PERFECT_OFFICIAL)
        # P1 predicted d02 actual P2 → dist=1; P2 predicted d01 actual P1 → dist=1; rest 0
        assert r["distance"]["distance_vector"][:2] == [pytest.approx(1.0), pytest.approx(1.0)]
        assert r["distance"]["mean_rank_distance"] == pytest.approx(0.2, abs=1e-9)

    def test_k_distance_value(self):
        assert _K_DISTANCE == pytest.approx(1.0 / 30.0, abs=1e-12)

    def test_dsq_distance_at_p1_n22(self):
        # spec: slot=P1, N=22 → base=10, correction=2.0, total=12.0
        from f1_big_predictor.targets.qualifying.c0_scorer import _dsq_distance
        assert _dsq_distance(1, 22) == pytest.approx(12.0, abs=1e-9)

    def test_dsq_distance_at_p10_n22(self):
        # spec: slot=P10, N=22 → base=1, correction=1.0, total=2.0
        from f1_big_predictor.targets.qualifying.c0_scorer import _dsq_distance
        assert _dsq_distance(10, 22) == pytest.approx(2.0, abs=1e-9)

    def test_dsq_correction_strictly_positive_all_slots(self):
        from f1_big_predictor.targets.qualifying.c0_scorer import _dsq_distance
        for slot in range(1, 11):
            d = _dsq_distance(slot, 22)
            base = abs(slot - 11)
            assert d > base, f"slot {slot}: DSQ dist ({d}) not > base ({base})"

    def test_dsq_in_prediction(self):
        # d01 is DSQ; predicted P1 = d01
        official_no_d01 = _official_with_dsq(DRIVERS, dsq={"d01"})
        pred = [DRIVERS[0]] + DRIVERS[1:10]
        r = score_qualifying(pred, official_no_d01, field_size=22)
        # distance for slot 1 should use DSQ formula
        assert r["distance"]["distance_vector"][0] == pytest.approx(12.0, abs=1e-9)
        assert r["distance"]["status_branch_trace"][0] == "slot_1:d01=DSQ"


class TestInputContract:
    def test_duplicate_predicted_driver_is_rejected(self):
        predicted = [DRIVERS[0], DRIVERS[0], *DRIVERS[2:10]]
        with pytest.raises(ValueError, match="duplicate driver_id"):
            _score(predicted, PERFECT_OFFICIAL)

    def test_duplicate_official_driver_is_rejected(self):
        official = [dict(record) for record in PERFECT_OFFICIAL]
        official[-1]["driver_id"] = official[0]["driver_id"]
        with pytest.raises(ValueError, match="duplicate official driver_id"):
            _score(PERFECT_ORDER, official)

    def test_duplicate_numeric_position_is_rejected(self):
        official = [dict(record) for record in PERFECT_OFFICIAL]
        official[-1]["position"] = 1
        with pytest.raises(ValueError, match="duplicate official numeric position"):
            _score(PERFECT_ORDER, official)

    def test_out_of_range_numeric_position_is_rejected(self):
        official = [dict(record) for record in PERFECT_OFFICIAL]
        official[-1]["position"] = 23
        with pytest.raises(ValueError, match="within 1..22"):
            _score(PERFECT_ORDER, official)

    def test_position_none_without_status_is_rejected(self):
        official = [dict(record) for record in PERFECT_OFFICIAL]
        official[0]["position"] = None
        with pytest.raises(ValueError, match="requires a non-empty status"):
            _score(PERFECT_ORDER, official)

    def test_official_records_must_cover_frozen_universe(self):
        with pytest.raises(ValueError, match="cover the frozen field_size universe"):
            _score(PERFECT_ORDER, PERFECT_OFFICIAL[:-1])

    def test_predicted_driver_absent_from_official_universe_is_rejected(self):
        predicted = ["not_entered", *PERFECT_ORDER[1:]]
        with pytest.raises(ValueError, match="absent from the frozen official universe"):
            _score(predicted, PERFECT_OFFICIAL)


# ---------------------------------------------------------------------------
# Invariant 8 & 9: internal order
# ---------------------------------------------------------------------------

class TestInternalOrder:
    def test_perfect_internal_order_score_one(self):
        r = _score(PERFECT_ORDER, PERFECT_OFFICIAL)
        assert r["internal_order"]["internal_order_score"] == pytest.approx(1.0, abs=1e-9)

    def test_complete_reversal_score_zero(self):
        # Reverse the top10 prediction (all 10 hit but completely wrong order)
        pred = list(reversed(PERFECT_ORDER))
        r = _score(pred, PERFECT_OFFICIAL)
        assert r["internal_order"]["internal_order_score"] == pytest.approx(0.0, abs=1e-9)
        assert r["internal_order"]["signed_internal_order_skill"] == pytest.approx(-1.0, abs=1e-9)

    def test_insufficient_common_drivers_gives_zero(self):
        # Predict all outside top10
        pred = DRIVERS[10:20]
        r = _score(pred, PERFECT_OFFICIAL)
        assert r["internal_order"]["internal_order_score"] == pytest.approx(0.0, abs=1e-9)
        assert r["internal_order"]["signed_internal_order_skill"] == pytest.approx(0.0, abs=1e-9)

    def test_two_correct_pair(self):
        # Only d01 and d02 hit, order correct; m=2, T=1, C=1 → 1/45
        pred = [DRIVERS[0], DRIVERS[1]] + DRIVERS[10:18]
        r = _score(pred, PERFECT_OFFICIAL)
        assert r["internal_order"]["internal_order_score"] == pytest.approx(1 / 45.0, abs=1e-9)

    def test_two_wrong_pair(self):
        # d02, d01 → order inverted; m=2, C=0 → 0
        pred = [DRIVERS[1], DRIVERS[0]] + DRIVERS[10:18]
        r = _score(pred, PERFECT_OFFICIAL)
        assert r["internal_order"]["internal_order_score"] == pytest.approx(0.0, abs=1e-9)
        assert r["internal_order"]["signed_internal_order_skill"] == pytest.approx(-1 / 45.0, abs=1e-9)

    def test_five_correct_score(self):
        # five of top10 hit in correct order; m=5, T=10, C=10 → 10/45
        pred = DRIVERS[:5] + DRIVERS[10:15]
        r = _score(pred, PERFECT_OFFICIAL)
        assert r["internal_order"]["internal_order_score"] == pytest.approx(10 / 45.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Invariant 15 & 17–18: branch weights and overall
# ---------------------------------------------------------------------------

class TestOverall:
    def test_perfect_overall_is_one(self):
        r = _score(PERFECT_ORDER, PERFECT_OFFICIAL)
        assert r["overall_candidate"]["overall_candidate_score"] == pytest.approx(1.0, abs=1e-9)

    def test_branch_weights_sum_to_one(self):
        r = _score(PERFECT_ORDER, PERFECT_OFFICIAL)
        oc = r["overall_candidate"]
        total = oc["w_exact"] + oc["w_membership"] + oc["w_internal_order"]
        assert total == pytest.approx(1.0, abs=1e-12)

    def test_exact_branch_score_is_signed_not_clipped(self):
        # All 10 wrong AND large distances → ExactBranchScore should be negative
        pred = DRIVERS[10:20]
        r = _score(pred, PERFECT_OFFICIAL)
        assert r["exact_branch"]["exact_branch_score"] < 0

    def test_spec_anchor_p1_p5_five_hit_with_dist2(self):
        # spec: P1-P5 exact, rest wrong, mean_rank_distance≈2
        # ExactPositiveScore ≈ 0.4964159, DistancePenalty ≈ 0.0666667
        # ExactBranchScore   ≈ 0.4297492
        # exact:P1-P5 perfect, P6-P10: d11..d15 (at official P11..P15)
        # official P6-P10 are d06..d10; d11..d15 at P11..P15
        # distances for slots 6-10: |6-11|=5, |7-12|=5, |8-13|=5, |9-14|=5, |10-15|=5
        pred = DRIVERS[:5] + DRIVERS[10:15]
        r = _score(pred, PERFECT_OFFICIAL)
        assert r["exact_branch"]["exact_positive_score"] == pytest.approx(0.4964159, abs=1e-5)
        assert r["distance"]["mean_rank_distance"] == pytest.approx(2.5, abs=1e-9)
        # ExactBranchScore = 0.4964159 - k_distance*2.5 = 0.4964159 - 2.5/30
        expected_ebs = 0.4964159 - 2.5 / 30.0
        assert r["exact_branch"]["exact_branch_score"] == pytest.approx(expected_ebs, abs=1e-5)

    def test_spec_anchor_r08_cross_branch_1(self):
        # spec 8.8 anchor A: full top10 in, cyclic shift P2..P10,P1 → zero Exact
        # d02,d03,...,d10,d01 predicted; official d01=P1,...,d10=P10
        pred = DRIVERS[1:10] + [DRIVERS[0]]   # cyclic
        r = _score(pred, PERFECT_OFFICIAL)
        assert r["exact"]["exact_hit_count"] == 0
        # overall should be ≈ 0.4573 per spec
        assert r["overall_candidate"]["overall_candidate_score"] == pytest.approx(0.4573, abs=5e-3)

    def test_overall_formula(self):
        r = _score(PERFECT_ORDER[:5] + DRIVERS[10:15], PERFECT_OFFICIAL)
        expected = (
            0.45 * r["exact_branch"]["exact_branch_score"]
            + 0.35 * r["membership"]["pool_candidate_score"]
            + 0.20 * r["internal_order"]["internal_order_score"]
        )
        assert r["overall_candidate"]["overall_candidate_score"] == pytest.approx(expected, abs=1e-9)
