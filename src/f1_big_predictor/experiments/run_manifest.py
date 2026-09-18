from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "target_run_manifest.v1"
TARGET_IDS = frozenset({"sprint_qualifying", "sprint_race", "qualifying", "race"})
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def validate_target_id(target_id: str) -> str:
    if target_id not in TARGET_IDS:
        raise ValueError(f"unsupported target_id: {target_id}")
    return target_id


def validate_run_id(run_id: str) -> str:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(f"invalid run_id: {run_id}")
    if run_id in {".", ".."} or "/" in run_id or "\\" in run_id:
        raise ValueError(f"invalid run_id: {run_id}")
    return run_id


def validate_model_id(target_id: str, model_id: str) -> str:
    return validate_target_scoped_id(target_id, model_id, "model_id")


def validate_feature_set_id(target_id: str, feature_set_id: str) -> str:
    return validate_target_scoped_id(target_id, feature_set_id, "feature_set_id")


def validate_search_space_id(target_id: str, search_space_id: str | None) -> str | None:
    if search_space_id is None:
        return None
    return validate_target_scoped_id(target_id, search_space_id, "search_space_id")


def validate_target_scoped_id(target_id: str, value: str, field_name: str) -> str:
    validate_target_id(target_id)
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    if not value.startswith(f"{target_id}."):
        raise ValueError(f"{field_name} must be target-scoped for {target_id}: {value}")
    reject_legacy_references(value)
    return value


def validate_output_files(output_files: list[str]) -> list[str]:
    for item in output_files:
        reject_legacy_references(item)
        path = Path(item)
        if not item or path.is_absolute() or "\\" in item or any(part in {".", ".."} for part in path.parts):
            raise ValueError(f"output file must be a relative run artifact path: {item}")
    return output_files


def target_run_dir(project_root: Path, target_id: str, run_id: str) -> Path:
    return (
        project_root
        / "outputs"
        / "experiments"
        / validate_target_id(target_id)
        / validate_run_id(run_id)
    )


def config_hash(model_config: dict[str, Any]) -> str:
    payload = json.dumps(model_config, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def build_run_manifest(
    *,
    run_id: str,
    target_id: str,
    model_id: str,
    model_config: dict[str, Any],
    feature_set_id: str,
    search_space_id: str | None,
    as_of_profile: dict[str, Any],
    evaluation_window: dict[str, Any],
    input_assets: list[dict[str, Any]],
    output_files: list[str],
    evidence_gaps: list[str],
    validation_commands: list[str],
) -> dict[str, Any]:
    validated_target_id = validate_target_id(target_id)
    reject_legacy_references(model_config)
    reject_legacy_references(as_of_profile)
    reject_legacy_references(evaluation_window)
    _validate_as_of_profile(as_of_profile)
    _validate_evaluation_window(evaluation_window)
    reject_legacy_references(input_assets)
    reject_legacy_references(evidence_gaps)
    reject_legacy_references(validation_commands)
    validated_output_files = validate_output_files(output_files)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": validate_run_id(run_id),
        "target_id": validated_target_id,
        "model_id": validate_model_id(validated_target_id, model_id),
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "config_hash": config_hash(model_config),
        "model_config": model_config,
        "feature_set_id": validate_feature_set_id(validated_target_id, feature_set_id),
        "search_space_id": validate_search_space_id(validated_target_id, search_space_id),
        "as_of_profile": as_of_profile,
        "evaluation_window": evaluation_window,
        "input_assets": input_assets,
        "output_files": validated_output_files,
        "evidence_gaps": evidence_gaps,
        "validation_commands": validation_commands,
    }


def write_run_manifest(
    *,
    project_root: Path,
    manifest: dict[str, Any],
    overwrite: bool = False,
) -> Path:
    manifest = validate_run_manifest(manifest)
    run_dir = target_run_dir(
        project_root,
        str(manifest.get("target_id")),
        str(manifest.get("run_id")),
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "run_manifest.json"
    if path.exists() and not overwrite:
        raise FileExistsError(f"run manifest already exists: {path}")
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def validate_run_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")
    target_id = validate_target_id(str(manifest.get("target_id")))
    validate_run_id(str(manifest.get("run_id")))
    validate_model_id(target_id, str(manifest.get("model_id", "")))
    validate_feature_set_id(target_id, str(manifest.get("feature_set_id", "")))
    validate_search_space_id(target_id, manifest.get("search_space_id"))
    if not isinstance(manifest.get("model_config"), dict):
        raise ValueError("model_config must be an object")
    if not isinstance(manifest.get("as_of_profile"), dict):
        raise ValueError("as_of_profile must be an object")
    _validate_as_of_profile(manifest["as_of_profile"])
    if not isinstance(manifest.get("evaluation_window"), dict):
        raise ValueError("evaluation_window must be an object")
    _validate_evaluation_window(manifest["evaluation_window"])
    if not isinstance(manifest.get("input_assets"), list):
        raise ValueError("input_assets must be a list")
    output_files = manifest.get("output_files")
    if not isinstance(output_files, list) or not all(isinstance(item, str) for item in output_files):
        raise ValueError("output_files must be a string list")
    validate_output_files(output_files)
    if not isinstance(manifest.get("evidence_gaps"), list):
        raise ValueError("evidence_gaps must be a list")
    if not isinstance(manifest.get("validation_commands"), list):
        raise ValueError("validation_commands must be a list")
    reject_legacy_references(manifest)
    return manifest


def reject_legacy_references(value: Any) -> None:
    text = json.dumps(value, sort_keys=True, ensure_ascii=True, default=str) if not isinstance(value, str) else value
    forbidden = (
        "model_" "v1.",
        "baseline_" "2026_v0",
        "rolling_" "review",
        "outputs/" "model_iterations",
        "race_" "only",
        "race-" "only",
        "baseline-" "scoreboard",
        "weight-" "calibration",
        "single-round-" "parameter-scan",
        "promotion" " review",
        "contest" " rules",
        "f1_big_predictor." "legacy",
        "f1_big_predictor." "event_predictor",
        "f1_big_predictor." "backtesting",
        "f1_big_predictor." "race_predictor",
        "outputs/" "backtests",
        "backtest-" "race",
        "backtest-" "weekend",
        "tests/" "legacy",
        "CURRENT_" "MODEL_VERSION",
        "CURRENT_" "MODEL_CONFIG",
        "REFERENCE_" "MODEL_VERSION",
        "SUPPORTED_" "BASE_MODELS",
    )
    for item in forbidden:
        if item in text:
            raise ValueError(f"legacy reference is not allowed in target run manifest: {item}")


_reject_legacy_references = reject_legacy_references


def _validate_as_of_profile(as_of_profile: dict[str, Any]) -> None:
    if not as_of_profile.get("as_of"):
        raise ValueError("as_of_profile.as_of is required")


def _validate_evaluation_window(evaluation_window: dict[str, Any]) -> None:
    rounds = evaluation_window.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        raise ValueError("evaluation_window.rounds must be a non-empty list")
