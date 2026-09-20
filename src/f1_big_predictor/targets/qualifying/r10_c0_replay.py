"""Isolated R10 qualifying C0 replay using the frozen 31-candidate roster.

The historical roster runner deliberately ends at R09.  This module creates a
temporary, as-of-R09 overlay so the existing candidates can emit an R10
prediction without modifying their frozen definitions.  R10's FIA result is
only used after each candidate has produced its Top 10 for C0 scoring.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import importlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from f1_big_predictor.data.archive import RawArchive
from f1_big_predictor.data.circuit_history import collect_circuit_history
from f1_big_predictor.data.jolpica import JolpicaClient, JolpicaFetchError

from .c0_roster import CandidateSpec, build_input_snapshot, candidate_registry
from .c0_scorer import score_qualifying
from .features import ACTUALS_PATH, CIRCUIT_HISTORY_DIR
from .official_labels import OFFICIAL_LABELS_PATH


REPLAY_SCHEMA_VERSION = "qualifying.r10_c0_replay.v1"
MANIFEST_SCHEMA_VERSION = "qualifying.r10_c0_replay_manifest.v1"
TARGET_ROUND = 10
SEASON = 2026
EXPECTED_TRAINING_ROUNDS = list(range(1, TARGET_ROUND))
R10_AUDIT_PATH = Path(
    "data/official_labels/"
    "qualifying_v1_r10_official_label_audit.json"
)
R10_CIRCUIT_HISTORY_FILENAME = "r10_spa_circuit_history.json"
R10_RESULTS_FILENAME = "r10_c0_results.json"
R10_MANIFEST_FILENAME = "run_manifest.json"
R10_RANKING_FILENAME = "r10_c0_ranking.csv"

_WALK_FORWARD_MODULE_NAMES = (
    "f1_big_predictor.targets.qualifying.walk_forward",
    "f1_big_predictor.targets.qualifying.walk_forward_baselines",
    "f1_big_predictor.targets.qualifying.walk_forward_borda",
    "f1_big_predictor.targets.qualifying.walk_forward_elastic_net",
    "f1_big_predictor.targets.qualifying.walk_forward_lambdamart",
    "f1_big_predictor.targets.qualifying.walk_forward_prob",
    "f1_big_predictor.targets.qualifying.walk_forward_rating",
    "f1_big_predictor.targets.qualifying.walk_forward_ridge",
)


class OfflineCacheMissError(RuntimeError):
    """A required circuit-history request was not already archived."""


class _OfflineJolpicaAdapter:
    """Adapter stub that makes an accidental network request fail closed."""

    source_id = "jolpica"

    def fetch(self, dataset: str, params: dict[str, str]) -> Any:
        raise JolpicaFetchError(
            f"offline cache miss for Jolpica {dataset} with params {params}"
        )


def run_r10_c0_replay(
    project_root: Path,
    output_directory: Path,
) -> tuple[dict[str, Any], dict[str, Path]]:
    """Run all frozen candidates for R10 and write reproducible artifacts.

    ``output_directory`` is intentionally outside the tracked evidence inputs.
    Existing files are replaced only by the same named run artifacts; no raw or
    processed project data is written.
    """

    project_root = project_root.resolve()
    output_directory = output_directory.resolve()
    output_directory.mkdir(parents=True, exist_ok=True)

    audit = load_r10_official_audit(project_root)
    registry = candidate_registry()
    if len(registry) != 31:
        raise ValueError(f"R10 replay requires the frozen 31-candidate roster, got {len(registry)}")

    base_snapshot = build_input_snapshot(project_root)
    circuit_history_path = output_directory / R10_CIRCUIT_HISTORY_FILENAME
    circuit_history = generate_r10_circuit_history_offline(
        project_root,
        circuit_history_path,
    )

    with temporary_r10_overlay(
        project_root=project_root,
        audit=audit,
        circuit_history_path=circuit_history_path,
    ) as overlay:
        with extended_walk_forward_round_limit(TARGET_ROUND):
            candidate_results = [
                replay_candidate_r10(spec, overlay.root, audit) for spec in registry
            ]

    summary = build_replay_summary(candidate_results, audit)
    input_snapshot = {
        "base_c0_input_snapshot": base_snapshot,
        "r10_official_audit": _file_record(project_root, R10_AUDIT_PATH),
        "r10_entry_list": dict(audit["entry_list_source"]),
        "r10_final_qualifying_classification": dict(audit["classification_source"]),
        "r10_structured_crosscheck": dict(audit["structured_crosscheck_source"]),
        "r10_circuit_history": {
            "path": circuit_history_path.name,
            "sha256": _sha256_file(circuit_history_path),
            "matched_historical_event_count": len(
                circuit_history["matched_historical_events"]
            ),
            "skipped_historical_event_count": len(
                circuit_history["skipped_historical_events"]
            ),
        },
        "temporary_overlay_actuals_sha256": overlay.actuals_sha256,
    }
    results = {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "target_id": "qualifying",
        "season": SEASON,
        "target_round": TARGET_ROUND,
        "race_name": audit["race_name"],
        "run_purpose": "post_event_as_of_r09_single_round_replay_not_production_prediction",
        "cutoff_semantics": {
            "training_rounds": EXPECTED_TRAINING_ROUNDS,
            "target_field": "FIA R10 entry-list universe only",
            "target_result": "FIA final qualifying classification used only after each prediction",
            "r10_openf1_practice_weather_race_data_used_as_model_input": False,
            "r10_agent_evidence_available": False,
            "prospective_evidence_claim": False,
        },
        "scoring_scheme_id": "qualifying.c0.frozen_candidate.2026-07-17",
        "official_target": {
            "field_size": audit["field_size"],
            "entry_field": audit["entry_field"],
            "official_records": audit["official_records"],
            "classification_source": audit["classification_source"],
            "entry_list_source": audit["entry_list_source"],
        },
        "candidate_registry": [spec.public_record() for spec in registry],
        "candidates": candidate_results,
        "summary": summary,
        "input_snapshot": input_snapshot,
    }
    artifact_paths = write_r10_replay_artifacts(
        project_root=project_root,
        output_directory=output_directory,
        results=results,
    )
    return results, artifact_paths


def load_r10_official_audit(project_root: Path) -> dict[str, Any]:
    """Load and fail closed on the R10 FIA-backed scoring audit."""

    path = project_root / R10_AUDIT_PATH
    payload = _load_json(path)
    validate_r10_official_audit(payload, project_root)
    return payload


def validate_r10_official_audit(payload: dict[str, Any], project_root: Path) -> None:
    """Validate the fixed R10 field, official classification, and source hashes."""

    if payload.get("schema_version") != "qualifying.r10_c0_official_label_audit.v1":
        raise ValueError("unsupported R10 official-label audit schema")
    if payload.get("season") != SEASON or payload.get("target_round") != TARGET_ROUND:
        raise ValueError("R10 official-label audit has the wrong season or round")

    field_size = payload.get("field_size")
    if isinstance(field_size, bool) or not isinstance(field_size, int) or field_size != 22:
        raise ValueError("R10 official-label audit must define the 22-driver field")

    for source_key in (
        "entry_list_source",
        "classification_source",
        "structured_crosscheck_source",
    ):
        _validate_hashed_source(project_root, payload.get(source_key), source_key)

    entry_field = payload.get("entry_field")
    official_records = payload.get("official_records")
    if not isinstance(entry_field, list) or len(entry_field) != field_size:
        raise ValueError("R10 entry field must contain every one of 22 drivers")
    if not isinstance(official_records, list) or len(official_records) != field_size:
        raise ValueError("R10 official records must cover every one of 22 drivers")

    entry_ids: list[str] = []
    for index, entry in enumerate(entry_field):
        if not isinstance(entry, dict):
            raise ValueError(f"R10 entry_field[{index}] must be an object")
        driver_id = entry.get("driver_id")
        constructor_id = entry.get("constructor_id")
        if not isinstance(driver_id, str) or not driver_id:
            raise ValueError(f"R10 entry_field[{index}] lacks a driver_id")
        if not isinstance(constructor_id, str) or not constructor_id:
            raise ValueError(f"R10 entry_field[{index}] lacks a constructor_id")
        entry_ids.append(driver_id)
    if len(set(entry_ids)) != field_size:
        raise ValueError("R10 entry field contains duplicate driver IDs")

    record_ids: list[str] = []
    positions: list[int] = []
    for index, record in enumerate(official_records):
        if not isinstance(record, dict):
            raise ValueError(f"R10 official_records[{index}] must be an object")
        driver_id = record.get("driver_id")
        position = record.get("position")
        status = record.get("classification_status")
        if not isinstance(driver_id, str) or not driver_id:
            raise ValueError(f"R10 official_records[{index}] lacks a driver_id")
        if isinstance(position, bool) or not isinstance(position, int):
            raise ValueError(f"R10 official_records[{index}] has an invalid position")
        if not isinstance(status, str) or not status:
            raise ValueError(f"R10 official_records[{index}] lacks a classification status")
        record_ids.append(driver_id)
        positions.append(position)
    if len(set(record_ids)) != field_size:
        raise ValueError("R10 official classification contains duplicate driver IDs")
    if positions != list(range(1, field_size + 1)):
        raise ValueError("R10 official classification must be ordered continuously P1-P22")
    if set(entry_ids) != set(record_ids):
        raise ValueError("R10 FIA entry field and final classification driver sets differ")

    crosscheck_path = _source_path(project_root, payload["structured_crosscheck_source"])
    raw_payload = _load_json(crosscheck_path)
    raw_results = (
        raw_payload.get("MRData", {})
        .get("RaceTable", {})
        .get("Races", [{}])[0]
        .get("QualifyingResults", [])
    )
    raw_rows = []
    for item in raw_results:
        driver_id = item.get("Driver", {}).get("driverId")
        position = _as_int(item.get("position"))
        if isinstance(driver_id, str) and position is not None:
            raw_rows.append((position, driver_id))
    raw_rows.sort()
    if [driver_id for _, driver_id in raw_rows] != record_ids:
        raise ValueError("R10 Jolpica cross-check does not match the FIA final order")


def generate_r10_circuit_history_offline(
    project_root: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Build the R10 Spa historical feature from cache only, never from network."""

    client = JolpicaClient(
        adapter=_OfflineJolpicaAdapter(),
        archive=RawArchive(project_root),
        archive_week_id="circuit_history_2026_round_10",
        reuse_any_archive=True,
    )
    try:
        payload = collect_circuit_history(
            season=SEASON,
            target_round=TARGET_ROUND,
            project_root=project_root,
            lookback_years=5,
            archive_week_id="circuit_history_2026_round_10",
            output_path=output_path,
            client=client,
        )
    except JolpicaFetchError as exc:
        raise OfflineCacheMissError(str(exc)) from exc

    if len(payload.get("matched_historical_events", [])) != 5:
        raise OfflineCacheMissError("R10 circuit history did not resolve all five archived Spa events")
    if payload.get("skipped_historical_events"):
        raise OfflineCacheMissError("R10 circuit history skipped an event in offline mode")
    if payload.get("evidence_issues"):
        raise OfflineCacheMissError("R10 circuit history has unresolved offline evidence issues")
    for event in payload["matched_historical_events"]:
        for dataset in event.get("datasets", {}).values():
            if dataset.get("status") == "error":
                raise OfflineCacheMissError("R10 circuit history encountered a cache miss")
    if len(payload.get("driver_history_scores", [])) != 22:
        raise ValueError("R10 circuit history must contain 22 current drivers")
    return payload


