"""Tests for feature_matrix and single_factor_diagnosis."""
from __future__ import annotations

import math
import pytest

from f1_big_predictor.targets.qualifying.feature_matrix import (
    FEATURE_NAMES,
    build_feature_matrix,
)
from f1_big_predictor.targets.qualifying.single_factor_diagnosis import (
    _spearman_rho,
    run_single_factor_diagnosis,
)


# ---------------------------------------------------------------------------
# Minimal synthetic fixture (3 rounds, 4 drivers, 2 constructors)
# ---------------------------------------------------------------------------

def _qual(order: list[str], ctor: dict[str, str]) -> dict:
    return {
        "status": "ok",
        "row_count": len(order),
        "records": [
            {"driver_id": did, "constructor_id": ctor[did], "position": pos}
            for pos, did in enumerate(order, start=1)
        ],
    }


def _race(order: list[str], ctor: dict[str, str]) -> dict:
    return {
        "status": "ok",
        "row_count": len(order),
        "records": [
            {"driver_id": did, "constructor_id": ctor[did], "position": pos, "status": "Finished"}
            for pos, did in enumerate(order, start=1)
        ],
    }


def _drv_standings(order: list[str]) -> dict:
    return {
        "status": "ok",
        "records": [
            {"driver_id": did, "position": pos, "points": float(100 - pos * 10), "wins": 0}
            for pos, did in enumerate(order, start=1)
        ],
    }


def _ctor_standings(order: list[str]) -> dict:
    return {
        "status": "ok",
        "records": [
            {"constructor_id": cid, "position": pos, "points": float(200 - pos * 20), "wins": 0}
            for pos, cid in enumerate(order, start=1)
        ],
    }


CTOR = {"a": "team_1", "b": "team_1", "c": "team_2", "d": "team_2"}


def _make_rounds() -> list[dict]:
    return [
        {
            "round": 1,
            "circuit_id": "circuit_alpha",
            "race_name": "Race One",
            "qualifying_results": _qual(["a", "b", "c", "d"], CTOR),
            "race_results": _race(["b", "a", "d", "c"], CTOR),
            "driver_standings": _drv_standings(["a", "b", "c", "d"]),
            "constructor_standings": _ctor_standings(["team_1", "team_2"]),
        },
        {
            "round": 2,
            "circuit_id": "circuit_beta",
            "race_name": "Race Two",
            "qualifying_results": _qual(["b", "a", "d", "c"], CTOR),
            "race_results": _race(["a", "b", "c", "d"], CTOR),
            "driver_standings": _drv_standings(["b", "a", "c", "d"]),
            "constructor_standings": _ctor_standings(["team_1", "team_2"]),
        },
        {
            "round": 3,
            "circuit_id": "circuit_alpha",   # same as R1 → triggers same-circuit feature
            "race_name": "Race Three",
            "qualifying_results": _qual(["a", "c", "b", "d"], CTOR),
            "race_results": _race(["a", "c", "b", "d"], CTOR),
            "driver_standings": _drv_standings(["a", "b", "c", "d"]),
            "constructor_standings": _ctor_standings(["team_1", "team_2"]),
        },
    ]


# ---------------------------------------------------------------------------
# feature_matrix tests
# ---------------------------------------------------------------------------

