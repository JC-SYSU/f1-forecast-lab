"""Tests for the four simple deterministic baseline predictors."""
from __future__ import annotations

import pytest

from f1_big_predictor.targets.qualifying.baselines import (
    FORM_WINDOW,
    predict_constructor_only,
    predict_form_w3,
    predict_latest_prior,
    predict_season_to_date,
)


# ---------------------------------------------------------------------------
# Minimal synthetic actuals fixture
# ---------------------------------------------------------------------------

def _make_qual_records(order: list[str], constructor_map: dict[str, str]) -> list[dict]:
    return [
        {
            "driver_id": did,
            "position": pos,
            "constructor_id": constructor_map.get(did, "team_a"),
        }
        for pos, did in enumerate(order, start=1)
    ]


def _make_driver_standings(order: list[str]) -> list[dict]:
    return [
        {"driver_id": did, "position": pos, "points": float(100 - pos * 5)}
        for pos, did in enumerate(order, start=1)
    ]


def _make_constructor_standings(ctor_order: list[str]) -> list[dict]:
    return [
        {"constructor_id": cid, "position": pos, "points": float(200 - pos * 10)}
        for pos, cid in enumerate(ctor_order, start=1)
    ]


# Canonical 3-round dataset:
#   R01: drivers A-J (10 drivers), A=P1 … J=P10
#   R02: drivers A-L (12 drivers, C and D missing from R01), A=P1 … J=P10, K=P11, L=P12
#   R03: drivers A-L, B=P1, A=P2, others shifted

CONSTRUCTORS = {
    "a": "team_a", "b": "team_a",
    "c": "team_b", "d": "team_b",
    "e": "team_c", "f": "team_c",
    "g": "team_d", "h": "team_d",
    "i": "team_e", "j": "team_e",
    "k": "team_f", "l": "team_f",
}

