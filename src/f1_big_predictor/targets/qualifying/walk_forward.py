from __future__ import annotations

from math import log2
from pathlib import Path
from statistics import mean
from typing import Any

from .._shared import driver_ids, rank_mae
from .evaluate import evaluate_qualifying_target
from .features import DEFAULT_SEASON, build_qualifying_features
from .model import predict_qualifying_target, score_qualifying_field
from .official_labels import load_officialized_actuals
from .types import (
    COMPONENT_NAMES,
    EVIDENCE_POLICY,
    TARGET_ID,
    TRACK_PROFILE_NAME,
    QualifyingFeatureConfig,
    QualifyingTargetConfig,
    QualifyingTargetInputs,
    resolve_weights,
)


FIRST_WALK_FORWARD_ROUND = 2
LAST_WALK_FORWARD_ROUND = 9


def run_walk_forward(
    project_root: Path, config: QualifyingFeatureConfig | None = None
) -> dict[str, Any]:
    feature_config = config or QualifyingFeatureConfig()
    target_config = QualifyingTargetConfig()
    actuals = load_officialized_actuals(project_root)
    completed_rounds = sorted(
        actuals.get("completed_rounds", []),
        key=lambda item: int(item["round"]),
    )
    completed_by_round = {int(item["round"]): item for item in completed_rounds}
    per_round: list[dict[str, Any]] = []
    run_gaps: list[str] = []
    aggregate_exclusions: dict[str, int] = {}

    for target_round in range(FIRST_WALK_FORWARD_ROUND, LAST_WALK_FORWARD_ROUND + 1):
        round_payload = completed_by_round.get(target_round)
        if round_payload is None:
            run_gaps.append(f"round_{target_round:02d}_missing_actuals")
            continue
        if round_payload.get("qualifying_results", {}).get("status") != "ok":
            run_gaps.append(f"round_{target_round:02d}_qualifying_results_not_ok")
            continue

        feature_payload = build_qualifying_features(
            project_root=project_root,
            target_round=target_round,
            season=int(actuals.get("season") or DEFAULT_SEASON),
            config=feature_config,
        )
        _merge_counts(
            aggregate_exclusions, feature_payload["evidence_exclusion_summary"]
        )

        # The feature builder owns the as-of evidence policy. Do not clear or rewrite
        # component values here; the walk-forward harness only consumes its output.
        driver_features = feature_payload["rows"]
        full_ranking = score_qualifying_field(driver_features=driver_features)
        prediction = predict_qualifying_target(
            inputs=QualifyingTargetInputs(
                driver_features=driver_features,
                evidence_gaps=list(feature_payload["evidence_gaps"]),
            ),
            config=target_config,
        )

        # Actual target labels are loaded only after the prediction path has completed.
        actual_driver_ids = _actual_qualifying_driver_ids(round_payload)
        if len(actual_driver_ids) < 10:
            run_gaps.append(
                f"round_{target_round:02d}_insufficient_actual_qualifying_results"
            )
            continue

        top10_driver_ids = driver_ids(prediction.entries)
        full_field_driver_ids = driver_ids(full_ranking)
        if prediction.status != "ok" or len(top10_driver_ids) != 10:
            run_gaps.append(f"round_{target_round:02d}_prediction_evidence_issue")
            continue
        if len(full_field_driver_ids) < len(top10_driver_ids):
            run_gaps.append(f"round_{target_round:02d}_incomplete_full_field_ranking")
            continue

        evaluation = evaluate_qualifying_target(
            predicted_driver_ids=top10_driver_ids,
            actual_driver_ids=actual_driver_ids,
            lap_time_mae=None,
        )
        metrics = {
            "top10_position_accuracy": evaluation.top10_position_accuracy,
            "rank_mae": round(evaluation.rank_mae, 6),
            "ndcg_at_10": round(_ndcg_at_10(top10_driver_ids, actual_driver_ids), 6),
            "full_field_rank_mae": round(
                rank_mae(full_field_driver_ids, actual_driver_ids), 6
            ),
        }
        per_round.append(
            {
                "round": target_round,
                "race_name": round_payload.get("race_name"),
                "top10_predicted_driver_ids": top10_driver_ids,
                "full_field_predicted_driver_ids": full_field_driver_ids,
                "actual_driver_ids": actual_driver_ids,
                "metrics": metrics,
                "prediction_status": prediction.status,
                "feature_evidence_gaps": feature_payload["evidence_gaps"],
                "prediction_evidence_gaps": prediction.evidence_gaps,
                "component_availability_summary": _component_availability_summary(
                    full_ranking
                ),
                "evidence_exclusion_summary": feature_payload[
                    "evidence_exclusion_summary"
                ],
                "effective_weight_summary": _effective_weight_summary(full_ranking),
                "full_field_diagnostic": _full_field_diagnostic(full_ranking),
                "training_rounds": [
                    int(item["round"])
                    for item in completed_rounds
                    if int(item["round"]) < target_round
                ],
            }
        )

    return {
        "target_id": TARGET_ID,
        "model_id": target_config.model_id,
        "feature_set_id": target_config.feature_set_id,
        "season": int(actuals.get("season") or DEFAULT_SEASON),
        "config": {
            "form_window": feature_config.form_window,
            "evidence_method": feature_config.evidence_method,
            "track_profile_method": feature_config.track_profile_method,
            "weights": resolve_weights(
                feature_config.track_profile_method, feature_config.weights
            ),
        },
        "evidence_policy": EVIDENCE_POLICY,
        "evidence_summary": {
            **aggregate_exclusions,
            "round_count": len(per_round),
        },
        "evaluation_window": {
            "start_round": per_round[0]["round"] if per_round else None,
            "end_round": per_round[-1]["round"] if per_round else None,
            "round_count": len(per_round),
            "method": "event_grouped_expanding_walk_forward",
        },
        "per_round": per_round,
        "summary": _summary(per_round),
        "evidence_gaps": run_gaps,
    }


