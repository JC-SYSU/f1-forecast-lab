from __future__ import annotations

import json
from pathlib import Path

from f1_big_predictor.targets.qualifying import (
    QualifyingFeatureConfig,
    build_qualifying_features,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_build_qualifying_features_round_04_reports_strict_historical_evidence_gap() -> (
    None
):
    payload = build_qualifying_features(project_root=PROJECT_ROOT, target_round=4)
    rows = payload["rows"]

    assert len(rows) == 22
    assert payload["feature_set_id"] == "qualifying.features.v1.explainable_score"
    assert payload["evidence_policy"] == "strict_historical_as_of"
    assert payload["evidence_exclusion_summary"]["eligible_count"] == 0
    assert all(row["evidence_score"] is None for row in rows)
    assert all(
        "no_eligible_qualifying_evidence" in row["component_gaps"] for row in rows
    )
    assert "evidence_exclusion_retrieved_after_cutoff" in payload["evidence_gaps"]


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
        "evidence_policy",
        "evidence_gaps",
        "evidence_exclusion_summary",
    }
    assert set(payload["config"]) == {
        "form_window",
        "evidence_method",
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
        "evidence_score",
        "reliability_score",
        "reliability_method",
        "seat_note",
        "track_profile_score",
        "track_profile_method",
        "track_profile",
        "evidence_method",
        "weights",
        "component_gaps",
    }
    assert row["weights"] == payload["config"]["weights"]
    assert isinstance(row["component_gaps"], list)


def test_current_historical_rounds_r02_to_r09_have_no_eligible_evidence() -> None:
    for target_round in range(2, 10):
        payload = build_qualifying_features(
            project_root=PROJECT_ROOT, target_round=target_round
        )
        assert all(row["evidence_score"] is None for row in payload["rows"])
        assert payload["evidence_exclusion_summary"]["eligible_count"] == 0
        assert "no_eligible_qualifying_evidence" in payload["evidence_gaps"]


def test_build_qualifying_features_round_01_reports_prior_round_gaps() -> None:
    payload = build_qualifying_features(project_root=PROJECT_ROOT, target_round=1)
    rows = payload["rows"]

    assert len(rows) == 22
    assert all(row["form_score"] is None for row in rows)
    assert all(row["reliability_score"] is None for row in rows)
    assert "no_prior_rounds_for_form" in payload["evidence_gaps"]
    assert "missing_form_score" in rows[0]["component_gaps"]


def test_directional_gate_rejects_published_retrieved_scope_and_usage_failures(
    tmp_path: Path,
) -> None:
    evidence = [
        _evidence(
            "ok",
            published="2026-01-01T00:00:00Z",
            retrieved="2026-01-02T00:00:00Z",
            scope=["qualifying"],
        ),
        _evidence(
            "published_late",
            published="2026-02-01T00:00:00Z",
            retrieved="2026-01-02T00:00:00Z",
            scope=["qualifying"],
        ),
        _evidence(
            "retrieved_late",
            published="2026-01-01T00:00:00Z",
            retrieved="2026-02-01T00:00:00Z",
            scope=["qualifying"],
        ),
        _evidence(
            "race_only",
            published="2026-01-01T00:00:00Z",
            retrieved="2026-01-02T00:00:00Z",
            scope=["race"],
        ),
        _evidence(
            "note",
            published="2026-01-01T00:00:00Z",
            retrieved="2026-01-02T00:00:00Z",
            scope=["qualifying"],
            usage="note",
        ),
    ]
    _write_fixture(tmp_path, evidence=evidence)

    payload = build_qualifying_features(
        project_root=tmp_path,
        target_round=2,
        officialize_actuals=False,
    )
    assert _row(payload["rows"], "driver_a")["evidence_score"] > 0.5
    assert _row(payload["rows"], "driver_b")["evidence_score"] is None
    summary = payload["evidence_exclusion_summary"]
    assert summary["eligible_count"] == 1
    assert summary["published_after_cutoff"] == 1
    assert summary["retrieved_after_cutoff"] == 1
    assert summary["qualifying_scope_missing"] == 1
    assert summary["model_usage_not_feature"] == 1


