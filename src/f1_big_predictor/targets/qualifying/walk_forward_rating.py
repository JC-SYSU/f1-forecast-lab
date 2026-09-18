"""Walk-forward harness for Elo, Massey, and Colley rating models."""

from __future__ import annotations

from math import log2
from pathlib import Path
from statistics import mean
from typing import Any

from .._shared import driver_ids, rank_mae
from .evaluate import evaluate_qualifying_target
from .features import DEFAULT_SEASON
from .official_labels import load_officialized_actuals
from .rating_models import (
    DEFAULT_K,
    MODEL_ID_ELO,
    MODEL_ID_MASSEY,
    MODEL_ID_COLLEY,
    MODEL_ID_KEENER,
    MODEL_ID_GLICKO,
    MODEL_ID_GAUSSIAN_PAIRWISE,
    FEATURE_SET_ID_ELO,
    FEATURE_SET_ID_MASSEY,
    FEATURE_SET_ID_COLLEY,
    FEATURE_SET_ID_KEENER,
    FEATURE_SET_ID_GLICKO,
    FEATURE_SET_ID_GAUSSIAN_PAIRWISE,
    predict_elo,
    predict_massey,
    predict_colley,
    predict_keener,
    predict_glicko,
    predict_gaussian_pairwise,
    INITIAL_GLICKO_RD,
    DEFAULT_GLICKO_C,
    DEFAULT_GP_BETA,
    DEFAULT_GP_TAU,
)

FIRST_WALK_FORWARD_ROUND = 2
LAST_WALK_FORWARD_ROUND = 9


def run_walk_forward_elo(project_root: Path, k: float = DEFAULT_K) -> dict[str, Any]:
    return _run(
        project_root,
        predict_elo,
        MODEL_ID_ELO,
        FEATURE_SET_ID_ELO,
        model_config={"k": k},
        predictor_kwargs={"k": k},
    )


def run_walk_forward_massey(project_root: Path) -> dict[str, Any]:
    return _run(
        project_root,
        predict_massey,
        MODEL_ID_MASSEY,
        FEATURE_SET_ID_MASSEY,
        model_config={},
        predictor_kwargs={},
    )


def run_walk_forward_colley(project_root: Path) -> dict[str, Any]:
    return _run(
        project_root,
        predict_colley,
        MODEL_ID_COLLEY,
        FEATURE_SET_ID_COLLEY,
        model_config={},
        predictor_kwargs={},
    )


def run_walk_forward_keener(
    project_root: Path,
    alpha: float = 0.25,
) -> dict[str, Any]:
    return _run(
        project_root,
        predict_keener,
        MODEL_ID_KEENER,
        FEATURE_SET_ID_KEENER,
        model_config={"alpha": alpha},
        predictor_kwargs={"alpha": alpha},
    )


def run_walk_forward_glicko(
    project_root: Path,
    initial_rd: float = INITIAL_GLICKO_RD,
    c: float = DEFAULT_GLICKO_C,
) -> dict[str, Any]:
    return _run(
        project_root,
        predict_glicko,
        MODEL_ID_GLICKO,
        FEATURE_SET_ID_GLICKO,
        model_config={"initial_rd": initial_rd, "c": c},
        predictor_kwargs={"initial_rd": initial_rd, "c": c},
    )


def run_walk_forward_gaussian_pairwise(
    project_root: Path,
    beta: float = DEFAULT_GP_BETA,
    tau: float = DEFAULT_GP_TAU,
) -> dict[str, Any]:
    return _run(
        project_root,
        predict_gaussian_pairwise,
        MODEL_ID_GAUSSIAN_PAIRWISE,
        FEATURE_SET_ID_GAUSSIAN_PAIRWISE,
        model_config={"beta": beta, "tau": tau},
        predictor_kwargs={"beta": beta, "tau": tau},
    )


def _run(
    project_root: Path,
    predictor,
    model_id: str,
    feature_set_id: str,
    model_config: dict[str, Any],
    predictor_kwargs: dict[str, Any],
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

        prediction, full_ranking = predictor(
            target_round, completed_rounds, **predictor_kwargs
        )
        actual_ids = _actual_qualifying_driver_ids(rnd_payload)
        if len(actual_ids) < 10:
            run_gaps.append(f"round_{target_round:02d}_insufficient_actual")
            continue

        top10_ids = driver_ids(prediction["entries"])
        full_field_ids = driver_ids(full_ranking)
        if prediction["status"] != "ok" or len(top10_ids) != 10:
            run_gaps.append(f"round_{target_round:02d}_prediction_issue")
            continue

        evaluation = evaluate_qualifying_target(
            predicted_driver_ids=top10_ids,
            actual_driver_ids=actual_ids,
            lap_time_mae=None,
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


def _actual_qualifying_driver_ids(round_payload: dict[str, Any]) -> list[str]:
    records = round_payload.get("qualifying_results", {}).get("records", []) or []
    rows = [r for r in records if r.get("driver_id") and r.get("position") is not None]
    return [
        str(r["driver_id"])
        for r in sorted(rows, key=lambda r: (int(r["position"]), str(r["driver_id"])))
    ]


def _ndcg_at_10(predicted: list[str], actual: list[str]) -> float:
    ar = {did: idx + 1 for idx, did in enumerate(actual)}
    ideal = _dcg([_rel(i + 1) for i in range(min(10, len(actual)))])
    return _dcg([_rel(ar.get(d)) for d in predicted[:10]]) / ideal if ideal > 0 else 0.0


def _rel(p: int | None) -> float:
    return float(11 - p) if p and p <= 10 else 0.0


def _dcg(r: list[float]) -> float:
    return sum(((2**v) - 1) / log2(i + 2) for i, v in enumerate(r))


def _summary(per_round: list[dict[str, Any]]) -> dict[str, Any]:
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
