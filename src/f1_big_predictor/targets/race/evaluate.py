from __future__ import annotations

from .._shared import rank_mae, top10_position_accuracy
from .types import EVALUATION_GATE, TARGET_ID, RaceTargetEvaluation


def evaluate_race_target(
    *,
    predicted_driver_ids: list[str],
    actual_driver_ids: list[str],
) -> RaceTargetEvaluation:
    return RaceTargetEvaluation(
        target_id=TARGET_ID,
        top10_position_accuracy=top10_position_accuracy(predicted_driver_ids, actual_driver_ids),
        rank_mae=rank_mae(predicted_driver_ids, actual_driver_ids),
        evaluation_gate=EVALUATION_GATE,
    )
