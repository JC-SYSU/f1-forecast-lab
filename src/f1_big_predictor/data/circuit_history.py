from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Callable

from .archive import RawArchive
from .jolpica import (
    DriverResult,
    DriverStanding,
    JolpicaClient,
    JolpicaFetchError,
    QualifyingResult,
    RaceInfo,
)


SCHEMA_VERSION = "circuit_history_event_v1"
DEFAULT_LOOKBACK_YEARS = 5
DEFAULT_RECENCY_DECAY = 0.72
NEUTRAL_SCORE = 0.5
RACE_POINTS_DENOMINATOR = 25.0
SPRINT_POINTS_DENOMINATOR = 8.0


@dataclass(frozen=True)
class CircuitHistoryDriverScore:
    driver_id: str
    driver_code: str | None
    driver_name: str
    coverage_count: int
    race_score: float
    qualifying_score: float
    sprint_score: float
    teammate_relative_score: float
    reliability_score: float
    composite_score: float
    evidence_issues: list[str]
    season_scores: list[dict[str, Any]]


@dataclass(frozen=True)
class CircuitHistoryEvent:
    historical_season: int
    historical_round: int
    race_name: str
    circuit_id: str | None
    match_method: str
    results: list[DriverResult]
    qualifying: list[QualifyingResult]
    sprint: list[DriverResult]


@dataclass(frozen=True)
class CircuitHistoryDataset:
    season: int
    target_round: int
    race_name: str
    circuit_id: str | None
    circuit_name: str | None
    driver_scores: list[CircuitHistoryDriverScore]
    evidence_issues: list[str]


_HistoricalEvent = CircuitHistoryEvent


def collect_circuit_history(
    *,
    season: int,
    target_round: int,
    project_root: Path,
    lookback_years: int = DEFAULT_LOOKBACK_YEARS,
    archive_week_id: str | None = None,
    output_path: Path | None = None,
    client: JolpicaClient | None = None,
    recency_decay: float = DEFAULT_RECENCY_DECAY,
) -> dict[str, Any]:
    if target_round < 1:
        raise ValueError("target_round must be at least 1 for circuit history")
    # For round 1 there is no "round 0" standings; use round 1 itself
    # to identify the current-season driver pool.
    standings_round = max(target_round - 1, 1)
    archive_week_id = archive_week_id or f"circuit_history_{season}_round_{target_round:02d}"
    archive = RawArchive(project_root)
    client = client or JolpicaClient(
        archive=archive,
        archive_week_id=archive_week_id,
        reuse_any_archive=True,
    )

    target_schedule = client.race_schedule(season)
    target_race = _race_by_round(target_schedule, target_round)
    if target_race is None:
        raise ValueError(f"round {target_round} is not present in the {season} schedule")

    current_drivers, current_driver_error = _safe_fetch(
        lambda: client.driver_standings(season, standings_round)
    )
    matched_events: list[dict[str, Any]] = []
    score_events: list[_HistoricalEvent] = []
    skipped_events: list[dict[str, Any]] = []

    for historical_season in range(season - 1, season - lookback_years - 1, -1):
        schedule, schedule_error = _safe_fetch(lambda year=historical_season: client.race_schedule(year))
        schedule_source = _archive_source(
            archive,
            "jolpica",
            "races",
            {"season": str(historical_season)},
        )
        if schedule_error:
            skipped_events.append(
                {
                    "historical_season": historical_season,
                    "reason": "schedule_unavailable",
                    "error": schedule_error,
                    "raw_archive_records": {"schedule": schedule_source},
                }
            )
            continue
        historical_race, match_method = _matching_target_race(schedule, target_race)
        if historical_race is None or historical_race.round is None:
            skipped_events.append(
                {
                    "historical_season": historical_season,
                    "reason": f"no matching race for {target_race.race_name}",
                    "raw_archive_records": {"schedule": schedule_source},
                }
            )
            continue

        historical_round = historical_race.round
        results, results_error = _safe_fetch(
            lambda year=historical_season, round_=historical_round: client.race_results(
                year,
                round_,
            )
        )
        qualifying, qualifying_error = _safe_fetch(
            lambda year=historical_season, round_=historical_round: client.qualifying_results(
                year,
                round_,
            )
        )
        sprint, sprint_error = _safe_fetch(
            lambda year=historical_season, round_=historical_round: client.sprint_results(
                year,
                round_,
            )
        )
        params = {"season": str(historical_season), "round": str(historical_round)}
        datasets = {
            "results": _dataset_payload(
                archive=archive,
                dataset="results",
                params=params,
                records=results,
                error=results_error,
            ),
            "qualifying": _dataset_payload(
                archive=archive,
                dataset="qualifying",
                params=params,
                records=qualifying,
                error=qualifying_error,
            ),
            "sprint": _dataset_payload(
                archive=archive,
                dataset="sprint",
                params=params,
                records=sprint,
                error=sprint_error,
                empty_status="not_applicable_or_unavailable",
            ),
        }
        raw_archive_records = {
            "schedule": schedule_source,
            **{key: value["source"] for key, value in datasets.items()},
        }
        matched_events.append(
            {
                "historical_season": historical_season,
                "historical_round": historical_round,
                "race_name": historical_race.race_name,
                "circuit_id": historical_race.circuit_id,
                "circuit_name": historical_race.circuit_name,
                "match_method": match_method,
                "datasets": datasets,
                "raw_archive_records": raw_archive_records,
            }
        )
        score_events.append(
            _HistoricalEvent(
                historical_season=historical_season,
                historical_round=historical_round,
                race_name=historical_race.race_name,
                circuit_id=historical_race.circuit_id,
                match_method=match_method,
                results=results,
                qualifying=qualifying,
                sprint=sprint,
            )
        )

    driver_scores = build_circuit_history_scores(
        current_drivers=current_drivers,
        historical_events=score_events,
        target_season=season,
        recency_decay=recency_decay,
    )
    evidence_issues = []
    if current_driver_error:
        evidence_issues.append(f"current driver standings unavailable: {current_driver_error}")

    payload: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "season": season,
        "target_round": target_round,
        "race_name": target_race.race_name,
        "circuit_id": target_race.circuit_id,
        "circuit_name": target_race.circuit_name,
        "lookback_years": lookback_years,
        "recency_decay": recency_decay,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "archive_week_id": archive_week_id,
        "source": "jolpica",
        "authority": (
            "structured collection mechanism, pending official FIA/F1 classification "
            "verification"
        ),
        "usage": "same-circuit historical driver scoring for target-scoped features",
        "target_schedule_source": _archive_source(
            archive,
            "jolpica",
            "races",
            {"season": str(season)},
        ),
        "current_driver_standings_source": _archive_source(
            archive,
            "jolpica",
            "driverstandings",
            {"season": str(season), "round": str(standings_round)},
        ),
        "evidence_issues": evidence_issues,
        "matched_historical_events": matched_events,
        "skipped_historical_events": skipped_events,
        "driver_history_scores": [asdict(score) for score in driver_scores],
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return payload


