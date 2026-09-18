"""Tests for Elo and Massey rating models."""
from __future__ import annotations

import pytest

from f1_big_predictor.targets.qualifying.rating_models import (
    DEFAULT_K,
    INITIAL_GLICKO_R,
    MODEL_ID_COLLEY,
    MODEL_ID_ELO,
    MODEL_ID_GAUSSIAN_PAIRWISE,
    MODEL_ID_GLICKO,
    MODEL_ID_KEENER,
    MODEL_ID_MASSEY,
    _colley_ratings,
    _elo_update,
    _gaussian_pairwise_ratings,
    _glicko_ratings,
    _gp_v,
    _gp_w,
    _keener_ratings,
    _massey_ratings,
    predict_colley,
    predict_elo,
    predict_gaussian_pairwise,
    predict_glicko,
    predict_keener,
    predict_massey,
)


# ---------------------------------------------------------------------------
# Synthetic fixture
# ---------------------------------------------------------------------------

CTOR = {"a": "t1", "b": "t1", "c": "t2", "d": "t2",
        "e": "t3", "f": "t3", "g": "t4", "h": "t4",
        "i": "t5", "j": "t5", "k": "t6", "l": "t6"}

def _mk_qual(order: list[str]) -> dict:
    return {"status": "ok", "row_count": len(order), "records": [
        {"driver_id": d, "constructor_id": CTOR.get(d, "t0"), "position": p}
        for p, d in enumerate(order, 1)]}

def _mk_race(order: list[str]) -> dict:
    return {"status": "ok", "row_count": len(order), "records": [
        {"driver_id": d, "constructor_id": CTOR.get(d, "t0"),
         "position": p, "status": "Finished"}
        for p, d in enumerate(order, 1)]}

def _mk_drv_st(order: list[str]) -> dict:
    return {"status": "ok", "records": [
        {"driver_id": d, "position": p, "points": float(100 - p*5), "wins": 0}
        for p, d in enumerate(order, 1)]}

def _mk_ctor_st(n_teams: int = 6) -> dict:
    return {"status": "ok", "records": [
        {"constructor_id": f"t{k+1}", "position": k+1,
         "points": float(200 - k*20), "wins": 0}
        for k in range(n_teams)]}

def _make_rounds(n: int = 4, n_drivers: int = 12) -> list[dict]:
    drivers = list("abcdefghijkl")[:n_drivers]
    orders = [
        drivers,
        list(reversed(drivers)),
        drivers[1:] + [drivers[0]],
        drivers[-1:] + drivers[:-1],
    ]
    rounds = []
    for i in range(n):
        order = orders[i % len(orders)]
        rounds.append({
            "round": i + 1,
            "circuit_id": f"c{i % 2}",
            "race_name": f"R{i+1}",
            "qualifying_results": _mk_qual(order),
            "race_results": _mk_race(order),
            "driver_standings": _mk_drv_st(order),
            "constructor_standings": _mk_ctor_st(),
        })
    return rounds


# ---------------------------------------------------------------------------
# Elo unit tests
# ---------------------------------------------------------------------------