R01_ORDER = ["a", "b", "e", "f", "g", "h", "i", "j", "c_missing", "d_missing"]
# R01 has 10 drivers; k and l are new entrants from R02 onwards
R01_QUAL = _make_qual_records(["a", "b", "e", "f", "g", "h", "i", "j"], CONSTRUCTORS)
R02_DRIVERS = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"]
R02_QUAL = _make_qual_records(["b", "a", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"], CONSTRUCTORS)

R01_DRIVER_STANDINGS = _make_driver_standings(["a", "b", "e", "f", "g", "h", "i", "j"])
R02_DRIVER_STANDINGS = _make_driver_standings(["b", "a", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"])
R01_CTOR_STANDINGS = _make_constructor_standings(["team_a", "team_c", "team_d", "team_e", "team_b", "team_f"])
R02_CTOR_STANDINGS = _make_constructor_standings(["team_a", "team_b", "team_c", "team_d", "team_e", "team_f"])


def _completed_rounds_2() -> list[dict]:
    """Two completed rounds."""
    return [
        {
            "round": 1,
            "race_name": "Race One",
            "circuit_id": "circuit_1",
            "qualifying_results": {"status": "ok", "row_count": len(R01_QUAL), "records": R01_QUAL},
            "driver_standings": {"status": "ok", "records": R01_DRIVER_STANDINGS},
            "constructor_standings": {"status": "ok", "records": R01_CTOR_STANDINGS},
        },
        {
            "round": 2,
            "race_name": "Race Two",
            "circuit_id": "circuit_2",
            "qualifying_results": {"status": "ok", "row_count": len(R02_QUAL), "records": R02_QUAL},
            "driver_standings": {"status": "ok", "records": R02_DRIVER_STANDINGS},
            "constructor_standings": {"status": "ok", "records": R02_CTOR_STANDINGS},
        },
    ]


# ---------------------------------------------------------------------------
# Helper assertions
# ---------------------------------------------------------------------------

def _top_ids(prediction: dict) -> list[str]:
    return [e["driver_id"] for e in prediction["entries"]]


def _full_ids(full_ranking: list[dict]) -> list[str]:
    return [e["driver_id"] for e in full_ranking]


# ---------------------------------------------------------------------------
# latest_prior tests
# ---------------------------------------------------------------------------

class TestLatestPrior:
    def test_known_drivers_ranked_by_prior_qualifying_position(self) -> None:
        completed = _completed_rounds_2()
        pred, full = predict_latest_prior(target_round=2, completed_rounds=completed)

        assert pred["status"] == "ok"
        assert pred["model_id"] == "qualifying.model.baseline.latest_prior"
        assert pred["feature_set_id"] == "qualifying.features.baseline.latest_prior"
        full_ids = _full_ids(full)
        # Known drivers from R01 should appear first in R01 order: a, b, e, f, g, h, i, j
        known_order = [e for e in full_ids if e in {r["driver_id"] for r in R01_QUAL}]
        assert known_order == ["a", "b", "e", "f", "g", "h", "i", "j"]

    def test_cold_start_drivers_appended_after_known(self) -> None:
        completed = _completed_rounds_2()
        _pred, full = predict_latest_prior(target_round=2, completed_rounds=completed)
        full_ids = _full_ids(full)
        # k and l were absent in R01 → should appear after the 8 known drivers
        known_pos = {did: idx for idx, did in enumerate(full_ids)}
        for known in ["a", "b", "e", "f", "g", "h", "i", "j"]:
            for cold in ["k", "l"]:
                assert known_pos[known] < known_pos[cold], (
                    f"{known} (pos {known_pos[known]}) should precede cold-start {cold} (pos {known_pos[cold]})"
                )

    def test_cold_start_gap_recorded(self) -> None:
        completed = _completed_rounds_2()
        pred, _ = predict_latest_prior(target_round=2, completed_rounds=completed)
        assert any("cold_start" in g for g in pred["evidence_gaps"])

    def test_entries_are_top10(self) -> None:
        completed = _completed_rounds_2()
        pred, full = predict_latest_prior(target_round=2, completed_rounds=completed)
        assert len(pred["entries"]) == 10
        assert len(full) == 12  # R02 has 12 drivers
        assert _top_ids(pred) == _full_ids(full)[:10]

    def test_positions_in_entries_are_sequential(self) -> None:
        completed = _completed_rounds_2()
        pred, _ = predict_latest_prior(target_round=2, completed_rounds=completed)
        assert [e["position"] for e in pred["entries"]] == list(range(1, 11))

    def test_missing_prior_round_flags_evidence_gap(self) -> None:
        # Only provide R02 actuals; prior round (R01) is missing
        completed = [_completed_rounds_2()[1]]
        pred, _ = predict_latest_prior(target_round=2, completed_rounds=completed)
        assert any("missing" in g for g in pred["evidence_gaps"])


# ---------------------------------------------------------------------------
# season_to_date tests
# ---------------------------------------------------------------------------

class TestSeasonToDate:
    def test_r2_is_degenerate_equal_to_latest_prior_for_known_drivers(self) -> None:
        """With only R01 history, season_to_date ≡ latest_prior for known drivers."""
        completed = _completed_rounds_2()
        pred_std, full_std = predict_season_to_date(target_round=2, completed_rounds=completed)
        pred_lp, full_lp = predict_latest_prior(target_round=2, completed_rounds=completed)

        known = {r["driver_id"] for r in R01_QUAL}
        std_known = [d for d in _full_ids(full_std) if d in known]
        lp_known = [d for d in _full_ids(full_lp) if d in known]
        assert std_known == lp_known

    def test_mean_position_used_across_multiple_rounds(self) -> None:
        """With 2 prior rounds the mean is computed, not just the last round."""
        # R03 prediction: prior = R01 + R02
        # driver "a": R01=P1, R02=P2 → mean=1.5
        # driver "b": R01=P2, R02=P1 → mean=1.5 (tie → more rounds same, driver standings breaks tie)
        # In R02 standings "b" is pos 1, "a" is pos 2 → b before a on tie
        completed = _completed_rounds_2()
        # Add a dummy R03 row so target_round=3 is resolvable
        r03_qual = _make_qual_records(["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"], CONSTRUCTORS)
        completed.append({
            "round": 3,
            "race_name": "Race Three",
            "qualifying_results": {"status": "ok", "row_count": 12, "records": r03_qual},
            "driver_standings": {"status": "ok", "records": R02_DRIVER_STANDINGS},
            "constructor_standings": {"status": "ok", "records": R02_CTOR_STANDINGS},
        })
        _pred, full = predict_season_to_date(target_round=3, completed_rounds=completed)
        full_ids = _full_ids(full)
        # Both a and b have mean 1.5; b has higher driver standing (pos 1 in R02) → b first
        assert full_ids.index("b") < full_ids.index("a")

    def test_cold_start_gap_recorded(self) -> None:
        completed = _completed_rounds_2()
        pred, _ = predict_season_to_date(target_round=2, completed_rounds=completed)
        assert any("cold_start" in g for g in pred["evidence_gaps"])


# ---------------------------------------------------------------------------
# constructor_only tests
# ---------------------------------------------------------------------------

class TestConstructorOnly:
    def test_ranked_by_constructor_standing(self) -> None:
        completed = _completed_rounds_2()
        _pred, full = predict_constructor_only(target_round=2, completed_rounds=completed)
        full_ids = _full_ids(full)

        # R01 ctor standings: team_a(1), team_c(2), team_d(3), team_e(4), team_b(5), team_f(6)
        # team_a drivers: a, b → both pos 1 ctor; within team: driver standings R01: a=1, b=2 → a before b
        # team_b drivers: c, d → ctor pos 5; driver standings R01: c, d not in R01 standings → 9999
        assert full_ids.index("a") < full_ids.index("b"), "a should precede b (driver standings tiebreak)"
        assert full_ids.index("a") < full_ids.index("e"), "team_a before team_c"
        assert full_ids.index("e") < full_ids.index("g"), "team_c before team_d"

    def test_no_cold_start_for_constructors(self) -> None:
        completed = _completed_rounds_2()
        pred, _ = predict_constructor_only(target_round=2, completed_rounds=completed)
        # All R02 constructors should be in R01 standings (no missing flag)
        assert pred["status"] == "ok"

    def test_model_and_feature_set_ids(self) -> None:
        completed = _completed_rounds_2()
        pred, _ = predict_constructor_only(target_round=2, completed_rounds=completed)
        assert pred["model_id"] == "qualifying.model.baseline.constructor_only"
        assert pred["feature_set_id"] == "qualifying.features.baseline.constructor_only"


# ---------------------------------------------------------------------------
# form_w3 tests
# ---------------------------------------------------------------------------

class TestFormW3:
    def test_window_limits_history_to_last_3_rounds(self) -> None:
        """driver history older than 3 rounds is excluded."""
        # Build 5 rounds: driver "old_leader" dominates R01 only
        r_old = _make_qual_records(["old_leader", "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k"], CONSTRUCTORS)
        r_base = _make_qual_records(["a", "b", "c", "old_leader", "d", "e", "f", "g", "h", "i", "j", "k"], CONSTRUCTORS)
        ds = _make_driver_standings(["a", "b", "c", "old_leader", "d", "e", "f", "g", "h", "i", "j", "k"])
        cs = _make_constructor_standings(["team_a", "team_b", "team_c", "team_d", "team_e", "team_f"])
        def _mk_round(n: int, qual_records: list) -> dict:
            return {
                "round": n,
                "qualifying_results": {"status": "ok", "row_count": len(qual_records), "records": qual_records},
                "driver_standings": {"status": "ok", "records": ds},
                "constructor_standings": {"status": "ok", "records": cs},
            }

        r5_qual = _make_qual_records(["a", "b", "c", "old_leader", "d", "e", "f", "g", "h", "i", "j", "k"], CONSTRUCTORS)
        completed = [
            _mk_round(1, r_old),   # old_leader dominates
            _mk_round(2, r_base),  # old_leader at P4
            _mk_round(3, r_base),  # old_leader at P4
            _mk_round(4, r_base),  # old_leader at P4
            _mk_round(5, r5_qual), # target round field (actual result not used for prediction)
        ]
        # Predicting R5: window=3 → only R2, R3, R4 count
        _pred, full = predict_form_w3(target_round=5, completed_rounds=completed, window=3)
        full_ids = _full_ids(full)
        # old_leader's mean in window R2-R4 is P4; a, b, c should be before old_leader
        for better in ["a", "b", "c"]:
            assert full_ids.index(better) < full_ids.index("old_leader"), (
                f"{better} (window mean < old_leader window mean) should precede old_leader"
            )

    def test_r2_form_reduces_to_single_round(self) -> None:
        """For R02 prediction, window is effectively 1 → same known-driver order as latest_prior."""
        completed = _completed_rounds_2()
        _pred_fw, full_fw = predict_form_w3(target_round=2, completed_rounds=completed)
        _pred_lp, full_lp = predict_latest_prior(target_round=2, completed_rounds=completed)

        known = {r["driver_id"] for r in R01_QUAL}
        fw_known = [d for d in _full_ids(full_fw) if d in known]
        lp_known = [d for d in _full_ids(full_lp) if d in known]
        assert fw_known == lp_known

    def test_default_window_constant(self) -> None:
        assert FORM_WINDOW == 3


# ---------------------------------------------------------------------------
# Cross-baseline structural tests
# ---------------------------------------------------------------------------

class TestBaselineStructure:
    @pytest.mark.parametrize("predictor", [
        predict_latest_prior,
        predict_season_to_date,
        predict_constructor_only,
        predict_form_w3,
    ])
    def test_output_shape(self, predictor) -> None:
        completed = _completed_rounds_2()
        pred, full = predictor(target_round=2, completed_rounds=completed)

        # Prediction keys
        assert set(pred) == {"target_id", "model_id", "feature_set_id",
                             "fallback_policy", "status", "entries", "evidence_gaps"}
        assert pred["target_id"] == "qualifying"
        assert pred["status"] == "ok"
        assert len(pred["entries"]) == 10

        # Entry keys
        for entry in pred["entries"]:
            assert "driver_id" in entry
            assert "position" in entry
            assert "score" in entry

        # Full ranking
        assert len(full) == 12  # R02 has 12 drivers
        assert [e["position"] for e in full] == list(range(1, 13))

    @pytest.mark.parametrize("predictor", [
        predict_latest_prior,
        predict_season_to_date,
        predict_constructor_only,
        predict_form_w3,
    ])
    def test_scores_decrease_monotonically(self, predictor) -> None:
        completed = _completed_rounds_2()
        _pred, full = predictor(target_round=2, completed_rounds=completed)
        scores = [e["score"] for e in full]
        assert scores == sorted(scores, reverse=True)