def build_circuit_history_scores(
    *,
    current_drivers: list[DriverStanding],
    historical_events: list[_HistoricalEvent],
    target_season: int,
    recency_decay: float = DEFAULT_RECENCY_DECAY,
) -> list[CircuitHistoryDriverScore]:
    scores: list[CircuitHistoryDriverScore] = []
    for standing in current_drivers:
        season_scores = [
            _driver_event_score(standing.driver_id, event, target_season, recency_decay)
            for event in historical_events
            if _driver_appeared(standing.driver_id, event)
        ]
        race_score, race_issue = _weighted_metric(season_scores, "race_year_score")
        qualifying_score, qualifying_issue = _weighted_metric(
            season_scores,
            "qualifying_year_score",
        )
        sprint_score, sprint_issue = _weighted_metric(season_scores, "sprint_year_score")
        teammate_score, teammate_issue = _weighted_metric(
            season_scores,
            "teammate_relative_year_score",
        )
        reliability_score, reliability_issue = _weighted_metric(
            season_scores,
            "reliability_year_score",
        )
        evidence_issues = [
            issue
            for issue in (
                race_issue,
                qualifying_issue,
                sprint_issue,
                teammate_issue,
                reliability_issue,
            )
            if issue
        ]
        if not season_scores:
            evidence_issues.append("no_same_circuit_history")
        if any(score.get("sprint_year_score") is not None for score in season_scores):
            composite = (
                0.35 * race_score
                + 0.25 * qualifying_score
                + 0.10 * sprint_score
                + 0.20 * teammate_score
                + 0.10 * reliability_score
            )
        else:
            composite = (
                0.40 * race_score
                + 0.30 * qualifying_score
                + 0.20 * teammate_score
                + 0.10 * reliability_score
            )
        scores.append(
            CircuitHistoryDriverScore(
                driver_id=standing.driver_id,
                driver_code=standing.driver_code,
                driver_name=standing.driver_name,
                coverage_count=len(season_scores),
                race_score=round(race_score, 4),
                qualifying_score=round(qualifying_score, 4),
                sprint_score=round(sprint_score, 4),
                teammate_relative_score=round(teammate_score, 4),
                reliability_score=round(reliability_score, 4),
                composite_score=round(composite, 4),
                evidence_issues=evidence_issues,
                season_scores=season_scores,
            )
        )
    return scores


