"""Tests for the LambdaMART learning-to-rank model."""
from __future__ import annotations


from f1_big_predictor.targets.qualifying.lambdamart_model import (
    FEATURE_SET_ID,
    MODEL_ID,
    _event_relevance,
    _fit_feature_medians,
    _impute_rows,
    _resolve_params,
    predict_lambdamart,
)


def _mk_rounds(n=6, nd=12):
    drivers = list("abcdefghijkl")[:nd]
    ctor = {d: f"t{i//2+1}" for i, d in enumerate(drivers)}

    def _mk(i):
        order = drivers[i % 3:] + drivers[:i % 3]
        return {
            "round": i + 1, "circuit_id": f"c{i%2}", "race_name": f"R{i+1}",
            "qualifying_results": {"status": "ok", "row_count": nd, "records": [
                {"driver_id": d, "constructor_id": ctor[d], "position": p}
                for p, d in enumerate(order, 1)]},
            "race_results": {"status": "ok", "row_count": nd, "records": [
                {"driver_id": d, "constructor_id": ctor[d], "position": p, "status": "Finished"}
                for p, d in enumerate(order, 1)]},
            "driver_standings": {"status": "ok", "records": [
                {"driver_id": d, "position": p, "points": float(100 - p * 5), "wins": 0}
                for p, d in enumerate(order, 1)]},
            "constructor_standings": {"status": "ok", "records": [
                {"constructor_id": f"t{k+1}", "position": k + 1,
                 "points": float(200 - k * 20), "wins": 0} for k in range(nd // 2)]},
        }

    return [_mk(i) for i in range(n)]


class TestHelpers:
    def test_relevance_is_field_size_independent_at_boundaries(self):
        assert _event_relevance(1, 19) == 20
        assert _event_relevance(1, 22) == 20
        assert _event_relevance(19, 19) == 0
        assert _event_relevance(22, 22) == 0

    def test_feature_medians_are_fitted_per_column(self):
        rows = [[1.0] * 10, [3.0] * 10, [None] * 10]
        assert _fit_feature_medians(rows, []) == [2.0] * 10

    def test_imputation_uses_fitted_column_medians(self):
        rows = [[None, 9.0]]
        assert _impute_rows(rows, [2.0, 4.0]) == [[2.0, 9.0]]

    def test_resolve_params_defaults(self):
        cfg = _resolve_params(None)
        assert cfg["num_leaves"] == 7
        assert cfg["n_estimators"] == 100

    def test_resolve_params_override(self):
        cfg = _resolve_params({"num_leaves": 15})
        assert cfg["num_leaves"] == 15
        assert cfg["n_estimators"] == 100  # unchanged default


class TestPredictLambdamart:
    def test_output_keys(self):
        rounds = _mk_rounds(6, 12)
        pred, full = predict_lambdamart(6, rounds)
        assert set(pred) == {"target_id", "model_id", "feature_set_id",
                             "fallback_policy", "status", "entries", "evidence_gaps"}
        assert pred["model_id"] == MODEL_ID
        assert pred["feature_set_id"] == FEATURE_SET_ID

    def test_ok_status_and_top10(self):
        rounds = _mk_rounds(6, 12)
        pred, full = predict_lambdamart(6, rounds)
        assert pred["status"] == "ok"
        assert len(pred["entries"]) == 10
        assert len(full) == 12

    def test_scores_monotone_descending(self):
        rounds = _mk_rounds(6, 12)
        _, full = predict_lambdamart(6, rounds)
        scores = [e["score"] for e in full]
        assert scores == sorted(scores, reverse=True)

    def test_no_training_data_gives_evidence_issue(self):
        rounds = _mk_rounds(6, 12)
        pred, full = predict_lambdamart(1, rounds)   # no prior rounds
        assert pred["status"] == "evidence_issue"
        assert full == []