class TestFeatureMatrix:
    def test_returns_one_row_per_driver(self) -> None:
        rounds = _make_rounds()
        matrix = build_feature_matrix(target_round=2, completed_rounds=rounds)
        assert len(matrix) == 4
        assert {row["driver_id"] for row in matrix} == {"a", "b", "c", "d"}

    def test_standings_features_populated(self) -> None:
        rounds = _make_rounds()
        matrix = build_feature_matrix(target_round=2, completed_rounds=rounds)
        row_a = next(r for r in matrix if r["driver_id"] == "a")
        assert row_a["drv_standings_pos"] == 1.0   # a is P1 in drv standings after R1
        assert row_a["ctor_standings_pos"] == 1.0  # team_1 is P1 in ctor standings

    def test_qual_pos_prev_correct(self) -> None:
        rounds = _make_rounds()
        matrix = build_feature_matrix(target_round=2, completed_rounds=rounds)
        row_a = next(r for r in matrix if r["driver_id"] == "a")
        row_b = next(r for r in matrix if r["driver_id"] == "b")
        assert row_a["qual_pos_prev"] == 1.0
        assert row_b["qual_pos_prev"] == 2.0

    def test_qual_pos_season_equals_prev_with_one_prior_round(self) -> None:
        rounds = _make_rounds()
        matrix = build_feature_matrix(target_round=2, completed_rounds=rounds)
        for row in matrix:
            assert row["qual_pos_season"] == row["qual_pos_prev"]

    def test_same_circuit_feature_on_repeat_circuit(self) -> None:
        rounds = _make_rounds()
        # R3 circuit_alpha == R1 circuit_alpha → should have prior data
        matrix = build_feature_matrix(target_round=3, completed_rounds=rounds)
        row_a = next(r for r in matrix if r["driver_id"] == "a")
        assert row_a["qual_same_circuit_mean"] == 1.0  # a was P1 at circuit_alpha in R1

    def test_same_circuit_none_on_new_circuit(self) -> None:
        rounds = _make_rounds()
        # R2 is at circuit_beta (never seen before)
        matrix = build_feature_matrix(target_round=2, completed_rounds=rounds)
        for row in matrix:
            assert row["qual_same_circuit_mean"] is None

    def test_teammate_delta_correct(self) -> None:
        rounds = _make_rounds()
        matrix = build_feature_matrix(target_round=2, completed_rounds=rounds)
        row_a = next(r for r in matrix if r["driver_id"] == "a")
        row_b = next(r for r in matrix if r["driver_id"] == "b")
        # R1: a=P1, b=P2 → a's delta = 1-2 = -1 (beat), b's = 2-1 = +1
        assert row_a["qual_teammate_delta_prev"] == pytest.approx(-1.0)
        assert row_b["qual_teammate_delta_prev"] == pytest.approx(1.0)

    def test_all_feature_names_present_in_each_row(self) -> None:
        rounds = _make_rounds()
        matrix = build_feature_matrix(target_round=2, completed_rounds=rounds)
        for row in matrix:
            for feat in FEATURE_NAMES:
                assert feat in row, f"Missing feature {feat!r} in row for {row['driver_id']}"

    def test_empty_on_missing_target_round(self) -> None:
        rounds = _make_rounds()
        assert build_feature_matrix(target_round=99, completed_rounds=rounds) == []

    def test_qual_mean3_averages_last_three(self) -> None:
        rounds = _make_rounds()
        # For R3: prior = R1(a=P1) + R2(a=P2) → mean3 = 1.5
        matrix = build_feature_matrix(target_round=3, completed_rounds=rounds)
        row_a = next(r for r in matrix if r["driver_id"] == "a")
        assert row_a["qual_pos_mean3"] == pytest.approx(1.5)

    def test_race_pos_prev_correct(self) -> None:
        rounds = _make_rounds()
        matrix = build_feature_matrix(target_round=2, completed_rounds=rounds)
        # R1 race: b=P1, a=P2, d=P3, c=P4
        row_a = next(r for r in matrix if r["driver_id"] == "a")
        assert row_a["race_pos_prev"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Spearman helper tests
# ---------------------------------------------------------------------------

class TestSpearmanRho:
    def test_perfect_positive(self) -> None:
        assert _spearman_rho([1, 2, 3, 4], [1, 2, 3, 4]) == pytest.approx(1.0)

    def test_perfect_negative(self) -> None:
        assert _spearman_rho([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)

    def test_nan_on_too_few_points(self) -> None:
        assert math.isnan(_spearman_rho([1.0, 2.0], [1.0, 2.0]))

    def test_nan_on_constant_x(self) -> None:
        assert math.isnan(_spearman_rho([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]))


# ---------------------------------------------------------------------------
# single_factor_diagnosis tests
# ---------------------------------------------------------------------------

class TestSingleFactorDiagnosis:
    def test_all_features_in_output(self) -> None:
        result = run_single_factor_diagnosis(_make_rounds(), first_round=2, last_round=3)
        assert {f["feature"] for f in result["features"]} == set(FEATURE_NAMES)

    def test_standings_coverage_is_full(self) -> None:
        result = run_single_factor_diagnosis(_make_rounds(), first_round=2, last_round=3)
        feat = next(f for f in result["features"] if f["feature"] == "drv_standings_pos")
        assert feat["coverage"] == pytest.approx(1.0)

    def test_same_circuit_partial_coverage(self) -> None:
        result = run_single_factor_diagnosis(_make_rounds(), first_round=2, last_round=3)
        feat = next(f for f in result["features"] if f["feature"] == "qual_same_circuit_mean")
        # R2 (circuit_beta): 0/4 have data; R3 (circuit_alpha): 4/4 have data
        # coverage = 4 / 8 = 0.5
        assert feat["coverage"] == pytest.approx(0.5)

    def test_per_round_length(self) -> None:
        result = run_single_factor_diagnosis(_make_rounds(), first_round=2, last_round=3)
        for feat in result["features"]:
            assert len(feat["per_round"]) == 2

    def test_summary_sorted_by_abs_rho_descending(self) -> None:
        result = run_single_factor_diagnosis(_make_rounds(), first_round=2, last_round=3)
        abs_rhos = [r["abs_rho"] for r in result["summary"]]
        assert abs_rhos == sorted(abs_rhos, reverse=True)

    def test_round_count_and_rounds_list(self) -> None:
        result = run_single_factor_diagnosis(_make_rounds(), first_round=2, last_round=3)
        assert result["round_count"] == 2
        assert result["rounds"] == [2, 3]

    def test_stability_fields_present(self) -> None:
        result = run_single_factor_diagnosis(_make_rounds(), first_round=2, last_round=3)
        for feat in result["features"]:
            stab = feat["stability"]
            assert set(stab.keys()) == {"n_rounds", "mean", "std", "min", "max"}