@contextmanager
def temporary_r10_overlay(
    *,
    project_root: Path,
    audit: dict[str, Any],
    circuit_history_path: Path,
) -> Iterator["ReplayOverlay"]:
    """Construct a minimal temporary project root with a synthetic R10 target row."""

    with tempfile.TemporaryDirectory(prefix="f1-r10-c0-overlay-") as temporary_directory:
        overlay_root = Path(temporary_directory)
        actuals_payload = _load_json(project_root / ACTUALS_PATH)
        rounds = list(actuals_payload.get("completed_rounds", []))
        round_numbers = [int(item["round"]) for item in rounds]
        if round_numbers != EXPECTED_TRAINING_ROUNDS:
            raise ValueError("R10 replay requires source actuals to contain exactly R01-R09")
        actuals_payload["completed_rounds"] = [
            *rounds,
            build_r10_target_event(audit),
        ]
        overlay_actuals_path = overlay_root / ACTUALS_PATH
        overlay_actuals_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(overlay_actuals_path, actuals_payload)

        _link(overlay_root / "data/manual", project_root / "data/manual")
        labels_destination = overlay_root / OFFICIAL_LABELS_PATH
        _link(labels_destination, project_root / OFFICIAL_LABELS_PATH)

        source_history_directory = project_root / CIRCUIT_HISTORY_DIR
        target_history_directory = overlay_root / CIRCUIT_HISTORY_DIR
        target_history_directory.mkdir(parents=True, exist_ok=True)
        for source_path in sorted(source_history_directory.glob("*.json")):
            _link(target_history_directory / source_path.name, source_path)
        _link(
            target_history_directory / "round_10_belgian_grand_prix.json",
            circuit_history_path,
        )

        yield ReplayOverlay(
            root=overlay_root,
            actuals_sha256=_sha256_file(overlay_actuals_path),
        )


