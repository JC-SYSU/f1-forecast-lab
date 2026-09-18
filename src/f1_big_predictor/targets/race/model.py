from __future__ import annotations

from .._shared import ranked_entries_from_features
from .types import TARGET_ID, RaceTargetConfig, RaceTargetInputs, RaceTargetPrediction


def predict_race_target(
    *,
    inputs: RaceTargetInputs,
    config: RaceTargetConfig,
) -> RaceTargetPrediction:
    entries = ranked_entries_from_features(inputs.driver_features, score_field="race_score")
    evidence_gaps = list(inputs.evidence_gaps)
    if not entries:
        evidence_gaps.append("missing_race_driver_features")
    return RaceTargetPrediction(
        target_id=TARGET_ID,
        model_id=config.model_id,
        feature_set_id=config.feature_set_id,
        fallback_policy=config.fallback_policy,
        status="ok" if entries else "evidence_issue",
        entries=entries,
        evidence_gaps=evidence_gaps,
    )
