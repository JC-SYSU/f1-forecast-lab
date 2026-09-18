from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters import JolpicaAdapter, payload_from_archive_cache
from .archive import RawArchive, archive_dataset_key


RACE_POINTS = (25, 18, 15, 12, 10, 8, 6, 4, 2, 1)
SPRINT_POINTS = (8, 7, 6, 5, 4, 3, 2, 1)


class JolpicaFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class DriverResult:
    driver_id: str
    driver_code: str | None
    driver_name: str
    constructor_id: str
    constructor_name: str
    position: int | None
    grid: int | None
    points: float
    status: str | None = None


@dataclass(frozen=True)
class QualifyingResult:
    driver_id: str
    driver_code: str | None
    driver_name: str
    constructor_id: str
    constructor_name: str
    position: int | None
    q1: str | None = None
    q2: str | None = None
    q3: str | None = None


@dataclass(frozen=True)
class DriverStanding:
    driver_id: str
    driver_code: str | None
    driver_name: str
    constructor_id: str
    constructor_name: str
    position: int | None
    points: float
    wins: int


@dataclass(frozen=True)
class ConstructorStanding:
    constructor_id: str
    constructor_name: str
    position: int | None
    points: float
    wins: int


@dataclass(frozen=True)
class RaceInfo:
    season: int | None
    round: int | None
    race_name: str
    date: str | None
    circuit_id: str | None = None
    circuit_name: str | None = None


class JolpicaClient:
    def __init__(
        self,
        adapter: JolpicaAdapter | None = None,
        archive: RawArchive | None = None,
        archive_week_id: str | None = None,
        reuse_any_archive: bool = False,
    ) -> None:
        self.adapter = adapter or JolpicaAdapter()
        self.archive = archive
        self.archive_week_id = archive_week_id
        self.reuse_any_archive = reuse_any_archive

    def race_results(self, season: int, round_: int) -> list[DriverResult]:
        payload = self._fetch("results", {"season": str(season), "round": str(round_)})
        payload_data = JolpicaAdapter.unwrap_mrdata(payload)
        return extract_race_results(payload_data)

    def qualifying_results(self, season: int, round_: int) -> list[QualifyingResult]:
        payload = self._fetch("qualifying", {"season": str(season), "round": str(round_)})
        payload_data = JolpicaAdapter.unwrap_mrdata(payload)
        return extract_qualifying_results(payload_data)

    def sprint_results(self, season: int, round_: int) -> list[DriverResult]:
        payload = self._fetch("sprint", {"season": str(season), "round": str(round_)})
        payload_data = JolpicaAdapter.unwrap_mrdata(payload)
        return extract_sprint_results(payload_data)

    def driver_standings(self, season: int, round_: int) -> list[DriverStanding]:
        payload = self._fetch("driverstandings", {"season": str(season), "round": str(round_)})
        payload_data = JolpicaAdapter.unwrap_mrdata(payload)
        return extract_driver_standings(payload_data)

    def constructor_standings(self, season: int, round_: int) -> list[ConstructorStanding]:
        payload = self._fetch(
            "constructorstandings",
            {"season": str(season), "round": str(round_)},
        )
        payload_data = JolpicaAdapter.unwrap_mrdata(payload)
        return extract_constructor_standings(payload_data)

    def race_info(self, season: int, round_: int) -> RaceInfo:
        payload = self._fetch("results", {"season": str(season), "round": str(round_)})
        payload_data = JolpicaAdapter.unwrap_mrdata(payload)
        return extract_race_info(payload_data)

    def race_schedule(self, season: int) -> list[RaceInfo]:
        payload = self._fetch("races", {"season": str(season)})
        payload_data = JolpicaAdapter.unwrap_mrdata(payload)
        return extract_race_schedule(payload_data)

    def _fetch(self, dataset: str, params: dict[str, str]):
        adapter_source_id = getattr(self.adapter, "source_id", "jolpica")
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
                f"Jolpica fetch failed for {dataset}: "
                f"status={payload.status_code} url={payload.url} error={payload.error}"
            )
        return payload


def archived_jolpica_client(project_root: Path, week_id: str) -> JolpicaClient:
    return JolpicaClient(archive=RawArchive(project_root), archive_week_id=week_id)


def extract_race_results(payload: dict[str, Any]) -> list[DriverResult]:
    race = _first_race(payload)
    results = race.get("Results", [])
    return [_driver_result(item) for item in results]


def extract_qualifying_results(payload: dict[str, Any]) -> list[QualifyingResult]:
    race = _first_race(payload)
    results = race.get("QualifyingResults", [])
    return [_qualifying_result(item) for item in results]


