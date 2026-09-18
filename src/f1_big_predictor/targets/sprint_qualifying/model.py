from __future__ import annotations

from .._shared import ranked_entries_from_features
from .types import (
    TARGET_ID,
    SprintQualifyingTargetConfig,
    SprintQualifyingTargetInputs,
    SprintQualifyingTargetPrediction,
)


def predict_sprint_qualifying_target(
    *,
    inputs: SprintQualifyingTargetInputs,
    config: SprintQualifyingTargetConfig,
) -> SprintQualifyingTargetPrediction:
    if not inputs.is_sprint_weekend:
        return SprintQualifyingTargetPrediction(
            target_id=TARGET_ID,
            model_id=config.model_id,
            feature_set_id=config.feature_set_id,
            fallback_policy=config.fallback_policy,
            status="not_applicable",
            entries=[],
            evidence_gaps=list(inputs.evidence_gaps),
        )
    entries = ranked_entries_from_features(
        inputs.driver_features,
        score_field="sprint_qualifying_score",
        lap_time_field="predicted_lap_time",
    )
    evidence_gaps = list(inputs.evidence_gaps)
    if not entries:
        evidence_gaps.append("missing_sprint_qualifying_driver_features")
    if entries and any(item.get("lap_time") is None for item in entries):
        evidence_gaps.append("missing_sprint_qualifying_lap_time")
    return SprintQualifyingTargetPrediction(
        target_id=TARGET_ID,
        model_id=config.model_id,
        feature_set_id=config.feature_set_id,
        fallback_policy=config.fallback_policy,
        status="ok" if entries else "evidence_issue",
        entries=entries,
        evidence_gaps=evidence_gaps,
    )
