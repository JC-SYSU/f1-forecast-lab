from __future__ import annotations

from pathlib import Path

import pytest

from f1_big_predictor.targets.qualifying import (
    QualifyingTargetConfig,
    QualifyingTargetInputs,
    build_qualifying_features,
    predict_qualifying_target,
    score_qualifying_field,
)
from f1_big_predictor.targets.qualifying.search_space import search_space
from f1_big_predictor.targets.qualifying.types import (
    INDEPENDENT_WEIGHTS,
    QualifyingFeatureConfig,
    resolve_weights,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_predict_qualifying_target_scores_22_component_rows() -> None:
    full_ranking = score_qualifying_field(driver_features=_component_features())
    prediction = predict_qualifying_target(
        inputs=QualifyingTargetInputs(driver_features=_component_features()),
        config=QualifyingTargetConfig(),
    )

    assert len(full_ranking) == 22
    assert [item["driver_id"] for item in full_ranking[:10]] == [
        item["driver_id"] for item in prediction.entries
    ]
    assert set(full_ranking[0]) >= {
        "driver_id",
        "position",
        "qualifying_score",
        "available_components",
        "effective_weights",
        "component_gaps",
    }
    assert prediction.status == "ok"
    assert len(prediction.entries) == 10
    assert [item["qualifying_score"] for item in prediction.entries] == sorted(
        [item["qualifying_score"] for item in prediction.entries],
        reverse=True,
    )
    assert prediction.entries[0]["driver_id"] == "driver_01"
    assert all(item["lap_time"] is None for item in prediction.entries)
    assert "lap_time_not_predicted_v1" in prediction.evidence_gaps


def test_predict_qualifying_target_entry_schema_is_stable() -> None:
    prediction = predict_qualifying_target(
        inputs=QualifyingTargetInputs(driver_features=_component_features()),
        config=QualifyingTargetConfig(),
    )
    first_entry = prediction.entries[0]

    assert set(first_entry) == {
        "driver_id",
        "position",
        "score",
        "driver_name",
        "constructor_id",
        "constructor_name",
        "lap_time",
        "lap_time_seconds",
        "delta_to_pole",
        "qualifying_score",
    }
    assert first_entry["position"] == 1
    assert first_entry["score"] == first_entry["qualifying_score"]
    assert first_entry["lap_time"] is None
    assert first_entry["lap_time_seconds"] is None
    assert first_entry["delta_to_pole"] is None


def test_predict_qualifying_target_renormalizes_when_one_component_is_missing() -> None:
    features = _component_features()
    for row in features:
        row["circuit_fit_score"] = None

    prediction = predict_qualifying_target(
        inputs=QualifyingTargetInputs(driver_features=features),
        config=QualifyingTargetConfig(),
    )

    assert prediction.status == "ok"
    assert len(prediction.entries) == 10
    assert prediction.entries[0]["qualifying_score"] > prediction.entries[-1]["qualifying_score"]


def test_predict_qualifying_target_reports_evidence_issue_when_all_components_missing() -> None:
    prediction = predict_qualifying_target(
        inputs=QualifyingTargetInputs(
            driver_features=[
                {
                    "driver_id": "driver_01",
                    "form_score": None,
                    "constructor_score": None,
                    "circuit_fit_score": None,
                    "evidence_score": None,
                    "reliability_score": None,
                }
            ]
        ),
        config=QualifyingTargetConfig(),
    )

    assert prediction.status == "evidence_issue"
    assert prediction.entries == []
    assert "missing_qualifying_component_scores" in prediction.evidence_gaps


def test_predict_qualifying_target_fails_loudly_with_fewer_than_top10_scored_rows() -> None:
    prediction = predict_qualifying_target(
        inputs=QualifyingTargetInputs(driver_features=_component_features()[:9]),
        config=QualifyingTargetConfig(),
    )

    assert prediction.status == "evidence_issue"
    assert prediction.entries == []
    assert "insufficient_qualifying_scored_drivers_for_top10" in prediction.evidence_gaps


def test_predict_qualifying_target_rejects_rows_without_driver_id() -> None:
    try:
        predict_qualifying_target(
            inputs=QualifyingTargetInputs(
                driver_features=[
                    {
                        "form_score": 1.0,
                        "constructor_score": 1.0,
                        "circuit_fit_score": 1.0,
                        "evidence_score": 1.0,
                        "reliability_score": 1.0,
                    }
                ]
            ),
            config=QualifyingTargetConfig(),
        )
    except ValueError as exc:
        assert str(exc) == "target feature rows require driver_id"
    else:
        raise AssertionError("missing driver_id should raise ValueError")


def test_predict_qualifying_target_applies_high_downforce_interaction_weights() -> None:
    prediction = predict_qualifying_target(
        inputs=QualifyingTargetInputs(
            driver_features=[
                {
                    "driver_id": "circuit_fit_driver",
                    "form_score": 0.0,
                    "constructor_score": None,
                    "circuit_fit_score": 1.0,
                    "evidence_score": None,
                    "reliability_score": None,
                    "track_profile_method": "interaction",
                    "track_profile_speed_type": "high_downforce",
                },
                {
                    "driver_id": "form_driver",
                    "form_score": 0.84,
                    "constructor_score": None,
                    "circuit_fit_score": 0.0,
                    "evidence_score": None,
                    "reliability_score": None,
                    "track_profile_method": "interaction",
                    "track_profile_speed_type": "high_downforce",
                },
                *[
                    {
                        "driver_id": f"padding_{index}",
                        "form_score": 0.0,
                        "constructor_score": 0.0,
                        "circuit_fit_score": 0.0,
                        "evidence_score": 0.0,
                        "reliability_score": 0.0,
                        "track_profile_method": "interaction",
                        "track_profile_speed_type": "high_downforce",
                    }
                    for index in range(8)
                ],
            ]
        ),
        config=QualifyingTargetConfig(),
    )

    assert [item["driver_id"] for item in prediction.entries[:2]] == ["circuit_fit_driver", "form_driver"]
    assert prediction.entries[0]["qualifying_score"] == 0.480769
    assert prediction.entries[1]["qualifying_score"] == 0.436154


def test_predict_qualifying_target_uses_track_profile_from_feature_builder_rows() -> None:
    payload = build_qualifying_features(project_root=PROJECT_ROOT, target_round=4)
    prediction = predict_qualifying_target(
        inputs=QualifyingTargetInputs(
            driver_features=[
                {
                    **payload["rows"][0],
                    "driver_id": "reliability_driver",
                    "form_score": 0.0,
                    "constructor_score": None,
                    "circuit_fit_score": None,
                    "evidence_score": None,
                    "reliability_score": 1.0,
                },
                {
                    **payload["rows"][1],
                    "driver_id": "form_driver",
                    "form_score": 0.35,
                    "constructor_score": None,
                    "circuit_fit_score": None,
                    "evidence_score": None,
                    "reliability_score": 0.0,
                },
                    *[
                        {
                            "driver_id": f"padding_{index}",
                            "form_score": 0.0,
                            "constructor_score": 0.0,
                            "circuit_fit_score": 0.0,
                            "evidence_score": 0.0,
                            "reliability_score": 0.0,
                            "track_profile_method": "interaction",
                            "track_profile": payload["track_profile"],
                        }
                        for index in range(8)
                    ],
            ]
        ),
        config=QualifyingTargetConfig(),
    )

    assert payload["rows"][0]["track_profile"]["track_type"] == "street"
    assert [item["driver_id"] for item in prediction.entries[:2]] == ["reliability_driver", "form_driver"]


def test_independent_effective_weights_match_registered_six_component_profile() -> None:
    rows = [
        {
            "driver_id": f"driver_{index:02d}",
            "form_score": 0.8,
            "constructor_score": 0.7,
            "circuit_fit_score": 0.6,
            "evidence_score": 0.5,
            "reliability_score": 0.4,
            "track_profile_score": 0.3,
            "track_profile_method": "independent",
        }
        for index in range(10)
    ]

    full_ranking = score_qualifying_field(driver_features=rows)
    effective = full_ranking[0]["effective_weights"]

    assert effective == INDEPENDENT_WEIGHTS
    assert sum(effective.values()) == 1.0
    assert search_space()["weight_profiles"]["independent"] == INDEPENDENT_WEIGHTS


def test_independent_missing_evidence_renormalizes_without_reusing_reliability_weight() -> None:
    rows = [
        {
            "driver_id": f"driver_{index:02d}",
            "form_score": 0.8,
            "constructor_score": 0.7,
            "circuit_fit_score": 0.6,
            "evidence_score": None,
            "reliability_score": 0.4,
            "track_profile_score": 0.3,
            "track_profile_method": "independent",
        }
        for index in range(10)
    ]

    effective = score_qualifying_field(driver_features=rows)[0]["effective_weights"]
    denominator = 0.27 + 0.225 + 0.18 + 0.09 + 0.10

    assert "evidence" not in effective
    assert effective["track_profile"] == pytest.approx(0.10 / denominator)
    assert effective["reliability"] == pytest.approx(0.09 / denominator)
    assert sum(effective.values()) == pytest.approx(1.0)


def test_qualifying_weight_validation_rejects_negative_zero_and_unknown_components() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        QualifyingFeatureConfig(weights={"form": -0.1})
    with pytest.raises(ValueError, match="all zero"):
        QualifyingFeatureConfig(weights={
            "form": 0.0,
            "constructor": 0.0,
            "circuit_fit": 0.0,
            "evidence": 0.0,
            "reliability": 0.0,
        })
    with pytest.raises(ValueError, match="unknown qualifying weight components"):
        QualifyingFeatureConfig(weights={"unknown": 1.0})
    with pytest.raises(ValueError, match="between zero and one"):
        QualifyingFeatureConfig(
            track_profile_method="independent",
            weights={"track_profile": 1.1},
        )


def test_custom_weight_profiles_are_normalized_without_changing_requested_track_share() -> None:
    interaction = resolve_weights("interaction", {"form": 0.60})
    independent = resolve_weights("independent", {"form": 0.60, "track_profile": 0.20})

    assert sum(interaction.values()) == pytest.approx(1.0)
    assert interaction["form"] == pytest.approx(0.60 / 1.30)
    assert sum(independent.values()) == pytest.approx(1.0)
    assert independent["track_profile"] == pytest.approx(0.20)
    assert sum(value for key, value in independent.items() if key != "track_profile") == pytest.approx(0.80)
    assert independent["form"] == pytest.approx(0.60 * 0.80 / 1.30)


@pytest.mark.parametrize(
    ("profile", "adjustments"),
    [
        ("high_downforce", {"form": 0.90, "circuit_fit": 1.25}),
        ("street", {"form": 1.10, "reliability": 1.20}),
        ("low_downforce", {"form": 1.15, "circuit_fit": 0.85}),
    ],
)
def test_interaction_profiles_keep_registered_component_multipliers(profile: str, adjustments: dict[str, float]) -> None:
    rows = [
        {
            "driver_id": f"driver_{index:02d}",
            "form_score": 0.8,
            "constructor_score": 0.7,
            "circuit_fit_score": 0.6,
            "evidence_score": 0.5,
            "reliability_score": 0.4,
            "track_profile_method": "interaction",
            "track_profile_speed_type": profile,
        }
        for index in range(10)
    ]
    effective = score_qualifying_field(driver_features=rows)[0]["effective_weights"]
    base = {"form": 0.30, "constructor": 0.25, "circuit_fit": 0.20, "evidence": 0.15, "reliability": 0.10}
    adjusted = {key: value * adjustments.get(key, 1.0) for key, value in base.items()}
    total = sum(adjusted.values())

    for key, value in adjusted.items():
        assert effective[key] == pytest.approx(value / total)


def test_full_field_diagnostic_preserves_component_gaps() -> None:
    rows = [
        {
            "driver_id": f"driver_{index:02d}",
            "form_score": None,
            "constructor_score": None,
            "circuit_fit_score": None,
            "evidence_score": None,
            "reliability_score": 0.5,
        }
        for index in range(10)
    ]

    diagnostic = score_qualifying_field(driver_features=rows)[0]

    assert diagnostic["available_components"] == ["reliability"]
    assert diagnostic["component_gaps"] == [
        "missing_form_score",
        "missing_constructor_score",
        "no_same_circuit_history",
        "missing_qualifying_evidence_signal",
    ]


def _component_features() -> list[dict[str, object]]:
    return [
        {
            "driver_id": f"driver_{index:02d}",
            "driver_name": f"Driver {index}",
            "constructor_id": f"team_{index % 10:02d}",
            "constructor_name": f"Team {index % 10}",
            "form_score": 1.0 - index / 100,
            "constructor_score": 0.75,
            "circuit_fit_score": 0.70,
            "evidence_score": 0.65,
            "reliability_score": 0.60,
            "track_profile_method": "interaction",
            "track_profile_speed_type": "street",
        }
        for index in range(1, 23)
    ]