def build_r10_target_event(audit: dict[str, Any]) -> dict[str, Any]:
    """Create the target-round schema row without adding R10 data to training."""

    positions = {
        str(record["driver_id"]): int(record["position"])
        for record in audit["official_records"]
    }
    records = [
        {
            "driver_id": entry["driver_id"],
            "driver_name": entry["display_name"],
            "constructor_id": entry["constructor_id"],
            "position": positions[entry["driver_id"]],
            "classification_status": "classified",
        }
        for entry in audit["entry_field"]
    ]
    return {
        "round": TARGET_ROUND,
        "race_name": audit["race_name"],
        "circuit_id": audit["circuit_id"],
        "circuit_name": "Circuit de Spa-Francorchamps",
        "race_date": "2026-07-19",
        "qualifying_results": {
            "status": "ok",
            "records": records,
            "row_count": len(records),
            "field_size": audit["field_size"],
            "official_verification_status": "r10_replay_score_after_prediction",
        },
        "race_results": {"status": "not_loaded_for_qualifying_replay", "records": []},
        "driver_standings": {"status": "not_loaded_for_qualifying_replay", "records": []},
        "constructor_standings": {"status": "not_loaded_for_qualifying_replay", "records": []},
        "sprint_qualifying": {"status": "not_applicable", "records": []},
        "sprint_results": {"status": "not_applicable", "records": []},
    }


