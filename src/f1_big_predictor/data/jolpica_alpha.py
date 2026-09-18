from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters import JolpicaAlphaAdapter, payload_from_archive_cache
from .archive import RawArchive, archive_dataset_key
from ..core import ClassificationEntry
from .jolpica import JolpicaFetchError


@dataclass(frozen=True)
class AlphaSession:
    session_id: str
    number: int | None
    session_type: str
    type_display: str
    round_id: str
    round_number: int | None
    round_name: str


@dataclass(frozen=True)
class AlphaSessionEntry:
    entry_id: str
    session_id: str
    session_type: str
    position: int | None
    driver_name: str
    team_name: str
    points: float
    status: str | None


@dataclass(frozen=True)
class AlphaLap:
    lap_id: str
    session_entry_id: str
    number: int | None
    time_display: str | None
    time_milliseconds: int | None
    is_entry_fastest_lap: bool


class JolpicaAlphaClient:
    def __init__(
        self,
        adapter: JolpicaAlphaAdapter | None = None,
        archive: RawArchive | None = None,
        archive_week_id: str | None = None,
        reuse_any_archive: bool = False,
    ) -> None:
        self.adapter = adapter or JolpicaAlphaAdapter()
        self.archive = archive
        self.archive_week_id = archive_week_id
        self.reuse_any_archive = reuse_any_archive
        self._schedule_cache: dict[int, dict[str, Any]] = {}

    def round_sessions(self, season: int, round_: int) -> list[AlphaSession]:
        if season not in self._schedule_cache:
            payload = self._fetch("schedule", {"season": str(season)})
            self._schedule_cache[season] = payload.json()
        return extract_round_sessions(self._schedule_cache[season], round_)

    def session_entries(self, session_id: str) -> list[AlphaSessionEntry]:
        payload = self._fetch("session_entries", {"session_id": session_id})
        return extract_session_entries(payload.json())

    def session_laps(self, session_id: str) -> list[AlphaLap]:
        payload = self._fetch("laps", {"session_id": session_id})
        return extract_laps(payload.json())

    def _fetch(self, dataset: str, params: dict[str, str]):
        adapter_source_id = getattr(self.adapter, "source_id", "jolpica_alpha")
        archive_dataset = archive_dataset_key(adapter_source_id, dataset, params)
        if self.archive and self.archive_week_id:
            cached = self.archive.read_latest_for_request(
                week_id=self.archive_week_id,
                source_id=adapter_source_id,
                dataset=dataset,
                params=params,
                require_ok=True,
            )
            if cached is not None:
                return payload_from_archive_cache(cached, dataset=dataset)
        if self.archive and self.reuse_any_archive:
            cached = self.archive.read_latest_for_request_any_week(
                source_id=adapter_source_id,
                dataset=dataset,
                params=params,
                require_ok=True,
            )
            if cached is not None:
                return payload_from_archive_cache(cached, dataset=dataset)
        payload = self.adapter.fetch(dataset, params)
        if self.archive and self.archive_week_id:
            self.archive.write(
                week_id=self.archive_week_id,
                source_id=payload.source_id,
                dataset=archive_dataset,
                url=payload.url,
                params=payload.params,
                payload=payload.body,
                extension=payload.extension(),
                content_type=payload.content_type,
                status_code=payload.status_code,
                ok=payload.ok,
                error=payload.error,
            )
        if not payload.ok:
            raise JolpicaFetchError(
                f"Jolpica alpha fetch failed for {dataset}: "
                f"status={payload.status_code} url={payload.url} error={payload.error}"
            )
        return payload


def archived_jolpica_alpha_client(project_root: Path, week_id: str) -> JolpicaAlphaClient:
    return JolpicaAlphaClient(archive=RawArchive(project_root), archive_week_id=week_id)


def extract_round_sessions(payload: dict[str, Any], round_: int) -> list[AlphaSession]:
    data = payload.get("data", {})
    events = data.get("events", [])
    for event in events:
        round_data = event.get("round", {})
        if _optional_int(round_data.get("number")) != round_:
            continue
        round_id = str(round_data.get("id", ""))
        round_name = str(round_data.get("name", ""))
        sessions: list[AlphaSession] = []
        for block in event.get("schedule", []):
            for session in block.get("sessions", []):
                sessions.append(
                    AlphaSession(
                        session_id=str(session.get("id", "")),
                        number=_optional_int(session.get("number")),
                        session_type=str(session.get("type", "")),
                        type_display=str(session.get("type_display", "")),
                        round_id=round_id,
                        round_number=round_,
                        round_name=round_name,
                    )
                )
        return sessions
    return []


