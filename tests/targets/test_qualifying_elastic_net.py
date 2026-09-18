"""Tests for the Elastic Net multi-factor model."""
from __future__ import annotations

import pytest

from f1_big_predictor.targets.qualifying.elastic_net_model import (
    DEFAULT_ALPHA,
    DEFAULT_L1_RATIO,
    MODEL_ID,
    _elastic_net_fit,
    _soft_threshold,
    predict_elastic_net,
)


# ---------------------------------------------------------------------------
# Helpers (same synthetic data as Ridge tests)
# ---------------------------------------------------------------------------

CTOR = {"a": "team_1", "b": "team_1", "c": "team_2", "d": "team_2"}

def _make_rounds(n=4):
    orders = [["a","b","c","d"],["b","a","d","c"],["a","c","b","d"],["b","a","c","d"]]
    def _mk(i):
        q = orders[i % len(orders)]
        r = list(reversed(q))
        drv_ord = [["a","b","c","d"],["b","a","c","d"]][i % 2]
        return {
            "round": i + 1, "circuit_id": f"c{i%2}", "race_name": f"R{i+1}",
            "qualifying_results": {"status":"ok","row_count":4,"records":[
                {"driver_id":d,"constructor_id":CTOR[d],"position":p} for p,d in enumerate(q,1)]},
            "race_results": {"status":"ok","row_count":4,"records":[
                {"driver_id":d,"constructor_id":CTOR[d],"position":p,"status":"Finished"} for p,d in enumerate(r,1)]},
            "driver_standings": {"status":"ok","records":[
                {"driver_id":d,"position":p,"points":float(100-p*10),"wins":0} for p,d in enumerate(drv_ord,1)]},
            "constructor_standings": {"status":"ok","records":[
                {"constructor_id":c,"position":p,"points":float(200-p*20),"wins":0} for p,c in enumerate(["team_1","team_2"],1)]},
        }
    return [_mk(i) for i in range(n)]


def _make_big_rounds(n=4, n_drivers=12):
    drivers = list("abcdefghijkl")[:n_drivers]
    ctor = {d: f"team_{i//2+1}" for i,d in enumerate(drivers)}
    n_teams = n_drivers // 2
    def _mk(i):
        order = drivers[i%2:] + drivers[:i%2]
        return {
            "round": i+1, "circuit_id": "c1", "race_name": f"R{i+1}",
            "qualifying_results": {"status":"ok","row_count":n_drivers,"records":[
                {"driver_id":d,"constructor_id":ctor[d],"position":p} for p,d in enumerate(order,1)]},
            "race_results": {"status":"ok","row_count":n_drivers,"records":[
                {"driver_id":d,"constructor_id":ctor[d],"position":p,"status":"Finished"} for p,d in enumerate(order,1)]},
            "driver_standings": {"status":"ok","records":[
                {"driver_id":d,"position":p,"points":float(100-p*5),"wins":0} for p,d in enumerate(order,1)]},
            "constructor_standings": {"status":"ok","records":[
                {"constructor_id":f"team_{k+1}","position":k+1,"points":float(200-k*20),"wins":0} for k in range(n_teams)]},
        }
    return [_mk(i) for i in range(n)]


# ---------------------------------------------------------------------------
# Unit tests for solver and helpers
# ---------------------------------------------------------------------------

class TestSoftThreshold:
    def test_positive_above_threshold(self):
        assert _soft_threshold(5.0, 2.0) == pytest.approx(3.0)

    def test_negative_above_threshold(self):
        assert _soft_threshold(-5.0, 2.0) == pytest.approx(-3.0)

    def test_within_threshold_returns_zero(self):
        assert _soft_threshold(1.0, 2.0) == 0.0
        assert _soft_threshold(-1.0, 2.0) == 0.0

    def test_exactly_at_threshold_returns_zero(self):
        assert _soft_threshold(2.0, 2.0) == 0.0