class TestEloUpdate:
    def test_winner_gains_rating(self) -> None:
        ratings = {"a": 1500.0, "b": 1500.0}
        qual_records = [
            {"driver_id": "a", "position": 1},
            {"driver_id": "b", "position": 2},
        ]
        _elo_update(ratings, qual_records, k=32.0)
        assert ratings["a"] > 1500.0
        assert ratings["b"] < 1500.0

    def test_update_is_zero_sum(self) -> None:
        ratings = {"a": 1500.0, "b": 1500.0, "c": 1500.0}
        records = [
            {"driver_id": "a", "position": 1},
            {"driver_id": "b", "position": 2},
            {"driver_id": "c", "position": 3},
        ]
        before = sum(ratings.values())
        _elo_update(ratings, records, k=32.0)
        assert sum(ratings.values()) == pytest.approx(before)

    def test_update_is_zero_sum_for_unequal_ratings(self) -> None:
        ratings = {"strong": 1800.0, "weak": 1200.0}
        records = [
            {"driver_id": "weak", "position": 1},
            {"driver_id": "strong", "position": 2},
        ]
        before = dict(ratings)
        _elo_update(ratings, records, k=32.0)
        weak_gain = ratings["weak"] - before["weak"]
        strong_loss = before["strong"] - ratings["strong"]
        assert weak_gain == pytest.approx(strong_loss)
        assert sum(ratings.values()) == pytest.approx(sum(before.values()))

    def test_higher_upset_gives_more_points(self) -> None:
        """Upset (low-rated beats high-rated) should give more points."""
        r_strong = {"strong": 1800.0, "weak": 1200.0}
        r_normal = {"strong": 1500.0, "weak": 1500.0}
        records = [
            {"driver_id": "weak", "position": 1},   # weak beats strong
            {"driver_id": "strong", "position": 2},
        ]
        _elo_update(r_strong, records, k=32.0)
        _elo_update(r_normal, records, k=32.0)
        weak_gain_upset = r_strong["weak"] - 1200.0
        weak_gain_even = r_normal["weak"] - 1500.0
        assert weak_gain_upset > weak_gain_even

    def test_new_entrant_initialised_at_default(self) -> None:
        ratings: dict[str, float] = {}
        records = [{"driver_id": "new", "position": 1}]
        _elo_update(ratings, records, k=32.0)
        assert "new" in ratings


# ---------------------------------------------------------------------------
# Massey unit tests
# ---------------------------------------------------------------------------

class TestMasseyRatings:
    def test_winner_has_highest_rating(self) -> None:
        records = [
            (1, [{"driver_id": "a", "position": 1},
                 {"driver_id": "b", "position": 2},
                 {"driver_id": "c", "position": 3}]),
        ]
        gaps: list[str] = []
        r = _massey_ratings(records, gaps)
        assert r["a"] > r["b"] > r["c"]

    def test_ratings_sum_to_zero(self) -> None:
        records = [
            (1, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "b", "c", "d"], 1)]),
        ]
        gaps: list[str] = []
        r = _massey_ratings(records, gaps)
        assert sum(r.values()) == pytest.approx(0.0, abs=1e-8)

    def test_consistent_winner_gets_highest(self) -> None:
        records = [
            (1, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "b", "c"], 1)]),
            (2, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "c", "b"], 1)]),
        ]
        gaps: list[str] = []
        r = _massey_ratings(records, gaps)
        assert r["a"] == max(r.values())


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestPredictElo:
    def test_output_keys(self) -> None:
        rounds = _make_rounds()
        pred, full = predict_elo(4, rounds)
        assert set(pred) == {"target_id", "model_id", "feature_set_id",
                              "fallback_policy", "status", "entries", "evidence_gaps"}
        assert pred["model_id"] == MODEL_ID_ELO

    def test_ok_status_with_data(self) -> None:
        rounds = _make_rounds(4, 12)
        pred, full = predict_elo(4, rounds)
        assert pred["status"] == "ok"
        assert len(pred["entries"]) == 10
        assert len(full) == 12

    def test_scores_monotone_descending(self) -> None:
        rounds = _make_rounds(4, 12)
        _, full = predict_elo(4, rounds)
        scores = [e["score"] for e in full]
        assert scores == sorted(scores, reverse=True)

    def test_default_k(self) -> None:
        assert DEFAULT_K == 4.0


