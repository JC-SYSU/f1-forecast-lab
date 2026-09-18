from datetime import date

from f1_big_predictor.archive import RawArchive, archive_dataset_key
from f1_big_predictor.actuals import collect_completed_season_actuals, merge_actuals_payload
from f1_big_predictor.jolpica import (
    ConstructorStanding,
    DriverResult,
    DriverStanding,
    QualifyingResult,
    RaceInfo,
    JolpicaClient,
)
from f1_big_predictor.jolpica_alpha import AlphaLap, AlphaSession, AlphaSessionEntry


def test_collect_completed_season_actuals_keeps_actual_data_and_sprint_qualifying(tmp_path) -> None:
    payload = collect_completed_season_actuals(
        season=2026,
        as_of_date=date(2026, 3, 10),
        project_root=tmp_path,
        client=_FakeActualsClient(),
        alpha_client=_FakeActualsAlphaClient(),
    )

    assert payload["round_count"] == 1
    assert payload["official_classification_status"] == "not_verified"
    assert payload["pending_rounds"][0]["round"] == 2
    round_1 = payload["completed_rounds"][0]
    assert round_1["round"] == 1
    assert round_1["race_results"]["row_count"] == 2
    assert round_1["qualifying_results"]["records"][0]["q3"] == "1:01.000"
    assert round_1["sprint_results"]["row_count"] == 2
    assert round_1["sprint_qualifying"]["status"] == "ok"
    assert round_1["sprint_qualifying"]["records"][0]["lap_time"] == "1:00.900"
    assert round_1["driver_standings"]["records"][0]["points"] == 33


def test_collect_completed_season_actuals_uses_archived_raw_sources(tmp_path) -> None:
    archive = RawArchive(tmp_path)
    _write_jolpica_archive(
        archive,
        dataset="races",
        params={"season": "2026"},
        payload={
            "MRData": {
                "RaceTable": {
                    "Races": [
                        {
                            "season": "2026",
                            "round": "1",
                            "raceName": "Archived Grand Prix",
                            "date": "2026-03-01",
                            "Circuit": {
                                "circuitId": "archived_ring",
                                "circuitName": "Archived Ring",
                            },
                        }
                    ]
                }
            }
        },
    )
    _write_jolpica_archive(
        archive,
        dataset="results",
        params={"season": "2026", "round": "1"},
        payload={
            "MRData": {
                "RaceTable": {
                    "Races": [
                        {
                            "Results": [
                                _driver_result_payload("alpha", "Alpha", "Driver", 1, 25),
                            ]
                        }
                    ]
                }
            }
        },
    )
    _write_jolpica_archive(
        archive,
        dataset="qualifying",
        params={"season": "2026", "round": "1"},
        payload={
            "MRData": {
                "RaceTable": {
                    "Races": [
                        {
                            "QualifyingResults": [
                                _qualifying_payload("alpha", "Alpha", "Driver", 1),
                            ]
                        }
                    ]
                }
            }
        },
    )
    _write_jolpica_archive(
        archive,
        dataset="sprint",
        params={"season": "2026", "round": "1"},
        payload={"MRData": {"RaceTable": {"Races": [{}]}}},
    )
    _write_jolpica_archive(
        archive,
        dataset="driverstandings",
        params={"season": "2026", "round": "1"},
        payload={
            "MRData": {
                "StandingsTable": {
                    "StandingsLists": [
                        {
                            "DriverStandings": [
                                _driver_standing_payload("alpha", "Alpha", "Driver", 25),
                            ]
                        }
                    ]
                }
            }
        },
    )
    _write_jolpica_archive(
        archive,
        dataset="constructorstandings",
        params={"season": "2026", "round": "1"},
        payload={
            "MRData": {
                "StandingsTable": {
                    "StandingsLists": [
                        {
                            "ConstructorStandings": [
                                _constructor_standing_payload("team_alpha", "Team Alpha", 25),
                            ]
                        }
                    ]
                }
            }
        },
    )

    output_path = tmp_path / "data" / "processed" / "season_2026_actuals" / "actuals.json"
    payload = collect_completed_season_actuals(
        season=2026,
        as_of_date=date(2026, 3, 2),
        project_root=tmp_path,
        output_path=output_path,
        client=JolpicaClient(
            adapter=_FailingAdapter(),  # type: ignore[arg-type]
            archive=archive,
            archive_week_id="season_2026_actuals",
            reuse_any_archive=True,
        ),
        alpha_client=_FakeActualsAlphaClient(),
    )

    round_1 = payload["completed_rounds"][0]
    source = round_1["race_results"]["source"]
    assert output_path.exists()
    assert source["archive_week_id"] == "old_week"
    assert source["payload_sha256"]
    assert source["retrieved_at"]
    assert round_1["race_results"]["records"][0]["driver_id"] == "alpha"


