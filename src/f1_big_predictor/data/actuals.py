from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .archive import RawArchive
from ..core import ClassificationEntry
from .jolpica import (
    ConstructorStanding,
    DriverResult,
    DriverStanding,
    JolpicaClient,
    JolpicaFetchError,
    QualifyingResult,
    RaceInfo,
)
from .jolpica_alpha import (
    AlphaSession,
    JolpicaAlphaClient,
    build_sprint_qualifying_classification,
    canonical_name_key,
)

ACTUAL_TARGETS = ("qualifying", "race", "sprint", "sprint_qualifying")
_TARGET_FIELDS = {
    "qualifying": "qualifying_results",
    "race": "race_results",
    "sprint": "sprint_results",
    "sprint_qualifying": "sprint_qualifying",
}


def collect_completed_season_actuals(
    *,
    season: int,
    as_of_date: date,
    project_root: Path,
    archive_week_id: str | None = None,
    output_path: Path | None = None,
    client: JolpicaClient | None = None,
    alpha_client: JolpicaAlphaClient | None = None,
    target_rounds: Sequence[int] | None = None,
    targets: Sequence[str] | None = None,
) -> dict[str, Any]:
    archive_week_id = archive_week_id or f"season_{season}_actuals"
    archive = RawArchive(project_root)
    selected_rounds = _normalize_rounds(target_rounds)
    selected_targets = _normalize_targets(targets)
    all_targets_selected = set(selected_targets) == set(ACTUAL_TARGETS)
    client = client or JolpicaClient(
        archive=archive,
        archive_week_id=archive_week_id,
        reuse_any_archive=True,
    )
    alpha_client = alpha_client or JolpicaAlphaClient(
        archive=archive,
        archive_week_id=archive_week_id,
        reuse_any_archive=True,
    )

    schedule = client.race_schedule(season)
    rounds: list[dict[str, Any]] = []
    skipped_rounds: list[dict[str, Any]] = []
    pending_rounds: list[dict[str, Any]] = []
    seen_rounds: set[int] = set()

    for race in sorted(
        [item for item in schedule if item.round is not None],
        key=lambda item: item.round or 999,
    ):
        round_ = race.round or 0
        seen_rounds.add(round_)
        if selected_rounds is not None and round_ not in selected_rounds:
            continue
        race_date = _parse_race_date(race)
        if race_date is None:
            skipped_rounds.append(_round_status(race, "missing_race_date"))
            continue
        if race_date > as_of_date:
            pending_rounds.append(_round_status(race, "future_race"))
            continue

        needs_race_results = all_targets_selected or {
            "race",
            "sprint_qualifying",
        }.intersection(selected_targets)
        needs_qualifying = all_targets_selected or {
            "qualifying",
            "sprint_qualifying",
        }.intersection(selected_targets)
        needs_sprint = all_targets_selected or {
            "sprint",
            "sprint_qualifying",
        }.intersection(selected_targets)
        needs_driver_standings = all_targets_selected or {
            "sprint_qualifying",
        }.intersection(selected_targets)
        needs_constructor_standings = all_targets_selected or {
            "sprint_qualifying",
        }.intersection(selected_targets)

        race_results, race_error = (
            _safe_fetch(lambda: client.race_results(season, round_))
            if needs_race_results
            else ([], None)
        )
        if all_targets_selected:
            if race_error:
                skipped_rounds.append(_round_status(race, "race_results_error", race_error))
                continue
            if not race_results:
                pending_rounds.append(_round_status(race, "race_results_not_available"))
                continue

        qualifying, qualifying_error = (
            _safe_fetch(lambda: client.qualifying_results(season, round_))
            if needs_qualifying
            else ([], None)
        )
        sprint, sprint_error = (
            _safe_fetch(lambda: client.sprint_results(season, round_))
            if needs_sprint
            else ([], None)
        )
        driver_standings, driver_standings_error = (
            _safe_fetch(lambda: client.driver_standings(season, round_))
            if needs_driver_standings
            else ([], None)
        )
        constructor_standings, constructor_standings_error = (
            _safe_fetch(lambda: client.constructor_standings(season, round_))
            if needs_constructor_standings
            else ([], None)
        )
        sprint_qualifying = (
            _collect_sprint_qualifying(
                season=season,
                round_=round_,
                alpha_client=alpha_client,
                archive=archive,
                race_results=race_results,
                qualifying=qualifying,
                sprint=sprint,
                driver_standings=driver_standings,
                constructor_standings=constructor_standings,
            )
            if "sprint_qualifying" in selected_targets
            else _not_requested_sprint_qualifying()
        )

        rounds.append(
            {
                **_race_payload(race),
                "race_results": (
                    _dataset_payload(
                        "jolpica",
                        "results",
                        {"season": str(season), "round": str(round_)},
                        archive,
                        records=race_results,
                        error=race_error,
                    )
                    if "race" in selected_targets
                    else _not_requested_dataset()
                ),
                "qualifying_results": (
                    _dataset_payload(
                        "jolpica",
                        "qualifying",
                        {"season": str(season), "round": str(round_)},
                        archive,
                        records=qualifying,
                        error=qualifying_error,
                    )
                    if "qualifying" in selected_targets
                    else _not_requested_dataset()
                ),
                "sprint_results": (
                    _dataset_payload(
                        "jolpica",
                        "sprint",
                        {"season": str(season), "round": str(round_)},
                        archive,
                        records=sprint,
                        error=sprint_error,
                        empty_status="not_applicable_or_unavailable",
                    )
                    if "sprint" in selected_targets
                    else _not_requested_dataset()
                ),
                "sprint_qualifying": sprint_qualifying,
                "driver_standings": (
                    _dataset_payload(
                        "jolpica",
                        "driverstandings",
                        {"season": str(season), "round": str(round_)},
                        archive,
                        records=driver_standings,
                        error=driver_standings_error,
                    )
                    if all_targets_selected
                    else _not_requested_dataset()
                ),
                "constructor_standings": (
                    _dataset_payload(
                        "jolpica",
                        "constructorstandings",
                        {"season": str(season), "round": str(round_)},
                        archive,
                        records=constructor_standings,
                        error=constructor_standings_error,
                    )
                    if all_targets_selected
                    else _not_requested_dataset()
                ),
            }
        )

    if selected_rounds is not None:
        missing_rounds = selected_rounds - seen_rounds
        if missing_rounds:
            raise ValueError(f"requested rounds are not in the {season} schedule: {sorted(missing_rounds)}")

    payload: dict[str, Any] = {
        "season": season,
        "as_of_date": as_of_date.isoformat(),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "archive_week_id": archive_week_id,
        "source": "jolpica + jolpica_alpha",
        "authority": "structured collection mechanism, pending official FIA/F1 classification verification",
        "official_classification_status": "not_verified",
        "official_gap": (
            "This manifest collects structured labels for completed races. "
            "Official FIA/F1 PDFs or result pages still take precedence for final classifications."
        ),
        "round_count": len(rounds),
        "completed_rounds": rounds,
        "pending_rounds": pending_rounds,
        "skipped_rounds": skipped_rounds,
        "usage": "structured season actual data for backtests and model iteration",
    }
    if target_rounds is not None or targets is not None:
        payload["selection"] = {
            "rounds": sorted(selected_rounds) if selected_rounds is not None else "all",
            "targets": list(selected_targets),
        }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return payload