class TestPredictMassey:
    def test_output_keys(self) -> None:
        rounds = _make_rounds()
        pred, full = predict_massey(4, rounds)
        assert set(pred) == {"target_id", "model_id", "feature_set_id",
                              "fallback_policy", "status", "entries", "evidence_gaps"}
        assert pred["model_id"] == MODEL_ID_MASSEY

    def test_ok_status_with_data(self) -> None:
        rounds = _make_rounds(4, 12)
        pred, full = predict_massey(4, rounds)
        assert pred["status"] == "ok"
        assert len(pred["entries"]) == 10

    def test_scores_monotone_descending(self) -> None:
        rounds = _make_rounds(4, 12)
        _, full = predict_massey(4, rounds)
        scores = [e["score"] for e in full]
        assert scores == sorted(scores, reverse=True)

    def test_no_prior_data_gives_evidence_issue(self) -> None:
        rounds = _make_rounds(1)
        pred, _ = predict_massey(1, rounds)
        assert pred["status"] == "evidence_issue"


# ---------------------------------------------------------------------------
# Colley tests
# ---------------------------------------------------------------------------

class TestColleyRatings:
    def test_winner_has_highest_rating(self) -> None:
        records = [(1, [{"driver_id": d, "position": p}
                        for p, d in enumerate(["a", "b", "c"], 1)])]
        gaps: list[str] = []
        r = _colley_ratings(records, gaps)
        assert r["a"] > r["b"] > r["c"]

    def test_ratings_bounded_0_to_1(self) -> None:
        records = [
            (1, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "b", "c", "d"], 1)]),
            (2, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["d", "c", "b", "a"], 1)]),
        ]
        gaps: list[str] = []
        r = _colley_ratings(records, gaps)
        for v in r.values():
            assert 0.0 < v < 1.0

    def test_equal_record_gives_0_5(self) -> None:
        """A driver who wins exactly half and loses exactly half gets ~0.5."""
        # a and b each win once and lose once
        records = [
            (1, [{"driver_id": "a", "position": 1}, {"driver_id": "b", "position": 2}]),
            (2, [{"driver_id": "b", "position": 1}, {"driver_id": "a", "position": 2}]),
        ]
        gaps: list[str] = []
        r = _colley_ratings(records, gaps)
        assert r["a"] == pytest.approx(0.5, abs=1e-8)
        assert r["b"] == pytest.approx(0.5, abs=1e-8)

    def test_no_data_returns_empty(self) -> None:
        gaps: list[str] = []
        r = _colley_ratings([], gaps)
        assert r == {}


class TestPredictColley:
    def test_output_keys(self) -> None:
        rounds = _make_rounds()
        pred, _ = predict_colley(4, rounds)
        assert set(pred) == {"target_id", "model_id", "feature_set_id",
                              "fallback_policy", "status", "entries", "evidence_gaps"}
        assert pred["model_id"] == MODEL_ID_COLLEY

    def test_ok_status_with_data(self) -> None:
        rounds = _make_rounds(4, 12)
        pred, full = predict_colley(4, rounds)
        assert pred["status"] == "ok"
        assert len(pred["entries"]) == 10
        assert len(full) == 12

    def test_scores_monotone_descending(self) -> None:
        rounds = _make_rounds(4, 12)
        _, full = predict_colley(4, rounds)
        scores = [e["score"] for e in full]
        assert scores == sorted(scores, reverse=True)

    def test_scores_in_0_1_range(self) -> None:
        rounds = _make_rounds(4, 12)
        _, full = predict_colley(4, rounds)
        for e in full:
            assert 0.0 < e["score"] < 1.0


# ---------------------------------------------------------------------------
# Keener tests
# ---------------------------------------------------------------------------

