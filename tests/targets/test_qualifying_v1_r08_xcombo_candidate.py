from __future__ import annotations

import hashlib
import math
from pathlib import Path

import pytest

from scripts.qualifying_v1_r08_synthetic_score_audit import (
    COMBO_BASE,
    CONTROL_X_COMBO,
    CURRENT_X_COMBO,
    _combo_runs,
    _legacy_combo_x,
    _position_values,
    _validate_combo_x,
    build_scenarios,
    load_r08_ground_truth,
    render_report,
    score_prediction,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_REPORT_SHA256 = (
    "99700b76316fede1de37d8e6f178a5a8d07459cdd5dd90f790d344616e499482"
)


def _scored_fixed(x_combo: float):
    truth = load_r08_ground_truth(PROJECT_ROOT)
    scenarios = build_scenarios(truth)
    return truth, {
        scenario.scenario_id: score_prediction(
            scenario.predicted_top10, truth, x_combo
        )
        for scenario in scenarios
        if scenario.kind == "fixed"
    }


def _combo_shape(start: int, length: int) -> float:
    mask = [False] * 10
    for index in range(start - 1, start - 1 + length):
        mask[index] = True
    runs = _combo_runs(mask)
    assert len(runs) == 1
    return runs[0].shape_contribution


def _historical_control_report() -> str:
    candidates = (
        PROJECT_ROOT
        / "docs/model_development/qualifying/single_event_scoring/evidence/qualifying_v1_r08_synthetic_score_audit_control_04323589504.md",
        PROJECT_ROOT
        / "docs/model_development/qualifying/single_event_scoring/evidence/qualifying_v1_r08_synthetic_score_audit.md",
    )
    for path in candidates:
        if not path.exists():
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() == CONTROL_REPORT_SHA256:
            return data.decode("utf-8")
    raise AssertionError("no byte-identical historical control report found")


def test_authoritative_r08_inputs_are_valid() -> None:
    truth = load_r08_ground_truth(PROJECT_ROOT)

    assert truth.round_id == "R08"
    assert truth.field_size == 22
    assert len(truth.official_order) == 22
    assert len(set(truth.official_order)) == 22
    assert truth.official_audit_status == "pass"
    assert truth.field_size_audit_status == "pass"
    assert truth.has_non_numeric_status is False


def test_combo_protocol_is_explicit_and_distance_coefficient_is_derived() -> None:
    position_values = _position_values()

    assert CURRENT_X_COMBO == pytest.approx(0.20, abs=1e-15)
    assert CONTROL_X_COMBO == pytest.approx(0.4323589504, abs=1e-15)
    assert _legacy_combo_x(position_values) == pytest.approx(
        CONTROL_X_COMBO, abs=5e-11
    )
    assert 1.0 / (25.0 * (1.0 + CURRENT_X_COMBO)) == pytest.approx(
        0.0333333333, abs=5e-11
    )
    assert 1.0 / (25.0 * (1.0 + CONTROL_X_COMBO)) == pytest.approx(
        0.0279259609, abs=5e-11
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.01])
def test_invalid_combo_protocol_fails_loud(value: float) -> None:
    with pytest.raises(ValueError, match="finite non-negative"):
        _validate_combo_x(value)


@pytest.mark.parametrize("x_combo", [CURRENT_X_COMBO, CONTROL_X_COMBO])
def test_perfect_prediction_is_unique_one_under_both_protocols(x_combo: float) -> None:
    truth = load_r08_ground_truth(PROJECT_ROOT)
    scored = [
        score_prediction(scenario.predicted_top10, truth, x_combo)
        for scenario in build_scenarios(truth)
    ]

    assert scored[0].overall_candidate_score == pytest.approx(1.0, abs=1e-12)
    assert scored[0].exact_branch_score == pytest.approx(1.0, abs=1e-12)
    assert scored[0].pool_membership_score == pytest.approx(1.0, abs=1e-12)
    assert scored[0].internal_order_score == pytest.approx(1.0, abs=1e-12)
    assert sum(
        math.isclose(result.overall_candidate_score, 1.0, abs_tol=1e-12)
        for result in scored
    ) == 1


def test_historical_control_report_remains_byte_identical() -> None:
    truth = load_r08_ground_truth(PROJECT_ROOT)
    generated = render_report(truth, build_scenarios(truth), CONTROL_X_COMBO)
    reference = _historical_control_report()

    assert generated == reference
    assert hashlib.sha256(generated.encode("utf-8")).hexdigest() == (
        CONTROL_REPORT_SHA256
    )


