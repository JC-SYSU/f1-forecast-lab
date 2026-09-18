"""Probability ranking models: Bradley-Terry and Plackett-Luce.

Both models estimate driver skill parameters via Maximum Likelihood Estimation
(MLE) using the MM (majorisation-minimisation) algorithm.  This is a
fundamentally different estimation paradigm from the rating-update heuristics
(Elo, Glicko, Gaussian pairwise approximation) and the linear-algebra batch
systems (Massey, Colley).

Bradley-Terry (pairwise MLE)
  P(i beats j) = λᵢ / (λᵢ + λⱼ)
  Input: all-pairs pairwise outcomes (same pairing as Elo/Massey).

Plackett-Luce (full-ranking MLE)
  P(ranked order π) = Π_k [ λ_{π_k} / Σ_{j≥k} λ_{π_j} ]
  Input: each round's complete 22-driver qualifying order.

Both use the Hunter (2004) MM update; O(n_rounds × n_drivers) per iteration
after precomputing suffix sums (PL) or suffix pairwise counts (B-T).
New entrants (no prior data) receive λ = 1.0 (geometric mean prior).
"""
from __future__ import annotations

from typing import Any

from .rating_models import _qual_records, _rank_by_rating, _empty_result

TARGET_ID = "qualifying"
MODEL_ID_BT = "qualifying.model.prob.bradley_terry"
MODEL_ID_PL = "qualifying.model.prob.plackett_luce"
FEATURE_SET_ID_BT = "qualifying.features.prob.bt_v1"
FEATURE_SET_ID_PL = "qualifying.features.prob.pl_v1"
FALLBACK_POLICY = "unit_lambda_for_new_entrants"
TOP10_SIZE = 10


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def predict_bradley_terry(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
    delta: float = 0.0,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """MLE Bradley-Terry skill parameters from all-pairs data.

    delta: Laplace smoothing — add delta virtual wins and delta virtual losses
    per driver pair.  delta=0 is pure MLE; delta=2.0 ameliorates cold-start
    for new entrants (tested optimum on R02–R09).
    """
    evidence_gaps: list[str] = []
    all_records = _collect_prior_records(target_round, completed_rounds, evidence_gaps, "bt")

    if not all_records:
        return _empty_result(MODEL_ID_BT, FEATURE_SET_ID_BT,
                              evidence_gaps + ["no_prior_qualifying_data"]), []

    ratings = _bradley_terry_ratings(all_records, evidence_gaps, delta=delta)
    return _rank_by_rating(
        target_round, completed_rounds, ratings,
        model_id=MODEL_ID_BT, feature_set_id=FEATURE_SET_ID_BT,
        default_score=1.0, evidence_gaps=evidence_gaps,
    )


def predict_plackett_luce(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """MLE Plackett-Luce skill parameters from full qualifying rankings."""
    evidence_gaps: list[str] = []
    all_records = _collect_prior_records(target_round, completed_rounds, evidence_gaps, "pl")

    if not all_records:
        return _empty_result(MODEL_ID_PL, FEATURE_SET_ID_PL,
                              evidence_gaps + ["no_prior_qualifying_data"]), []

    ratings = _plackett_luce_ratings(all_records, evidence_gaps)
    return _rank_by_rating(
        target_round, completed_rounds, ratings,
        model_id=MODEL_ID_PL, feature_set_id=FEATURE_SET_ID_PL,
        default_score=1.0, evidence_gaps=evidence_gaps,
    )


# ---------------------------------------------------------------------------
# Bradley-Terry MM algorithm
# ---------------------------------------------------------------------------

def _bradley_terry_ratings(
    all_records: list[tuple[int, list[dict[str, Any]]]],
    evidence_gaps: list[str],
    delta: float = 0.0,
    max_iter: int = 2000,
    tol: float = 1e-9,
) -> dict[str, float]:
    """Return dict[driver_id → λ] via MM update on all-pairs outcomes.

    delta > 0 adds Laplace smoothing: each ordered pair gets delta virtual
    wins, so every driver has delta*(n-1) prior wins and each pair plays 2*delta
    extra games.  This stabilises new entrants with little or no real data.
    """
    driver_set, driver_index = _build_driver_index(all_records)
    n = len(driver_set)
    if n == 0:
        return {}

    # W[i] = total pairwise wins for driver i
    # G[i][j] = number of games between i and j (symmetric)
    W = [0.0] * n
    G: list[list[float]] = [[0.0] * n for _ in range(n)]

    for _, records in all_records:
        ids = _sorted_ids(records)
        m = len(ids)
        for i in range(m):
            for j in range(i + 1, m):
                a, b = driver_index[ids[i]], driver_index[ids[j]]
                W[a] += 1         # ids[i] beat ids[j]
                G[a][b] += 1
                G[b][a] += 1

    # Laplace smoothing: delta virtual wins + delta virtual losses per pair
    if delta > 0:
        for i in range(n):
            W[i] += delta * (n - 1)
            for j in range(n):
                if i != j:
                    G[i][j] += 2 * delta

    lam = [1.0] * n

    for _ in range(max_iter):
        lam_new = [0.0] * n
        for i in range(n):
            if W[i] == 0:
                lam_new[i] = lam[i]   # no data → keep prior
                continue
            denom = sum(G[i][j] / (lam[i] + lam[j]) for j in range(n) if G[i][j] > 0)
            lam_new[i] = W[i] / denom if denom > 1e-15 else lam[i]

        # Normalise so mean λ = 1
        mean_lam = sum(lam_new) / n
        if mean_lam > 0:
            lam_new = [x / mean_lam for x in lam_new]

        if max(abs(lam_new[i] - lam[i]) for i in range(n)) < tol:
            lam = lam_new
            break
        lam = lam_new

    return {driver_set[i]: lam[i] for i in range(n)}


# ---------------------------------------------------------------------------
# Plackett-Luce MM algorithm  (Hunter 2004)
# ---------------------------------------------------------------------------

def _plackett_luce_ratings(
    all_records: list[tuple[int, list[dict[str, Any]]]],
    evidence_gaps: list[str],
    max_iter: int = 2000,
    tol: float = 1e-9,
) -> dict[str, float]:
    """Return dict[driver_id → λ] via PL MM update on full rankings."""
    driver_set, driver_index = _build_driver_index(all_records)
    n = len(driver_set)
    if n == 0:
        return {}

    # Pre-compute rankings (sorted driver-id lists, best first)
    rankings: list[list[str]] = [_sorted_ids(recs) for _, recs in all_records]

    # W[i] = number of observed selections.  The final item contributes no
    # numerator term because its PL factor is lambda/lambda = 1.
    W = [0] * n
    for ranking in rankings:
        for did in ranking[:-1]:
            W[driver_index[did]] += 1

    lam = [1.0] * n

    for _ in range(max_iter):
        denom = [0.0] * n

        for ranking in rankings:
            m = len(ranking)
            idx = [driver_index[did] for did in ranking]

            # Suffix sums: suffix[k] = Σ_{j=k}^{m-1} λ[idx[j]]
            suffix = [0.0] * (m + 1)
            for k in range(m - 1, -1, -1):
                suffix[k] = suffix[k + 1] + lam[idx[k]]

            # Only stages 0..m-2 are non-constant PL likelihood factors.
            # psum[k] = Σ_{j=0}^{k-1} 1/suffix[j].
            psum = [0.0] * (m + 1)
            for k in range(max(0, m - 1)):
                psum[k + 1] = psum[k] + (1.0 / suffix[k] if suffix[k] > 1e-15 else 0.0)
            if m:
                psum[m] = psum[m - 1]

            # Driver at position pos (0-based) contributes psum[pos+1] to its denom
            for pos, did in enumerate(ranking):
                denom[driver_index[did]] += psum[pos + 1]

        lam_new = [W[i] / denom[i] if denom[i] > 1e-15 else lam[i] for i in range(n)]

        mean_lam = sum(lam_new) / n
        if mean_lam > 0:
            lam_new = [x / mean_lam for x in lam_new]

        if max(abs(lam_new[i] - lam[i]) for i in range(n)) < tol:
            lam = lam_new
            break
        lam = lam_new

    return {driver_set[i]: lam[i] for i in range(n)}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _collect_prior_records(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
    evidence_gaps: list[str],
    tag: str,
) -> list[tuple[int, list[dict[str, Any]]]]:
    records_out: list[tuple[int, list[dict[str, Any]]]] = []
    for rnd in sorted(completed_rounds, key=lambda r: int(r["round"])):
        rn = int(rnd["round"])
        if rn >= target_round:
            break
        recs = _qual_records(rnd)
        if recs:
            records_out.append((rn, recs))
        else:
            evidence_gaps.append(f"round_{rn:02d}_qualifying_missing_for_{tag}")
    return records_out


def _build_driver_index(
    all_records: list[tuple[int, list[dict[str, Any]]]],
) -> tuple[list[str], dict[str, int]]:
    driver_set: list[str] = []
    driver_index: dict[str, int] = {}
    for _, records in all_records:
        for r in records:
            did = str(r["driver_id"])
            if did not in driver_index:
                driver_index[did] = len(driver_set)
                driver_set.append(did)
    return driver_set, driver_index


def _sorted_ids(records: list[dict[str, Any]]) -> list[str]:
    return [str(r["driver_id"]) for r in sorted(records, key=lambda r: int(r["position"]))]
