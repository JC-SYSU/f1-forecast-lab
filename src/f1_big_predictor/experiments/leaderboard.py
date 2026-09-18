from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .run_manifest import (
    reject_legacy_references,
    target_run_dir,
    validate_target_id,
    validate_target_scoped_id,
    validate_model_id,
    validate_run_id,
)


METRIC_ORDER = {
    "race": (("top10_position_accuracy", "desc"), ("rank_mae", "asc")),
    "sprint_race": (("top10_position_accuracy", "desc"), ("rank_mae", "asc")),
    "qualifying": (("top10_position_accuracy", "desc"), ("rank_mae", "asc"), ("lap_time_mae", "asc")),
    "sprint_qualifying": (("top10_position_accuracy", "desc"), ("rank_mae", "asc"), ("lap_time_mae", "asc")),
}


@dataclass(frozen=True)
class LeaderboardRow:
    target_id: str
    run_id: str
    candidate_id: str
    model_id: str
    status: str
    metrics: dict[str, float]
    evidence_gaps: list[str]
    config_hash: str


def sort_leaderboard(target_id: str, rows: list[LeaderboardRow]) -> list[LeaderboardRow]:
    validated_target_id = validate_target_id(target_id)
    for row in rows:
        if row.target_id != validated_target_id:
            raise ValueError("leaderboard rows must not mix target_id values")
        validate_run_id(row.run_id)
        validate_model_id(validated_target_id, row.model_id)
        validate_target_scoped_id(validated_target_id, row.candidate_id, "candidate_id")
        reject_legacy_references(asdict(row))
        for metric_name, _direction in METRIC_ORDER[validated_target_id]:
            if metric_name not in row.metrics:
                raise ValueError(f"missing leaderboard metric for {validated_target_id}: {metric_name}")
    return sorted(rows, key=lambda row: _sort_key(validated_target_id, row))


def write_leaderboard(
    *,
    project_root: Path,
    target_id: str,
    run_id: str,
    rows: list[LeaderboardRow],
    overwrite: bool = False,
) -> tuple[Path, Path]:
    sorted_rows = sort_leaderboard(target_id, rows)
    for row in sorted_rows:
        if row.run_id != run_id:
            raise ValueError("leaderboard row run_id must match output run_id")
    run_dir = target_run_dir(project_root, target_id, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    json_path = run_dir / "leaderboard.json"
    csv_path = run_dir / "leaderboard.csv"
    if not overwrite and (json_path.exists() or csv_path.exists()):
        raise FileExistsError(f"leaderboard already exists under: {run_dir}")
    payload = [asdict(row) for row in sorted_rows]
    reject_legacy_references(payload)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["target_id", "run_id", "candidate_id", "model_id", "status", "config_hash", "metrics", "evidence_gaps"],
        )
        writer.writeheader()
        for row in sorted_rows:
            writer.writerow(
                {
                    "target_id": row.target_id,
                    "run_id": row.run_id,
                    "candidate_id": row.candidate_id,
                    "model_id": row.model_id,
                    "status": row.status,
                    "config_hash": row.config_hash,
                    "metrics": json.dumps(row.metrics, sort_keys=True),
                    "evidence_gaps": json.dumps(row.evidence_gaps, sort_keys=True),
                }
            )
    return json_path, csv_path


def _sort_key(target_id: str, row: LeaderboardRow) -> tuple[float, ...]:
    values: list[float] = []
    for metric_name, direction in METRIC_ORDER[target_id]:
        value = float(row.metrics[metric_name])
        values.append(-value if direction == "desc" else value)
    return tuple(values)