def test_collect_completed_season_actuals_can_select_rounds_and_targets(tmp_path) -> None:
    client = _TargetedActualsClient()

    payload = collect_completed_season_actuals(
        season=2026,
        as_of_date=date(2026, 3, 10),
        project_root=tmp_path,
        client=client,
        target_rounds=[1],
        targets=["qualifying"],
    )

    assert payload["round_count"] == 1
    assert payload["selection"] == {"rounds": [1], "targets": ["qualifying"]}
    round_1 = payload["completed_rounds"][0]
    assert round_1["round"] == 1
    assert round_1["qualifying_results"]["status"] == "ok"
    assert round_1["qualifying_results"]["row_count"] == 1
    assert round_1["race_results"]["status"] == "not_requested"
    assert round_1["sprint_results"]["status"] == "not_requested"
    assert round_1["sprint_qualifying"]["status"] == "not_requested"
    assert round_1["driver_standings"]["status"] == "not_requested"
    assert round_1["constructor_standings"]["status"] == "not_requested"
    assert client.calls == ["qualifying_results"]


def test_merge_actuals_payload_preserves_unselected_round_data(tmp_path) -> None:
    existing = collect_completed_season_actuals(
        season=2026,
        as_of_date=date(2026, 3, 10),
        project_root=tmp_path / "existing",
        client=_FakeActualsClient(),
        alpha_client=_FakeActualsAlphaClient(),
    )
    patch = collect_completed_season_actuals(
        season=2026,
        as_of_date=date(2026, 3, 10),
        project_root=tmp_path / "patch",
        client=_TargetedActualsClient(),
        target_rounds=[1],
        targets=["qualifying"],
    )

    merged = merge_actuals_payload(
        existing,
        patch,
        target_rounds=[1],
        targets=["qualifying"],
    )

    existing_round = existing["completed_rounds"][0]
    merged_round = merged["completed_rounds"][0]
    assert merged_round["race_results"] == existing_round["race_results"]
    assert merged_round["sprint_results"] == existing_round["sprint_results"]
    assert merged_round["sprint_qualifying"] == existing_round["sprint_qualifying"]
    assert merged_round["qualifying_results"] == patch["completed_rounds"][0]["qualifying_results"]


class _TargetedActualsClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def race_schedule(self, season: int) -> list[RaceInfo]:
        return [RaceInfo(season, 1, "Opening Grand Prix", "2026-03-01", "alpha_ring", "Alpha Ring")]

    def qualifying_results(self, season: int, round_: int) -> list[QualifyingResult]:
        self.calls.append("qualifying_results")
        return [QualifyingResult("alpha", "ALP", "Alpha Driver", "team_a", "Team A", 1, q3="1:01.000")]


class _FakeActualsClient:
    def race_schedule(self, season: int) -> list[RaceInfo]:
        return [
            RaceInfo(season, 1, "Opening Grand Prix", "2026-03-01", "alpha_ring", "Alpha Ring"),
            RaceInfo(season, 2, "No Results Grand Prix", "2026-03-08", "beta_ring", "Beta Ring"),
            RaceInfo(season, 3, "Future Grand Prix", "2026-03-22", "gamma_ring", "Gamma Ring"),
        ]

    def race_results(self, season: int, round_: int) -> list[DriverResult]:
        if round_ != 1:
            return []
        return [
            DriverResult("alpha", "ALP", "Alpha Driver", "team_a", "Team A", 1, 1, 25, "Finished"),
            DriverResult("beta", "BET", "Beta Driver", "team_b", "Team B", 2, 2, 18, "Finished"),
        ]

    def qualifying_results(self, season: int, round_: int) -> list[QualifyingResult]:
        return [
            QualifyingResult("alpha", "ALP", "Alpha Driver", "team_a", "Team A", 1, q3="1:01.000"),
            QualifyingResult("beta", "BET", "Beta Driver", "team_b", "Team B", 2, q3="1:01.200"),
        ]

    def sprint_results(self, season: int, round_: int) -> list[DriverResult]:
        return [
            DriverResult("alpha", "ALP", "Alpha Driver", "team_a", "Team A", 1, 1, 8, "Finished"),
            DriverResult("beta", "BET", "Beta Driver", "team_b", "Team B", 2, 2, 7, "Finished"),
        ]

    def driver_standings(self, season: int, round_: int) -> list[DriverStanding]:
        return [
            DriverStanding("alpha", "ALP", "Alpha Driver", "team_a", "Team A", 1, 33, 1),
            DriverStanding("beta", "BET", "Beta Driver", "team_b", "Team B", 2, 25, 0),
        ]

    def constructor_standings(self, season: int, round_: int) -> list[ConstructorStanding]:
        return [
            ConstructorStanding("team_a", "Team A", 1, 33, 1),
            ConstructorStanding("team_b", "Team B", 2, 25, 0),
        ]


