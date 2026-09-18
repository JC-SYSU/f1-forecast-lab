from __future__ import annotations

from .types import SEARCH_SPACE_ID, TARGET_ID


def search_space() -> dict[str, object]:
    return {
        "target_id": TARGET_ID,
        "search_space_id": SEARCH_SPACE_ID,
        "parameters": [
            {"name": "sprint_race_score_weight", "type": "float", "default": 1.0},
            {"name": "sprint_qualifying_position_weight", "type": "float", "default": 0.35},
        ],
    }
