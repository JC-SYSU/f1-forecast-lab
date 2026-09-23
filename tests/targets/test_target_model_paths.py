from __future__ import annotations

import pytest

from f1_big_predictor.targets.qualifying import (
    QualifyingTargetConfig,
    QualifyingTargetInputs,
    predict_qualifying_target,
)
from f1_big_predictor.targets.qualifying.evaluate import evaluate_qualifying_target
from f1_big_predictor.targets.qualifying.search_space import search_space as qualifying_search_space
from f1_big_predictor.targets.race import RaceTargetConfig, RaceTargetInputs, predict_race_target
from f1_big_predictor.targets.race.evaluate import evaluate_race_target
from f1_big_predictor.targets.race.search_space import search_space as race_search_space
from f1_big_predictor.targets.sprint_qualifying import (
    SprintQualifyingTargetConfig,
    SprintQualifyingTargetInputs,
    predict_sprint_qualifying_target,
)
from f1_big_predictor.targets.sprint_qualifying.search_space import search_space as sprint_qualifying_search_space
from f1_big_predictor.targets.sprint_race import (
    SprintRaceAsOfProfile,
    SprintRaceTargetConfig,
    SprintRaceTargetInputs,
    predict_sprint_race_target,
)
from f1_big_predictor.targets.sprint_race.search_space import search_space as sprint_race_search_space

def test_race_target_has_independent_schema() -> None:
    prediction = predict_race_target(
        inputs=RaceTargetInputs(driver_features=_race_features()),
        config=RaceTargetConfig(),
    )

    assert prediction.target_id == "race"
    assert prediction.model_id == "race.model.v0"
    assert prediction.feature_set_id == "race.features.v0.driver_scores"
    assert prediction.fallback_policy == "require_race_driver_features_else_evidence_issue"
    assert prediction.status == "ok"
    assert [item["driver_id"] for item in prediction.entries[:2]] == ["driver_01", "driver_02"]
    assert race_search_space()["search_space_id"] == "race.search_space.v0.weighted"
    assert race_search_space()["parameters"]


def test_race_target_rejects_missing_feature_score() -> None:
    with pytest.raises(ValueError, match="race_score"):
        predict_race_target(
            inputs=RaceTargetInputs(driver_features=[{"driver_id": "driver_01"}]),
            config=RaceTargetConfig(),
        )


def test_qualifying_target_reports_missing_lap_time_gap() -> None:
    features = _qualifying_component_features()

    prediction = predict_qualifying_target(
        inputs=QualifyingTargetInputs(driver_features=features),
        config=QualifyingTargetConfig(),
    )

    assert prediction.target_id == "qualifying"
    assert prediction.model_id == "qualifying.model.v1.explainable_score"
    assert prediction.feature_set_id == "qualifying.features.v1.explainable_score"
    assert qualifying_search_space()["search_space_id"] == "qualifying.search_space.v1.weighted"
    assert "track_profile_weight" in {
        item["name"] for item in qualifying_search_space()["parameters"]
    }
    assert qualifying_search_space()["weight_profiles"]["independent"]["track_profile"] == 0.10
    assert prediction.status == "ok"
    assert "lap_time_not_predicted_v1" in prediction.evidence_gaps


def test_qualifying_target_ranks_by_component_score() -> None:
    prediction = predict_qualifying_target(
        inputs=QualifyingTargetInputs(
            driver_features=[
                {
                    "driver_id": "slow",
                    "form_score": 0.2,
                    "constructor_score": 0.2,
                    "circuit_fit_score": 0.2,
                    "reliability_score": 0.2,
                },
                {
                    "driver_id": "fast",
                    "form_score": 0.9,
                    "constructor_score": 0.9,
                    "circuit_fit_score": 0.9,
                    "reliability_score": 0.9,
                },
                *[
                    {
                        "driver_id": f"padding_{index}",
                        "form_score": 0.0,
                        "constructor_score": 0.0,
                        "circuit_fit_score": 0.0,
                        "reliability_score": 0.0,
                    }
                    for index in range(8)
                ],
            ]
        ),
        config=QualifyingTargetConfig(),
    )

    assert [item["driver_id"] for item in prediction.entries[:2]] == ["fast", "slow"]
    assert prediction.entries[0]["lap_time"] is None
    assert prediction.entries[0]["delta_to_pole"] is None


