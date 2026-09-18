from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TARGET_ID = "race"
MODEL_ID = "race.model.v0"
FEATURE_SET_ID = "race.features.v0.driver_scores"
SEARCH_SPACE_ID = "race.search_space.v0.weighted"
FALLBACK_POLICY = "require_race_driver_features_else_evidence_issue"
EVALUATION_GATE = "top10_accuracy_rank_mae"


@dataclass(frozen=True)
class RaceTargetConfig:
    model_id: str = MODEL_ID
    feature_set_id: str = FEATURE_SET_ID
    search_space_id: str = SEARCH_SPACE_ID
    fallback_policy: str = FALLBACK_POLICY
    evaluation_gate: str = EVALUATION_GATE


@dataclass(frozen=True)
class RaceTargetInputs:
    driver_features: list[Any]
    evidence_gaps: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RaceTargetPrediction:
    target_id: str
    model_id: str
    feature_set_id: str
    fallback_policy: str
    status: str
    entries: list[dict[str, Any]]
    evidence_gaps: list[str]


@dataclass(frozen=True)
class RaceTargetEvaluation:
    target_id: str
    top10_position_accuracy: float
    rank_mae: float
    evaluation_gate: str = EVALUATION_GATE
