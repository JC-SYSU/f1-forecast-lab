from __future__ import annotations

from .types import DEFAULT_WEIGHTS, INDEPENDENT_WEIGHTS, SEARCH_SPACE_ID, TARGET_ID


def search_space() -> dict[str, object]:
    return {
        "target_id": TARGET_ID,
        "search_space_id": SEARCH_SPACE_ID,
        "parameters": [
            {"name": "form_weight", "type": "float", "default": 0.30},
            {"name": "constructor_weight", "type": "float", "default": 0.25},
            {"name": "circuit_fit_weight", "type": "float", "default": 0.20},
            {"name": "evidence_weight", "type": "float", "default": 0.15},
            {"name": "reliability_weight", "type": "float", "default": 0.10},
            {"name": "track_profile_weight", "type": "float", "default": 0.10},
            {"name": "form_window", "type": "int", "default": 3},
            {"name": "evidence_method", "type": "str", "default": "directional"},
            {"name": "track_profile_method", "type": "str", "default": "interaction"},
        ],
        "weight_profiles": {
            "interaction": dict(DEFAULT_WEIGHTS),
            "independent": dict(INDEPENDENT_WEIGHTS),
        },
    }