def load_circuit_history_scores(path: Path) -> dict[str, float]:
    dataset = load_circuit_history_dataset(path)
    return {
        score.driver_id: score.composite_score
        for score in dataset.driver_scores
    }


def load_circuit_history_dataset(path: Path) -> CircuitHistoryDataset:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA_VERSION:
        raise ValueError(f"{path}: expected schema {SCHEMA_VERSION}")
    driver_scores = [
        CircuitHistoryDriverScore(
            driver_id=str(row["driver_id"]),
            driver_code=row.get("driver_code"),
            driver_name=str(row["driver_name"]),
            coverage_count=int(row["coverage_count"]),
            race_score=float(row["race_score"]),
            qualifying_score=float(row["qualifying_score"]),
            sprint_score=float(row["sprint_score"]),
            teammate_relative_score=float(row["teammate_relative_score"]),
            reliability_score=float(row["reliability_score"]),
            composite_score=float(row["composite_score"]),
            evidence_issues=[str(issue) for issue in row.get("evidence_issues", [])],
            season_scores=list(row.get("season_scores", [])),
        )
        for row in payload.get("driver_history_scores", [])
    ]
    return CircuitHistoryDataset(
        season=int(payload["season"]),
        target_round=int(payload["target_round"]),
        race_name=str(payload["race_name"]),
        circuit_id=payload.get("circuit_id"),
        circuit_name=payload.get("circuit_name"),
        driver_scores=driver_scores,
        evidence_issues=[str(issue) for issue in payload.get("evidence_issues", [])],
    )


def circuit_history_scores_for_round(
    path: Path,
    *,
    season: int | None = None,
    target_round: int | None = None,
) -> tuple[dict[str, float], list[str]]:
    dataset = load_circuit_history_dataset(path)
    if season is not None and dataset.season != season:
        raise ValueError(f"{path}: expected season {season}, got {dataset.season}")
    if target_round is not None and dataset.target_round != target_round:
        raise ValueError(
            f"{path}: expected target_round {target_round}, got {dataset.target_round}"
        )
    scores = {score.driver_id: score.composite_score for score in dataset.driver_scores}
    evidence_issues = list(dataset.evidence_issues)
    for score in dataset.driver_scores:
        for issue in score.evidence_issues:
            evidence_issues.append(f"{score.driver_id}: {issue}")
    return scores, evidence_issues


def _driver_event_score(
    driver_id: str,
    event: _HistoricalEvent,
    target_season: int,
    recency_decay: float,
) -> dict[str, Any]:
    race_result = _record_for_driver(event.results, driver_id)
    qualifying_result = _record_for_driver(event.qualifying, driver_id)
    sprint_result = _record_for_driver(event.sprint, driver_id)
    race_position = _position_score(
        race_result.position if race_result else None,
        _field_size(event.results),
    )
    race_points = (
        min(max(race_result.points, 0.0) / RACE_POINTS_DENOMINATOR, 1.0)
        if race_result is not None
        else None
    )
    reliability = _reliability_score(race_result.status if race_result else None)
    qualifying_position = _position_score(
        qualifying_result.position if qualifying_result else None,
        _field_size(event.qualifying),
    )
    sprint_position = _position_score(
        sprint_result.position if sprint_result else None,
        _field_size(event.sprint),
    )
    sprint_points = (
        min(max(sprint_result.points, 0.0) / SPRINT_POINTS_DENOMINATOR, 1.0)
        if sprint_result is not None
        else None
    )
    teammate_scores = [
        score
        for score in (
            _teammate_relative_score(driver_id, event.results),
            _teammate_relative_score(driver_id, event.qualifying),
            _teammate_relative_score(driver_id, event.sprint),
        )
        if score is not None
    ]
    age = target_season - 1 - event.historical_season
    return {
        "historical_season": event.historical_season,
        "historical_round": event.historical_round,
        "race_name": event.race_name,
        "circuit_id": event.circuit_id,
        "match_method": event.match_method,
        "recency_weight": round(recency_decay**age, 6),
        "race_year_score": _weighted_components(
            [(race_position, 0.55), (race_points, 0.25), (reliability, 0.20)]
        ),
        "qualifying_year_score": qualifying_position,
        "sprint_year_score": _weighted_components(
            [(sprint_position, 0.65), (sprint_points, 0.35)]
        ),
        "teammate_relative_year_score": mean(teammate_scores) if teammate_scores else None,
        "reliability_year_score": reliability,
    }


