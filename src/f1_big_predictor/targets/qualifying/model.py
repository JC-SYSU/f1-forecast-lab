from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from .._shared import ranked_entries_from_features
from .types import (
    TOP10_SIZE,
    TARGET_ID,
    QualifyingTargetConfig,
    QualifyingTargetInputs,
    QualifyingTargetPrediction,
    resolve_weights,
)


COMPONENT_FIELDS: tuple[tuple[str, str], ...] = (
    ("form", "form_score"),
    ("constructor", "constructor_score"),
    ("circuit_fit", "circuit_fit_score"),
    ("evidence", "evidence_score"),
    ("reliability", "reliability_score"),
)
TRACK_PROFILE_COMPONENT = ("track_profile", "track_profile_score")
LAP_TIME_GAP = "lap_time_not_predicted_v1"


def predict_qualifying_target(
    *,
    inputs: QualifyingTargetInputs,
    config: QualifyingTargetConfig,
) -> QualifyingTargetPrediction:
    feature_rows = _feature_rows(inputs.driver_features)
    full_ranking = score_qualifying_field(driver_features=feature_rows)
    entries = ranked_entries_from_features(
        full_ranking[:TOP10_SIZE],
        score_field="qualifying_score",
        lap_time_field="predicted_lap_time",
    )
    for entry in entries:
        entry["qualifying_score"] = entry["score"]
    evidence_gaps = list(inputs.evidence_gaps)
    if not feature_rows:
        evidence_gaps.append("missing_qualifying_driver_features")
    elif not full_ranking:
        evidence_gaps.append("missing_qualifying_component_scores")
    elif len(full_ranking) < TOP10_SIZE:
        evidence_gaps.append("insufficient_qualifying_scored_drivers_for_top10")
        entries = []
    if entries:
        _append_gap(evidence_gaps, LAP_TIME_GAP)
    return QualifyingTargetPrediction(
        target_id=TARGET_ID,
        model_id=config.model_id,
        feature_set_id=config.feature_set_id,
        fallback_policy=config.fallback_policy,
        status="ok" if len(full_ranking) >= TOP10_SIZE else "evidence_issue",
        entries=entries,
        evidence_gaps=evidence_gaps,
    )


def _feature_rows(features: list[Any] | None) -> list[dict[str, Any]]:
    if not features:
        return []
    rows = []
    for item in features:
        if isinstance(item, Mapping):
            row = dict(item)
        else:
            row = asdict(item)
        if "driver_id" not in row:
            raise ValueError("target feature rows require driver_id")
        rows.append(row)
    return rows


def score_qualifying_field(*, driver_features: list[Any] | None) -> list[dict[str, Any]]:
    """Return the complete target-local field ranking with diagnostic data."""

    rows = _feature_rows(driver_features)
    method = _track_profile_method(rows)
    profile_type = _track_profile_type(rows)
    scored: list[dict[str, Any]] = []
    for row in rows:
        score, effective_weights, available_components = _qualifying_score_details(
            row,
            method=method,
            profile_type=profile_type,
        )
        if score is None:
            continue
        scored_row = dict(row)
        scored_row["qualifying_score"] = round(score, 6)
        scored_row["predicted_lap_time"] = None
        scored_row["available_components"] = available_components
        scored_row["effective_weights"] = _auditable_weights(effective_weights)
        scored_row["component_gaps"] = _component_gaps(row, method)
        scored.append(scored_row)
    ranked = sorted(scored, key=lambda item: (-float(item["qualifying_score"]), str(item["driver_id"])))
    for position, row in enumerate(ranked, start=1):
        row["position"] = position
        row["score"] = row["qualifying_score"]
    return ranked


def _qualifying_score_details(
    row: dict[str, Any],
    *,
    method: str,
    profile_type: str | None,
) -> tuple[float | None, dict[str, float], list[str]]:
    has_component_fields = (
        any(field in row for _, field in COMPONENT_FIELDS) or TRACK_PROFILE_COMPONENT[1] in row
    )
    if not has_component_fields:
        score = _optional_float(row.get("qualifying_score"))
        return score, {}, ["qualifying_score"] if score is not None else []

    weights = _row_weights(row, method)
    if method == "interaction":
        weights = _interaction_weights(weights, profile_type)
    components = list(COMPONENT_FIELDS)
    if method == "independent":
        components.append(TRACK_PROFILE_COMPONENT)

    available: list[tuple[str, float, float]] = []
    for component, field in components:
        value = _optional_float(row.get(field))
        weight = _optional_float(weights.get(component)) or 0.0
        if value is not None and weight > 0:
            available.append((component, value, weight))
    total_weight = sum(weight for _, _, weight in available)
    if total_weight <= 0:
        return None, {}, []
    effective_weights = {
        component: weight / total_weight for component, _, weight in available
    }
    return (
        sum(value * effective_weights[component] for component, value, _ in available),
        effective_weights,
        [component for component, _, _ in available],
    )