def test_current_report_is_deterministic_and_declares_current_protocol() -> None:
    truth = load_r08_ground_truth(PROJECT_ROOT)
    scenarios = build_scenarios(truth)
    first = render_report(truth, scenarios, CURRENT_X_COMBO)
    second = render_report(truth, scenarios, CURRENT_X_COMBO)

    assert first == second
    assert "| x_combo | 0.2000000000 |" in first
    assert "| k_distance | 0.0333333333 |" in first
    assert "current authoritative algorithm specification and ELG" in first
    assert "All 30 predicted rankings differ" in first
    assert "P1-P5 consecutive Exact should narrowly beat the fully shuffled Top10" in first
    assert "podium Exact with severe misses should slightly beat the fully reversed Top10" in first


def test_all_previously_confirmed_fixed_directions_hold_for_current() -> None:
    _, by_id = _scored_fixed(CURRENT_X_COMBO)

    assert by_id["FIX-03-BOTTOM-SWAP"].overall_candidate_score > by_id[
        "FIX-02-TOP-SWAP"
    ].overall_candidate_score
    assert by_id["FIX-06-P1-P5-COMBO"].overall_candidate_score > by_id[
        "FIX-07-P6-P10-COMBO"
    ].overall_candidate_score
    assert by_id["FIX-09-PODIUM-NEAR"].overall_candidate_score > by_id[
        "FIX-10-PODIUM-FAR"
    ].overall_candidate_score
    assert by_id["FIX-04-CYCLIC"].overall_candidate_score > by_id[
        "FIX-05-REVERSE"
    ].overall_candidate_score
    assert by_id["FIX-12-FOUR-EXACT-FAR"].overall_candidate_score > by_id[
        "FIX-11-FIVE-ORDERED-NO-EXACT"
    ].overall_candidate_score


def test_first_cross_branch_anchor_has_accepted_tiny_margin() -> None:
    _, by_id = _scored_fixed(CURRENT_X_COMBO)
    p1_p5 = by_id["FIX-06-P1-P5-COMBO"].overall_candidate_score
    cyclic = by_id["FIX-04-CYCLIC"].overall_candidate_score

    assert p1_p5 > cyclic
    assert p1_p5 - cyclic == pytest.approx(0.0004982472, abs=5e-10)


def test_second_cross_branch_anchor_is_narrow_and_both_are_poor() -> None:
    _, by_id = _scored_fixed(CURRENT_X_COMBO)
    podium_far = by_id["FIX-10-PODIUM-FAR"].overall_candidate_score
    reverse = by_id["FIX-05-REVERSE"].overall_candidate_score

    assert podium_far > reverse
    assert podium_far - reverse == pytest.approx(0.0055083967, abs=5e-10)
    assert podium_far < 0.20
    assert reverse < 0.20


def test_single_p1_miss_and_single_p5_miss_are_near_tied() -> None:
    truth = load_r08_ground_truth(PROJECT_ROOT)
    perfect = list(truth.official_order[:10])
    p1_miss = perfect.copy()
    p5_miss = perfect.copy()
    p1_miss[0] = truth.official_order[10]
    p5_miss[4] = truth.official_order[10]

    p1_score = score_prediction(p1_miss, truth, CURRENT_X_COMBO)
    p5_score = score_prediction(p5_miss, truth, CURRENT_X_COMBO)

    assert p1_score.overall_candidate_score > p5_score.overall_candidate_score
    assert p1_score.overall_candidate_score - p5_score.overall_candidate_score == (
        pytest.approx(0.007762, abs=5e-6)
    )


def test_p1_p5_raw_combo_increment_is_46258_percent_not_ten_percent() -> None:
    _, by_id = _scored_fixed(CURRENT_X_COMBO)
    result = by_id["FIX-06-P1-P5-COMBO"]

    assert result.combo_bonus / result.exact_position_score == pytest.approx(
        0.0462578605, abs=5e-11
    )
    assert result.combo_bonus / result.exact_position_score != pytest.approx(
        0.10, abs=1e-6
    )


def test_historical_combo_length_and_start_preferences_are_unchanged() -> None:
    f2 = COMBO_BASE ** (2 - 10)
    f3 = COMBO_BASE ** (3 - 10)
    f4 = COMBO_BASE ** (4 - 10)
    f5 = COMBO_BASE ** (5 - 10)

    assert 2 * f4 > f4 + f3 > f5 > 2 * f3 > f3 + f2
    p1_two = _combo_shape(1, 2)
    assert _combo_shape(3, 3) > p1_two
    assert _combo_shape(4, 3) == pytest.approx(p1_two, abs=1e-12)
    assert _combo_shape(5, 3) < p1_two


def test_every_overall_score_recomposes_from_reported_contributions() -> None:
    truth = load_r08_ground_truth(PROJECT_ROOT)
    for scenario in build_scenarios(truth):
        result = score_prediction(
            scenario.predicted_top10, truth, CURRENT_X_COMBO
        )
        assert result.overall_candidate_score == pytest.approx(
            result.exact_contribution
            + result.membership_contribution
            + result.internal_order_contribution,
            abs=1e-12,
        )
