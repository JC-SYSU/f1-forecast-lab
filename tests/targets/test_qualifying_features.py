from __future__ import annotations

from pathlib import Path

from f1_big_predictor.targets.qualifying import (
    build_qualifying_features,
)
from f1_big_predictor.targets.qualifying.types import (
    COMPONENT_NAMES,
    DEFAULT_WEIGHTS,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _row(rows: list[dict[str, object]], driver_id: str) -> dict[str, object]:
    return next(row for row in rows if row["driver_id"] == driver_id)


def test_build_qualifying_features_round_04_component_scores() -> None:
    payload = build_qualifying_features(project_root=PROJECT_ROOT, target_round=4)
    rows = payload["rows"]

    assert len(rows) == 22
    assert payload["feature_set_id"] == "qualifying.features.v1.explainable_score"
    assert all("evidence_score" not in row for row in rows)
    assert "evidence_policy" not in payload
    assert "evidence_exclusion_summary" not in payload
    assert "evidence_method" not in payload["config"]


def test_evidence_component_formally_removed_from_mainline() -> None:
    """After the 2026-09-23 dormant ruling the evidence component has been
    removed from the main line (decision log, entry 16). This test locks in
    the removal."""
    payload = build_qualifying_features(project_root=PROJECT_ROOT, target_round=5)
    assert all("evidence_score" not in row for row in payload["rows"])
    assert "evidence_policy" not in payload
    assert "evidence" not in payload["config"]
    assert "evidence" not in COMPONENT_NAMES
    assert "evidence" not in DEFAULT_WEIGHTS


def test_build_qualifying_features_payload_and_row_schema_are_auditable() -> None:
    payload = build_qualifying_features(project_root=PROJECT_ROOT, target_round=4)
    row = _row(payload["rows"], "norris")

    assert set(payload) == {
        "feature_set_id",
        "season",
        "target_round",
        "target_event",
        "config",
        "track_profile",
        "rows",
        "evidence_gaps",
    }
    assert set(payload["config"]) == {
        "form_window",
        "track_profile_method",
        "weights",
    }
    assert set(payload["target_event"]) == {
        "round",
        "race_name",
        "circuit_id",
        "pre_qualifying_cutoff",
    }
    assert set(row) == {
        "feature_set_id",
        "season",
        "target_round",
        "driver_id",
        "driver_name",
        "constructor_id",
        "constructor_name",
        "form_score",
        "constructor_score",
        "circuit_fit_score",
        "reliability_score",
        "reliability_method",
        "seat_note",
        "track_profile_score",
        "track_profile_method",
        "track_profile",
        "weights",
        "component_gaps",
    }
    assert row["weights"] == payload["config"]["weights"]
    assert isinstance(row["component_gaps"], list)


def test_build_qualifying_features_round_01_reports_prior_round_gaps() -> None:
    payload = build_qualifying_features(project_root=PROJECT_ROOT, target_round=1)
    rows = payload["rows"]

    assert len(rows) == 22
    assert all(row["form_score"] is None for row in rows)
    assert all(row["reliability_score"] is None for row in rows)
    assert "no_prior_rounds_for_form" in payload["evidence_gaps"]
    assert "missing_form_score" in rows[0]["component_gaps"]
