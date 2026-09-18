"""Tests for Bradley-Terry and Plackett-Luce probability ranking models."""
from __future__ import annotations

import pytest

from f1_big_predictor.targets.qualifying.probability_models import (
    MODEL_ID_BT, MODEL_ID_PL,
    _bradley_terry_ratings, _plackett_luce_ratings,
    predict_bradley_terry, predict_plackett_luce,
)


# ---------------------------------------------------------------------------
# Synthetic fixture
# ---------------------------------------------------------------------------

def _mk_rounds(n=4, nd=12):
    drivers = list("abcdefghijkl")[:nd]
    ctor = {d: f"t{i//2+1}" for i, d in enumerate(drivers)}

    def _mk(i):
        order = drivers[i % 2:] + drivers[:i % 2]
        return {
            "round": i + 1, "circuit_id": "c1", "race_name": f"R{i+1}",
            "qualifying_results": {"status": "ok", "row_count": nd, "records": [
                {"driver_id": d, "constructor_id": ctor[d], "position": p}
                for p, d in enumerate(order, 1)]},
            "race_results": {"status": "ok", "row_count": nd, "records": []},
            "driver_standings": {"status": "ok", "records": []},
            "constructor_standings": {"status": "ok", "records": []},
        }

    return [_mk(i) for i in range(n)]


# ---------------------------------------------------------------------------
# Bradley-Terry unit tests
# ---------------------------------------------------------------------------

class TestBradleyTerry:
    def test_consistent_winner_has_highest_lambda(self):
        records = [
            (1, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "b", "c", "d"], 1)]),
            (2, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "b", "c", "d"], 1)]),
        ]
        gaps = []
        r = _bradley_terry_ratings(records, gaps)
        assert r["a"] > r["b"] > r["c"] > r["d"]

    def test_symmetric_gives_equal_lambda(self):
        """a wins half, b wins half → nearly equal λ."""
        records = [
            (1, [{"driver_id": "a", "position": 1}, {"driver_id": "b", "position": 2}]),
            (2, [{"driver_id": "b", "position": 1}, {"driver_id": "a", "position": 2}]),
        ]
        gaps = []
        r = _bradley_terry_ratings(records, gaps)
        assert abs(r["a"] - r["b"]) < 1e-6

    def test_mean_lambda_is_one(self):
        records = [
            (1, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "b", "c"], 1)]),
        ]
        gaps = []
        r = _bradley_terry_ratings(records, gaps)
        assert sum(r.values()) / len(r) == pytest.approx(1.0, abs=1e-6)

    def test_predict_output_shape(self):
        rounds = _mk_rounds(4, 12)
        pred, full = predict_bradley_terry(4, rounds)
        assert pred["model_id"] == MODEL_ID_BT
        assert pred["status"] == "ok"
        assert len(pred["entries"]) == 10
        assert len(full) == 12

    def test_scores_monotone(self):
        rounds = _mk_rounds(4, 12)
        _, full = predict_bradley_terry(4, rounds)
        scores = [e["score"] for e in full]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Plackett-Luce unit tests
# ---------------------------------------------------------------------------

class TestPlackettLuce:
    def test_consistent_winner_has_highest_lambda(self):
        records = [
            (1, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "b", "c", "d"], 1)]),
            (2, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "b", "c", "d"], 1)]),
        ]
        gaps = []
        r = _plackett_luce_ratings(records, gaps)
        assert r["a"] > r["b"] > r["c"] > r["d"]

    def test_mean_lambda_is_one(self):
        records = [
            (1, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "b", "c"], 1)]),
        ]
        gaps = []
        r = _plackett_luce_ratings(records, gaps)
        assert sum(r.values()) / len(r) == pytest.approx(1.0, abs=1e-6)

    def test_one_mm_iteration_excludes_constant_final_stage(self):
        records = [
            (1, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "b", "c"], 1)]),
        ]
        ratings = _plackett_luce_ratings(records, [], max_iter=1)
        assert ratings == pytest.approx({
            "a": 15.0 / 7.0,
            "b": 6.0 / 7.0,
            "c": 0.0,
        })

    def test_circular_gives_uniform(self):
        """Circular dominance → uniform λ."""
        records = [
            (1, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "b", "c"], 1)]),
            (2, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["b", "c", "a"], 1)]),
            (3, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["c", "a", "b"], 1)]),
        ]
        gaps = []
        r = _plackett_luce_ratings(records, gaps)
        vals = list(r.values())
        assert max(vals) - min(vals) == pytest.approx(0.0, abs=1e-4)

    def test_predict_output_shape(self):
        rounds = _mk_rounds(4, 12)
        pred, full = predict_plackett_luce(4, rounds)
        assert pred["model_id"] == MODEL_ID_PL
        assert pred["status"] == "ok"
        assert len(pred["entries"]) == 10
        assert len(full) == 12

    def test_scores_monotone(self):
        rounds = _mk_rounds(4, 12)
        _, full = predict_plackett_luce(4, rounds)
        scores = [e["score"] for e in full]
        assert scores == sorted(scores, reverse=True)
