"""Tests for the Ridge multi-factor model."""
from __future__ import annotations

import pytest

from f1_big_predictor.targets.qualifying.ridge_model import (
    MODEL_ID,
    STAT_FEATURES,
    _fit_scaler,
    _apply_scaler,
    _ridge_fit,
    _solve_linear,
    _target,
    predict_ridge,
)


# ---------------------------------------------------------------------------
# Synthetic fixture (reused from test_qualifying_single_factor)
# ---------------------------------------------------------------------------

CTOR = {"a": "team_1", "b": "team_1", "c": "team_2", "d": "team_2"}


def _qual(order, ctor=CTOR):
    return {"status": "ok", "row_count": len(order), "records": [
        {"driver_id": d, "constructor_id": ctor[d], "position": p}
        for p, d in enumerate(order, 1)
    ]}


def _race(order, ctor=CTOR):
    return {"status": "ok", "row_count": len(order), "records": [
        {"driver_id": d, "constructor_id": ctor[d], "position": p, "status": "Finished"}
        for p, d in enumerate(order, 1)
    ]}


def _drv_st(order):
    return {"status": "ok", "records": [
        {"driver_id": d, "position": p, "points": float(100 - p * 10), "wins": 0}
        for p, d in enumerate(order, 1)
    ]}


def _ctor_st(order):
    return {"status": "ok", "records": [
        {"constructor_id": c, "position": p, "points": float(200 - p * 20), "wins": 0}
        for p, c in enumerate(order, 1)
    ]}


def _make_rounds(n: int = 4) -> list[dict]:
    """Build n rounds of synthetic data (4 drivers, consistent ordering)."""
    orders = [
        ["a", "b", "c", "d"],
        ["b", "a", "d", "c"],
        ["a", "c", "b", "d"],
        ["b", "a", "c", "d"],
    ]
    drv_sts = [
        ["a", "b", "c", "d"],
        ["b", "a", "c", "d"],
        ["a", "b", "c", "d"],
        ["b", "a", "c", "d"],
    ]
    rounds = []
    for i in range(n):
        q_order = orders[i % len(orders)]
        r_order = list(reversed(q_order))
        rounds.append({
            "round": i + 1,
            "circuit_id": f"circuit_{i % 2}",
            "race_name": f"Race {i + 1}",
            "qualifying_results": _qual(q_order),
            "race_results": _race(r_order),
            "driver_standings": _drv_st(drv_sts[i % len(drv_sts)]),
            "constructor_standings": _ctor_st(["team_1", "team_2"]),
        })
    return rounds


# ---------------------------------------------------------------------------
# Linear algebra helpers
# ---------------------------------------------------------------------------

class TestLinearAlgebra:
    def test_solve_identity(self) -> None:
        # Ax = b where A=I, b=[1,2,3] → x=[1,2,3]
        A = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
        b = [1.0, 2.0, 3.0]
        x = _solve_linear(A, b)
        assert x == pytest.approx([1.0, 2.0, 3.0])

    def test_solve_2x2(self) -> None:
        # 2x + y = 5, x + 3y = 10 → x=1, y=3
        A = [[2.0, 1.0], [1.0, 3.0]]
        b = [5.0, 10.0]
        x = _solve_linear(A, b)
        assert x == pytest.approx([1.0, 3.0], abs=1e-10)

    def test_ridge_fit_recovers_true_weights(self) -> None:
        """With low alpha on a clean dataset, Ridge should nearly recover weights."""
        # y = 2*x1 + 3*x2 + 1 (intercept)
        X = [
            [1.0, 0.0, 1.0],  # intercept always last
            [0.0, 1.0, 1.0],
            [1.0, 1.0, 1.0],
            [2.0, 0.0, 1.0],
            [0.0, 2.0, 1.0],
            [2.0, 2.0, 1.0],
        ]
        y = [2 * x[0] + 3 * x[1] + 1 for x in X]
        beta = _ridge_fit(X, y, alpha=0.001)
        # With small alpha, should be close to [2, 3, 1]
        assert beta[0] == pytest.approx(2.0, abs=0.05)
        assert beta[1] == pytest.approx(3.0, abs=0.05)
        assert beta[2] == pytest.approx(1.0, abs=0.05)


