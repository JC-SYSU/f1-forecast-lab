"""Ridge regression multi-factor model for qualifying prediction.

Implements Ridge (L2-regularised OLS) using the closed-form normal equations:
    β = (X'X + αI)^{-1} X'y

No external dependencies beyond the standard library — all matrix operations
are written in pure Python so the project stays dependency-free at runtime.

Training target: event-relative inverted score s = (N + 1 - pos) / N ∈ (0, 1]
  (higher = better, consistent with baselines and the v1 explainable-score)

Features used (10, dropping qual_teammate_delta_prev and qual_same_circuit_mean
based on Stage-1 diagnosis showing near-zero / zero-coverage for those two):
  drv_standings_pos, drv_standings_pts,
  ctor_standings_pos, ctor_standings_pts,
  qual_pos_prev, qual_pos_mean3, qual_pos_season,
  race_pos_prev, race_pos_mean3, race_pos_season
"""
from __future__ import annotations

from typing import Any

from .feature_matrix import build_feature_matrix

TARGET_ID = "qualifying"
MODEL_ID = "qualifying.model.stat.ridge"
FEATURE_SET_ID = "qualifying.features.stat.v1"
FALLBACK_POLICY = "impute_training_column_mean"
TOP10_SIZE = 10
DEFAULT_ALPHA = 5.0   # primary candidate #6; α=10.0 is also a confirmed candidate (#5)

