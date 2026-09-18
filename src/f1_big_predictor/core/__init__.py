"""Shared core primitives for target-scoped prediction models."""

from .classifications import ClassificationEntry, is_dnf_status
from .time import lap_time_to_seconds, seconds_to_lap_time

__all__ = [
    "ClassificationEntry",
    "is_dnf_status",
    "lap_time_to_seconds",
    "seconds_to_lap_time",
]
