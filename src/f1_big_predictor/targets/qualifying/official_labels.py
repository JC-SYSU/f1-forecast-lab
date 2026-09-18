"""Status-aware official qualifying labels for historical development runs."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any


ACTUALS_PATH = Path("data/processed/season_2026_actuals/actuals.json")
OFFICIAL_LABELS_PATH = Path(
    "docs/data_and_evidence/qualifying/official_labels/"
    "qualifying_v1_official_labels_r01_r09.json"
)
_SUPPORTED_NON_NUMERIC_STATUSES = {"DSQ"}


def load_official_qualifying_labels(project_root: Path) -> dict[str, Any]:
    """Load and validate the tracked R01-R09 official-label manifest."""
    path = project_root / OFFICIAL_LABELS_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_official_qualifying_labels(payload)
    return payload


def official_records_for_round(
    project_root: Path,
    round_number: int,
    *,
    require_c0_scoreable: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """Return C0-ready official records and field size for one round."""
    manifest = load_official_qualifying_labels(project_root)
    label = _round_label(manifest, round_number)
    if require_c0_scoreable and not label["c0_scoreable"]:
        raise ValueError(
            f"R{round_number:02d} is not C0-scoreable: {label['scoreability_note']}"
        )
    return deepcopy(label["official_records"]), int(label["field_size"])


def load_officialized_actuals(project_root: Path) -> dict[str, Any]:
    """Load structured actuals and replace qualifying labels with FIA truth.

    Non-qualifying sections remain untouched. The ignored collector output is
    therefore only a feature-data container; qualifying training and scoring
    always see the tracked, status-aware official overlay.
    """
    actuals = json.loads((project_root / ACTUALS_PATH).read_text(encoding="utf-8"))
    manifest = load_official_qualifying_labels(project_root)
    return apply_official_qualifying_labels(actuals, manifest)


def apply_official_qualifying_labels(
    actuals: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Return a deep-copied actuals payload with official qualifying labels."""
    validate_official_qualifying_labels(manifest)
    result = deepcopy(actuals)
    completed = {
        int(item["round"]): item for item in result.get("completed_rounds", [])
    }

    for label in manifest["rounds"]:
        round_number = int(label["round"])
        round_payload = completed.get(round_number)
        if round_payload is None:
            raise ValueError(f"actuals missing R{round_number:02d}")

        qualifying = round_payload.setdefault("qualifying_results", {})
        collected_records = qualifying.get("records", []) or []
        collected_by_driver = {
            str(record["driver_id"]): record
            for record in collected_records
            if record.get("driver_id")
        }

        officialized_records: list[dict[str, Any]] = []
        for official in label["official_records"]:
            driver_id = str(official["driver_id"])
            if driver_id not in collected_by_driver:
                raise ValueError(
                    f"R{round_number:02d} collector actuals missing official driver {driver_id}"
                )
            record = deepcopy(collected_by_driver[driver_id])
            record["position"] = official["position"]
            record["classification_status"] = official["classification_status"]
            officialized_records.append(record)

        qualifying["records"] = officialized_records
        qualifying["row_count"] = len(officialized_records)
        qualifying["field_size"] = int(label["field_size"])
        qualifying["numeric_position_count"] = sum(
            record["position"] is not None for record in officialized_records
        )
        qualifying["non_numeric_count"] = sum(
            record["position"] is None for record in officialized_records
        )
        qualifying["official_verification_status"] = (
            "c0_scoreable" if label["c0_scoreable"] else "training_seed_only"
        )
        qualifying["official_label_round_id"] = label["round_id"]
        qualifying["official_classification_source"] = deepcopy(
            label["classification_source"]
        )
        qualifying["official_field_size_source"] = deepcopy(label["field_size_source"])

    result["qualifying_official_classification_status"] = (
        "R02-R09_c0_scoreable_R01_training_seed_only"
    )
    result["qualifying_official_label_manifest"] = str(OFFICIAL_LABELS_PATH)
    return result


def validate_official_qualifying_labels(manifest: dict[str, Any]) -> None:
    """Fail closed on malformed, incomplete, or unreviewed label branches."""
    if manifest.get("schema_version") != "qualifying.official_labels.v1":
        raise ValueError("unsupported official qualifying label schema")
    if manifest.get("season") != 2026:
        raise ValueError("official qualifying labels must be for season 2026")

    rounds = manifest.get("rounds")
    if not isinstance(rounds, list) or len(rounds) != 9:
        raise ValueError("official qualifying labels must contain R01-R09")
    round_numbers = [item.get("round") for item in rounds]
    if round_numbers != list(range(1, 10)):
        raise ValueError("official qualifying label rounds must be ordered R01-R09")

    for label in rounds:
        round_id = str(label.get("round_id"))
        field_size = label.get("field_size")
        records = label.get("official_records")
        if (
            isinstance(field_size, bool)
            or not isinstance(field_size, int)
            or field_size < 10
        ):
            raise ValueError(f"{round_id} field_size must be an integer >= 10")
        if not isinstance(records, list):
            raise ValueError(f"{round_id} official_records must be a list")

        driver_ids: list[str] = []
        positions: list[int] = []
        for record in records:
            driver_id = record.get("driver_id")
            if not isinstance(driver_id, str) or not driver_id:
                raise ValueError(f"{round_id} driver_id must be a non-empty string")
            driver_ids.append(driver_id)
            position = record.get("position")
            status = record.get("classification_status")
            if position is None:
                if status not in _SUPPORTED_NON_NUMERIC_STATUSES:
                    raise ValueError(
                        f"{round_id} unsupported non-numeric status for {driver_id}: {status}"
                    )
            else:
                if isinstance(position, bool) or not isinstance(position, int):
                    raise ValueError(f"{round_id} position must be integer or null")
                positions.append(position)

        _require_unique(driver_ids, f"{round_id} driver_id")
        _require_unique(positions, f"{round_id} position")
        if positions != list(range(1, len(positions) + 1)):
            raise ValueError(f"{round_id} numeric positions must be contiguous from P1")
        if label.get("c0_scoreable") and len(records) != field_size:
            raise ValueError(f"{round_id} scoreable records must cover field_size")


def _round_label(manifest: dict[str, Any], round_number: int) -> dict[str, Any]:
    for label in manifest["rounds"]:
        if int(label["round"]) == round_number:
            return label
    raise ValueError(f"official qualifying labels missing R{round_number:02d}")


def _require_unique(values: list[Any], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")
