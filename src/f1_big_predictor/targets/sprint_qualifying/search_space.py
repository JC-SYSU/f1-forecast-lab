from __future__ import annotations

from .types import SEARCH_SPACE_ID, TARGET_ID


def search_space() -> dict[str, object]:
    return {
        "target_id": TARGET_ID,
        "search_space_id": SEARCH_SPACE_ID,
        "parameters": [
            {"name": "sprint_qualifying_score_weight", "type": "float", "default": 1.0},
            {"name": "short_run_pace_weight", "type": "float", "default": 0.4},
        ],
    }