class TestElasticNetFit:
    def _make_X_with_intercept(self, X_feat):
        return [row + [1.0] for row in X_feat]

    def test_recovers_weights_low_alpha(self):
        # y = 2x1 + 3x2 + 1 on standardised features → near [2, 3, 1]
        X_feat = [[1.0, 0.0],[0.0,1.0],[1.0,1.0],[2.0,0.0],[0.0,2.0],[2.0,2.0],
                   [-1.0,0.0],[0.0,-1.0],[1.5,0.5],[-0.5,1.5]]
        X = self._make_X_with_intercept(X_feat)
        y = [2*r[0] + 3*r[1] + 1 for r in X_feat]
        beta = _elastic_net_fit(X, y, alpha=0.001, l1_ratio=0.5)
        assert beta[0] == pytest.approx(2.0, abs=0.1)
        assert beta[1] == pytest.approx(3.0, abs=0.1)
        assert beta[2] == pytest.approx(1.0, abs=0.1)

    def test_lasso_produces_sparse_solution(self):
        # l1_ratio=1 → pure Lasso → should zero out irrelevant features
        # y depends only on x1; x2 is noise
        import random

        random.seed(42)
        X_feat = [[float(i), random.uniform(-0.01, 0.01)] for i in range(-10, 10)]
        X = self._make_X_with_intercept(X_feat)
        y = [x[0] * 2.0 for x in X_feat]
        beta = _elastic_net_fit(X, y, alpha=5.0, l1_ratio=1.0)
        # x2 coefficient should be near zero (or exactly zero)
        assert abs(beta[1]) < 0.2

    def test_ridge_limit_nonzero(self):
        # l1_ratio=0 → pure Ridge → all features stay non-zero (same as Ridge)
        X_feat = [[1.0, 2.0],[3.0, 4.0],[5.0, 6.0],[2.0, 1.0],[4.0, 3.0],
                  [0.0, 5.0],[5.0, 0.0],[-1.0, 2.0],[2.0, -1.0],[0.0, 0.0]]
        X = self._make_X_with_intercept(X_feat)
        y = [x[0] * 2 + x[1] * 1 for x in X_feat]
        beta = _elastic_net_fit(X, y, alpha=1.0, l1_ratio=0.0)
        # Neither coefficient should be exactly zero
        assert abs(beta[0]) > 0.1
        assert abs(beta[1]) > 0.1


# ---------------------------------------------------------------------------
# Integration tests for predict_elastic_net
# ---------------------------------------------------------------------------

class TestPredictElasticNet:
    def test_output_keys(self):
        rounds = _make_rounds(4)
        pred, full = predict_elastic_net(target_round=4, completed_rounds=rounds)
        assert set(pred) == {"target_id","model_id","feature_set_id",
                              "fallback_policy","status","entries","evidence_gaps"}
        assert pred["model_id"] == MODEL_ID

    def test_ok_with_enough_data(self):
        rounds = _make_big_rounds(4, 12)
        pred, full = predict_elastic_net(target_round=4, completed_rounds=rounds)
        assert pred["status"] == "ok"
        assert len(pred["entries"]) == 10
        assert len(full) == 12

    def test_evidence_issue_no_prior(self):
        rounds = _make_rounds(1)
        pred, _ = predict_elastic_net(target_round=1, completed_rounds=rounds)
        assert pred["status"] == "evidence_issue"

    def test_scores_monotone_descending(self):
        rounds = _make_rounds(4)
        _, full = predict_elastic_net(target_round=4, completed_rounds=rounds)
        if len(full) >= 2:
            scores = [e["score"] for e in full]
            assert scores == sorted(scores, reverse=True)

    def test_default_hyperparams(self):
        assert DEFAULT_ALPHA == pytest.approx(0.2)
        assert DEFAULT_L1_RATIO == pytest.approx(0.7)

    def test_stat_features_shared_with_ridge(self):
        from f1_big_predictor.targets.qualifying.ridge_model import STAT_FEATURES as RF
        from f1_big_predictor.targets.qualifying.elastic_net_model import STAT_FEATURES as ENF
        assert RF is ENF  # same object, imported from ridge_model
