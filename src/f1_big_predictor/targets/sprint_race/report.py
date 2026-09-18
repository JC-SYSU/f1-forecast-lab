from __future__ import annotations

from .types import SprintRaceTargetPrediction


def render_report(prediction: SprintRaceTargetPrediction) -> str:
    return f"sprint_race {prediction.status}: {len(prediction.entries)} entries"