def test_ordinal_gate_requires_frozen_cutoff_scope_and_all_evidence_references(
    tmp_path: Path,
) -> None:
    evidence = [
        _evidence(
            "ok",
            published="2026-01-01T00:00:00Z",
            retrieved="2026-01-02T00:00:00Z",
            scope=["qualifying"],
        )
    ]
    residual = {
        "event_round": 2,
        "frozen": True,
        "frozen_at": "2026-02-01T00:00:00Z",
        "entries": [
            {
                "event_round": 2,
                "target": {"type": "driver", "ids": ["driver_a"]},
                "ordinal_signal": 1.5,
                "confidence": 1.0,
                "evidence_ids": ["missing"],
                "session_scope": ["qualifying"],
            }
        ],
    }
    _write_fixture(tmp_path, evidence=evidence, residual=residual)

    payload = build_qualifying_features(
        project_root=tmp_path,
        target_round=2,
        config=QualifyingFeatureConfig(evidence_method="ordinal"),
        officialize_actuals=False,
    )
    assert _row(payload["rows"], "driver_a")["evidence_score"] is None
    assert (
        "residual_exclusion_unresolved_evidence_reference" in payload["evidence_gaps"]
    )

    residual["frozen"] = False
    residual["frozen_at"] = "2026-03-01T00:00:00Z"
    residual["entries"][0]["evidence_ids"] = ["ok"]
    residual["entries"][0]["session_scope"] = ["race"]
    _write_fixture(tmp_path, evidence=evidence, residual=residual)
    payload = build_qualifying_features(
        project_root=tmp_path,
        target_round=2,
        config=QualifyingFeatureConfig(evidence_method="ordinal"),
        officialize_actuals=False,
    )
    summary = payload["evidence_exclusion_summary"]
    assert summary["residual_not_frozen"] == 1
    assert summary["residual_frozen_after_cutoff"] == 1
    assert summary["residual_scope_missing"] == 1
    assert _row(payload["rows"], "driver_a")["evidence_score"] is None


def test_eligible_ordinal_fixture_scores_and_does_not_use_neutral_missing_fallback(
    tmp_path: Path,
) -> None:
    evidence = [
        _evidence(
            "ok",
            published="2026-01-01T00:00:00Z",
            retrieved="2026-01-02T00:00:00Z",
            scope=["qualifying"],
        )
    ]
    residual = {
        "event_round": 2,
        "frozen": True,
        "frozen_at": "2026-01-03T00:00:00Z",
        "entries": [
            {
                "event_round": 2,
                "target": {"type": "driver", "ids": ["driver_a"]},
                "ordinal_signal": 1.5,
                "confidence": 1.0,
                "evidence_ids": ["ok"],
                "session_scope": ["qualifying"],
            }
        ],
    }
    _write_fixture(tmp_path, evidence=evidence, residual=residual)

    payload = build_qualifying_features(
        project_root=tmp_path,
        target_round=2,
        config=QualifyingFeatureConfig(evidence_method="ordinal"),
        officialize_actuals=False,
    )
    assert _row(payload["rows"], "driver_a")["evidence_score"] == 0.875
    assert _row(payload["rows"], "driver_b")["evidence_score"] is None
    assert (
        "missing_qualifying_evidence_signal"
        in _row(payload["rows"], "driver_b")["component_gaps"]
    )


def _row(rows: list[dict[str, object]], driver_id: str) -> dict[str, object]:
    return next(row for row in rows if row["driver_id"] == driver_id)


