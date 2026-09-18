from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TARGET_ID = "sprint_qualifying"
MODEL_ID = "sprint_qualifying.model.v0"
FEATURE_SET_ID = "sprint_qualifying.features.v0.driver_scores_lap_times"
SEARCH_SPACE_ID = "sprint_qualifying.search_space.v0.weighted"
FALLBACK_POLICY = "not_applicable_if_not_sprint_else_require_driver_features_lap_time_gap_if_missing"
EVALUATION_GATE = "top10_accuracy_rank_mae_lap_time_mae"


@dataclass(frozen=True)
class SprintQualifyingTargetConfig:
    model_id: str = MODEL_ID
    feature_set_id: str = FEATURE_SET_ID
    search_space_id: str = SEARCH_SPACE_ID
    fallback_policy: str = FALLBACK_POLICY
    evaluation_gate: str = EVALUATION_GATE


@dataclass(frozen=True)
class SprintQualifyingTargetInputs:
    driver_features: list[Any] | None
    is_sprint_weekend: bool
    evidence_gaps: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SprintQualifyingTargetPrediction:
    target_id: str
    model_id: str
    feature_set_id: str
    fallback_policy: str
    status: str
    entries: list[dict[str, Any]]
    evidence_gaps: list[str]


@dataclass(frozen=True)
class SprintQualifyingTargetEvaluation:
    target_id: str
    top10_position_accuracy: float
    rank_mae: float
    lap_time_mae: float | None
    evaluation_gate: str = EVALUATION_GATE
