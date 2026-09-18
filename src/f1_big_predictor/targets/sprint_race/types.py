from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TARGET_ID = "sprint_race"
MODEL_ID = "sprint_race.model.v0"
FEATURE_SET_ID = "sprint_race.features.v0.driver_scores"
SEARCH_SPACE_ID = "sprint_race.search_space.v0.weighted"
FALLBACK_POLICY = "not_applicable_if_not_sprint_else_rank_driver_features_with_optional_sprint_qualifying_position"
EVALUATION_GATE = "top10_accuracy_rank_mae"


@dataclass(frozen=True)
class SprintRaceTargetConfig:
    model_id: str = MODEL_ID
    feature_set_id: str = FEATURE_SET_ID
    search_space_id: str = SEARCH_SPACE_ID
    fallback_policy: str = FALLBACK_POLICY
    evaluation_gate: str = EVALUATION_GATE


@dataclass(frozen=True)
class SprintRaceAsOfProfile:
    is_sprint_weekend: bool
    sprint_qualifying_available: bool
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SprintRaceTargetInputs:
    driver_features: list[Any] | None
    as_of_profile: SprintRaceAsOfProfile
    evidence_gaps: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SprintRaceTargetPrediction:
    target_id: str
    model_id: str
    feature_set_id: str
    fallback_policy: str
    status: str
    entries: list[dict[str, Any]]
    evidence_gaps: list[str]


@dataclass(frozen=True)
class SprintRaceTargetEvaluation:
    target_id: str
    top10_position_accuracy: float
    rank_mae: float
    evaluation_gate: str = EVALUATION_GATE