def _evidence(
    evidence_id: str,
    *,
    published: str,
    retrieved: str,
    scope: list[str],
    usage: str = "feature",
) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "event_round": 2,
        "published_on": published,
        "retrieved_on": retrieved,
        "applies_to": {"type": "driver", "ids": ["driver_a"]},
        "direction": "positive",
        "confidence": 1.0,
        "model_usage": usage,
        "session_scope": scope,
    }


def _write_fixture(
    root: Path,
    *,
    evidence: list[dict[str, object]],
    residual: dict[str, object] | None = None,
) -> None:
    (root / "data/manual").mkdir(parents=True, exist_ok=True)
    (root / "data/processed/season_2026_actuals").mkdir(parents=True, exist_ok=True)
    (root / "data/processed/circuit_history_2026_v1").mkdir(parents=True, exist_ok=True)
    _dump(
        root / "data/manual/seat_changes_2026_v1.json",
        {"schema_version": "seat_changes_2026_v1", "events": [], "exemptions": []},
    )
    (root / "data/manual/subjective_residuals_2026_v1").mkdir(
        parents=True, exist_ok=True
    )
    _dump(
        root / "data/manual/2026_grid.json",
        {
            "drivers": [
                {
                    "driver_id": "driver_a",
                    "display_name": "Driver A",
                    "team_id": "team_a",
                },
                {
                    "driver_id": "driver_b",
                    "display_name": "Driver B",
                    "team_id": "team_b",
                },
            ],
            "teams": [
                {"team_id": "team_a", "display_name": "Team A"},
                {"team_id": "team_b", "display_name": "Team B"},
            ],
        },
    )
    _dump(
        root / "data/processed/season_2026_actuals/actuals.json",
        {
            "season": 2026,
            "completed_rounds": [
                {
                    "round": 1,
                    "race_name": "Prior",
                    "circuit_id": "prior",
                    "qualifying_results": {
                        "row_count": 2,
                        "records": [
                            {"driver_id": "driver_a", "position": 1},
                            {"driver_id": "driver_b", "position": 2},
                        ],
                    },
                    "race_results": {
                        "records": [
                            {"driver_id": "driver_a", "status": "Finished"},
                            {"driver_id": "driver_b", "status": "Finished"},
                        ]
                    },
                    "constructor_standings": {
                        "records": [
                            {"constructor_id": "team_a", "points": 10},
                            {"constructor_id": "team_b", "points": 5},
                        ]
                    },
                },
                {
                    "round": 2,
                    "race_name": "Target",
                    "circuit_id": "target",
                    "qualifying_results": {
                        "row_count": 2,
                        "records": [
                            {"driver_id": "driver_a", "position": 1},
                            {"driver_id": "driver_b", "position": 2},
                        ],
                    },
                    "race_results": {
                        "records": [
                            {"driver_id": "driver_a", "status": "Finished"},
                            {"driver_id": "driver_b", "status": "Finished"},
                        ]
                    },
                    "constructor_standings": {
                        "records": [
                            {"constructor_id": "team_a", "points": 10},
                            {"constructor_id": "team_b", "points": 5},
                        ]
                    },
                },
            ],
        },
    )
    _dump(
        root / "data/processed/circuit_history_2026_v1/round_02_target.json",
        {
            "driver_history_scores": [
                {"driver_id": "driver_a", "coverage_count": 1, "qualifying_score": 0.8},
                {"driver_id": "driver_b", "coverage_count": 1, "qualifying_score": 0.6},
            ]
        },
    )
    _dump(root / "data/manual/track_profile_2026_v1.json", {"profiles": []})
    _dump(
        root / "data/manual/agent_evidence_2026_v1.json",
        {
            "events": [
                {
                    "event_round": 2,
                    "pre_qualifying_cutoff": "2026-01-10T00:00:00Z",
                    "evidence": evidence,
                }
            ]
        },
    )
    if residual is not None:
        _dump(
            root / "data/manual/subjective_residuals_2026_v1/round_02_target.json",
            residual,
        )


def _dump(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
