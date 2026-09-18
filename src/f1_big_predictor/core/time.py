from __future__ import annotations


def lap_time_to_seconds(lap_time: str) -> float:
    parts = lap_time.strip().split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        minutes = int(parts[0])
        return minutes * 60 + float(parts[1])
    raise ValueError(f"Unsupported lap time: {lap_time}")


def seconds_to_lap_time(seconds: float) -> str:
    minutes = int(seconds // 60)
    remaining = seconds - minutes * 60
    return f"{minutes}:{remaining:06.3f}"
