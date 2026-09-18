from __future__ import annotations

from .types import FEATURE_SET_ID


def required_features() -> tuple[str, ...]:
    return ("driver_id", "sprint_qualifying_score", "predicted_lap_time", "is_sprint_weekend")