def extract_sprint_results(payload: dict[str, Any]) -> list[DriverResult]:
    race = _first_race(payload)
    results = race.get("SprintResults", [])
    return [_driver_result(item) for item in results]


def extract_driver_standings(payload: dict[str, Any]) -> list[DriverStanding]:
    table = payload.get("StandingsTable", {})
    lists = table.get("StandingsLists", [])
    if not lists:
        return []
    standings = lists[0].get("DriverStandings", [])
    return [_driver_standing(item) for item in standings]


def extract_constructor_standings(payload: dict[str, Any]) -> list[ConstructorStanding]:
    table = payload.get("StandingsTable", {})
    lists = table.get("StandingsLists", [])
    if not lists:
        return []
    standings = lists[0].get("ConstructorStandings", [])
    return [_constructor_standing(item) for item in standings]


def extract_race_info(payload: dict[str, Any]) -> RaceInfo:
    race = _first_race(payload)
    return _race_info(race)


def extract_race_schedule(payload: dict[str, Any]) -> list[RaceInfo]:
    races = payload.get("RaceTable", {}).get("Races", [])
    return [_race_info(race) for race in races]


def _race_info(race: dict[str, Any]) -> RaceInfo:
    circuit = race.get("Circuit", {})
    return RaceInfo(
        season=_optional_int(race.get("season")),
        round=_optional_int(race.get("round")),
        race_name=str(race.get("raceName") or "Unknown Grand Prix"),
        date=race.get("date"),
        circuit_id=circuit.get("circuitId"),
        circuit_name=circuit.get("circuitName"),
    )


def driver_points_from_order(
    driver_ids: list[str],
    points_table: tuple[int, ...] = RACE_POINTS,
) -> dict[str, int]:
    return {
        driver_id: points_table[index]
        for index, driver_id in enumerate(driver_ids[: len(points_table)])
    }


def _first_race(payload: dict[str, Any]) -> dict[str, Any]:
    races = payload.get("RaceTable", {}).get("Races", [])
    if not races:
        return {}
    return races[0]


def _driver_result(item: dict[str, Any]) -> DriverResult:
    driver = item.get("Driver", {})
    constructor = item.get("Constructor", {})
    return DriverResult(
        driver_id=str(driver.get("driverId", "")),
        driver_code=driver.get("code"),
        driver_name=_driver_name(driver),
        constructor_id=str(constructor.get("constructorId", "")),
        constructor_name=str(constructor.get("name", "")),
        position=_optional_int(item.get("position")),
        grid=_optional_int(item.get("grid")),
        points=float(item.get("points") or 0),
        status=item.get("status"),
    )


def _qualifying_result(item: dict[str, Any]) -> QualifyingResult:
    driver = item.get("Driver", {})
    constructor = item.get("Constructor", {})
    return QualifyingResult(
        driver_id=str(driver.get("driverId", "")),
        driver_code=driver.get("code"),
        driver_name=_driver_name(driver),
        constructor_id=str(constructor.get("constructorId", "")),
        constructor_name=str(constructor.get("name", "")),
        position=_optional_int(item.get("position")),
        q1=item.get("Q1"),
        q2=item.get("Q2"),
        q3=item.get("Q3"),
    )


def _driver_standing(item: dict[str, Any]) -> DriverStanding:
    driver = item.get("Driver", {})
    constructor = (item.get("Constructors") or [{}])[0]
    return DriverStanding(
        driver_id=str(driver.get("driverId", "")),
        driver_code=driver.get("code"),
        driver_name=_driver_name(driver),
        constructor_id=str(constructor.get("constructorId", "")),
        constructor_name=str(constructor.get("name", "")),
        position=_optional_int(item.get("position")),
        points=float(item.get("points") or 0),
        wins=int(item.get("wins") or 0),
    )


def _constructor_standing(item: dict[str, Any]) -> ConstructorStanding:
    constructor = item.get("Constructor", {})
    return ConstructorStanding(
        constructor_id=str(constructor.get("constructorId", "")),
        constructor_name=str(constructor.get("name", "")),
        position=_optional_int(item.get("position")),
        points=float(item.get("points") or 0),
        wins=int(item.get("wins") or 0),
    )


def _driver_name(driver: dict[str, Any]) -> str:
    given = str(driver.get("givenName", "")).strip()
    family = str(driver.get("familyName", "")).strip()
    return f"{given} {family}".strip()


def _optional_int(value: Any) -> int | None:
    if value in (None, "", "NC", "DQ"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
