from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest

from f1_big_predictor.data.jolpica import JolpicaFetchError
from f1_big_predictor.targets.qualifying.c0_roster import CandidateSpec, candidate_registry
from f1_big_predictor.targets.qualifying.r11_c0_replay import (
    ACTUALS_PATH,
    CIRCUIT_HISTORY_DIR,
    EXPECTED_TRAINING_ROUNDS,
    SOURCE_ACTUALS_ROUNDS,
    TARGET_ROUND,
    _OfflineJolpicaAdapter,
    build_r11_target_event,
    extended_walk_forward_round_limit,
    load_r11_official_audit,
    replay_candidate_r11,
    temporary_r11_overlay,
)
from f1_big_predictor.targets.qualifying.r10_c0_replay import load_r10_official_audit


ROOT = Path(__file__).resolve().parents[2]


def test_r11_fia_audit_is_complete_and_matches_the_31_model_field() -> None:
    audit = load_r11_official_audit(ROOT)

    assert audit["target_round"] == TARGET_ROUND
    assert audit["field_size"] == 22
    assert len(audit["entry_field"]) == 22
    assert [record["position"] for record in audit["official_records"]] == list(
        range(1, 23)
    )
    assert audit["official_records"][0]["driver_id"] == "norris"
    assert audit["official_records"][-1]["driver_id"] == "perez"
    assert len(candidate_registry()) == 31


def test_r11_overlay_keeps_source_actuals_unchanged_and_adds_r10_history_and_r11_target(
    tmp_path: Path,
) -> None:
    r10_audit = load_r10_official_audit(ROOT)
    audit = load_r11_official_audit(ROOT)
    source_actuals = ROOT / ACTUALS_PATH
    source_digest_before = hashlib.sha256(source_actuals.read_bytes()).hexdigest()
    r10_circuit_history = tmp_path / "r10_history.json"
    r10_circuit_history.write_text("{}\n", encoding="utf-8")
    r11_circuit_history = tmp_path / "r11_history.json"
    r11_circuit_history.write_text("{}\n", encoding="utf-8")

    with temporary_r11_overlay(
        project_root=ROOT,
        r10_audit=r10_audit,
        audit=audit,
        r10_circuit_history_path=r10_circuit_history,
        r11_circuit_history_path=r11_circuit_history,
    ) as overlay:
        overlay_actuals = json.loads(
            (overlay.root / ACTUALS_PATH).read_text(encoding="utf-8")
        )
        assert [int(item["round"]) for item in overlay_actuals["completed_rounds"]] == [
            *SOURCE_ACTUALS_ROUNDS,
            10,
            TARGET_ROUND,
        ]
        r10 = overlay_actuals["completed_rounds"][-2]
        r11 = overlay_actuals["completed_rounds"][-1]
        assert r10["circuit_id"] == "spa"
        assert r11["circuit_id"] == "hungaroring"
        assert len(r11["qualifying_results"]["records"]) == 22
        history_root = overlay.root / CIRCUIT_HISTORY_DIR
        assert (history_root / "round_10_belgian_grand_prix.json").is_symlink()
        assert (history_root / "round_11_hungarian_grand_prix.json").is_symlink()
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


def test_candidate_r11_score_is_computed_after_a_valid_top10_prediction() -> None:
    audit = load_r11_official_audit(ROOT)
    perfect_top10 = [
        record["driver_id"] for record in audit["official_records"][:10]
    ]
    spec = CandidateSpec(
        ordinal=1,
        candidate_id="qv1-001-r11-test",
        model_id="test.r11",
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

    result = replay_candidate_r11(spec, ROOT, audit)

    assert result["status"] == "completed"
    assert result["training_rounds"] == EXPECTED_TRAINING_ROUNDS
    assert result["c0"]["exact"]["exact_hit_count"] == 10
    assert result["c0"]["overall_candidate"]["overall_candidate_score"] == 1.0


def test_offline_adapter_rejects_any_cache_miss() -> None:
    with pytest.raises(JolpicaFetchError, match="offline cache miss"):
        _OfflineJolpicaAdapter().fetch("qualifying", {"season": "2026", "round": "11"})


def test_r11_target_event_preserves_the_fia_entry_universe() -> None:
    audit = load_r11_official_audit(ROOT)
    target = build_r11_target_event(audit)

    records = target["qualifying_results"]["records"]
    assert target["round"] == TARGET_ROUND
    assert target["qualifying_results"]["field_size"] == 22
    assert {record["driver_id"] for record in records} == {
        entry["driver_id"] for entry in audit["entry_field"]
    }
    assert {record["position"] for record in records} == set(range(1, 23))
