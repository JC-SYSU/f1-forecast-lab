"""Walk-forward harness for Bradley-Terry and Plackett-Luce."""

from __future__ import annotations

from math import log2
from pathlib import Path
from statistics import mean
from typing import Any

from .._shared import driver_ids, rank_mae
from .evaluate import evaluate_qualifying_target
from .features import DEFAULT_SEASON
from .official_labels import load_officialized_actuals
from .probability_models import (
    MODEL_ID_BT,
    MODEL_ID_PL,
    FEATURE_SET_ID_BT,
    FEATURE_SET_ID_PL,
    predict_bradley_terry,
    predict_plackett_luce,
)

FIRST_WALK_FORWARD_ROUND = 2
LAST_WALK_FORWARD_ROUND = 9


def run_walk_forward_bradley_terry(
    project_root: Path, delta: float = 0.0
) -> dict[str, Any]:
    return _run(
        project_root,
        predict_bradley_terry,
        MODEL_ID_BT,
        FEATURE_SET_ID_BT,
        model_config={"delta": delta},
        predictor_kwargs={"delta": delta},
    )


def run_walk_forward_plackett_luce(project_root: Path) -> dict[str, Any]:
    return _run(
        project_root,
        predict_plackett_luce,
        MODEL_ID_PL,
        FEATURE_SET_ID_PL,
        model_config={},
        predictor_kwargs={},
    )


def _run(
    project_root,
    predictor,
    model_id,
    feature_set_id,
    model_config,
    predictor_kwargs=None,
):
    predictor_kwargs = predictor_kwargs or {}
    actuals = load_officialized_actuals(project_root)
    completed_rounds = sorted(
        actuals.get("completed_rounds", []), key=lambda r: int(r["round"])
    )
    season = int(actuals.get("season") or DEFAULT_SEASON)
    by_round = {int(r["round"]): r for r in completed_rounds}

    per_round: list[dict[str, Any]] = []
    run_gaps: list[str] = []

    for target_round in range(FIRST_WALK_FORWARD_ROUND, LAST_WALK_FORWARD_ROUND + 1):
        payload = by_round.get(target_round)
        if payload is None:
            run_gaps.append(f"round_{target_round:02d}_missing_actuals")
            continue
        if payload.get("qualifying_results", {}).get("status") != "ok":
            run_gaps.append(f"round_{target_round:02d}_not_ok")
            continue

        prediction, full_ranking = predictor(
            target_round, completed_rounds, **predictor_kwargs
        )
        actual_ids = _actual_ids(payload)
        if len(actual_ids) < 10:
            run_gaps.append(f"round_{target_round:02d}_insufficient_actual")
            continue

        top10 = driver_ids(prediction["entries"])
        full_ids = driver_ids(full_ranking)
        if prediction["status"] != "ok" or len(top10) != 10:
            run_gaps.append(f"round_{target_round:02d}_prediction_issue")
            continue

        ev = evaluate_qualifying_target(
            predicted_driver_ids=top10, actual_driver_ids=actual_ids, lap_time_mae=None
        )
        per_round.append(
            {
                "round": target_round,
                "race_name": payload.get("race_name"),
                "top10_predicted_driver_ids": top10,
                "full_field_predicted_driver_ids": full_ids,
                "actual_driver_ids": actual_ids,
                "metrics": {
                    "top10_position_accuracy": ev.top10_position_accuracy,
                    "rank_mae": round(ev.rank_mae, 6),
                    "ndcg_at_10": round(_ndcg(top10, actual_ids), 6),
                    "full_field_rank_mae": round(rank_mae(full_ids, actual_ids), 6),
                },
                "prediction_status": prediction["status"],
                "prediction_evidence_gaps": prediction["evidence_gaps"],
            }
        )

    return {
        "model_id": model_id,
        "feature_set_id": feature_set_id,
        "season": season,
        "model_config": model_config,
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


def _actual_ids(payload):
    recs = payload.get("qualifying_results", {}).get("records", []) or []
    return [
        str(r["driver_id"])
        for r in sorted(
            [r for r in recs if r.get("driver_id") and r.get("position") is not None],
            key=lambda r: (int(r["position"]), str(r["driver_id"])),
        )
    ]


def _ndcg(predicted, actual):
    ar = {d: i + 1 for i, d in enumerate(actual)}
    ideal = _dcg([float(11 - i) for i in range(1, min(11, len(actual) + 1))])
    return (
        _dcg(
            [float(11 - ar[d]) if ar.get(d, 99) <= 10 else 0.0 for d in predicted[:10]]
        )
        / ideal
        if ideal > 0
        else 0.0
    )


def _dcg(r):
    return sum(((2**v) - 1) / log2(i + 2) for i, v in enumerate(r))


def _summary(per_round):
    if not per_round:
        return {
            "round_count": 0,
            "top10_position_accuracy_avg": None,
            "rank_mae_avg": None,
            "ndcg_at_10_avg": None,
            "full_field_rank_mae_avg": None,
        }
    m = [r["metrics"] for r in per_round]
    return {
        "round_count": len(per_round),
        "top10_position_accuracy_avg": round(
            mean(float(x["top10_position_accuracy"]) for x in m), 6
        ),
        "rank_mae_avg": round(mean(float(x["rank_mae"]) for x in m), 6),
        "ndcg_at_10_avg": round(mean(float(x["ndcg_at_10"]) for x in m), 6),
        "full_field_rank_mae_avg": round(
            mean(float(x["full_field_rank_mae"]) for x in m), 6
        ),
    }