def _actual_qualifying_driver_ids(round_payload: dict[str, Any]) -> list[str]:
    records = round_payload.get("qualifying_results", {}).get("records", []) or []
    rows = [
        item
        for item in records
        if item.get("driver_id") and item.get("position") is not None
    ]
    return [
        str(item["driver_id"])
        for item in sorted(
            rows,
            key=lambda item: (int(item["position"]), str(item["driver_id"])),
        )
    ]


def _ndcg_at_10(predicted: list[str], actual: list[str]) -> float:
    actual_rank = {driver_id: index + 1 for index, driver_id in enumerate(actual)}
    ideal_relevances = [_relevance(index + 1) for index in range(min(10, len(actual)))]
    ideal_dcg = _dcg(ideal_relevances)
    if ideal_dcg <= 0:
        return 0.0
    relevances = [
        _relevance(actual_rank.get(driver_id)) for driver_id in predicted[:10]
    ]
    return _dcg(relevances) / ideal_dcg


def _relevance(actual_position: int | None) -> float:
    if actual_position is None or actual_position > 10:
        return 0.0
    return float(11 - actual_position)


def _dcg(relevances: list[float]) -> float:
    return sum(
        ((2.0**relevance) - 1.0) / log2(index + 2)
        for index, relevance in enumerate(relevances)
    )


def _summary(per_round: list[dict[str, Any]]) -> dict[str, float | int | None]:
    if not per_round:
        return {
            "round_count": 0,
            "top10_position_accuracy_avg": None,
            "rank_mae_avg": None,
            "ndcg_at_10_avg": None,
            "full_field_rank_mae_avg": None,
        }
    metrics = [item["metrics"] for item in per_round]
    return {
        "round_count": len(per_round),
        "top10_position_accuracy_avg": round(
            mean(float(item["top10_position_accuracy"]) for item in metrics),
            6,
        ),
        "rank_mae_avg": round(mean(float(item["rank_mae"]) for item in metrics), 6),
        "ndcg_at_10_avg": round(mean(float(item["ndcg_at_10"]) for item in metrics), 6),
        "full_field_rank_mae_avg": round(
            mean(float(item["full_field_rank_mae"]) for item in metrics), 6
        ),
    }


def _full_field_diagnostic(full_ranking: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "driver_id": row["driver_id"],
            "position": row["position"],
            "qualifying_score": row["qualifying_score"],
            "available_components": list(row.get("available_components", [])),
            "component_gaps": list(row.get("component_gaps", [])),
            "effective_weights": dict(row.get("effective_weights", {})),
        }
        for row in full_ranking
    ]


def _component_availability_summary(
    full_ranking: list[dict[str, Any]],
) -> dict[str, int]:
    components = [*COMPONENT_NAMES, TRACK_PROFILE_NAME]
    return {
        component: sum(
            component in row.get("available_components", []) for row in full_ranking
        )
        for component in components
    }


def _effective_weight_summary(full_ranking: list[dict[str, Any]]) -> dict[str, float]:
    keys = sorted(
        {key for row in full_ranking for key in row.get("effective_weights", {})}
    )
    return {
        key: round(
            mean(
                float(row["effective_weights"][key])
                for row in full_ranking
                if key in row.get("effective_weights", {})
            ),
            12,
        )
        for key in keys
    }


def _merge_counts(target: dict[str, int], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if key in {"eligible_evidence_ids"}:
            continue
        if isinstance(value, int):
            target[key] = target.get(key, 0) + value
