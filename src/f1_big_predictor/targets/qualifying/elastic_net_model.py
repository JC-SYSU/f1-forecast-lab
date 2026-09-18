"""Elastic Net multi-factor model for qualifying prediction.

Elastic Net combines L1 (sparsity) and L2 (stability) regularisation:
    β = argmin_β  ||y - Xβ||² + α·l1_ratio·||β||₁ + α·(1-l1_ratio)/2·||β||²

Optimised via coordinate descent (Lasso/EN standard solver).  No external
dependencies — all numerics are pure Python.

Shares the same feature set and target transform as the Ridge model:
  features : STAT_FEATURES (10 features, same as qualifying.features.stat.v1)
  target   : s = (N + 1 - pos) / N   (higher = better)
  defaults : alpha=10.0, l1_ratio=0.5
"""
from __future__ import annotations

from typing import Any

from .feature_matrix import build_feature_matrix
from .ridge_model import (
    FALLBACK_POLICY,
    FEATURE_SET_ID,
    STAT_FEATURES,
    TARGET_ID,
    TOP10_SIZE,
    _apply_scaler,
    _empty_prediction,
    _fit_scaler,
    _target,
)

MODEL_ID = "qualifying.model.stat.elastic_net"
DEFAULT_ALPHA = 0.2     # calibrated to keep L1 threshold below feature gradients (~0.15–0.22)
DEFAULT_L1_RATIO = 0.7  # primary candidate #8; higher L1 → sparser solution (R03-R09 mae best)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def predict_elastic_net(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
    alpha: float = DEFAULT_ALPHA,
    l1_ratio: float = DEFAULT_L1_RATIO,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Train on all rounds < target_round via coordinate descent, predict for target_round."""
    evidence_gaps: list[str] = []

    # ---- Build training set ------------------------------------------------
    X_train: list[list[float | None]] = []
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
            X_train.append([row.get(f) for f in STAT_FEATURES])
            y_train.append(_target(actual_pos[did], field_size))

    n_train = len(X_train)
    if n_train < len(STAT_FEATURES) + 1:
        evidence_gaps.append(f"insufficient_training_samples_{n_train}")

    # ---- Build test set ----------------------------------------------------
    test_matrix = build_feature_matrix(target_round, completed_rounds)
    if not test_matrix:
        return _empty_prediction(evidence_gaps + ["target_round_field_missing"]), []

    X_test = [[row.get(f) for f in STAT_FEATURES] for row in test_matrix]
    test_driver_ids = [row["driver_id"] for row in test_matrix]

    # ---- Fit and predict ---------------------------------------------------
    if n_train == 0:
        evidence_gaps.append("no_training_data")
        scores = [0.5] * len(test_driver_ids)
    else:
        col_means, col_stds = _fit_scaler(X_train)
        X_tr = _apply_scaler(X_train, col_means, col_stds)   # includes intercept col
        X_te = _apply_scaler(X_test, col_means, col_stds)
        try:
            beta = _elastic_net_fit(X_tr, y_train, alpha=alpha, l1_ratio=l1_ratio)
            scores = [sum(beta[j] * x[j] for j in range(len(beta))) for x in X_te]
        except ValueError as exc:
            evidence_gaps.append(f"elastic_net_fit_failed_{exc}")
            scores = [0.5] * len(test_driver_ids)

    # ---- Build output ------------------------------------------------------
    ranked = sorted(zip(test_driver_ids, scores), key=lambda t: (-t[1], t[0]))
    n = len(ranked)
    full_ranking = [
        {"driver_id": did, "position": pos, "score": round(score, 6)}
        for pos, (did, score) in enumerate(ranked, start=1)
    ]
    if n >= TOP10_SIZE:
        entries, status = full_ranking[:TOP10_SIZE], "ok"
    else:
        entries, status = [], "evidence_issue"
        evidence_gaps.append("insufficient_drivers_for_top10")

    return {
        "target_id": TARGET_ID,
        "model_id": MODEL_ID,
        "feature_set_id": FEATURE_SET_ID,
        "fallback_policy": FALLBACK_POLICY,
        "status": status,
        "entries": entries,
        "evidence_gaps": evidence_gaps,
    }, full_ranking


# ---------------------------------------------------------------------------
# Coordinate descent solver (pure Python)
# ---------------------------------------------------------------------------

def _soft_threshold(z: float, lam: float) -> float:
    """Proximal operator for L1: sign(z)·max(|z|-λ, 0)."""
    if z > lam:
        return z - lam
    if z < -lam:
        return z + lam
    return 0.0


def _elastic_net_fit(
    X: list[list[float]],
    y: list[float],
    alpha: float,
    l1_ratio: float,
    max_iter: int = 2000,
    tol: float = 1e-7,
) -> list[float]:
    """Coordinate descent for Elastic Net.

    X is n_samples × (n_feat + 1); the last column is the intercept (all 1s).
    The intercept is NOT regularised.  Returns β of length n_feat + 1.
    """
    n_samples = len(y)
    n_total = len(X[0])          # n_feat + 1 (intercept)
    n_feat = n_total - 1

    # Pre-compute ||Xⱼ||²/n for each feature column (not intercept)
    xj_sq = [
        sum(X[i][j] ** 2 for i in range(n_samples)) / n_samples
        for j in range(n_feat)
    ]

    beta = [0.0] * n_total
    # residuals r = y - X·β (initially all y since β=0)
    r = list(y)

    for _iteration in range(max_iter):
        beta_old = beta[:]

        # --- Update feature coefficients (regularised) --------------------
        for j in range(n_feat):
            if xj_sq[j] == 0.0:
                beta[j] = 0.0
                continue
            # Add back the current contribution of βⱼ to residuals
            bj = beta[j]
            if bj != 0.0:
                for i in range(n_samples):
                    r[i] += X[i][j] * bj
            # ρⱼ = Xⱼᵀ·r / n
            rho_j = sum(X[i][j] * r[i] for i in range(n_samples)) / n_samples
            # Elastic Net update
            beta[j] = _soft_threshold(rho_j, alpha * l1_ratio) / (xj_sq[j] + alpha * (1.0 - l1_ratio))
            # Subtract new contribution
            bj_new = beta[j]
            if bj_new != 0.0:
                for i in range(n_samples):
                    r[i] -= X[i][j] * bj_new

        # --- Update intercept (unregularised OLS) -------------------------
        # Add back old intercept contribution, then refit
        old_int = beta[n_feat]
        for i in range(n_samples):
            r[i] += old_int
        new_int = sum(r) / n_samples
        beta[n_feat] = new_int
        for i in range(n_samples):
            r[i] -= new_int

        # --- Convergence check --------------------------------------------
        if max(abs(beta[k] - beta_old[k]) for k in range(n_total)) < tol:
            break

    return beta
