"""Multi-factor race finish prediction model.

Combines:
  - Qualifying features (form, constructor, circuit fit, evidence, reliability)
  - Grid_delta racecraft features (N2f6 hit rate + C3 confidence weighting)
  - Grid position baseline

Predicts Top-10 race finish order, evaluated with C0 scoring.

Usage:
    python3 scripts/multi_factor_race_model.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from statistics import mean, stdev
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from f1_big_predictor.targets.race.grid_delta_features import (
    _extract_finisher_records,
    _fit_linear,
)
from f1_big_predictor.targets.qualifying.features import build_qualifying_features

ACTUALS_PATH = PROJECT_ROOT / "data/processed/season_2026_actuals/actuals.json"
EVAL_ROUNDS = list(range(3, 12))  # R03-R11

# C0 scoring weights
C0_EXACT = 0.45
C0_MEMBERSHIP = 0.35
C0_INTERNAL_ORDER = 0.20


def c0_score(predicted: list[str], actual: list[str]) -> float:
    """C0 scoring for Top-10 prediction."""
    predicted_set = set(predicted[:10])
    actual_set = set(actual[:10])

    exact = sum(1 for i in range(10) if i < len(predicted) and i < len(actual)
                and predicted[i] == actual[i])
    exact_score = (exact / 10) * C0_EXACT

    membership = len(predicted_set & actual_set)
    membership_score = (membership / 10) * C0_MEMBERSHIP

    common = predicted_set & actual_set
    if len(common) >= 2:
        pred_order = {d: i for i, d in enumerate(predicted[:10]) if d in common}
        actual_order = {d: i for i, d in enumerate(actual[:10]) if d in common}
        pairs = [(d1, d2) for d1 in common for d2 in common if d1 != d2]
        concordant = sum(1 for d1, d2 in pairs
                        if (pred_order[d1] < pred_order[d2]) == (actual_order[d1] < actual_order[d2]))
        order_score = (concordant / len(pairs)) * C0_INTERNAL_ORDER if pairs else 0.0
    else:
        order_score = 0.0

    return exact_score + membership_score + order_score


def load_actuals():
    with ACTUALS_PATH.open() as f:
        data = json.load(f)
    return sorted(data["completed_rounds"], key=lambda r: int(r["round"]))


def extract_grid_delta_features(completed_rounds: list[dict], target_round: int) -> dict[str, dict]:
    """Compute N2f6 hit rate + C3 confidence for all drivers."""
    training = [r for r in completed_rounds if int(r["round"]) < target_round]
    train_recs = _extract_finisher_records(training)
    lin_a, lin_b = _fit_linear(train_recs)

    driver_history = {}
    for rec in sorted(train_recs, key=lambda x: x["round"]):
        driver_history.setdefault(rec["driver_id"], []).append(rec)

    features = {}
    for did, hist in driver_history.items():
        if not hist:
            continue
        adj_deltas = [h["delta"] - (lin_a * h["grid"] + lin_b) for h in hist]
        hit_rate = sum(1 for d in adj_deltas if d > 0) / len(adj_deltas)
        n_history = len(hist)
        confidence = min(1.0, n_history / 5.0)

        features[did] = {
            "hit_rate": hit_rate,
            "n_history": n_history,
            "confidence": confidence,
            "racecraft_score": (hit_rate - 0.5) * 10 * confidence,  # C3 correction
        }

    return features


def build_combined_features(completed_rounds: list[dict], target_round: int) -> dict[str, dict]:
    """Build feature dict for all drivers in target round."""
    # Grid delta features
    grid_delta = extract_grid_delta_features(completed_rounds, target_round)

    # Qualifying features
    try:
        qual_data = build_qualifying_features(
            project_root=PROJECT_ROOT,
            target_round=target_round,
            season=2026,
        )
        qual_features = {
            row["driver_id"]: {
                "form_score": row.get("form_score", 0.0),
                "constructor_score": row.get("constructor_score", 0.0),
                "circuit_fit_score": row.get("circuit_fit_score", 0.0),
                "evidence_score": row.get("evidence_score", 0.0),
                "reliability_score": row.get("reliability_score", 0.0),
            }
            for row in qual_data.get("features", [])
        }
    except Exception as e:
        print(f"Warning: Could not load qualifying features for R{target_round:02d}: {e}")
        qual_features = {}

    # Get grid positions from target round
    target = next((r for r in completed_rounds if int(r["round"]) == target_round), None)
    if not target:
        return {}

    combined = {}
    for rec in target["race_results"]["records"]:
        did = rec["driver_id"]
        grid = rec.get("grid")

        if grid is None:
            continue

        combined[did] = {
            "driver_id": did,
            "grid": grid,
            "racecraft_score": grid_delta.get(did, {}).get("racecraft_score", 0.0),
            "hit_rate": grid_delta.get(did, {}).get("hit_rate", 0.5),
            "n_history": grid_delta.get(did, {}).get("n_history", 0),
            **qual_features.get(did, {
                "form_score": 0.0,
                "constructor_score": 0.0,
                "circuit_fit_score": 0.0,
                "evidence_score": 0.0,
                "reliability_score": 0.0,
            }),
        }

    return combined


def predict_baseline_grid(features: dict[str, dict]) -> list[str]:
    """Baseline: sort by grid position."""
    sorted_drivers = sorted(features.items(), key=lambda x: x[1]["grid"])
    return [d[0] for d in sorted_drivers]


def predict_grid_plus_racecraft(features: dict[str, dict]) -> list[str]:
    """Grid + racecraft only (no qualifying)."""
    predictions = []
    for did, feat in features.items():
        # Predicted finish = grid - racecraft_score
        pred_pos = feat["grid"] - feat["racecraft_score"]
        predictions.append((did, pred_pos))

    predictions.sort(key=lambda x: x[1])
    return [p[0] for p in predictions]


def predict_multi_factor_simple(features: dict[str, dict]) -> list[str]:
    """Simple weighted combination of all features."""
    predictions = []

    for did, feat in features.items():
        # Base prediction from grid
        base_score = feat["grid"]

        # Racecraft adjustment (negative = better)
        racecraft_adj = -feat["racecraft_score"]

        # Qualifying adjustments (positive scores = better → lower finish position)
        qual_adj = -(
            feat.get("form_score", 0.0) * 0.3 +
            feat.get("constructor_score", 0.0) * 0.4 +
            feat.get("circuit_fit_score", 0.0) * 0.2 +
            feat.get("evidence_score", 0.0) * 0.1
        )

        # Combined prediction (lower = better finish)
        pred_pos = base_score + racecraft_adj * 0.4 + qual_adj * 0.3

        predictions.append((did, pred_pos))

    predictions.sort(key=lambda x: x[1])
    return [p[0] for p in predictions]


def evaluate_model(completed_rounds: list[dict], predict_fn, model_name: str) -> dict:
    """Walk-forward evaluation on R03-R11."""
    scores = []

    for target_round in EVAL_ROUNDS:
        features = build_combined_features(completed_rounds, target_round)
        if not features:
            continue

        # Predict
        predicted = predict_fn(features)

        # Actual
        target = next((r for r in completed_rounds if int(r["round"]) == target_round), None)
        if not target:
            continue

        actual_order = sorted(
            target["race_results"]["records"],
            key=lambda x: x.get("position", 999)
        )
        actual = [r["driver_id"] for r in actual_order if r.get("position") is not None]

        # Score
        score = c0_score(predicted, actual)
        scores.append(score)

        print(f"  R{target_round:02d}: {score:.4f}")

    return {
        "model": model_name,
        "mean_c0": mean(scores) if scores else 0.0,
        "std_c0": stdev(scores) if len(scores) > 1 else 0.0,
        "scores": scores,
    }


def main():
    completed_rounds = load_actuals()

    print("=" * 80)
    print("Multi-Factor Race Finish Prediction Model")
    print("=" * 80)
    print()

    models = [
        (predict_baseline_grid, "Baseline: Grid Position Only"),
        (predict_grid_plus_racecraft, "Grid + Racecraft (N2f6+C3)"),
        (predict_multi_factor_simple, "Multi-Factor: Grid + Racecraft + Qualifying"),
    ]

    results = []
    for predict_fn, name in models:
        print(f"\nEvaluating: {name}")
        print("-" * 80)
        result = evaluate_model(completed_rounds, predict_fn, name)
        results.append(result)
        print(f"  → Mean C0: {result['mean_c0']:.4f} ± {result['std_c0']:.4f}")

    print()
    print("=" * 80)
    print("Summary (sorted by C0 score):")
    print("=" * 80)
    print(f"{'Model':<50} {'Mean C0':>10} {'Std':>8}")
    print("-" * 80)

    results.sort(key=lambda x: x["mean_c0"], reverse=True)
    for r in results:
        print(f"{r['model']:<50} {r['mean_c0']:>10.4f} {r['std_c0']:>8.4f}")

    print()


if __name__ == "__main__":
    main()