def _weighted_metric(
    season_scores: list[dict[str, Any]],
    key: str,
) -> tuple[float, str | None]:
    weighted_total = 0.0
    total_weight = 0.0
    for score in season_scores:
        value = score.get(key)
        if value is None:
            continue
        weight = float(score["recency_weight"])
        weighted_total += float(value) * weight
        total_weight += weight
    if total_weight == 0:
        return NEUTRAL_SCORE, f"missing_{key}"
    return weighted_total / total_weight, None


def _weighted_components(components: list[tuple[float | None, float]]) -> float | None:
    total = 0.0
    total_weight = 0.0
    for value, weight in components:
        if value is None:
            continue
        total += value * weight
        total_weight += weight
    if total_weight == 0:
        return None
    return total / total_weight


def _teammate_relative_score(
    driver_id: str,
    records: list[DriverResult] | list[QualifyingResult],
) -> float | None:
    driver = _record_for_driver(records, driver_id)
    field_size = _field_size(records)
    if driver is None or driver.position is None or field_size <= 0:
        return None
    teammate_scores = []
    for teammate in records:
        if teammate.driver_id == driver_id:
            continue
        if teammate.constructor_id != driver.constructor_id or teammate.position is None:
            continue
        teammate_scores.append(
            max(0.0, min(1.0, 0.5 + (teammate.position - driver.position) / field_size))
        )
    if not teammate_scores:
        return NEUTRAL_SCORE
    return mean(teammate_scores)


def _position_score(position: int | None, field_size: int) -> float | None:
    if position is None or position <= 0 or field_size <= 0:
        return None
    return max(0.0, min(1.0, (field_size + 1 - position) / field_size))


def _reliability_score(status: str | None) -> float:
    if not status:
        return 0.8
    lowered = status.lower()
    if lowered == "finished" or "lap" in lowered:
        return 1.0
    if "accident" in lowered or "collision" in lowered or "damage" in lowered:
        return 0.35
    return 0.55


def _record_for_driver(
    records: list[DriverResult] | list[QualifyingResult],
    driver_id: str,
) -> DriverResult | QualifyingResult | None:
    for record in records:
        if record.driver_id == driver_id:
            return record
    return None


def _driver_appeared(driver_id: str, event: _HistoricalEvent) -> bool:
    return any(
        _record_for_driver(records, driver_id) is not None
        for records in (event.results, event.qualifying, event.sprint)
    )


def _field_size(records: list[DriverResult] | list[QualifyingResult]) -> int:
    positions = [record.position for record in records if record.position is not None]
    return max([len(records), *positions], default=0)


def _dataset_payload(
    *,
    archive: RawArchive,
    dataset: str,
    params: dict[str, str],
    records: list[Any],
    error: str | None,
    empty_status: str = "empty",
) -> dict[str, Any]:
    if error:
        status = "error"
    elif records:
        status = "ok"
    else:
        status = empty_status
    return {
        "status": status,
        "row_count": len(records),
        "records": [
            asdict(record) if hasattr(record, "__dataclass_fields__") else dict(record)
            for record in records
        ],
        "source": _archive_source(archive, "jolpica", dataset, params, require_ok=error is None),
        "error": error,
    }


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


def _matching_target_race(
    schedule: list[RaceInfo],
    target_race_info: RaceInfo,
) -> tuple[RaceInfo | None, str]:
    if target_race_info.circuit_id:
        same_circuit = [
            race for race in schedule
            if race.circuit_id == target_race_info.circuit_id
        ]
        for race in same_circuit:
            if race.race_name.casefold() == target_race_info.race_name.casefold():
                return race, "circuit_id"
        if same_circuit:
            return same_circuit[0], "circuit_id"
        return None, "none"
    target_name = target_race_info.race_name.casefold()
    for race in schedule:
        if race.race_name.casefold() == target_name:
            return race, "race_name"
    return None, "none"


def _race_by_round(schedule: list[RaceInfo], round_: int) -> RaceInfo | None:
    for race in schedule:
        if race.round == round_:
            return race
    return None


def _safe_fetch(fetcher: Callable[[], list[Any]]) -> tuple[list[Any], str | None]:
    try:
        return list(fetcher()), None
    except (AttributeError, JolpicaFetchError, ValueError) as exc:
        return [], str(exc)