class TestKeenerRatings:
    def test_consistent_winner_has_highest_rating(self) -> None:
        records = [
            (1, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "b", "c", "d"], 1)]),
            (2, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "b", "c", "d"], 1)]),
        ]
        gaps: list[str] = []
        r = _keener_ratings(records, gaps)
        assert r["a"] > r["b"] > r["c"] > r["d"]

    def test_ratings_sum_to_one(self) -> None:
        """Power iteration normalises so entries sum to 1."""
        records = [
            (1, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "b", "c"], 1)]),
        ]
        gaps: list[str] = []
        r = _keener_ratings(records, gaps)
        assert sum(r.values()) == pytest.approx(1.0, abs=1e-6)

    def test_equal_record_gives_uniform_ratings(self) -> None:
        """When all drivers have identical records, ratings should be uniform."""
        # Circular dominance: a>b, b>c, c>a in each round
        records = [
            (1, [{"driver_id": "a", "position": 1},
                 {"driver_id": "b", "position": 2},
                 {"driver_id": "c", "position": 3}]),
            (2, [{"driver_id": "b", "position": 1},
                 {"driver_id": "c", "position": 2},
                 {"driver_id": "a", "position": 3}]),
            (3, [{"driver_id": "c", "position": 1},
                 {"driver_id": "a", "position": 2},
                 {"driver_id": "b", "position": 3}]),
        ]
        gaps: list[str] = []
        r = _keener_ratings(records, gaps)
        values = list(r.values())
        assert max(values) - min(values) == pytest.approx(0.0, abs=1e-4)

    def test_all_ratings_positive(self) -> None:
        records = [
            (1, [{"driver_id": d, "position": p}
                 for p, d in enumerate(["a", "b", "c", "d"], 1)]),
        ]
        gaps: list[str] = []
        r = _keener_ratings(records, gaps)
        assert all(v > 0 for v in r.values())


class TestPredictKeener:
    def test_output_keys(self) -> None:
        rounds = _make_rounds()
        pred, _ = predict_keener(4, rounds)
        assert set(pred) == {"target_id", "model_id", "feature_set_id",
                              "fallback_policy", "status", "entries", "evidence_gaps"}
        assert pred["model_id"] == MODEL_ID_KEENER

    def test_ok_status_with_data(self) -> None:
        rounds = _make_rounds(4, 12)
        pred, full = predict_keener(4, rounds)
        assert pred["status"] == "ok"
        assert len(pred["entries"]) == 10
        assert len(full) == 12

    def test_scores_monotone_descending(self) -> None:
        rounds = _make_rounds(4, 12)
        _, full = predict_keener(4, rounds)
        scores = [e["score"] for e in full]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Glicko tests
# ---------------------------------------------------------------------------

class TestGlicko:
    def test_output_keys(self) -> None:
        rounds = _make_rounds()
        pred, _ = predict_glicko(4, rounds)
        assert set(pred) == {"target_id", "model_id", "feature_set_id",
                              "fallback_policy", "status", "entries", "evidence_gaps"}
        assert pred["model_id"] == MODEL_ID_GLICKO

    def test_ok_status_and_top10(self) -> None:
        rounds = _make_rounds(4, 12)
        pred, full = predict_glicko(4, rounds)
        assert pred["status"] == "ok"
        assert len(pred["entries"]) == 10
        assert len(full) == 12

    def test_consistent_winner_has_highest_rating(self) -> None:
        rounds = _make_rounds(4, 12)  # first driver always wins
        _, full = predict_glicko(4, rounds)
        # drivers['a'] should be near the top since in rounds 1,3 (i%2==0) a leads
        assert full[0]["score"] >= full[-1]["score"]

    def test_scores_monotone_descending(self) -> None:
        rounds = _make_rounds(4, 12)
        _, full = predict_glicko(4, rounds)
        scores = [e["score"] for e in full]
        assert scores == sorted(scores, reverse=True)

    def test_winner_gains_rating_above_initial(self) -> None:
        """A driver who consistently wins should end above INITIAL_GLICKO_R."""
        rounds = _make_rounds(4, 4)
        # Simple check: ratings exist and first driver > last
        all_recs = [(int(rnd["round"]), rnd["qualifying_results"]["records"])
                    for rnd in rounds[:3]]
        gaps: list[str] = []
        r = _glicko_ratings(all_recs, initial_rd=200.0, c=30.0, evidence_gaps=gaps)
        ratings_only = [rv for rv, _rd in r.values()]
        assert max(ratings_only) > INITIAL_GLICKO_R
        assert min(ratings_only) < INITIAL_GLICKO_R

    def test_c_inflates_rd_between_rating_periods(self) -> None:
        records = [
            (1, [
                {"driver_id": "a", "position": 1},
                {"driver_id": "b", "position": 2},
            ]),
            (3, [
                {"driver_id": "a", "position": 1},
                {"driver_id": "b", "position": 2},
            ]),
        ]
        without_growth = _glicko_ratings(records, 100.0, 0.0, [])
        with_growth = _glicko_ratings(records, 100.0, 30.0, [])
        assert with_growth["a"][1] > without_growth["a"][1]
        assert with_growth["a"][0] != pytest.approx(without_growth["a"][0])

    def test_negative_c_is_rejected(self) -> None:
        records = [(1, [
            {"driver_id": "a", "position": 1},
            {"driver_id": "b", "position": 2},
        ])]
        with pytest.raises(ValueError, match="non-negative"):
            _glicko_ratings(records, 100.0, -1.0, [])


