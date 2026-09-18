from __future__ import annotations

from .._shared import rank_mae, top10_position_accuracy
from .types import EVALUATION_GATE, TARGET_ID, SprintQualifyingTargetEvaluation


def evaluate_sprint_qualifying_target(
    *,
    predicted_driver_ids: list[str],
    actual_driver_ids: list[str],
    lap_time_mae: float | None = None,
) -> SprintQualifyingTargetEvaluation:
    return SprintQualifyingTargetEvaluation(
        target_id=TARGET_ID,
        top10_position_accuracy=top10_position_accuracy(predicted_driver_ids, actual_driver_ids),
        rank_mae=rank_mae(predicted_driver_ids, actual_driver_ids),
        lap_time_mae=lap_time_mae,
        evaluation_gate=EVALUATION_GATE,
    )
