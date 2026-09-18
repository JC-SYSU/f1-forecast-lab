from __future__ import annotations

from dataclasses import asdict
from collections.abc import Mapping
from typing import Any, Iterable, Sequence

from ..core.time import lap_time_to_seconds


def ranked_entries_from_features(
    features: Sequence[Any] | None,
    *,
    score_field: str,
    lap_time_field: str | None = None,
) -> list[dict[str, Any]]:
    if not features:
        return []
    rows = [_entry_payload(item) for item in features]
    for row in rows:
        if "driver_id" not in row:
            raise ValueError("target feature rows require driver_id")
        if score_field not in row:
            raise ValueError(f"target feature rows require {score_field}")
    ranked = sorted(rows, key=lambda item: (-float(item[score_field]), str(item["driver_id"])))
    pole_seconds = _fastest_lap_seconds(ranked, lap_time_field)
    entries: list[dict[str, Any]] = []
    for position, row in enumerate(ranked, start=1):
        entry = {"driver_id": str(row["driver_id"]), "position": position, "score": float(row[score_field])}
        for field in ("driver_name", "constructor_id", "constructor_name"):
            if field in row:
                entry[field] = row[field]
        if lap_time_field is not None:
            entry["lap_time"] = row.get(lap_time_field)
            lap_time_seconds = _lap_time_seconds(row, lap_time_field)
            entry["lap_time_seconds"] = lap_time_seconds
            entry["delta_to_pole"] = row.get("delta_to_pole", _delta_to_pole(lap_time_seconds, pole_seconds))
        entries.append(entry)
    return entries


def _fastest_lap_seconds(rows: Sequence[dict[str, Any]], lap_time_field: str | None) -> float | None:
    if lap_time_field is None:
        return None
    values = [_lap_time_seconds(row, lap_time_field) for row in rows]
    valid = [value for value in values if value is not None]
    return min(valid) if valid else None


def _lap_time_seconds(row: dict[str, Any], lap_time_field: str) -> float | None:
    if isinstance(row.get("lap_time_seconds"), (int, float)):
        return float(row["lap_time_seconds"])
    lap_time = row.get(lap_time_field)
    if isinstance(lap_time, str) and lap_time:
        return lap_time_to_seconds(lap_time)
    return None


def _delta_to_pole(lap_time_seconds: float | None, pole_seconds: float | None) -> float | None:
    if lap_time_seconds is None or pole_seconds is None:
        return None
    return round(lap_time_seconds - pole_seconds, 3)

def _entry_payload(item: Any) -> dict[str, Any]:
    if isinstance(item, Mapping):
        return dict(item)
    return asdict(item)


def top10_position_accuracy(predicted: Sequence[str], actual: Sequence[str]) -> float:
    pairs = list(zip(predicted[:10], actual[:10]))
    if len(pairs) < 10:
        raise ValueError("top10 position accuracy requires 10 predicted and 10 actual entries")
    return sum(1 for left, right in pairs if left == right) / 10.0


def rank_mae(predicted: Sequence[str], actual: Sequence[str]) -> float:
    if not predicted or not actual:
        raise ValueError("rank MAE requires predicted and actual entries")
    predicted_rank = {driver_id: index + 1 for index, driver_id in enumerate(predicted)}
    actual_rank = {driver_id: index + 1 for index, driver_id in enumerate(actual)}
    shared = [driver_id for driver_id in predicted_rank if driver_id in actual_rank]
    if not shared:
        raise ValueError("rank MAE requires at least one shared driver")
    return sum(abs(predicted_rank[item] - actual_rank[item]) for item in shared) / len(shared)


def driver_ids(entries: Iterable[dict[str, Any]]) -> list[str]:
    return [str(item["driver_id"]) for item in entries]