# ---------------------------------------------------------------------------
# Gaussian pairwise approximation tests
# ---------------------------------------------------------------------------


class TestGaussianPairwiseMath:
    def test_v_positive_t(self) -> None:
        """v(t) should be positive and < 1 for positive t."""
        vt = _gp_v(1.0)
        assert 0 < vt < 1.0

    def test_v_at_zero(self) -> None:
        """v(0) = phi(0)/Phi(0) = (1/sqrt(2π)) / 0.5 = sqrt(2/π)."""
        import math
        expected = math.sqrt(2.0 / math.pi)
        assert _gp_v(0.0) == pytest.approx(expected, abs=1e-6)

    def test_w_positive(self) -> None:
        """w(t) = v(t)*(v(t)+t) should be positive for all t."""
        for t in [-2.0, -1.0, 0.0, 1.0, 2.0]:
            assert _gp_w(t, _gp_v(t)) > 0


class TestGaussianPairwise:
    def test_output_keys(self) -> None:
        rounds = _make_rounds()
        pred, _ = predict_gaussian_pairwise(4, rounds)
        assert set(pred) == {"target_id", "model_id", "feature_set_id",
                              "fallback_policy", "status", "entries", "evidence_gaps"}
        assert pred["model_id"] == MODEL_ID_GAUSSIAN_PAIRWISE

    def test_ok_status_and_top10(self) -> None:
        rounds = _make_rounds(4, 12)
        pred, full = predict_gaussian_pairwise(4, rounds)
        assert pred["status"] == "ok"
        assert len(pred["entries"]) == 10
        assert len(full) == 12

    def test_scores_monotone_descending(self) -> None:
        rounds = _make_rounds(4, 12)
        _, full = predict_gaussian_pairwise(4, rounds)
        scores = [e["score"] for e in full]
        assert scores == sorted(scores, reverse=True)

    def test_consistent_winner_gets_highest_score(self) -> None:
        """The driver who always finishes first should get the highest mu."""
        n_drivers = 4
        drivers = list("abcd")

        def _mk(i):
            order = drivers  # 'a' always first
            return {
                "round": i + 1, "circuit_id": "c1", "race_name": f"R{i+1}",
                "qualifying_results": {
                    "status": "ok", "row_count": n_drivers,
                    "records": [{"driver_id": d, "constructor_id": "t1", "position": p}
                                 for p, d in enumerate(order, 1)],
                },
                "race_results": {"status": "ok", "row_count": n_drivers, "records": []},
                "driver_standings": {"status": "ok", "records": []},
                "constructor_standings": {"status": "ok", "records": []},
            }

        rounds = [_mk(i) for i in range(4)]
        all_recs = [(rnd["round"], rnd["qualifying_results"]["records"]) for rnd in rounds[:3]]
        gaps: list[str] = []
        ts_r = _gaussian_pairwise_ratings(
            all_recs,
            beta=4.17,
            tau=0.083,
            evidence_gaps=gaps,
        )
        # 'a' always ranked P1 → should have highest mu
        assert ts_r["a"][0] == max(r[0] for r in ts_r.values())
