from __future__ import annotations

from .types import SprintQualifyingTargetPrediction


def render_report(prediction: SprintQualifyingTargetPrediction) -> str:
    return f"sprint_qualifying {prediction.status}: {len(prediction.entries)} entries"
