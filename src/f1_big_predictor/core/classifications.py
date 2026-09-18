from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClassificationEntry:
    driver_id: str
    constructor_id: str
    position: int
    lap_time: str | None = None
    points: float = 0.0


def is_dnf_status(status: str | None) -> bool:
    if not status:
        return False
    lowered = status.lower()
    if lowered == "finished" or "lap" in lowered:
        return False
    return True
