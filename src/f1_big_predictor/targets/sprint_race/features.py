from __future__ import annotations

from .types import FEATURE_SET_ID


def required_features() -> tuple[str, ...]:
    return ("driver_id", "sprint_race_score")
