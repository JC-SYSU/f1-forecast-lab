from __future__ import annotations

import hashlib
import json
from pathlib import Path

from f1_big_predictor.targets.qualifying.c0_roster import (
    CandidateSpec,
    candidate_registry,
    run_c0_roster,
    write_run_artifacts,
)
from f1_big_predictor.targets.qualifying.official_labels import (
    official_records_for_round,
)


ROOT = Path(__file__).resolve().parents[2]


def test_candidate_registry_matches_confirmed_31_entry_roster() -> None:
    registry = candidate_registry()

    assert len(registry) == 31
    assert [item.ordinal for item in registry] == list(range(1, 32))
    assert len({item.candidate_id for item in registry}) == 31
    assert registry[4].public_config == {"alpha": 10.0}
    assert registry[19].public_config == {"alpha": 0.25}
    assert registry[22].model_id.endswith("gaussian_pairwise_approx")
    # #28/#29 LambdaMART cold starts both begin at R03
    assert [item.first_scoring_round for item in registry[27:29]] == [3, 3]
    # #30/#31 ST-6d slot-assembly ensembles
    assert registry[29].model_id.endswith("ensemble.slot_specialist")
    assert registry[30].model_id.endswith("ensemble.slot_specialist")
    assert registry[29].public_config["method"] == "top_down"
    assert registry[30].public_config["method"] == "set_first"
    assert [item.first_scoring_round for item in registry[-2:]] == [3, 3]


def test_unified_runner_scores_rounds_and_isolates_candidate_failure() -> None:
    healthy = _fake_spec(1, "healthy", _perfect_history)

    def broken_runner(_: Path) -> dict:
        raise RuntimeError("intentional test failure")

    broken = _fake_spec(2, "broken", broken_runner)
    result = run_c0_roster(ROOT, candidates=[healthy, broken])

    assert result["summary"] == {
        "candidate_count": 2,
        "completed_candidate_count": 1,
        "failed_candidate_count": 1,
        "scored_prediction_count": 7,
        "expected_scoring_opportunity_count": 14,
    }
    assert result["candidates"][0]["status"] == "completed"
    assert all(item["status"] == "scored" for item in result["candidates"][0]["rounds"])
    assert result["candidates"][1]["failure"] == {
        "type": "RuntimeError",
        "message": "intentional test failure",
    }
    assert all(item["status"] == "failed" for item in result["candidates"][1]["rounds"])


def test_expected_cold_start_exclusion_is_not_a_failure() -> None:
    # R02 is globally excluded now, so a model that also skips R03 (first_scoring_round=4)
    # still exercises the preregistered-exclusion machinery: R03 becomes an expected
    # exclusion, not a failure, and the remaining R04-R09 score normally.
    late_start = CandidateSpec(
        ordinal=28,
        candidate_id="qv1-028-test-late",
        model_id="test.late",
        variant="test",
        related_group="ltr-G",
        first_scoring_round=4,
        public_config={},
        runner=lambda root: _perfect_history(root, first_round=4),
    )

    result = run_c0_roster(ROOT, candidates=[late_start])
    candidate = result["candidates"][0]

    assert candidate["status"] == "completed"
    assert candidate["rounds"][0]["status"] == "expected_exclusion"
    assert candidate["summary"] == {
        "scored_round_count": 6,
        "failed_round_count": 0,
        "expected_exclusion_count": 1,
        "overall_candidate_scores": [
            item["c0"]["overall_candidate"]["overall_candidate_score"]
            for item in candidate["rounds"][1:]
        ],
    }


def test_core_results_and_written_result_hash_are_deterministic(tmp_path: Path) -> None:
    spec = _fake_spec(1, "stable", _perfect_history)
    first = run_c0_roster(ROOT, candidates=[spec])
    second = run_c0_roster(ROOT, candidates=[spec])

    assert first == second

    paths = write_run_artifacts(ROOT, tmp_path, first)
    results_bytes = paths["results"].read_bytes()
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert json.loads(results_bytes) == first
    assert manifest["results_sha256"] == hashlib.sha256(results_bytes).hexdigest()
    assert manifest["candidate_count"] == 1
    assert manifest["evaluation_rounds"] == list(range(3, 10))


def _fake_spec(ordinal: int, slug: str, runner) -> CandidateSpec:
    return CandidateSpec(
        ordinal=ordinal,
        candidate_id=f"qv1-{ordinal:03d}-{slug}",
        model_id=f"test.{slug}",
        variant="test",
        related_group=None,
        first_scoring_round=3,
        public_config={},
        runner=runner,
    )


def _perfect_history(project_root: Path, first_round: int = 2) -> dict:
    per_round = []
    for round_number in range(first_round, 10):
        records, _ = official_records_for_round(project_root, round_number)
        numeric = sorted(
            (item for item in records if item["position"] is not None),
            key=lambda item: item["position"],
        )
        per_round.append(
            {
                "round": round_number,
                "race_name": f"R{round_number:02d}",
                "top10_predicted_driver_ids": [
                    item["driver_id"] for item in numeric[:10]
                ],
                "training_rounds": list(range(1, round_number)),
                "prediction_evidence_gaps": [],
            }
        )
    return {"per_round": per_round, "evidence_gaps": []}