@contextmanager
def extended_walk_forward_round_limit(target_round: int) -> Iterator[None]:
    """Temporarily expose one target round to existing frozen runners."""

    modules = [importlib.import_module(name) for name in _WALK_FORWARD_MODULE_NAMES]
    previous_limits: list[tuple[Any, int]] = []
    for module in modules:
        current = getattr(module, "LAST_WALK_FORWARD_ROUND", None)
        if current != 9:
            raise RuntimeError(
                f"{module.__name__} no longer has the frozen R09 walk-forward limit"
            )
        previous_limits.append((module, current))

    try:
        for module, _ in previous_limits:
            module.LAST_WALK_FORWARD_ROUND = target_round
        yield
    finally:
        for module, previous in previous_limits:
            module.LAST_WALK_FORWARD_ROUND = previous


def replay_candidate_r10(
    spec: CandidateSpec,
    overlay_root: Path,
    audit: dict[str, Any],
) -> dict[str, Any]:
    """Run one frozen candidate and score its R10 Top 10 after prediction."""

    public_record = spec.public_record()
    try:
        history = spec.runner(overlay_root)
        round_result = _round_result(history, TARGET_ROUND)
        prediction = list(round_result.get("top10_predicted_driver_ids") or [])
        _validate_prediction(prediction, audit)

        reported_training = round_result.get("training_rounds")
        if reported_training is not None:
            normalized_training = [int(value) for value in reported_training]
            if normalized_training != EXPECTED_TRAINING_ROUNDS:
                raise ValueError(
                    "candidate reported target-round training outside R01-R09: "
                    f"{normalized_training}"
                )

        c0 = score_qualifying(
            prediction,
            audit["official_records"],
            int(audit["field_size"]),
        )
        return {
            **public_record,
            "status": "completed",
            "failure": None,
            "training_rounds": EXPECTED_TRAINING_ROUNDS,
            "runner_reported_training_rounds": reported_training,
            "prediction_top10": prediction,
            "full_field_predicted_driver_ids": list(
                round_result.get("full_field_predicted_driver_ids") or []
            ),
            "prediction_status": round_result.get("prediction_status"),
            "prediction_evidence_gaps": list(
                round_result.get("prediction_evidence_gaps") or []
            ),
            "runner_evidence_gaps": list(history.get("evidence_gaps") or []),
            "c0": c0,
        }
    except Exception as exc:
        return {
            **public_record,
            "status": "failed",
            "failure": {"type": type(exc).__name__, "message": str(exc)},
            "training_rounds": EXPECTED_TRAINING_ROUNDS,
            "runner_reported_training_rounds": None,
            "prediction_top10": None,
            "full_field_predicted_driver_ids": [],
            "prediction_status": None,
            "prediction_evidence_gaps": [],
            "runner_evidence_gaps": [],
            "c0": None,
        }