STAT_FEATURES: tuple[str, ...] = (
    "drv_standings_pos",
    "drv_standings_pts",
    "ctor_standings_pos",
    "ctor_standings_pts",
    "qual_pos_prev",
    "qual_pos_mean3",
    "qual_pos_season",
    "race_pos_prev",
    "race_pos_mean3",
    "race_pos_season",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def predict_ridge(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
    alpha: float = DEFAULT_ALPHA,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Train on all rounds < target_round, predict for target_round.

    Returns (prediction_dict, full_ranking_list) following the same shape
    as predict_latest_prior and the other baseline predictors.
    """
    evidence_gaps: list[str] = []

    # ---- Build training set ------------------------------------------------
    X_train: list[list[float]] = []
    y_train: list[float] = []

    for rnd in sorted(completed_rounds, key=lambda r: int(r["round"])):
        rn = int(rnd["round"])
        if rn >= target_round:
            continue
        qualifying_records = rnd.get("qualifying_results", {}).get("records", [])
        field_size = len({
            str(record["driver_id"])
            for record in qualifying_records
            if record.get("driver_id")
        })
        actual_pos = {
            str(r["driver_id"]): int(r["position"])
            for r in qualifying_records
            if r.get("driver_id") and r.get("position") is not None
        }
        for row in build_feature_matrix(rn, completed_rounds):
            did = row["driver_id"]
            if did not in actual_pos:
                continue
            x = [row.get(f) for f in STAT_FEATURES]  # may contain None
            X_train.append(x)
            y_train.append(_target(actual_pos[did], field_size))

    n_train = len(X_train)
    if n_train < len(STAT_FEATURES) + 1:
        evidence_gaps.append(f"insufficient_training_samples_{n_train}")

    # ---- Build test set ----------------------------------------------------
    test_matrix = build_feature_matrix(target_round, completed_rounds)
    if not test_matrix:
        pred = _empty_prediction(evidence_gaps + ["target_round_field_missing"])
        return pred, []

    X_test = [[row.get(f) for f in STAT_FEATURES] for row in test_matrix]
    test_driver_ids = [row["driver_id"] for row in test_matrix]

    # ---- Fit and predict ---------------------------------------------------
    if n_train == 0:
        # No training data at all — fall back to uniform score
        evidence_gaps.append("no_training_data")
        scores = [0.5] * len(test_driver_ids)
    else:
        col_means, col_stds = _fit_scaler(X_train)
        X_tr = _apply_scaler(X_train, col_means, col_stds)
        X_te = _apply_scaler(X_test, col_means, col_stds)
        try:
            beta = _ridge_fit(X_tr, y_train, alpha)
            scores = [_linear_predict(beta, x_row) for x_row in X_te]
        except ValueError as exc:
            evidence_gaps.append(f"ridge_fit_failed_{exc}")
            scores = [0.5] * len(test_driver_ids)

    # ---- Build output ------------------------------------------------------
    ranked = sorted(
        zip(test_driver_ids, scores),
        key=lambda t: (-t[1], t[0]),  # desc score, then alpha by driver_id
    )
    n = len(ranked)
    full_ranking = [
        {"driver_id": did, "position": pos, "score": round(score, 6)}
        for pos, (did, score) in enumerate(ranked, start=1)
    ]
    if n >= TOP10_SIZE:
        entries = full_ranking[:TOP10_SIZE]
        status = "ok"
    else:
        entries = []
        status = "evidence_issue"
        evidence_gaps.append("insufficient_drivers_for_top10")

    prediction: dict[str, Any] = {
        "target_id": TARGET_ID,
        "model_id": MODEL_ID,
        "feature_set_id": FEATURE_SET_ID,
        "fallback_policy": FALLBACK_POLICY,
        "status": status,
        "entries": entries,
        "evidence_gaps": evidence_gaps,
    }
    return prediction, full_ranking


# ---------------------------------------------------------------------------
# Matrix / linear-algebra helpers (pure Python, no numpy)
# ---------------------------------------------------------------------------

def _target(pos: int, field_size: int) -> float:
    """Event-relative inverted score: P1 → 1; final place → 1/N."""
    if field_size < 1:
        raise ValueError(f"field_size must be positive, got {field_size}")
    if not 1 <= pos <= field_size:
        raise ValueError(f"position must be within 1..{field_size}, got {pos}")
    return (field_size + 1 - pos) / field_size


def _fit_scaler(
    X: list[list[float | None]],
) -> tuple[list[float], list[float]]:
    """Compute column-wise mean and std from training data (ignoring None)."""
    n_feat = len(X[0]) if X else 0
    means: list[float] = []
    stds: list[float] = []
    for j in range(n_feat):
        vals = [row[j] for row in X if row[j] is not None]
        if not vals:
            means.append(0.0)
            stds.append(1.0)
        else:
            m = sum(vals) / len(vals)
            variance = sum((v - m) ** 2 for v in vals) / len(vals)
            s = variance ** 0.5 if variance > 0 else 1.0
            means.append(m)
            stds.append(s)
    return means, stds


def _apply_scaler(
    X: list[list[float | None]],
    means: list[float],
    stds: list[float],
) -> list[list[float]]:
    """Impute None with column mean then standardise; add intercept column."""
    result: list[list[float]] = []
    for row in X:
        standardised = [
            ((row[j] if row[j] is not None else means[j]) - means[j]) / stds[j]
            for j in range(len(means))
        ]
        result.append(standardised + [1.0])  # append intercept
    return result


def _ridge_fit(
    X: list[list[float]],
    y: list[float],
    alpha: float,
) -> list[float]:
    """Solve β = (X'X + αI)^{-1} X'y.  Intercept column not regularised."""
    n_feat = len(X[0])  # includes intercept
    # A = X'X
    A = _xTx(X, n_feat)
    # Add α to diagonal (skip the last column = intercept term)
    for j in range(n_feat - 1):
        A[j][j] += alpha
    # b = X'y
    b = _xTy(X, y, n_feat)
    return _solve_linear(A, b)


def _linear_predict(beta: list[float], x_row: list[float]) -> float:
    return sum(beta[j] * x_row[j] for j in range(len(beta)))


def _xTx(X: list[list[float]], n_feat: int) -> list[list[float]]:
    A = [[0.0] * n_feat for _ in range(n_feat)]
    for row in X:
        for i in range(n_feat):
            for j in range(n_feat):
                A[i][j] += row[i] * row[j]
    return A


def _xTy(X: list[list[float]], y: list[float], n_feat: int) -> list[float]:
    b = [0.0] * n_feat
    for row, yi in zip(X, y):
        for j in range(n_feat):
            b[j] += row[j] * yi
    return b


def _solve_linear(A: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting.  A is n×n, b is n-vector."""
    n = len(b)
    M = [A[i][:] + [b[i]] for i in range(n)]
    for col in range(n):
        pivot_row = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[pivot_row] = M[pivot_row], M[col]
        piv = M[col][col]
        if abs(piv) < 1e-14:
            raise ValueError(f"near-singular at column {col}")
        for row in range(col + 1, n):
            f = M[row][col] / piv
            for j in range(col, n + 1):
                M[row][j] -= f * M[col][j]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = M[i][n] / M[i][i]
        for j in range(i + 1, n):
            x[i] -= M[i][j] * x[j] / M[i][i]
    return x


def _empty_prediction(evidence_gaps: list[str]) -> dict[str, Any]:
    return {
        "target_id": TARGET_ID,
        "model_id": MODEL_ID,
        "feature_set_id": FEATURE_SET_ID,
        "fallback_policy": FALLBACK_POLICY,
        "status": "evidence_issue",
        "entries": [],
        "evidence_gaps": evidence_gaps,
    }
