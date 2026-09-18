from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .run_manifest import (
    SCHEMA_VERSION,
    reject_legacy_references,
    target_run_dir,
    validate_run_manifest,
    validate_feature_set_id,
    validate_model_id,
    validate_output_files,
    validate_run_id,
    validate_search_space_id,
    validate_target_id,
)


@dataclass(frozen=True)
class AuditIssue:
    severity: str
    code: str
    field_path: str
    message: str


@dataclass(frozen=True)
class AuditReport:
    target_id: str
    run_id: str
    ok: bool
    issues: list[AuditIssue]


def audit_manifest(manifest: dict[str, Any]) -> AuditReport:
    target_id = str(manifest.get("target_id", ""))
    run_id = str(manifest.get("run_id", ""))
    issues: list[AuditIssue] = []
    _capture(issues, "schema_version", lambda: _require_equal(manifest.get("schema_version"), SCHEMA_VERSION, "schema_version"))
    _capture(issues, "target_id", lambda: validate_target_id(target_id))
    _capture(issues, "run_id", lambda: validate_run_id(run_id))
    _capture(issues, "model_id", lambda: validate_model_id(target_id, str(manifest.get("model_id", ""))))
    _capture(issues, "feature_set_id", lambda: validate_feature_set_id(target_id, str(manifest.get("feature_set_id", ""))))
    _capture(issues, "search_space_id", lambda: validate_search_space_id(target_id, manifest.get("search_space_id")))
    _capture(issues, "output_files", lambda: _validate_manifest_output_files(manifest))
    _capture(issues, "$", lambda: reject_legacy_references(manifest))
    return AuditReport(target_id=target_id, run_id=run_id, ok=not issues, issues=issues)


def audit_run_dir(project_root: Path, target_id: str, run_id: str) -> AuditReport:
    issues: list[AuditIssue] = []
    try:
        run_dir = target_run_dir(project_root, target_id, run_id)
    except ValueError as error:
        return AuditReport(target_id=target_id, run_id=run_id, ok=False, issues=[_issue("critical", "invalid_run_path", "run_dir", str(error))])
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        return AuditReport(target_id=target_id, run_id=run_id, ok=False, issues=[_issue("critical", "missing_manifest", "run_manifest.json", "run manifest is required")])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("target_id") != target_id:
        issues.append(_issue("critical", "path_target_mismatch", "target_id", "manifest target_id must match its run directory"))
    if manifest.get("run_id") != run_id:
        issues.append(_issue("critical", "path_run_mismatch", "run_id", "manifest run_id must match its run directory"))
    report = audit_manifest(manifest)
    issues.extend(report.issues)
    try:
        validate_run_manifest(manifest)
    except ValueError:
        return AuditReport(target_id=target_id, run_id=run_id, ok=False, issues=issues)
    for item in manifest.get("output_files", []):
        artifact = run_dir / item
        if not artifact.exists():
            issues.append(_issue("major", "missing_output_file", f"output_files.{item}", "listed output file is missing"))
    return AuditReport(target_id=target_id, run_id=run_id, ok=not issues, issues=issues)


def write_audit_report(
    *,
    project_root: Path,
    report: AuditReport,
    round_id: str = "review_round_1",
    overwrite: bool = False,
) -> Path:
    run_dir = target_run_dir(project_root, report.target_id, report.run_id)
    validate_run_id(round_id)
    audit_dir = run_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"{round_id}.md"
    if path.exists() and not overwrite:
        raise FileExistsError(f"audit report already exists: {path}")
    lines = [f"# Audit {report.target_id}/{report.run_id}", "", f"Status: {'PASS' if report.ok else 'FAIL'}", ""]
    if report.issues:
        lines.append("## Issues")
        for item in report.issues:
            lines.append(f"- {item.severity} {item.code} {item.field_path}: {item.message}")
    else:
        lines.append("No issues found.")
    text = "\n".join(lines) + "\n"
    reject_legacy_references(text)
    path.write_text(text, encoding="utf-8")
    return path


def _capture(issues: list[AuditIssue], field_path: str, action: Callable[[], object]) -> None:
    try:
        action()
    except (TypeError, ValueError) as error:
        issues.append(_issue("critical", "invalid_manifest_field", field_path, str(error)))


def _require_equal(left: object, right: object, field_path: str) -> None:
    if left != right:
        raise ValueError(f"{field_path} must be {right}")


def _issue(severity: str, code: str, field_path: str, message: str) -> AuditIssue:
    return AuditIssue(severity=severity, code=code, field_path=field_path, message=message)


def _validate_manifest_output_files(manifest: dict[str, Any]) -> None:
    output_files = manifest.get("output_files")
    if not isinstance(output_files, list) or not all(isinstance(item, str) for item in output_files):
        raise ValueError("output_files must be a string list")
    validate_output_files(output_files)