def build_replay_summary(
    candidates: Sequence[dict[str, Any]],
    audit: dict[str, Any],
) -> dict[str, Any]:
    """Create ranking and consensus summaries without selecting a new champion."""

    completed = [item for item in candidates if item["status"] == "completed"]
    failed = [item for item in candidates if item["status"] == "failed"]
    score_rows = sorted(
        (
            {
                "ordinal": item["ordinal"],
                "candidate_id": item["candidate_id"],
                "model_id": item["model_id"],
                "variant": item["variant"],
                "overall_c0_score": _overall_score(item),
                "exact_hit_count": int(item["c0"]["exact"]["exact_hit_count"]),
                "top10_membership_score": float(
                    item["c0"]["membership"]["top10_set_score"]
                ),
                "mean_rank_distance": float(
                    item["c0"]["distance"]["mean_rank_distance"]
                ),
            }
            for item in completed
        ),
        key=lambda item: (-item["overall_c0_score"], item["ordinal"]),
    )
    for index, row in enumerate(score_rows, start=1):
        row["rank"] = index

    scores = [row["overall_c0_score"] for row in score_rows]
    official_positions = {
        str(record["driver_id"]): int(record["position"])
        for record in audit["official_records"]
    }
    names = {
        str(entry["driver_id"]): str(entry["display_name"])
        for entry in audit["entry_field"]
    }
    inclusion_counts: Counter[str] = Counter()
    positions_by_driver: dict[str, list[int]] = {}
    position_votes: dict[int, Counter[str]] = {
        position: Counter() for position in range(1, 11)
    }
    for candidate in completed:
        for position, driver_id in enumerate(candidate["prediction_top10"], start=1):
            inclusion_counts[driver_id] += 1
            positions_by_driver.setdefault(driver_id, []).append(position)
            position_votes[position][driver_id] += 1

    inclusion_summary = [
        {
            "driver_id": driver_id,
            "display_name": names.get(driver_id, driver_id),
            "predicted_top10_count": count,
            "predicted_top10_share": round(count / len(completed), 6)
            if completed
            else 0.0,
            "mean_predicted_position": round(
                sum(positions_by_driver[driver_id]) / len(positions_by_driver[driver_id]),
                6,
            ),
            "official_position": official_positions[driver_id],
        }
        for driver_id, count in sorted(
            inclusion_counts.items(),
            key=lambda item: (-item[1], sum(positions_by_driver[item[0]]) / len(positions_by_driver[item[0]]), item[0]),
        )
    ]
    position_consensus = []
    for position, votes in position_votes.items():
        max_count = max(votes.values(), default=0)
        leaders = sorted(driver_id for driver_id, count in votes.items() if count == max_count)
        position_consensus.append(
            {
                "predicted_position": position,
                "leader_driver_ids": leaders,
                "leader_display_names": [names.get(driver_id, driver_id) for driver_id in leaders],
                "leader_vote_count": max_count,
                "leader_vote_share": round(max_count / len(completed), 6)
                if completed
                else 0.0,
                "official_driver_id": next(
                    driver_id
                    for driver_id, official_position in official_positions.items()
                    if official_position == position
                ),
            }
        )

    return {
        "candidate_count": len(candidates),
        "completed_candidate_count": len(completed),
        "failed_candidate_count": len(failed),
        "failed_candidate_ids": [item["candidate_id"] for item in failed],
        "score_ranking": score_rows,
        "score_distribution": {
            "maximum": max(scores) if scores else None,
            "median": _median(scores),
            "minimum": min(scores) if scores else None,
            "mean": round(sum(scores) / len(scores), 10) if scores else None,
        },
        "top10_inclusion_consensus": inclusion_summary,
        "position_consensus": position_consensus,
    }