def _row_weights(row: dict[str, Any], method: str) -> dict[str, float]:
    raw_weights = row.get("weights")
    if not isinstance(raw_weights, Mapping):
        config = row.get("config")
        raw_weights = config.get("weights") if isinstance(config, Mapping) else None
    return resolve_weights(method, raw_weights if isinstance(raw_weights, Mapping) else None)


def _component_gaps(row: dict[str, Any], method: str) -> list[str]:
    existing = row.get("component_gaps")
    gaps = list(existing) if isinstance(existing, list) else []
    fields = list(COMPONENT_FIELDS)
    if method == "independent":
        fields.append(TRACK_PROFILE_COMPONENT)
    for component, field in fields:
        if _optional_float(row.get(field)) is not None:
            continue
        if component == "circuit_fit":
            gap = "no_same_circuit_history"
        elif component == "evidence":
            gap = "missing_qualifying_evidence_signal"
        elif component == "track_profile":
            gap = "no_same_track_profile_history"
        else:
            gap = f"missing_{component}_score"
        _append_gap(gaps, gap)
    return gaps


def _auditable_weights(weights: dict[str, float]) -> dict[str, float]:
    rounded = {key: round(value, 12) for key, value in weights.items()}
    if rounded:
        last_key = next(reversed(rounded))
        rounded[last_key] = round(rounded[last_key] + (1.0 - sum(rounded.values())), 12)
    return rounded


def _interaction_weights(weights: dict[str, float], profile_type: str | None) -> dict[str, float]:
    adjusted = dict(weights)
    if profile_type == "high_downforce":
        adjusted["circuit_fit"] = adjusted.get("circuit_fit", 0.0) * 1.25
        adjusted["form"] = adjusted.get("form", 0.0) * 0.90
    elif profile_type == "street":
        adjusted["reliability"] = adjusted.get("reliability", 0.0) * 1.20
        adjusted["form"] = adjusted.get("form", 0.0) * 1.10
    elif profile_type == "low_downforce":
        adjusted["form"] = adjusted.get("form", 0.0) * 1.15
        adjusted["circuit_fit"] = adjusted.get("circuit_fit", 0.0) * 0.85
    total = sum(value for value in adjusted.values() if value > 0)
    if total <= 0:
        return adjusted
    return {key: (value / total if value > 0 else 0.0) for key, value in adjusted.items()}


def _track_profile_method(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        method = row.get("track_profile_method")
        if method is not None:
            return str(method)
    return "interaction"


def _track_profile_type(rows: list[dict[str, Any]]) -> str | None:
    for row in rows:
        value = _track_profile_value(row)
        if value:
            return value
    return None


def _track_profile_value(row: dict[str, Any]) -> str | None:
    profile = row.get("track_profile")
    if isinstance(profile, Mapping):
        profile_type = _profile_from_mapping(profile)
        if profile_type:
            return profile_type
    for key in ("track_profile_speed_type", "profile_type", "track_type", "downforce", "speed_type"):
        value = _profile_value_for_key(key, row.get(key))
        if value:
            return value
    if row.get("is_street") is True:
        return "street"
    return None


def _profile_from_mapping(profile: Mapping[str, Any]) -> str | None:
    if _normalize_profile_value(profile.get("track_type")) == "street" or profile.get("is_street") is True:
        return "street"
    downforce = _profile_value_for_key("downforce", profile.get("downforce"))
    if downforce:
        return downforce
    for key in ("speed_type", "profile_type"):
        value = _profile_value_for_key(key, profile.get(key))
        if value:
            return value
    return None


def _profile_value_for_key(key: str, value: Any) -> str | None:
    normalized = _normalize_profile_value(value)
    if normalized:
        return normalized
    if key != "downforce":
        return None
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text == "high":
        return "high_downforce"
    if text == "low":
        return "low_downforce"
    return None


def _normalize_profile_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    if text in {"high_downforce", "street", "low_downforce"}:
        return text
    return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _append_gap(gaps: list[str], value: str) -> None:
    if value not in gaps:
        gaps.append(value)