class _FakeActualsAlphaClient:
    def round_sessions(self, season: int, round_: int) -> list[AlphaSession]:
        return [
            AlphaSession("sq1", 1, "SQ1", "SQ1", "round_1", 1, "Opening Grand Prix"),
            AlphaSession("sq2", 2, "SQ2", "SQ2", "round_1", 1, "Opening Grand Prix"),
            AlphaSession("sq3", 3, "SQ3", "SQ3", "round_1", 1, "Opening Grand Prix"),
        ]

    def session_entries(self, session_id: str) -> list[AlphaSessionEntry]:
        return [
            AlphaSessionEntry(
                "entry_alpha",
                session_id,
                session_id.upper(),
                1,
                "Alpha Driver",
                "Team A",
                0,
                None,
            ),
            AlphaSessionEntry(
                "entry_beta",
                session_id,
                session_id.upper(),
                2,
                "Beta Driver",
                "Team B",
                0,
                None,
            ),
        ]

    def session_laps(self, session_id: str) -> list[AlphaLap]:
        return [
            AlphaLap("lap_alpha", "entry_alpha", 1, "1:00.900", 60900, True),
            AlphaLap("lap_beta", "entry_beta", 1, "1:01.100", 61100, True),
        ]


class _FailingAdapter:
    source_id = "jolpica"

    def fetch(self, dataset, params):  # type: ignore[no-untyped-def]
        raise AssertionError("network should not be called")


def _write_jolpica_archive(
    archive: RawArchive,
    *,
    dataset: str,
    params: dict[str, str],
    payload: dict[str, object],
) -> None:
    archive.write(
        week_id="old_week",
        source_id="jolpica",
        dataset=archive_dataset_key("jolpica", dataset, params),
        url=f"https://example.test/{dataset}.json",
        params=params,
        payload=payload,
        extension="json",
        content_type="application/json",
        status_code=200,
        ok=True,
    )


def _driver_result_payload(
    driver_id: str,
    given_name: str,
    family_name: str,
    position: int,
    points: int,
) -> dict[str, object]:
    return {
        "position": str(position),
        "grid": str(position),
        "points": str(points),
        "status": "Finished",
        "Driver": {
            "driverId": driver_id,
            "givenName": given_name,
            "familyName": family_name,
        },
        "Constructor": {"constructorId": "team_alpha", "name": "Team Alpha"},
    }


def _qualifying_payload(
    driver_id: str,
    given_name: str,
    family_name: str,
    position: int,
) -> dict[str, object]:
    return {
        "position": str(position),
        "Q3": "1:01.000",
        "Driver": {
            "driverId": driver_id,
            "givenName": given_name,
            "familyName": family_name,
        },
        "Constructor": {"constructorId": "team_alpha", "name": "Team Alpha"},
    }


def _driver_standing_payload(
    driver_id: str,
    given_name: str,
    family_name: str,
    points: int,
) -> dict[str, object]:
    return {
        "position": "1",
        "points": str(points),
        "wins": "1",
        "Driver": {
            "driverId": driver_id,
            "givenName": given_name,
            "familyName": family_name,
        },
        "Constructors": [{"constructorId": "team_alpha", "name": "Team Alpha"}],
    }


def _constructor_standing_payload(
    constructor_id: str,
    constructor_name: str,
    points: int,
) -> dict[str, object]:
    return {
        "position": "1",
        "points": str(points),
        "wins": "1",
        "Constructor": {"constructorId": constructor_id, "name": constructor_name},
    }
