from f1_big_predictor.circuit_history import (
    CircuitHistoryDataset,
    circuit_history_scores_for_round,
    collect_circuit_history,
    load_circuit_history_dataset,
    load_circuit_history_scores,
)
from f1_big_predictor.jolpica import (
    ConstructorStanding,
    DriverResult,
    DriverStanding,
    QualifyingResult,
    RaceInfo,
)


def test_collect_circuit_history_matches_same_circuit_and_scores_current_drivers(tmp_path):
    output = tmp_path / "processed" / "canada.json"
    payload = collect_circuit_history(
        season=2026,
        target_round=5,
        lookback_years=2,
        project_root=tmp_path,
        output_path=output,
        client=_FakeCircuitHistoryClient(),
    )

    assert output.exists()
    assert payload["schema"] == "circuit_history_event_v1"
    assert payload["race_name"] == "Canadian Grand Prix"
    assert payload["matched_historical_events"][0]["historical_season"] == 2025
    assert payload["matched_historical_events"][0]["match_method"] == "circuit_id"
    assert payload["skipped_historical_events"][0]["historical_season"] == 2024

    scores = {row["driver_id"]: row for row in payload["driver_history_scores"]}
    assert scores["alpha"]["coverage_count"] == 1
    assert scores["alpha"]["race_score"] > scores["beta"]["race_score"]
    assert scores["alpha"]["teammate_relative_score"] > 0.5
    assert scores["rookie"]["coverage_count"] == 0
    assert scores["rookie"]["composite_score"] == 0.5
    assert "no_same_circuit_history" in scores["rookie"]["evidence_issues"]
    assert load_circuit_history_scores(output)["rookie"] == 0.5
    dataset = load_circuit_history_dataset(output)
    assert isinstance(dataset, CircuitHistoryDataset)
    assert dataset.target_round == 5
    model_scores, evidence_issues = circuit_history_scores_for_round(
        output,
        season=2026,
        target_round=5,
    )
    assert model_scores["rookie"] == 0.5
    assert "rookie: no_same_circuit_history" in evidence_issues


def test_collect_circuit_history_prefers_same_race_name_when_circuit_repeats(tmp_path):
    payload = collect_circuit_history(
        season=2026,
        target_round=8,
        lookback_years=1,
        project_root=tmp_path,
        client=_FakeRepeatedCircuitClient(),
    )

    matched = payload["matched_historical_events"][0]
    assert matched["race_name"] == "Austrian Grand Prix"
    assert matched["historical_round"] == 2
    assert matched["match_method"] == "circuit_id"


class _FakeCircuitHistoryClient:
    def race_info(self, season: int, round_: int):  # pragma: no cover - must not be used
        raise AssertionError("target race_info would fetch target race results")

    def race_schedule(self, season: int) -> list[RaceInfo]:
        if season == 2026:
            return [
                RaceInfo(
                    season,
                    5,
                    "Canadian Grand Prix",
                    "2026-05-24",
                    "villeneuve",
                    "Circuit Gilles Villeneuve",
                )
            ]
        if season == 2025:
            return [
                RaceInfo(
                    season,
                    9,
                    "Montreal Grand Prix",
                    "2025-06-15",
                    "villeneuve",
                    "Circuit Gilles Villeneuve",
                )
            ]
        return [
            RaceInfo(
                season,
                9,
                "Canadian Grand Prix",
                "2024-06-09",
                "different_circuit",
                "Different Circuit",
            )
        ]

    def driver_standings(self, season: int, round_: int) -> list[DriverStanding]:
        assert season == 2026
        assert round_ == 4
        return [
            DriverStanding("alpha", "ALP", "Alpha Driver", "team_a", "Team A", 1, 80, 2),
            DriverStanding("beta", "BET", "Beta Driver", "team_a", "Team A", 2, 70, 1),
            DriverStanding("rookie", "ROO", "Rookie Driver", "team_b", "Team B", 3, 10, 0),
        ]

    def constructor_standings(self, season: int, round_: int) -> list[ConstructorStanding]:
        return []

    def race_results(self, season: int, round_: int) -> list[DriverResult]:
        assert (season, round_) == (2025, 9)
        return [
            DriverResult("alpha", "ALP", "Alpha Driver", "team_a", "Team A", 1, 1, 25, "Finished"),
            DriverResult("gamma", "GAM", "Gamma Driver", "team_b", "Team B", 2, 2, 18, "Finished"),
            DriverResult("beta", "BET", "Beta Driver", "team_a", "Team A", 3, 3, 15, "Accident"),
        ]

    def qualifying_results(self, season: int, round_: int) -> list[QualifyingResult]:
        assert (season, round_) == (2025, 9)
        return [
            QualifyingResult("beta", "BET", "Beta Driver", "team_a", "Team A", 1, q3="1:10.000"),
            QualifyingResult("alpha", "ALP", "Alpha Driver", "team_a", "Team A", 2, q3="1:10.100"),
            QualifyingResult("gamma", "GAM", "Gamma Driver", "team_b", "Team B", 3, q3="1:10.200"),
        ]

    def sprint_results(self, season: int, round_: int) -> list[DriverResult]:
        assert (season, round_) == (2025, 9)
        return []


class _FakeRepeatedCircuitClient:
    def race_schedule(self, season: int) -> list[RaceInfo]:
        if season == 2026:
            return [
                RaceInfo(
                    season,
                    8,
                    "Austrian Grand Prix",
                    "2026-06-28",
                    "red_bull_ring",
                    "Red Bull Ring",
                )
            ]
        return [
            RaceInfo(
                season,
                1,
                "Styrian Grand Prix",
                "2025-06-22",
                "red_bull_ring",
                "Red Bull Ring",
            ),
            RaceInfo(
                season,
                2,
                "Austrian Grand Prix",
                "2025-06-29",
                "red_bull_ring",
                "Red Bull Ring",
            ),
        ]

    def driver_standings(self, season: int, round_: int) -> list[DriverStanding]:
        return [
            DriverStanding("alpha", "ALP", "Alpha Driver", "team_a", "Team A", 1, 80, 2),
        ]

    def race_results(self, season: int, round_: int) -> list[DriverResult]:
        assert (season, round_) == (2025, 2)
        return [
            DriverResult("alpha", "ALP", "Alpha Driver", "team_a", "Team A", 1, 1, 25, "Finished"),
        ]

    def qualifying_results(self, season: int, round_: int) -> list[QualifyingResult]:
        assert (season, round_) == (2025, 2)
        return [
            QualifyingResult("alpha", "ALP", "Alpha Driver", "team_a", "Team A", 1, q3="1:04.000"),
        ]

    def sprint_results(self, season: int, round_: int) -> list[DriverResult]:
        assert (season, round_) == (2025, 2)
        return []
