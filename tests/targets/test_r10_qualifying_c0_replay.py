from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest

from f1_big_predictor.data.jolpica import JolpicaFetchError
from f1_big_predictor.targets.qualifying.c0_roster import CandidateSpec, candidate_registry
from f1_big_predictor.targets.qualifying.r10_c0_replay import (
    ACTUALS_PATH,
    EXPECTED_TRAINING_ROUNDS,
    TARGET_ROUND,
    _OfflineJolpicaAdapter,
    build_r10_target_event,
    extended_walk_forward_round_limit,
    load_r10_official_audit,
    replay_candidate_r10,
    temporary_r10_overlay,
)


ROOT = Path(__file__).resolve().parents[2]


def test_r10_fia_audit_is_complete_and_matches_the_31_model_field() -> None:
    audit = load_r10_official_audit(ROOT)

    assert audit["target_round"] == TARGET_ROUND
    assert audit["field_size"] == 22
    assert len(audit["entry_field"]) == 22
    assert [record["position"] for record in audit["official_records"]] == list(
        range(1, 23)
    )
    assert audit["official_records"][0]["driver_id"] == "antonelli"
    assert audit["official_records"][-1]["driver_id"] == "stroll"
    assert len(candidate_registry()) == 31


def test_r10_overlay_keeps_source_actuals_unchanged_and_only_adds_target_round(
    tmp_path: Path,
) -> None:
    audit = load_r10_official_audit(ROOT)
    source_actuals = ROOT / ACTUALS_PATH
    source_digest_before = hashlib.sha256(source_actuals.read_bytes()).hexdigest()
    circuit_history = tmp_path / "r10_history.json"
    circuit_history.write_text("{}\n", encoding="utf-8")

    with temporary_r10_overlay(
        project_root=ROOT,
        audit=audit,
        circuit_history_path=circuit_history,
    ) as overlay:
        overlay_actuals = json.loads(
            (overlay.root / ACTUALS_PATH).read_text(encoding="utf-8")
        )
        assert [int(item["round"]) for item in overlay_actuals["completed_rounds"]] == [
            *EXPECTED_TRAINING_ROUNDS,
            TARGET_ROUND,
        ]
        r10 = overlay_actuals["completed_rounds"][-1]
        assert r10["circuit_id"] == "spa"
        assert len(r10["qualifying_results"]["records"]) == 22
        assert overlay.actuals_sha256 == hashlib.sha256(
            (overlay.root / ACTUALS_PATH).read_bytes()
        ).hexdigest()

    assert hashlib.sha256(source_actuals.read_bytes()).hexdigest() == source_digest_before


def test_temporary_round_limit_is_restored_after_the_replay_scope() -> None:
    module_names = (
        "f1_big_predictor.targets.qualifying.walk_forward",
        "f1_big_predictor.targets.qualifying.walk_forward_baselines",
        "f1_big_predictor.targets.qualifying.walk_forward_borda",
        "f1_big_predictor.targets.qualifying.walk_forward_elastic_net",
        "f1_big_predictor.targets.qualifying.walk_forward_lambdamart",
        "f1_big_predictor.targets.qualifying.walk_forward_prob",
        "f1_big_predictor.targets.qualifying.walk_forward_rating",
        "f1_big_predictor.targets.qualifying.walk_forward_ridge",
    )
    modules = [importlib.import_module(name) for name in module_names]
    assert [module.LAST_WALK_FORWARD_ROUND for module in modules] == [9] * len(modules)

    with extended_walk_forward_round_limit(TARGET_ROUND):
        assert [module.LAST_WALK_FORWARD_ROUND for module in modules] == [
            TARGET_ROUND
        ] * len(modules)

    assert [module.LAST_WALK_FORWARD_ROUND for module in modules] == [9] * len(modules)


def test_candidate_r10_score_is_computed_after_a_valid_top10_prediction() -> None:
    audit = load_r10_official_audit(ROOT)
    perfect_top10 = [
        record["driver_id"] for record in audit["official_records"][:10]
    ]
    spec = CandidateSpec(
        ordinal=1,
        candidate_id="qv1-001-r10-test",
        model_id="test.r10",
        variant="test",
        related_group=None,
        first_scoring_round=3,
        public_config={},
        runner=lambda _: {
            "per_round": [
                {
                    "round": TARGET_ROUND,
                    "top10_predicted_driver_ids": perfect_top10,
                    "full_field_predicted_driver_ids": perfect_top10,
                    "training_rounds": EXPECTED_TRAINING_ROUNDS,
                    "prediction_status": "ok",
                    "prediction_evidence_gaps": [],
                }
            ],
            "evidence_gaps": [],
        },
    )

    result = replay_candidate_r10(spec, ROOT, audit)

    assert result["status"] == "completed"
    assert result["training_rounds"] == EXPECTED_TRAINING_ROUNDS
    assert result["c0"]["exact"]["exact_hit_count"] == 10
    assert result["c0"]["overall_candidate"]["overall_candidate_score"] == 1.0


def test_offline_adapter_rejects_any_cache_miss() -> None:
    with pytest.raises(JolpicaFetchError, match="offline cache miss"):
        _OfflineJolpicaAdapter().fetch("qualifying", {"season": "2026", "round": "10"})


def test_r10_target_event_preserves_the_fia_entry_universe() -> None:
    audit = load_r10_official_audit(ROOT)
    target = build_r10_target_event(audit)

    records = target["qualifying_results"]["records"]
    assert target["round"] == TARGET_ROUND
    assert target["qualifying_results"]["field_size"] == 22
    assert {record["driver_id"] for record in records} == {
        entry["driver_id"] for entry in audit["entry_field"]
    }
    assert {record["position"] for record in records} == set(range(1, 23))