def write_r10_replay_artifacts(
    *,
    project_root: Path,
    output_directory: Path,
    results: dict[str, Any],
) -> dict[str, Path]:
    """Write the machine-readable results, a concise CSV, and a provenance manifest."""

    results_path = output_directory / R10_RESULTS_FILENAME
    results_bytes = _pretty_json(results).encode("utf-8")
    results_path.write_bytes(results_bytes)

    ranking_path = output_directory / R10_RANKING_FILENAME
    ranking_path.write_text(_ranking_csv(results), encoding="utf-8")

    status = _git_output(project_root, "status", "--porcelain", "--untracked-files=normal")
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "code_commit": _git_output(project_root, "rev-parse", "HEAD"),
        "working_tree_clean": not bool(status),
        "working_tree_status": status.splitlines(),
        "results_path": results_path.name,
        "results_sha256": hashlib.sha256(results_bytes).hexdigest(),
        "ranking_path": ranking_path.name,
        "ranking_sha256": _sha256_file(ranking_path),
        "circuit_history_path": R10_CIRCUIT_HISTORY_FILENAME,
        "circuit_history_sha256": results["input_snapshot"]["r10_circuit_history"]["sha256"],
        "candidate_count": results["summary"]["candidate_count"],
        "completed_candidate_count": results["summary"]["completed_candidate_count"],
        "failed_candidate_count": results["summary"]["failed_candidate_count"],
        "network_access": "disabled_by_offline_jolpica_adapter_for_circuit_history",
        "cutoff_semantics": results["cutoff_semantics"],
    }
    manifest_path = output_directory / R10_MANIFEST_FILENAME
    manifest_path.write_text(_pretty_json(manifest), encoding="utf-8")
    return {
        "results": results_path,
        "ranking": ranking_path,
        "manifest": manifest_path,
        "circuit_history": output_directory / R10_CIRCUIT_HISTORY_FILENAME,
    }