def test_sprint_qualifying_target_can_be_not_applicable() -> None:
    prediction = predict_sprint_qualifying_target(
        inputs=SprintQualifyingTargetInputs(driver_features=None, is_sprint_weekend=False),
        config=SprintQualifyingTargetConfig(),
    )

    assert prediction.target_id == "sprint_qualifying"
    assert prediction.model_id == "sprint_qualifying.model.v0"
    assert prediction.feature_set_id == "sprint_qualifying.features.v0.driver_scores_lap_times"
    assert sprint_qualifying_search_space()["search_space_id"] == "sprint_qualifying.search_space.v0.weighted"
    assert prediction.status == "not_applicable"
    assert prediction.entries == []


def test_sprint_qualifying_target_reports_missing_feature_gap_on_sprint_weekend() -> None:
    prediction = predict_sprint_qualifying_target(
        inputs=SprintQualifyingTargetInputs(driver_features=[], is_sprint_weekend=True),
        config=SprintQualifyingTargetConfig(),
    )

    assert prediction.status == "evidence_issue"
    assert "missing_sprint_qualifying_driver_features" in prediction.evidence_gaps


def test_sprint_race_target_can_run_before_sprint_qualifying() -> None:
    prediction = predict_sprint_race_target(
        inputs=SprintRaceTargetInputs(
            driver_features=[
                {"driver_id": "pre_2", "sprint_race_score": 1.0},
                {"driver_id": "pre_1", "sprint_race_score": 2.0},
            ],
            as_of_profile=SprintRaceAsOfProfile(
                is_sprint_weekend=True,
                sprint_qualifying_available=False,
            ),
        ),
        config=SprintRaceTargetConfig(),
    )

    assert prediction.status == "ok"
    assert [item["driver_id"] for item in prediction.entries] == ["pre_1", "pre_2"]
    assert "missing_sprint_race_sprint_qualifying_position" not in prediction.evidence_gaps
    assert sprint_race_search_space()["search_space_id"] == "sprint_race.search_space.v0.weighted"


def test_sprint_race_target_uses_sprint_race_score_features() -> None:
    prediction = predict_sprint_race_target(
        inputs=SprintRaceTargetInputs(
            driver_features=[
                {"driver_id": "p2", "sprint_race_score": 1.0, "sprint_qualifying_position": 2},
                {"driver_id": "p1", "sprint_race_score": 2.0, "sprint_qualifying_position": 1},
            ],
            as_of_profile=SprintRaceAsOfProfile(is_sprint_weekend=True, sprint_qualifying_available=True),
        ),
        config=SprintRaceTargetConfig(),
    )

    assert [item["driver_id"] for item in prediction.entries] == ["p1", "p2"]


def test_sprint_race_target_reports_missing_sprint_qualifying_position_after_session() -> None:
    prediction = predict_sprint_race_target(
        inputs=SprintRaceTargetInputs(
            driver_features=[{"driver_id": "p1", "sprint_race_score": 2.0}],
            as_of_profile=SprintRaceAsOfProfile(is_sprint_weekend=True, sprint_qualifying_available=True),
        ),
        config=SprintRaceTargetConfig(),
    )

    assert "missing_sprint_race_sprint_qualifying_position" in prediction.evidence_gaps


def test_target_evaluation_helpers_are_position_based() -> None:
    predicted = [f"driver_{index:02d}" for index in range(1, 11)]
    actual = ["driver_02", "driver_01", *predicted[2:]]

    race = evaluate_race_target(predicted_driver_ids=predicted, actual_driver_ids=actual)
    qualifying = evaluate_qualifying_target(
        predicted_driver_ids=predicted,
        actual_driver_ids=actual,
        lap_time_mae=1.25,
    )

    assert race.top10_position_accuracy == 0.8
    assert race.rank_mae == 0.2
    assert race.evaluation_gate == "top10_accuracy_rank_mae"
    assert qualifying.lap_time_mae == 1.25
    assert qualifying.evaluation_gate == "top10_accuracy_rank_mae_lap_time_mae"


def _race_features() -> list[dict[str, object]]:
    return [
        {"driver_id": f"driver_{index:02d}", "driver_name": f"Driver {index}", "race_score": 100 - index}
        for index in range(1, 11)
    ]


def _session_features(score_field: str) -> list[dict[str, object]]:
    return [
        {
            "driver_id": f"driver_{index:02d}",
            "driver_name": f"Driver {index}",
            score_field: 100 - index,
            "predicted_lap_time": "1:20.000",
        }
        for index in range(1, 11)
    ]


def _qualifying_component_features() -> list[dict[str, object]]:
    return [
        {
            "driver_id": f"driver_{index:02d}",
            "driver_name": f"Driver {index}",
            "form_score": 1.0 - index / 100,
            "constructor_score": 0.8,
            "circuit_fit_score": 0.7,
            "reliability_score": 0.5,
        }
        for index in range(1, 11)
    ]