class TestScaler:
    def test_fit_scaler_returns_correct_stats(self) -> None:
        X = [[1.0, 10.0], [3.0, 20.0], [5.0, 30.0]]
        means, stds = _fit_scaler(X)
        assert means == pytest.approx([3.0, 20.0])
        assert stds == pytest.approx([pytest.approx(x) for x in [
            ((4 + 0 + 4) / 3) ** 0.5,  # std of [1,3,5]
            ((100 + 0 + 100) / 3) ** 0.5,  # std of [10,20,30]
        ]])

    def test_apply_scaler_imputes_none(self) -> None:
        X_train = [[1.0, 2.0], [3.0, 4.0]]
        means, stds = _fit_scaler(X_train)
        X_test = [[None, 3.0]]
        result = _apply_scaler(X_test, means, stds)
        # None → imputed with mean (2.0 for first col) → standardised to 0
        assert result[0][0] == pytest.approx(0.0)

    def test_apply_scaler_adds_intercept(self) -> None:
        X_train = [[1.0, 2.0], [3.0, 4.0]]
        means, stds = _fit_scaler(X_train)
        result = _apply_scaler(X_train, means, stds)
        assert result[0][-1] == 1.0  # intercept always appended


class TestTargetTransform:
    def test_p1_maps_to_one(self) -> None:
        assert _target(1, 22) == pytest.approx(1.0)

    def test_p22_maps_to_small_positive(self) -> None:
        assert _target(22, 22) == pytest.approx(1 / 22.0)

    def test_p19_uses_the_19_driver_event_size(self) -> None:
        assert _target(19, 19) == pytest.approx(1 / 19.0)

    def test_strictly_decreasing(self) -> None:
        scores = [_target(p, 22) for p in range(1, 23)]
        assert scores == sorted(scores, reverse=True)

    def test_out_of_range_position_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="within 1..19"):
            _target(20, 19)


# ---------------------------------------------------------------------------
# predict_ridge integration tests
# ---------------------------------------------------------------------------

class TestPredictRidge:
    def test_output_shape(self) -> None:
        rounds = _make_rounds(4)
        pred, full = predict_ridge(target_round=4, completed_rounds=rounds)
        assert set(pred) == {
            "target_id", "model_id", "feature_set_id",
            "fallback_policy", "status", "entries", "evidence_gaps",
        }
        assert pred["target_id"] == "qualifying"
        assert pred["model_id"] == MODEL_ID

    def test_ok_status_and_top10_with_enough_data(self) -> None:
        # Build 12-driver rounds so top10 is feasible
        drivers = list("abcdefghijkl")
        ctor = {d: f"team_{i // 2 + 1}" for i, d in enumerate(drivers)}

        def _make_big_round(n, order):
            return {
                "round": n,
                "circuit_id": "c1",
                "race_name": f"R{n}",
                "qualifying_results": {
                    "status": "ok", "row_count": len(order),
                    "records": [{"driver_id": d, "constructor_id": ctor[d], "position": p}
                                 for p, d in enumerate(order, 1)]
                },
                "race_results": {
                    "status": "ok", "row_count": len(order),
                    "records": [{"driver_id": d, "constructor_id": ctor[d], "position": p, "status": "Finished"}
                                 for p, d in enumerate(order, 1)]
                },
                "driver_standings": {"status": "ok", "records": [
                    {"driver_id": d, "position": p, "points": float(100 - p * 5), "wins": 0}
                    for p, d in enumerate(order, 1)
                ]},
                "constructor_standings": {"status": "ok", "records": [
                    {"constructor_id": f"team_{i+1}", "position": i + 1,
                     "points": float(200 - i * 20), "wins": 0}
                    for i in range(6)
                ]},
            }

        base = list("abcdefghijkl")
        rounds = [_make_big_round(i + 1, base) for i in range(4)]
        pred, full = predict_ridge(target_round=4, completed_rounds=rounds)
        assert pred["status"] == "ok"
        assert len(pred["entries"]) == 10
        assert len(full) == 12

    def test_evidence_gap_when_no_prior_data(self) -> None:
        rounds = _make_rounds(1)
        pred, _ = predict_ridge(target_round=1, completed_rounds=rounds)
        assert pred["status"] == "evidence_issue"

    def test_scores_decrease_monotonically_in_full_ranking(self) -> None:
        rounds = _make_rounds(4)
        _pred, full = predict_ridge(target_round=4, completed_rounds=rounds)
        if len(full) >= 2:
            scores = [e["score"] for e in full]
            assert scores == sorted(scores, reverse=True)

    def test_stat_features_contains_10_features(self) -> None:
        assert len(STAT_FEATURES) == 10
        assert "qual_teammate_delta_prev" not in STAT_FEATURES
        assert "qual_same_circuit_mean" not in STAT_FEATURES
