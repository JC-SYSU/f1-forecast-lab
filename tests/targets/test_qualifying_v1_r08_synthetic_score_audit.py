from __future__ import annotations

from pathlib import Path

import pytest

from scripts.qualifying_v1_r08_synthetic_score_audit import (
    CURRENT_X_COMBO,
    build_scenarios,
    load_r08_ground_truth,
    render_report,
    score_prediction,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_r08_ground_truth_passes_authoritative_gates() -> None:
    truth = load_r08_ground_truth(PROJECT_ROOT)

    assert truth.round_id == "R08"
    assert truth.field_size == 22
    assert len(truth.official_order) == 22
    assert len(set(truth.official_order)) == 22
    assert truth.official_order[:10] == (
        "russell",
        "leclerc",
        "hamilton",
        "antonelli",
        "max_verstappen",
        "norris",
        "piastri",
        "hadjar",
        "lawson",
        "arvid_lindblad",
    )
    assert truth.official_audit_status == "pass"
    assert truth.field_size_audit_status == "pass"
    assert truth.has_non_numeric_status is False


def test_perfect_prediction_scores_one_on_every_main_branch() -> None:
    truth = load_r08_ground_truth(PROJECT_ROOT)
    result = score_prediction(truth.official_order[:10], truth)

    assert result.top3_set_score == 1.0
    assert result.top5_set_score == 1.0
    assert result.top10_set_score == 1.0
    assert result.pool_membership_score == 1.0
    assert result.exact_hit_count == 10
    assert result.exact_position_score == 1.0
    assert result.combo_shape == 1.0
    assert result.combo_x == CURRENT_X_COMBO
    assert result.exact_positive_score == 1.0
    assert result.mean_rank_distance == 0.0
    assert result.distance_penalty == 0.0
    assert result.exact_branch_score == 1.0
    assert result.internal_order_score == 1.0
    assert result.signed_internal_order_skill == 1.0
    assert result.overall_candidate_score == 1.0


def test_full_reverse_keeps_signed_diagnostic_but_nonnegative_order_score() -> None:
    truth = load_r08_ground_truth(PROJECT_ROOT)
    result = score_prediction(tuple(reversed(truth.official_order[:10])), truth)

    assert result.exact_hit_count == 0
    assert result.top10_set_score == 1.0
    assert result.pool_membership_score == pytest.approx(0.7)
    assert result.mean_rank_distance == pytest.approx(5.0)
    assert result.observed_pair_count == 45
    assert result.inversion_count == 45
    assert result.correct_pair_count == 0
    assert result.internal_order_score == 0.0
    assert result.signed_internal_order_skill == -1.0
    assert result.exact_branch_score < 0.0
    assert result.overall_candidate_score == pytest.approx(0.1700000, abs=1e-6)


def test_scenario_suite_has_12_fixed_and_18_reproducible_stratified_random() -> None:
    truth = load_r08_ground_truth(PROJECT_ROOT)
    first = build_scenarios(truth)
    second = build_scenarios(truth)

    assert first == second
    assert len(first) == 30
    assert len({scenario.scenario_id for scenario in first}) == 30
    assert len({scenario.predicted_top10 for scenario in first}) == 30
    assert sum(scenario.kind == "fixed" for scenario in first) == 12
    assert sum(scenario.kind == "weighted_random" for scenario in first) == 18

    universe = set(truth.official_order)
    random_cells: dict[tuple[str, str], int] = {}
    membership_ranges = {
        "high": range(8, 11),
        "medium": range(5, 8),
        "low": range(2, 5),
    }
    official_top10 = set(truth.official_order[:10])

    for scenario in first:
        assert len(scenario.predicted_top10) == 10
        assert len(set(scenario.predicted_top10)) == 10
        assert set(scenario.predicted_top10) <= universe
        if scenario.kind != "weighted_random":
            continue
        key = (scenario.membership_tier, scenario.order_tier)
        random_cells[key] = random_cells.get(key, 0) + 1
        common_count = len(set(scenario.predicted_top10) & official_top10)
        assert common_count in membership_ranges[scenario.membership_tier]

    assert set(random_cells.values()) == {2}
    assert len(random_cells) == 9


def test_rendered_report_exposes_every_sample_and_all_score_families() -> None:
    truth = load_r08_ground_truth(PROJECT_ROOT)
    scenarios = build_scenarios(truth)
    report = render_report(truth, scenarios)

    for scenario in scenarios:
        assert report.count(scenario.scenario_id) >= 7
        result = score_prediction(scenario.predicted_top10, truth)
        assert result.overall_candidate_score == pytest.approx(
            result.exact_contribution
            + result.membership_contribution
            + result.internal_order_contribution
        )
    for required_heading in (
        "## 1. Authoritative data and gates",
        "## 4. Overall ranking and main branches",
        "## 5. Membership details",
        "## 6. Exact, Combo, and Distance details",
        "## 7. Internal Order details",
        "## 8. Outer weight contributions",
        "## 9. Fixed adversarial checks",
        "## 10. Project lead's preliminary judgment",
        "## 11. Limitations and next steps",
    ):
        assert required_heading in report
    assert "must not be used as an official comparator backtest" in report
