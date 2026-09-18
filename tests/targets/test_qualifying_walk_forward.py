from __future__ import annotations

from pathlib import Path

from f1_big_predictor.targets.qualifying import QualifyingFeatureConfig, run_walk_forward
from f1_big_predictor.targets.qualifying import walk_forward as walk_forward_module


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_run_walk_forward_outputs_strict_evidence_and_two_level_metrics() -> None:
    payload = run_walk_forward(PROJECT_ROOT)
    per_round = payload["per_round"]

    assert set(payload) == {
        "target_id",
        "model_id",
        "feature_set_id",
        "season",
        "config",
        "evidence_policy",
        "evidence_summary",
        "evaluation_window",
        "per_round",
        "summary",
        "evidence_gaps",
    }
    assert payload["target_id"] == "qualifying"
    assert payload["model_id"] == "qualifying.model.v1.explainable_score"
    assert payload["feature_set_id"] == "qualifying.features.v1.explainable_score"
    assert payload["season"] == 2026
    assert payload["evidence_policy"] == "strict_historical_as_of"
    assert payload["evidence_summary"]["eligible_count"] == 0
    assert payload["evidence_summary"]["retrieved_after_cutoff"] > 0
    assert [item["round"] for item in per_round] == list(range(2, 10))
    assert payload["evaluation_window"] == {
        "start_round": 2,
        "end_round": 9,
        "round_count": 8,
        "method": "event_grouped_expanding_walk_forward",
    }
    assert payload["summary"]["round_count"] == 8
    assert set(payload["summary"]) == {
        "round_count",
        "top10_position_accuracy_avg",
        "rank_mae_avg",
        "ndcg_at_10_avg",
        "full_field_rank_mae_avg",
    }
    assert payload["evidence_gaps"] == []

    for item in per_round:
        assert set(item) == {
            "round",
            "race_name",
            "top10_predicted_driver_ids",
            "full_field_predicted_driver_ids",
            "actual_driver_ids",
            "metrics",
            "prediction_status",
            "feature_evidence_gaps",
            "prediction_evidence_gaps",
            "component_availability_summary",
            "evidence_exclusion_summary",
            "effective_weight_summary",
            "full_field_diagnostic",
            "training_rounds",
        }
        metrics = item["metrics"]
        assert 0.0 <= metrics["top10_position_accuracy"] <= 1.0
        assert metrics["rank_mae"] >= 0.0
        assert 0.0 <= metrics["ndcg_at_10"] <= 1.0
        assert metrics["full_field_rank_mae"] >= 0.0
        assert set(metrics) == {
            "top10_position_accuracy",
            "rank_mae",
            "ndcg_at_10",
            "full_field_rank_mae",
        }
        assert len(item["top10_predicted_driver_ids"]) == 10
        assert len(item["full_field_predicted_driver_ids"]) == 22
        assert len(item["full_field_diagnostic"]) == 22
        assert item["evidence_exclusion_summary"]["eligible_count"] == 0
        assert "same_round_evidence_excluded_for_walk_forward" not in item["prediction_evidence_gaps"]
        assert all(training_round < item["round"] for training_round in item["training_rounds"])


def test_run_walk_forward_supports_independent_track_profile_weight_profile() -> None:
    payload = run_walk_forward(
        PROJECT_ROOT,
        QualifyingFeatureConfig(evidence_method="ordinal", track_profile_method="independent"),
    )

    assert payload["config"]["evidence_method"] == "ordinal"
    assert payload["config"]["track_profile_method"] == "independent"
    assert payload["config"]["weights"] == {
        "form": 0.27,
        "constructor": 0.225,
        "circuit_fit": 0.18,
        "evidence": 0.135,
        "reliability": 0.09,
        "track_profile": 0.1,
    }
    assert len(payload["per_round"]) == 8
    assert payload["summary"]["rank_mae_avg"] >= 0.0


def test_walk_forward_can_consume_prospectively_eligible_evidence(monkeypatch) -> None:
    original_builder = walk_forward_module.build_qualifying_features

    def builder(**kwargs):
        payload = original_builder(**kwargs)
        if kwargs["target_round"] == 2:
            for row in payload["rows"]:
                row["evidence_score"] = 0.9
                row["component_gaps"] = [
                    gap for gap in row["component_gaps"] if "evidence" not in gap
                ]
            payload["evidence_gaps"] = []
            payload["evidence_exclusion_summary"] = {
                "eligible_count": 22,
                "eligible_evidence_ids": ["synthetic_prospective"],
            }
        return payload

    monkeypatch.setattr(walk_forward_module, "build_qualifying_features", builder)
    payload = walk_forward_module.run_walk_forward(PROJECT_ROOT)
    round_two = payload["per_round"][0]

    assert "evidence" in round_two["component_availability_summary"]
    assert round_two["evidence_exclusion_summary"]["eligible_count"] == 22
    assert "evidence" in round_two["full_field_diagnostic"][0]["effective_weights"]


def test_walk_forward_does_not_pass_actual_labels_into_prediction(monkeypatch) -> None:
    original_predictor = walk_forward_module.predict_qualifying_target

    def predictor(*, inputs, config):
        assert all("actual_driver_ids" not in row for row in inputs.driver_features)
        return original_predictor(inputs=inputs, config=config)

    monkeypatch.setattr(walk_forward_module, "predict_qualifying_target", predictor)
    payload = walk_forward_module.run_walk_forward(PROJECT_ROOT)

    assert len(payload["per_round"]) == 8