def _round_result(history: dict[str, Any], round_number: int) -> dict[str, Any]:
    per_round = history.get("per_round")
    if not isinstance(per_round, list):
        raise ValueError("candidate runner must return a per_round list")
    matches = [item for item in per_round if int(item.get("round", -1)) == round_number]
    if len(matches) != 1:
        raise ValueError(f"candidate runner must emit exactly one R{round_number:02d} result")
    if not isinstance(matches[0], dict):
        raise ValueError("candidate R10 result must be an object")
    return matches[0]


def _validate_prediction(prediction: list[str], audit: dict[str, Any]) -> None:
    if len(prediction) != 10:
        raise ValueError(f"candidate R10 prediction must contain exactly 10 drivers, got {len(prediction)}")
    if len(set(prediction)) != len(prediction):
        raise ValueError("candidate R10 prediction contains duplicate drivers")
    field = {str(entry["driver_id"]) for entry in audit["entry_field"]}
    unknown = [driver_id for driver_id in prediction if driver_id not in field]
    if unknown:
        raise ValueError("candidate R10 prediction contains drivers outside the FIA field: " + ", ".join(unknown))


def _overall_score(candidate: dict[str, Any]) -> float:
    return float(candidate["c0"]["overall_candidate"]["overall_candidate_score"])


def _ranking_csv(results: dict[str, Any]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=(
            "rank",
            "ordinal",
            "candidate_id",
            "model_id",
            "variant",
            "overall_c0_score",
            "exact_hit_count",
            "top10_membership_score",
            "mean_rank_distance",
        ),
    )
    writer.writeheader()
    writer.writerows(results["summary"]["score_ranking"])
    return output.getvalue()


def _validate_hashed_source(
    project_root: Path,
    source: Any,
    source_key: str,
) -> None:
    if not isinstance(source, dict):
        raise ValueError(f"R10 audit {source_key} must be an object")
    if not isinstance(source.get("url"), str) or not source["url"]:
        raise ValueError(f"R10 audit {source_key} lacks a URL")
    expected_sha = source.get("sha256")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise ValueError(f"R10 audit {source_key} lacks a SHA-256")
    path = _source_path(project_root, source)
    if not path.is_file():
        raise FileNotFoundError(f"R10 audit {source_key} source is missing: {path}")
    actual_sha = _sha256_file(path)
    if actual_sha != expected_sha:
        raise ValueError(
            f"R10 audit {source_key} SHA-256 mismatch: expected {expected_sha}, got {actual_sha}"
        )


def _source_path(project_root: Path, source: dict[str, Any]) -> Path:
    raw_path = source.get("raw_path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("R10 audit source lacks a relative raw_path")
    relative_path = Path(raw_path)
    if relative_path.is_absolute():
        raise ValueError("R10 audit raw_path must be relative to the project root")
    resolved = (project_root / relative_path).resolve()
    try:
        resolved.relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError("R10 audit raw_path escapes the project root") from exc
    return resolved


def _file_record(project_root: Path, relative_path: Path) -> dict[str, str]:
    path = project_root / relative_path
    return {"path": relative_path.as_posix(), "sha256": _sha256_file(path)}


def _link(destination: Path, source: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(source.resolve())


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(_pretty_json(payload), encoding="utf-8")


def _pretty_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return round((ordered[midpoint - 1] + ordered[midpoint]) / 2, 10)


def _git_output(project_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(project_root), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout.strip()


class ReplayOverlay:
    """Metadata needed after the temporary overlay directory is cleaned up."""

    def __init__(self, *, root: Path, actuals_sha256: str) -> None:
        self.root = root
        self.actuals_sha256 = actuals_sha256
