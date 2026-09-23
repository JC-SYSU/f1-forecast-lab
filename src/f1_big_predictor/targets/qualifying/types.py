from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

TARGET_ID = "qualifying"
MODEL_ID = "qualifying.model.v1.explainable_score"
FEATURE_SET_ID = "qualifying.features.v1.explainable_score"
SEARCH_SPACE_ID = "qualifying.search_space.v1.weighted"
FALLBACK_POLICY = "require_qualifying_driver_features_lap_time_gap_if_missing"
EVALUATION_GATE = "top10_accuracy_rank_mae_lap_time_mae"
TOP10_SIZE = 10

COMPONENT_NAMES: tuple[str, ...] = (
    "form",
    "constructor",
    "circuit_fit",
    "reliability",
)
TRACK_PROFILE_NAME = "track_profile"

DEFAULT_WEIGHTS: dict[str, float] = {
    "form": 0.30,
    "constructor": 0.25,
    "circuit_fit": 0.20,
    "reliability": 0.10,
}

INDEPENDENT_WEIGHTS: dict[str, float] = {
    "form": 0.270,
    "constructor": 0.225,
    "circuit_fit": 0.180,
    "reliability": 0.090,
    "track_profile": 0.100,
}


def resolve_weights(method: str, raw_weights: Mapping[str, Any] | None = None) -> dict[str, float]:
    """Resolve and validate target-local component weights for a scoring method."""

    if method not in {"interaction", "independent"}:
        raise ValueError(f"unknown track_profile_method: {method}")
    raw = dict(raw_weights or {})
    allowed = set(COMPONENT_NAMES) | ({TRACK_PROFILE_NAME} if method == "independent" else set())
    unknown = sorted(str(key) for key in raw if str(key) not in allowed)
    if unknown:
        raise ValueError(f"unknown qualifying weight components: {', '.join(unknown)}")

    parsed: dict[str, float] = {}
    for key, value in raw.items():
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"qualifying weight must be numeric: {key}") from exc
        if not isfinite(number) or number < 0:
            raise ValueError(f"qualifying weight must be finite and non-negative: {key}")
        parsed[str(key)] = number

    if method == "interaction":
        weights = dict(DEFAULT_WEIGHTS)
        weights.update(parsed)
        return _scale_weights(weights, target_total=1.0)

    track_profile_weight = parsed.pop(TRACK_PROFILE_NAME, INDEPENDENT_WEIGHTS[TRACK_PROFILE_NAME])
    if track_profile_weight > 1.0:
        raise ValueError("track_profile weight must be between zero and one")
    base_weights = dict(DEFAULT_WEIGHTS)
    base_weights.update(parsed)
    weights = _scale_weights(base_weights, target_total=1.0 - track_profile_weight)
    weights[TRACK_PROFILE_NAME] = track_profile_weight
    return weights


def _scale_weights(weights: Mapping[str, float], *, target_total: float) -> dict[str, float]:
    total = sum(weights.values())
    if target_total == 0:
        return {key: 0.0 for key in weights}
    if total <= 0:
        raise ValueError("qualifying weights cannot be all zero")
    scaled = {
        key: round(value * target_total / total, 12)
        for key, value in weights.items()
    }
    last_key = next(reversed(scaled))
    scaled[last_key] = round(scaled[last_key] + (target_total - sum(scaled.values())), 12)
    return scaled


@dataclass(frozen=True)
class QualifyingTargetConfig:
    model_id: str = MODEL_ID
    feature_set_id: str = FEATURE_SET_ID
    search_space_id: str = SEARCH_SPACE_ID
    fallback_policy: str = FALLBACK_POLICY
    evaluation_gate: str = EVALUATION_GATE


@dataclass(frozen=True)
class QualifyingFeatureConfig:
    """Configuration for the v1 explainable score feature builder."""

    form_window: int = 3
    track_profile_method: str = "interaction"
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    def __post_init__(self) -> None:
        if self.form_window < 1:
            raise ValueError("form_window must be at least 1")
        resolve_weights(self.track_profile_method, self.weights)


@dataclass(frozen=True)
class QualifyingTargetInputs:
    driver_features: list[Any]
    evidence_gaps: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QualifyingTargetPrediction:
    target_id: str
    model_id: str
    feature_set_id: str
    fallback_policy: str
    status: str
    entries: list[dict[str, Any]]
    evidence_gaps: list[str]


@dataclass(frozen=True)
class QualifyingTargetEvaluation:
    target_id: str
    top10_position_accuracy: float
    rank_mae: float
    lap_time_mae: float | None
    evaluation_gate: str = EVALUATION_GATE