def merge_actuals_payload(
    existing_payload: Mapping[str, Any],
    patch_payload: Mapping[str, Any],
    *,
    target_rounds: Sequence[int] | None = None,
    targets: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Merge a targeted collector payload without replacing unselected data."""

    selected_rounds = _normalize_rounds(target_rounds)
    selected_targets = _normalize_targets(targets)
    merged = deepcopy(dict(existing_payload))
    existing_rounds = {
        int(item["round"]): item
        for item in merged.get("completed_rounds", [])
        if item.get("round") is not None
    }

    for patch_round in patch_payload.get("completed_rounds", []):
        round_ = int(patch_round["round"])
        if selected_rounds is not None and round_ not in selected_rounds:
            continue
        current = existing_rounds.get(round_)
        if current is None:
            existing_rounds[round_] = deepcopy(patch_round)
            continue
        for key in ("round", "race_name", "race_date", "circuit_id", "circuit_name"):
            if key in patch_round:
                current[key] = deepcopy(patch_round[key])
        for target in selected_targets:
            field = _TARGET_FIELDS[target]
            if field in patch_round:
                current[field] = deepcopy(patch_round[field])

    merged["completed_rounds"] = [
        existing_rounds[round_]
        for round_ in sorted(existing_rounds)
    ]
    completed_rounds = set(existing_rounds)
    merged["pending_rounds"] = _merge_round_statuses(
        merged.get("pending_rounds", []),
        patch_payload.get("pending_rounds", []),
        completed_rounds,
    )
    merged["skipped_rounds"] = _merge_round_statuses(
        merged.get("skipped_rounds", []),
        patch_payload.get("skipped_rounds", []),
        completed_rounds,
    )
    for key in ("as_of_date", "generated_at"):
        if key in patch_payload:
            merged[key] = patch_payload[key]
    merged["round_count"] = len(merged["completed_rounds"])
    merged.pop("selection", None)
    return merged


def default_actuals_output_path(project_root: Path, season: int) -> Path:
    return project_root / "data" / "processed" / f"season_{season}_actuals" / "actuals.json"


def _collect_sprint_qualifying(
    *,
    season: int,
    round_: int,
    alpha_client: JolpicaAlphaClient,
    archive: RawArchive,
    race_results: list[DriverResult],
    qualifying: list[QualifyingResult],
    sprint: list[DriverResult],
    driver_standings: list[DriverStanding],
    constructor_standings: list[ConstructorStanding],
) -> dict[str, Any]:
    if not sprint:
        return {"status": "not_applicable", "row_count": 0, "records": [], "sources": []}
    try:
        sessions = alpha_client.round_sessions(season, round_)
        sessions_by_type = {session.session_type: session for session in sessions}
        missing = [
            session_type
            for session_type in ("SQ1", "SQ2", "SQ3")
            if session_type not in sessions_by_type
        ]
        if missing:
            return {
                "status": "missing",
                "row_count": 0,
                "records": [],
                "missing_sessions": missing,
                "sources": _alpha_schedule_sources(archive, season),
            }
        sq1 = alpha_client.session_entries(sessions_by_type["SQ1"].session_id)
        sq2 = alpha_client.session_entries(sessions_by_type["SQ2"].session_id)
        sq3 = alpha_client.session_entries(sessions_by_type["SQ3"].session_id)
        sq3_laps = alpha_client.session_laps(sessions_by_type["SQ3"].session_id)
        classification = build_sprint_qualifying_classification(
            sq1=sq1,
            sq2=sq2,
            sq3=sq3,
            sq3_laps=sq3_laps,
            driver_ids_by_name=_driver_ids_by_name(
                race_results,
                qualifying,
                sprint,
                driver_standings,
            ),
            constructor_ids_by_team=_constructor_ids_by_team(
                race_results,
                qualifying,
                sprint,
                driver_standings,
                constructor_standings,
            ),
        )
        return {
            "status": "ok" if classification else "empty",
            "row_count": len(classification),
            "records": _records_payload(classification),
            "session_ids": {
                session_type: sessions_by_type[session_type].session_id
                for session_type in ("SQ1", "SQ2", "SQ3")
            },
            "sources": _sprint_qualifying_sources(archive, season, sessions_by_type),
        }
    except (JolpicaFetchError, ValueError) as exc:
        return {
            "status": "error",
            "row_count": 0,
            "records": [],
            "error": str(exc),
            "sources": _alpha_schedule_sources(archive, season),
        }


def _dataset_payload(
    source_id: str,
    dataset: str,
    params: dict[str, str],
    archive: RawArchive,
    *,
    records: list[Any],
    error: str | None,
    empty_status: str = "empty",
) -> dict[str, Any]:
    if error is not None:
        status = "error"
    elif records:
        status = "ok"
    else:
        status = empty_status
    return {
        "status": status,
        "row_count": len(records),
        "records": _records_payload(records),
        "source": _archive_source(archive, source_id, dataset, params, require_ok=error is None),
        "error": error,
    }


def _not_requested_dataset() -> dict[str, Any]:
    return {
        "status": "not_requested",
        "row_count": 0,
        "records": [],
        "source": None,
        "error": None,
    }


def _not_requested_sprint_qualifying() -> dict[str, Any]:
    return {
        "status": "not_requested",
        "row_count": 0,
        "records": [],
        "sources": [],
    }


def _normalize_rounds(rounds: Sequence[int] | None) -> set[int] | None:
    if rounds is None:
        return None
    normalized = {int(round_) for round_ in rounds}
    if not normalized or any(round_ <= 0 for round_ in normalized):
        raise ValueError("target_rounds must contain positive round numbers")
    return normalized


def _normalize_targets(targets: Sequence[str] | None) -> tuple[str, ...]:
    if targets is None:
        return ACTUAL_TARGETS
    normalized = tuple(dict.fromkeys(targets))
    unknown = sorted(set(normalized) - set(ACTUAL_TARGETS))
    if not normalized or unknown:
        raise ValueError(
            f"targets must be one or more of {', '.join(ACTUAL_TARGETS)}; "
            f"unknown={unknown}"
        )
    return tuple(target for target in ACTUAL_TARGETS if target in normalized)


def _merge_round_statuses(
    existing: list[dict[str, Any]],
    patch: list[dict[str, Any]],
    completed_rounds: set[int],
) -> list[dict[str, Any]]:
    merged = {
        int(item["round"]): deepcopy(item)
        for item in existing + patch
        if item.get("round") is not None and int(item["round"]) not in completed_rounds
    }
    return [merged[round_] for round_ in sorted(merged)]


def _archive_source(
    archive: RawArchive,
    source_id: str,
    dataset: str,
    params: dict[str, str],
    *,
    require_ok: bool = True,
) -> dict[str, Any] | None:
    cached = archive.read_latest_for_request_any_week(
        source_id=source_id,
        dataset=dataset,
        params=params,
        require_ok=require_ok,
    )
    if cached is None:
        return None
    record = cached.record
    return {
        "archive_week_id": record.week_id,
        "dataset": record.dataset,
        "url": record.url,
        "retrieved_at": record.retrieved_at,
        "status_code": record.status_code,
        "content_type": record.content_type,
        "payload_sha256": record.payload_sha256,
        "data_path": record.data_path,
        "meta_path": record.meta_path,
    }


def _sprint_qualifying_sources(
    archive: RawArchive,
    season: int,
    sessions_by_type: dict[str, AlphaSession],
) -> list[dict[str, Any]]:
    sources = _alpha_schedule_sources(archive, season)
    for session_type in ("SQ1", "SQ2", "SQ3"):
        session = sessions_by_type[session_type]
        entry_source = _archive_source(
            archive,
            "jolpica_alpha",
            "session_entries",
            {"session_id": session.session_id},
        )
        if entry_source is not None:
            sources.append({"session_type": session_type, **entry_source})
    sq3 = sessions_by_type["SQ3"]
    lap_source = _archive_source(
        archive,
        "jolpica_alpha",
        "laps",
        {"session_id": sq3.session_id},
    )
    if lap_source is not None:
        sources.append({"session_type": "SQ3", **lap_source})
    return sources


def _alpha_schedule_sources(archive: RawArchive, season: int) -> list[dict[str, Any]]:
    source = _archive_source(archive, "jolpica_alpha", "schedule", {"season": str(season)})
    return [source] if source is not None else []


def _records_payload(records: list[Any]) -> list[dict[str, Any]]:
    return [
        asdict(record) if hasattr(record, "__dataclass_fields__") else dict(record)
        for record in records
    ]


def _safe_fetch(fetcher: Any) -> tuple[list[Any], str | None]:
    try:
        return list(fetcher()), None
    except (JolpicaFetchError, ValueError) as exc:
        return [], str(exc)


def _race_payload(race: RaceInfo) -> dict[str, Any]:
    return {
        "round": race.round,
        "race_name": race.race_name,
        "race_date": race.date,
        "circuit_id": race.circuit_id,
        "circuit_name": race.circuit_name,
    }


def _round_status(race: RaceInfo, status: str, error: str | None = None) -> dict[str, Any]:
    payload = {**_race_payload(race), "status": status}
    if error is not None:
        payload["error"] = error
    return payload


def _parse_race_date(race: RaceInfo) -> date | None:
    if not race.date:
        return None
    try:
        return date.fromisoformat(race.date)
    except ValueError:
        return None


def _driver_ids_by_name(*groups: list[Any]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for item in _flatten(groups):
        name = getattr(item, "driver_name", "")
        driver_id = getattr(item, "driver_id", "")
        if name and driver_id:
            ids[canonical_name_key(name)] = driver_id
    return ids


def _constructor_ids_by_team(*groups: list[Any]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for item in _flatten(groups):
        name = getattr(item, "constructor_name", "")
        constructor_id = getattr(item, "constructor_id", "")
        if name and constructor_id:
            ids[canonical_name_key(name)] = constructor_id
    return ids


def _flatten(groups: tuple[list[Any], ...]) -> list[Any]:
    return [item for group in groups for item in group]
