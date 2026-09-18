from __future__ import annotations

from .._shared import ranked_entries_from_features
from .types import TARGET_ID, SprintRaceTargetConfig, SprintRaceTargetInputs, SprintRaceTargetPrediction


def predict_sprint_race_target(
    *,
    inputs: SprintRaceTargetInputs,
    config: SprintRaceTargetConfig,
) -> SprintRaceTargetPrediction:
    profile = inputs.as_of_profile
    if not profile.is_sprint_weekend:
        return SprintRaceTargetPrediction(
            target_id=TARGET_ID,
            model_id=config.model_id,
            feature_set_id=config.feature_set_id,
            fallback_policy=config.fallback_policy,
            status="not_applicable",
            entries=[],
            evidence_gaps=list(inputs.evidence_gaps),
        )
    entries = ranked_entries_from_features(inputs.driver_features, score_field="sprint_race_score")
    evidence_gaps = list(inputs.evidence_gaps)
    if not entries:
        evidence_gaps.append("missing_sprint_race_driver_features")
    elif profile.sprint_qualifying_available and any("sprint_qualifying_position" not in item for item in inputs.driver_features or []):
        evidence_gaps.append("missing_sprint_race_sprint_qualifying_position")
    return SprintRaceTargetPrediction(
        target_id=TARGET_ID,
        model_id=config.model_id,
        feature_set_id=config.feature_set_id,
        fallback_policy=config.fallback_policy,
        status="ok" if entries else "evidence_issue",
        entries=entries,
        evidence_gaps=evidence_gaps,
    )