def extract_session_entries(payload: dict[str, Any]) -> list[AlphaSessionEntry]:
    entries: list[AlphaSessionEntry] = []
    for item in payload.get("data", []):
        session = item.get("session", {})
        driver = item.get("driver", {})
        team = item.get("team", {})
        entries.append(
            AlphaSessionEntry(
                entry_id=str(item.get("id", "")),
                session_id=str(session.get("id", "")),
                session_type=str(session.get("type", "")),
                position=_optional_int(item.get("position")),
                driver_name=_alpha_driver_name(driver),
                team_name=str(team.get("name", "")),
                points=float(item.get("points") or 0),
                status=item.get("status_display"),
            )
        )
    return entries


def extract_laps(payload: dict[str, Any]) -> list[AlphaLap]:
    laps: list[AlphaLap] = []
    for item in payload.get("data", []):
        session_entry = item.get("session_entry", {})
        laps.append(
            AlphaLap(
                lap_id=str(item.get("id", "")),
                session_entry_id=str(session_entry.get("id", "")),
                number=_optional_int(item.get("number")),
                time_display=item.get("time_display"),
                time_milliseconds=_optional_int(item.get("time_milliseconds")),
                is_entry_fastest_lap=bool(item.get("is_entry_fastest_lap")),
            )
        )
    return laps


def build_sprint_qualifying_classification(
    *,
    sq1: list[AlphaSessionEntry],
    sq2: list[AlphaSessionEntry],
    sq3: list[AlphaSessionEntry],
    sq3_laps: list[AlphaLap],
    driver_ids_by_name: dict[str, str],
    constructor_ids_by_team: dict[str, str],
) -> list[ClassificationEntry]:
    rows: list[ClassificationEntry] = []
    included_names: set[str] = set()
    sq3_lap_times = _fastest_lap_times_by_entry(sq3_laps)

    for entry in sorted(_positioned(sq3), key=lambda item: item.position or 999):
        rows.append(
            _classification_entry(
                entry,
                position=entry.position or len(rows) + 1,
                driver_ids_by_name=driver_ids_by_name,
                constructor_ids_by_team=constructor_ids_by_team,
                lap_time=sq3_lap_times.get(entry.entry_id),
            )
        )
        included_names.add(canonical_name_key(entry.driver_name))

    sq2_eliminated = [
        entry for entry in sorted(_positioned(sq2), key=lambda item: item.position or 999)
        if canonical_name_key(entry.driver_name) not in included_names
    ]
    for entry in sq2_eliminated:
        rows.append(
            _classification_entry(
                entry,
                position=len(rows) + 1,
                driver_ids_by_name=driver_ids_by_name,
                constructor_ids_by_team=constructor_ids_by_team,
            )
        )
        included_names.add(canonical_name_key(entry.driver_name))

    sq1_eliminated = [
        entry for entry in sorted(_positioned(sq1), key=lambda item: item.position or 999)
        if canonical_name_key(entry.driver_name) not in included_names
    ]
    for entry in sq1_eliminated:
        rows.append(
            _classification_entry(
                entry,
                position=len(rows) + 1,
                driver_ids_by_name=driver_ids_by_name,
                constructor_ids_by_team=constructor_ids_by_team,
            )
        )
    return rows


def _classification_entry(
    entry: AlphaSessionEntry,
    *,
    position: int,
    driver_ids_by_name: dict[str, str],
    constructor_ids_by_team: dict[str, str],
    lap_time: str | None = None,
) -> ClassificationEntry:
    name_key = canonical_name_key(entry.driver_name)
    team_key = canonical_name_key(entry.team_name)
    return ClassificationEntry(
        driver_id=driver_ids_by_name.get(name_key, name_key.replace(" ", "_")),
        constructor_id=constructor_ids_by_team.get(team_key, team_key.replace(" ", "_")),
        position=position,
        lap_time=lap_time,
        points=entry.points,
    )


def _fastest_lap_times_by_entry(laps: list[AlphaLap]) -> dict[str, str]:
    best: dict[str, AlphaLap] = {}
    for lap in laps:
        if lap.time_milliseconds is None or not lap.time_display:
            continue
        current = best.get(lap.session_entry_id)
        if current is None or lap.time_milliseconds <= (current.time_milliseconds or 10**9):
            best[lap.session_entry_id] = lap
    return {entry_id: lap.time_display or "" for entry_id, lap in best.items()}


def _positioned(entries: list[AlphaSessionEntry]) -> list[AlphaSessionEntry]:
    return [entry for entry in entries if entry.position is not None]


def _alpha_driver_name(driver: dict[str, Any]) -> str:
    given = str(driver.get("given_name", "")).strip()
    family = str(driver.get("family_name", "")).strip()
    return f"{given} {family}".strip()


def canonical_name_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_value.lower().split())


def _optional_int(value: Any) -> int | None:
    if value in (None, "", "NC", "DQ"):
        return None
    return int(value)
