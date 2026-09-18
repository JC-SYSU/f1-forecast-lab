"""Walk-forward harness for the Elastic Net multi-factor model."""

from __future__ import annotations

from math import log2
from pathlib import Path
from statistics import mean
from typing import Any

from .._shared import driver_ids, rank_mae
from .elastic_net_model import (
    DEFAULT_ALPHA,
    DEFAULT_L1_RATIO,
    FEATURE_SET_ID,
    MODEL_ID,
    predict_elastic_net,
)
from .evaluate import evaluate_qualifying_target
from .features import DEFAULT_SEASON
from .official_labels import load_officialized_actuals
from .ridge_model import STAT_FEATURES

FIRST_WALK_FORWARD_ROUND = 2
LAST_WALK_FORWARD_ROUND = 9


def run_walk_forward_elastic_net(
    project_root: Path,
    alpha: float = DEFAULT_ALPHA,
    l1_ratio: float = DEFAULT_L1_RATIO,
) -> dict[str, Any]:
    actuals = load_officialized_actuals(project_root)
    completed_rounds = sorted(
        actuals.get("completed_rounds", []), key=lambda r: int(r["round"])
    )
    season = int(actuals.get("season") or DEFAULT_SEASON)
    completed_by_round = {int(r["round"]): r for r in completed_rounds}

    per_round: list[dict[str, Any]] = []
    run_gaps: list[str] = []

    for target_round in range(FIRST_WALK_FORWARD_ROUND, LAST_WALK_FORWARD_ROUND + 1):
        rnd_payload = completed_by_round.get(target_round)
        if rnd_payload is None:
            run_gaps.append(f"round_{target_round:02d}_missing_actuals")
            continue
        if rnd_payload.get("qualifying_results", {}).get("status") != "ok":
            run_gaps.append(f"round_{target_round:02d}_qualifying_results_not_ok")
            continue

        prediction, full_ranking = predict_elastic_net(
            target_round, completed_rounds, alpha=alpha, l1_ratio=l1_ratio
        )
        actual_ids = _actual_qualifying_driver_ids(rnd_payload)
        if len(actual_ids) < 10:
            run_gaps.append(
                f"round_{target_round:02d}_insufficient_actual_qualifying_results"
            )
            continue

        top10_ids = driver_ids(prediction["entries"])
        full_field_ids = driver_ids(full_ranking)
        if prediction["status"] != "ok" or len(top10_ids) != 10:
            run_gaps.append(f"round_{target_round:02d}_prediction_evidence_issue")
            continue

        evaluation = evaluate_qualifying_target(
            predicted_driver_ids=top10_ids,
            actual_driver_ids=actual_ids,
            lap_time_mae=None,
        )
        n_train = sum(
            len(
                [
                    r
                    for r in completed_by_round[rn]
                    .get("qualifying_results", {})
                    .get("records", [])
                    if r.get("driver_id") and r.get("position") is not None
                ]
            )
            for rn in range(1, target_round)
            if rn in completed_by_round
        )
        per_round.append(
            {
                "round": target_round,
                "race_name": rnd_payload.get("race_name"),
                "top10_predicted_driver_ids": top10_ids,
                "full_field_predicted_driver_ids": full_field_ids,
                "actual_driver_ids": actual_ids,
                "metrics": {
                    "top10_position_accuracy": evaluation.top10_position_accuracy,
                    "rank_mae": round(evaluation.rank_mae, 6),
                    "ndcg_at_10": round(_ndcg_at_10(top10_ids, actual_ids), 6),
                    "full_field_rank_mae": round(
                        rank_mae(full_field_ids, actual_ids), 6
                    ),
                },
                "prediction_status": prediction["status"],
                "prediction_evidence_gaps": prediction["evidence_gaps"],
                "n_training_samples": n_train,
                "training_rounds": [
                    rn for rn in range(1, target_round) if rn in completed_by_round
                ],
            }
        )

    return {
        "model_id": MODEL_ID,
        "feature_set_id": FEATURE_SET_ID,
        "season": season,
        "model_config": {
            "alpha": alpha,
            "l1_ratio": l1_ratio,
            "features": list(STAT_FEATURES),
            "target_transform": "(field_size + 1 - pos) / field_size",
            "missing_imputation": "training_column_mean",
            "standardisation": "zero_mean_unit_std_from_training",
        },
        "evaluation_window": {
            "rounds": list(
                range(FIRST_WALK_FORWARD_ROUND, LAST_WALK_FORWARD_ROUND + 1)
            ),
            "round_count": LAST_WALK_FORWARD_ROUND - FIRST_WALK_FORWARD_ROUND + 1,
            "method": "event_grouped_expanding_walk_forward",
        },
        "per_round": per_round,
        "summary": _summary(per_round),
        "evidence_gaps": run_gaps,
    }


def _actual_qualifying_driver_ids(round_payload: dict[str, Any]) -> list[str]:
    records = round_payload.get("qualifying_results", {}).get("records", []) or []
    rows = [r for r in records if r.get("driver_id") and r.get("position") is not None]
    return [
        str(r["driver_id"])
        for r in sorted(rows, key=lambda r: (int(r["position"]), str(r["driver_id"])))
    ]


def _ndcg_at_10(predicted: list[str], actual: list[str]) -> float:
    actual_rank = {did: idx + 1 for idx, did in enumerate(actual)}
    ideal_dcg = _dcg([_relevance(i + 1) for i in range(min(10, len(actual)))])
    return (
        _dcg([_relevance(actual_rank.get(did)) for did in predicted[:10]]) / ideal_dcg
        if ideal_dcg > 0
        else 0.0
    )


def _relevance(pos: int | None) -> float:
    return float(11 - pos) if pos is not None and pos <= 10 else 0.0


def _dcg(relevances: list[float]) -> float:
    return sum(((2.0**r) - 1.0) / log2(i + 2) for i, r in enumerate(relevances))


def _summary(per_round: list[dict[str, Any]]) -> dict[str, Any]:
    if not per_round:
        return {
            "round_count": 0,
            "top10_position_accuracy_avg": None,
            "rank_mae_avg": None,
            "ndcg_at_10_avg": None,
            "full_field_rank_mae_avg": None,
        }
    metrics = [r["metrics"] for r in per_round]
    return {
        "round_count": len(per_round),
        "top10_position_accuracy_avg": round(
            mean(float(m["top10_position_accuracy"]) for m in metrics), 6
        ),
        "rank_mae_avg": round(mean(float(m["rank_mae"]) for m in metrics), 6),
        "ndcg_at_10_avg": round(mean(float(m["ndcg_at_10"]) for m in metrics), 6),
        "full_field_rank_mae_avg": round(
            mean(float(m["full_field_rank_mae"]) for m in metrics), 6
        ),
    }
