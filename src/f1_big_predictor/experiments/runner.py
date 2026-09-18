from __future__ import annotations

import json
import csv
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Callable

from .run_manifest import (
    build_run_manifest,
    reject_legacy_references,
    target_run_dir,
    validate_output_files,
    validate_search_space_id,
    validate_target_id,
    validate_feature_set_id,
    validate_model_id,
    validate_run_id,
    write_run_manifest,
)
from .audit import audit_manifest, write_audit_report
from .leaderboard import write_leaderboard


@dataclass(frozen=True)
class TargetRunSpec:
    project_root: Path
    target_id: str
    run_id: str
    model_id: str
    model_config: dict[str, Any]
    feature_set_id: str
    search_space_id: str | None
    as_of_profile: dict[str, Any]
    evaluation_window: dict[str, Any]
    input_assets: list[dict[str, Any]]
    validation_commands: list[str]


@dataclass(frozen=True)
class TargetRunResult:
    target_id: str
    run_id: str
    run_dir: Path
    manifest_path: Path
    output_files: list[str]


def run_target(
    *,
    spec: TargetRunSpec,
    predict_fn: Callable[..., Any],
    inputs: Any,
    config: Any,
    search_space: dict[str, Any],
    render_report_fn: Callable[[Any], str] | None = None,
    overwrite: bool = False,
) -> TargetRunResult:
    target_id = validate_target_id(spec.target_id)
    run_id = validate_run_id(spec.run_id)
    validate_model_id(target_id, spec.model_id)
    validate_feature_set_id(target_id, spec.feature_set_id)
    validate_search_space_id(target_id, spec.search_space_id)
    _validate_search_space(target_id, search_space)

    prediction = predict_fn(inputs=inputs, config=config)
    prediction_payload = _to_payload(prediction)
    if prediction_payload.get("target_id") != target_id:
        raise ValueError("prediction target_id does not match run spec")
    if prediction_payload.get("model_id") != spec.model_id:
        raise ValueError("prediction model_id does not match run spec")

    run_dir = target_run_dir(spec.project_root, target_id, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    output_files = [
        "prediction.json",
        "target_config.json",
        "feature_versions.json",
        "search_space.json",
        "leaderboard.csv",
        "leaderboard.json",
        "per_round_metrics.csv",
        "report.md",
        "audit/review_round_1.md",
        "audit/review_round_2.md",
    ]
    validate_output_files(output_files)
    _ensure_run_files_can_write(run_dir, [*output_files, "run_manifest.json"], overwrite=overwrite)

    _write_json(run_dir / "target_config.json", _to_payload(config), overwrite=overwrite)
    _write_json(
        run_dir / "feature_versions.json",
        {"target_id": target_id, "feature_set_id": spec.feature_set_id},
        overwrite=overwrite,
    )
    _write_json(run_dir / "search_space.json", search_space, overwrite=overwrite)
    write_leaderboard(project_root=spec.project_root, target_id=target_id, run_id=run_id, rows=[], overwrite=overwrite)
    _write_per_round_metrics(run_dir / "per_round_metrics.csv", target_id, run_id, spec.evaluation_window, overwrite=overwrite)
    report_text = render_report_fn(prediction) if render_report_fn is not None else f"# {target_id} {run_id}\n\nStatus: {prediction_payload.get('status')}\n"
    _write_text(run_dir / "report.md", report_text, overwrite=overwrite)

    manifest = build_run_manifest(
        run_id=run_id,
        target_id=target_id,
        model_id=spec.model_id,
        model_config=spec.model_config,
        feature_set_id=spec.feature_set_id,
        search_space_id=spec.search_space_id,
        as_of_profile=spec.as_of_profile,
        evaluation_window=spec.evaluation_window,
        input_assets=spec.input_assets,
        output_files=output_files,
        evidence_gaps=list(prediction_payload.get("evidence_gaps", [])),
        validation_commands=spec.validation_commands,
    )
    manifest_path = write_run_manifest(project_root=spec.project_root, manifest=manifest, overwrite=overwrite)
    prediction_payload = {
        **prediction_payload,
        "as_of": spec.as_of_profile["as_of"],
        "run_manifest_path": str(manifest_path),
    }
    _write_json(run_dir / "prediction.json", prediction_payload, overwrite=overwrite)
    audit_report = audit_manifest(manifest)
    write_audit_report(project_root=spec.project_root, report=audit_report, round_id="review_round_1", overwrite=overwrite)
    write_audit_report(project_root=spec.project_root, report=audit_report, round_id="review_round_2", overwrite=overwrite)
    return TargetRunResult(target_id=target_id, run_id=run_id, run_dir=run_dir, manifest_path=manifest_path, output_files=output_files)


def _validate_search_space(target_id: str, search_space: dict[str, Any]) -> None:
    reject_legacy_references(search_space)
    if search_space.get("target_id") != target_id:
        raise ValueError("search_space target_id does not match run spec")


def _to_payload(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def _write_json(path: Path, payload: Any, *, overwrite: bool) -> None:
    reject_legacy_references(payload)
    if path.exists() and not overwrite:
        raise FileExistsError(f"run artifact already exists: {path}")
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ensure_run_files_can_write(run_dir: Path, output_files: list[str], *, overwrite: bool) -> None:
    if overwrite:
        return
    for item in output_files:
        path = run_dir / item
        if path.exists():
            raise FileExistsError(f"run artifact already exists: {path}")


def _write_text(path: Path, text: str, *, overwrite: bool) -> None:
    reject_legacy_references(text)
    if path.exists() and not overwrite:
        raise FileExistsError(f"run artifact already exists: {path}")
    path.write_text(text, encoding="utf-8")


def _write_per_round_metrics(path: Path, target_id: str, run_id: str, evaluation_window: dict[str, Any], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"run artifact already exists: {path}")
    rounds = evaluation_window.get("rounds", [])
    if not isinstance(rounds, list):
        raise ValueError("evaluation_window.rounds must be a list when provided")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["target_id", "run_id", "event_round", "status"])
        writer.writeheader()
        for event_round in rounds:
            writer.writerow({"target_id": target_id, "run_id": run_id, "event_round": event_round, "status": "not_evaluated"})
