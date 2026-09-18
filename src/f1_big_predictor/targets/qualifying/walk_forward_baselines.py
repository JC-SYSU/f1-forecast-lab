"""Walk-forward harness for the four simple deterministic baseline models.

Mirrors the structure of walk_forward.py so baseline results can be compared
directly with the v1 explainable-score results.  All four baselines are run
over the same R02–R09 evaluation window with the same metrics.
"""

from __future__ import annotations

from math import log2
from pathlib import Path
from statistics import mean
from typing import Any, Callable

from .._shared import driver_ids, rank_mae
from .baselines import (
    predict_constructor_only,
    predict_form_w3,
    predict_latest_prior,
    predict_season_to_date,
)
from .evaluate import evaluate_qualifying_target
from .features import DEFAULT_SEASON
from .official_labels import load_officialized_actuals


FIRST_WALK_FORWARD_ROUND = 2
LAST_WALK_FORWARD_ROUND = 9

# Each entry: (short_name, predictor_callable)
# The predictor signature is (target_round, completed_rounds) → (prediction, full_ranking)
_BASELINES: list[tuple[str, Callable]] = [
    ("latest_prior", predict_latest_prior),
    ("season_to_date", predict_season_to_date),
    ("constructor_only", predict_constructor_only),
    ("form_w3", predict_form_w3),
]


def run_walk_forward_baselines(project_root: Path) -> dict[str, Any]:
    """Run all four baselines over R02–R09 and return combined results."""
    actuals = load_officialized_actuals(project_root)
    completed_rounds = sorted(
        actuals.get("completed_rounds", []),
        key=lambda item: int(item["round"]),
    )
    season = int(actuals.get("season") or DEFAULT_SEASON)

    baseline_results: dict[str, Any] = {}
    for name, predictor in _BASELINES:
        baseline_results[name] = _run_single_baseline(
            name=name,
            predictor=predictor,
            completed_rounds=completed_rounds,
            season=season,
        )

    return {
        "season": season,
        "evaluation_window": {
            "rounds": list(
                range(FIRST_WALK_FORWARD_ROUND, LAST_WALK_FORWARD_ROUND + 1)
            ),
            "round_count": LAST_WALK_FORWARD_ROUND - FIRST_WALK_FORWARD_ROUND + 1,
            "method": "event_grouped_expanding_walk_forward",
        },
        "baselines": baseline_results,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _run_single_baseline(
    *,
    name: str,
    predictor: Callable,
    completed_rounds: list[dict[str, Any]],
    season: int,
) -> dict[str, Any]:
    completed_by_round = {int(r["round"]): r for r in completed_rounds}
    per_round: list[dict[str, Any]] = []
    run_gaps: list[str] = []

    for target_round in range(FIRST_WALK_FORWARD_ROUND, LAST_WALK_FORWARD_ROUND + 1):
        round_payload = completed_by_round.get(target_round)
        if round_payload is None:
            run_gaps.append(f"round_{target_round:02d}_missing_actuals")
            continue
        if round_payload.get("qualifying_results", {}).get("status") != "ok":
            run_gaps.append(f"round_{target_round:02d}_qualifying_results_not_ok")
            continue

        prediction, full_ranking = predictor(target_round, completed_rounds)

        actual_driver_ids = _actual_qualifying_driver_ids(round_payload)
        if len(actual_driver_ids) < 10:
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
            actual_driver_ids=actual_driver_ids,
            lap_time_mae=None,
        )
        metrics = {
            "top10_position_accuracy": evaluation.top10_position_accuracy,
            "rank_mae": round(evaluation.rank_mae, 6),
            "ndcg_at_10": round(_ndcg_at_10(top10_ids, actual_driver_ids), 6),
            "full_field_rank_mae": round(
                rank_mae(full_field_ids, actual_driver_ids), 6
            ),
        }
        per_round.append(
            {
                "round": target_round,
                "race_name": round_payload.get("race_name"),
                "top10_predicted_driver_ids": top10_ids,
                "full_field_predicted_driver_ids": full_field_ids,
                "actual_driver_ids": actual_driver_ids,
                "metrics": metrics,
                "prediction_status": prediction["status"],
                "prediction_evidence_gaps": prediction["evidence_gaps"],
                "training_rounds": [
                    int(r["round"])
                    for r in completed_rounds
                    if int(r["round"]) < target_round
                ],
            }
        )

    return {
        "model_id": _baseline_model_id(name),
        "feature_set_id": _baseline_feature_set_id(name),
        "season": season,
        "per_round": per_round,
        "summary": _summary(per_round),
        "evidence_gaps": run_gaps,
    }


def _baseline_model_id(name: str) -> str:
    return f"qualifying.model.baseline.{name}"


def _baseline_feature_set_id(name: str) -> str:
    return f"qualifying.features.baseline.{name}"


def _actual_qualifying_driver_ids(round_payload: dict[str, Any]) -> list[str]:
    records = round_payload.get("qualifying_results", {}).get("records", []) or []
    rows = [r for r in records if r.get("driver_id") and r.get("position") is not None]
    return [
        str(r["driver_id"])
        for r in sorted(rows, key=lambda r: (int(r["position"]), str(r["driver_id"])))
    ]


def _ndcg_at_10(predicted: list[str], actual: list[str]) -> float:
    actual_rank = {did: idx + 1 for idx, did in enumerate(actual)}
    ideal_relevances = [_relevance(idx + 1) for idx in range(min(10, len(actual)))]
    ideal_dcg = _dcg(ideal_relevances)
    if ideal_dcg <= 0:
        return 0.0
    relevances = [_relevance(actual_rank.get(did)) for did in predicted[:10]]
    return _dcg(relevances) / ideal_dcg


def _relevance(actual_position: int | None) -> float:
    if actual_position is None or actual_position > 10:
        return 0.0
    return float(11 - actual_position)


def _dcg(relevances: list[float]) -> float:
    return sum(((2.0**rel) - 1.0) / log2(idx + 2) for idx, rel in enumerate(relevances))


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
