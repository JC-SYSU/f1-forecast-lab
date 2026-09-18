"""Rating-system models for qualifying prediction.

Elo    — incremental pairwise update, K-factor configurable
Massey — batch linear system, binary margin, sum-to-zero constraint
Colley — batch linear system, Laplace-regularised, ratings in (0, 1)
Keener — principal eigenvector of Laplace-smoothed pairwise win-rate matrix
Glicko — Elo + rating deviation (uncertainty); batch update per period (all-pairs)
Gaussian pairwise approximation — custom all-pairs truncated-normal updates

Pairwise convention for Elo/Massey/Colley/Keener/Glicko (all-pairs):
  N=22 → N*(N-1)/2 = 231 pairs per round.

The Gaussian approximation is not standard TrueSkill.  It decomposes the full
ranking into all pairs and applies a batch truncated-normal approximation.
"""
from __future__ import annotations

import math
from typing import Any

from .feature_matrix import _target_round_field   # reuse driver list helper
from .ridge_model import _solve_linear            # reuse Gaussian elimination

TARGET_ID = "qualifying"
MODEL_ID_ELO = "qualifying.model.rating.elo"
MODEL_ID_MASSEY = "qualifying.model.rating.massey"
MODEL_ID_COLLEY = "qualifying.model.rating.colley"
MODEL_ID_KEENER = "qualifying.model.rating.keener"
MODEL_ID_GLICKO = "qualifying.model.rating.glicko"
MODEL_ID_GAUSSIAN_PAIRWISE = "qualifying.model.rating.gaussian_pairwise_approx"
FEATURE_SET_ID_ELO = "qualifying.features.rating.elo_v1"
FEATURE_SET_ID_MASSEY = "qualifying.features.rating.massey_v1"
FEATURE_SET_ID_COLLEY = "qualifying.features.rating.colley_v1"
FEATURE_SET_ID_KEENER = "qualifying.features.rating.keener_v1"
FEATURE_SET_ID_GLICKO = "qualifying.features.rating.glicko_v1"
FEATURE_SET_ID_GAUSSIAN_PAIRWISE = (
    "qualifying.features.rating.gaussian_pairwise_approx_v1"
)
FALLBACK_POLICY = "initial_rating_for_new_entrants"
TOP10_SIZE = 10

INITIAL_ELO = 1500.0
DEFAULT_K = 4.0   # per pairwise comparison; chosen so max ≈21*4=84 pts/round


# ===========================================================================
# Public API
# ===========================================================================

def predict_elo(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
    k: float = DEFAULT_K,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Train Elo on rounds < target_round; rank by pre-round rating."""
    evidence_gaps: list[str] = []
    ratings: dict[str, float] = {}

    for rnd in sorted(completed_rounds, key=lambda r: int(r["round"])):
        rn = int(rnd["round"])
        if rn >= target_round:
            break
        records = _qual_records(rnd)
        if not records:
            evidence_gaps.append(f"round_{rn:02d}_qualifying_missing_for_elo")
            continue
        _elo_update(ratings, records, k)

    return _rank_by_rating(
        target_round, completed_rounds, ratings,
        model_id=MODEL_ID_ELO, feature_set_id=FEATURE_SET_ID_ELO,
        default_score=INITIAL_ELO, evidence_gaps=evidence_gaps,
    )


def predict_massey(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Solve Massey linear system on all rounds < target_round; rank by rating."""
    evidence_gaps: list[str] = []
    all_records: list[tuple[int, list[dict[str, Any]]]] = []

    for rnd in sorted(completed_rounds, key=lambda r: int(r["round"])):
        rn = int(rnd["round"])
        if rn >= target_round:
            break
        records = _qual_records(rnd)
        if records:
            all_records.append((rn, records))
        else:
            evidence_gaps.append(f"round_{rn:02d}_qualifying_missing_for_massey")

    if not all_records:
        return _empty_result(MODEL_ID_MASSEY, FEATURE_SET_ID_MASSEY,
                              evidence_gaps + ["no_prior_qualifying_data"])

    ratings = _massey_ratings(all_records, evidence_gaps)

    return _rank_by_rating(
        target_round, completed_rounds, ratings,
        model_id=MODEL_ID_MASSEY, feature_set_id=FEATURE_SET_ID_MASSEY,
        default_score=0.0, evidence_gaps=evidence_gaps,
    )


# ===========================================================================
# Elo update
# ===========================================================================

def _elo_update(
    ratings: dict[str, float],
    qual_records: list[dict[str, Any]],
    k: float,
) -> None:
    """Batch-update Elo ratings in-place from one round's all-pairs result."""
    sorted_rec = sorted(qual_records, key=lambda r: int(r["position"]))
    drivers = [str(r["driver_id"]) for r in sorted_rec]
    n = len(drivers)

    # Ensure all drivers have an entry (new entrants start at INITIAL_ELO)
    for d in drivers:
        ratings.setdefault(d, INITIAL_ELO)

    # Collect all deltas first (batch update avoids within-round order effects)
    delta: dict[str, float] = {d: 0.0 for d in drivers}
    for i in range(n):
        for j in range(i + 1, n):
            # i beat j
            r_i, r_j = ratings[drivers[i]], ratings[drivers[j]]
            expected_i = 1.0 / (1.0 + 10.0 ** ((r_j - r_i) / 400.0))
            pair_delta = k * (1.0 - expected_i)
            delta[drivers[i]] += pair_delta
            delta[drivers[j]] -= pair_delta

    for d, dv in delta.items():
        ratings[d] += dv


# ===========================================================================
# Massey linear system
# ===========================================================================

def _massey_ratings(
    all_records: list[tuple[int, list[dict[str, Any]]]],
    evidence_gaps: list[str],
) -> dict[str, float]:
    """Solve the Massey system from all prior round data.

    Returns driver_id → rating (sum-to-zero constraint).
    """
    # Collect all known drivers
    driver_set: list[str] = []
    driver_index: dict[str, int] = {}
    for _, records in all_records:
        for r in records:
            did = str(r["driver_id"])
            if did not in driver_index:
                driver_index[did] = len(driver_set)
                driver_set.append(did)
    n = len(driver_set)
    if n == 0:
        return {}

    # Build Massey matrix M (n×n) and RHS p (n)
    M = [[0.0] * n for _ in range(n)]
    p = [0.0] * n

    for _, records in all_records:
        sorted_rec = sorted(records, key=lambda r: int(r["position"]))
        ids = [str(r["driver_id"]) for r in sorted_rec]
        m = len(ids)
        for i in range(m):
            for j in range(i + 1, m):
                # ids[i] beat ids[j] (all-pairs, binary margin ±1)
                a, b = driver_index[ids[i]], driver_index[ids[j]]
                M[a][a] += 1
                M[b][b] += 1
                M[a][b] -= 1
                M[b][a] -= 1
                p[a] += 1
                p[b] -= 1

    # Replace last row with sum-to-zero constraint
    for j in range(n):
        M[n - 1][j] = 1.0
    p[n - 1] = 0.0

    try:
        ratings_vec = _solve_linear(M, p)
    except ValueError as exc:
        evidence_gaps.append(f"massey_solve_failed:{exc}")
        return {d: 0.0 for d in driver_set}

    return {driver_set[i]: ratings_vec[i] for i in range(n)}


# ===========================================================================
# Shared helpers
# ===========================================================================

def _rank_by_rating(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
    ratings: dict[str, float],
    *,
    model_id: str,
    feature_set_id: str,
    default_score: float,
    evidence_gaps: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    target_drivers, _ = _target_round_field(completed_rounds, target_round)
    if not target_drivers:
        return _empty_result(model_id, feature_set_id,
                              evidence_gaps + ["target_round_field_missing"])

    new_entrants = [d for d in target_drivers if d not in ratings]
    if new_entrants:
        evidence_gaps.append(f"new_entrants_{len(new_entrants)}_assigned_default")

    ordered = sorted(
        target_drivers,
        key=lambda d: (-ratings.get(d, default_score), d),
    )
    n = len(ordered)
    full_ranking = [
        {"driver_id": did, "position": pos,
         "score": round(ratings.get(did, default_score), 6)}
        for pos, did in enumerate(ordered, start=1)
    ]
    if n >= TOP10_SIZE:
        entries, status = full_ranking[:TOP10_SIZE], "ok"
    else:
        entries, status = [], "evidence_issue"
        evidence_gaps.append("insufficient_drivers_for_top10")

    return {
        "target_id": TARGET_ID, "model_id": model_id,
        "feature_set_id": feature_set_id, "fallback_policy": FALLBACK_POLICY,
        "status": status, "entries": entries, "evidence_gaps": evidence_gaps,
    }, full_ranking


def _qual_records(rnd: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        r for r in (rnd.get("qualifying_results", {}).get("records") or [])
        if r.get("driver_id") and r.get("position") is not None
    ]


def _empty_result(model_id: str, feature_set_id: str, gaps: list[str]) -> tuple[dict, list]:
    return {
        "target_id": TARGET_ID, "model_id": model_id, "feature_set_id": feature_set_id,
        "fallback_policy": FALLBACK_POLICY, "status": "evidence_issue",
        "entries": [], "evidence_gaps": gaps,
    }, []


# ===========================================================================
# Colley
# ===========================================================================

def predict_colley(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Solve the Colley matrix system on all rounds < target_round.

    New entrants (not seen in any prior round) receive the prior rating 0.5.
    Colley's matrix is positive-definite by construction; no external
    sum-to-zero constraint is needed.
    """
    evidence_gaps: list[str] = []
    all_records: list[tuple[int, list[dict[str, Any]]]] = []

    for rnd in sorted(completed_rounds, key=lambda r: int(r["round"])):
        rn = int(rnd["round"])
        if rn >= target_round:
            break
        records = _qual_records(rnd)
        if records:
            all_records.append((rn, records))
        else:
            evidence_gaps.append(f"round_{rn:02d}_qualifying_missing_for_colley")

    if not all_records:
        return _empty_result(MODEL_ID_COLLEY, FEATURE_SET_ID_COLLEY,
                              evidence_gaps + ["no_prior_qualifying_data"])

    ratings = _colley_ratings(all_records, evidence_gaps)

    return _rank_by_rating(
        target_round, completed_rounds, ratings,
        model_id=MODEL_ID_COLLEY, feature_set_id=FEATURE_SET_ID_COLLEY,
        default_score=0.5,   # Colley prior for new entrants
        evidence_gaps=evidence_gaps,
    )


def _colley_ratings(
    all_records: list[tuple[int, list[dict[str, Any]]]],
    evidence_gaps: list[str],
) -> dict[str, float]:
    """Solve the Colley linear system.

    Colley matrix C (n×n):
      C_ii = 2 + total_games_i      (Laplace "+2" ensures positive-definiteness)
      C_ij = -games_between_i_and_j  (off-diagonal, symmetric)

    Right-hand side b_i = 1 + (wins_i - losses_i) / 2
      (starts at 1 = Laplace prior of 0.5 win-rate; data moves it up or down)
    """
    driver_set: list[str] = []
    driver_index: dict[str, int] = {}
    for _, records in all_records:
        for r in records:
            did = str(r["driver_id"])
            if did not in driver_index:
                driver_index[did] = len(driver_set)
                driver_set.append(did)
    n = len(driver_set)
    if n == 0:
        return {}

    C = [[0.0] * n for _ in range(n)]
    b = [0.0] * n

    # Initialise diagonal with Laplace correction +2 and b with 1
    for i in range(n):
        C[i][i] = 2.0
        b[i] = 1.0

    for _, records in all_records:
        sorted_rec = sorted(records, key=lambda r: int(r["position"]))
        ids = [str(r["driver_id"]) for r in sorted_rec]
        m = len(ids)
        for i in range(m):
            for j in range(i + 1, m):
                # ids[i] beat ids[j]
                a, bb = driver_index[ids[i]], driver_index[ids[j]]
                C[a][a] += 1      # total games for winner
                C[bb][bb] += 1    # total games for loser
                C[a][bb] -= 1     # symmetric off-diagonal
                C[bb][a] -= 1
                b[a] += 0.5       # win  → b increases by 0.5
                b[bb] -= 0.5      # loss → b decreases by 0.5

    try:
        ratings_vec = _solve_linear(C, b)
    except ValueError as exc:
        evidence_gaps.append(f"colley_solve_failed:{exc}")
        return {d: 0.5 for d in driver_set}

    return {driver_set[i]: ratings_vec[i] for i in range(n)}


# ===========================================================================
# Keener
# ===========================================================================

def predict_keener(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
    alpha: float = 0.25,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compute Keener eigenvector ratings on all rounds < target_round.

    Keener (1993): build pairwise win-rate matrix A with Laplace smoothing
      A[i][j] = (s_ij + alpha) / (s_ij + s_ji + 2*alpha)  for i ≠ j
      A[i][i] = 0
    then find the principal eigenvector via power iteration.

    alpha=0.25 (default) is the grid-search optimum on R02–R08 and R03–R08
    evaluation windows (both windows agree on the same value).  Compared to
    the standard alpha=1.0, the lighter smoothing lets the model differentiate
    drivers faster once even a little pairwise data exists.
    New entrants receive A[new][j] = 0.5 when alpha→0 or alpha→∞, so they
    always get an approximately average eigenvector entry regardless of alpha.
    """
    evidence_gaps: list[str] = []
    all_records: list[tuple[int, list[dict[str, Any]]]] = []

    for rnd in sorted(completed_rounds, key=lambda r: int(r["round"])):
        rn = int(rnd["round"])
        if rn >= target_round:
            break
        records = _qual_records(rnd)
        if records:
            all_records.append((rn, records))
        else:
            evidence_gaps.append(f"round_{rn:02d}_qualifying_missing_for_keener")

    if not all_records:
        return _empty_result(MODEL_ID_KEENER, FEATURE_SET_ID_KEENER,
                              evidence_gaps + ["no_prior_qualifying_data"])

    ratings = _keener_ratings(all_records, evidence_gaps, alpha=alpha)
    default = 1.0 / max(len(ratings), 1)

    return _rank_by_rating(
        target_round, completed_rounds, ratings,
        model_id=MODEL_ID_KEENER, feature_set_id=FEATURE_SET_ID_KEENER,
        default_score=default, evidence_gaps=evidence_gaps,
    )


def _keener_ratings(
    all_records: list[tuple[int, list[dict[str, Any]]]],
    evidence_gaps: list[str],
    alpha: float = 0.25,
    max_iter: int = 2000,
    tol: float = 1e-9,
) -> dict[str, float]:
    """Build Keener matrix and return principal eigenvector via power iteration.

    A[i][j] = (s_ij + alpha) / (s_ij + s_ji + 2*alpha)   i ≠ j
    A[i][i] = 0

    All off-diagonal entries are ≥ 1/(total_games+2) > 0, so the matrix is
    irreducible and Perron-Frobenius guarantees convergence to a unique
    positive leading eigenvector.
    """
    driver_set: list[str] = []
    driver_index: dict[str, int] = {}
    for _, records in all_records:
        for r in records:
            did = str(r["driver_id"])
            if did not in driver_index:
                driver_index[did] = len(driver_set)
                driver_set.append(did)
    n = len(driver_set)
    if n == 0:
        return {}

    # s[i][j] = times i finished ahead of j (all prior rounds combined)
    s: list[list[int]] = [[0] * n for _ in range(n)]
    for _, records in all_records:
        sorted_rec = sorted(records, key=lambda r: int(r["position"]))
        ids = [str(r["driver_id"]) for r in sorted_rec]
        m = len(ids)
        for i in range(m):
            for j in range(i + 1, m):
                a, b = driver_index[ids[i]], driver_index[ids[j]]
                s[a][b] += 1

    # Build Keener matrix (Laplace-smoothed pairwise win rates)
    A: list[list[float]] = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                sij, sji = s[i][j], s[j][i]
                A[i][j] = (sij + alpha) / (sij + sji + 2.0 * alpha)

    # Power iteration — uniform start, L1-normalise each step
    r = [1.0 / n] * n
    for _ in range(max_iter):
        r_new = [sum(A[i][j] * r[j] for j in range(n)) for i in range(n)]
        norm = sum(r_new)
        if norm < 1e-14:
            evidence_gaps.append("keener_power_iteration_degenerate")
            break
        r_new = [x / norm for x in r_new]
        if max(abs(r_new[i] - r[i]) for i in range(n)) < tol:
            r = r_new
            break
        r = r_new

    return {driver_set[i]: r[i] for i in range(n)}


# ===========================================================================
# Glicko  (pairwise, all-pairs, batch update per period)
# ===========================================================================

# Glicko constants
_GLICKO_Q = math.log(10.0) / 400.0          # ≈ 0.005756
_GLICKO_PI2 = math.pi ** 2
INITIAL_GLICKO_R = 1500.0
INITIAL_GLICKO_RD = 200.0
DEFAULT_GLICKO_C = 30.0   # RD grows by c per inactive period
GLICKO_RD_MAX = 350.0


def predict_glicko(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
    initial_rd: float = INITIAL_GLICKO_RD,
    c: float = DEFAULT_GLICKO_C,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Glicko ratings: Elo + rating deviation (uncertainty)."""
    evidence_gaps: list[str] = []
    all_records: list[tuple[int, list[dict[str, Any]]]] = []

    for rnd in sorted(completed_rounds, key=lambda r: int(r["round"])):
        rn = int(rnd["round"])
        if rn >= target_round:
            break
        records = _qual_records(rnd)
        if records:
            all_records.append((rn, records))
        else:
            evidence_gaps.append(f"round_{rn:02d}_qualifying_missing_for_glicko")

    if not all_records:
        return _empty_result(MODEL_ID_GLICKO, FEATURE_SET_ID_GLICKO,
                              evidence_gaps + ["no_prior_qualifying_data"])

    ratings = _glicko_ratings(all_records, initial_rd, c, evidence_gaps)
    # Rank by r only (RD not used for ranking, just for uncertainty info)
    score_map = {d: r for d, (r, _rd) in ratings.items()}

    return _rank_by_rating(
        target_round, completed_rounds, score_map,
        model_id=MODEL_ID_GLICKO, feature_set_id=FEATURE_SET_ID_GLICKO,
        default_score=INITIAL_GLICKO_R, evidence_gaps=evidence_gaps,
    )


def _glicko_ratings(
    all_records: list[tuple[int, list[dict[str, Any]]]],
    initial_rd: float,
    c: float,
    evidence_gaps: list[str],
) -> dict[str, tuple[float, float]]:
    """Return dict[driver_id → (r, RD)] after processing all records."""
    if initial_rd <= 0 or initial_rd > GLICKO_RD_MAX:
        raise ValueError(
            f"initial_rd must be within (0, {GLICKO_RD_MAX}], got {initial_rd}"
        )
    if c < 0:
        raise ValueError(f"c must be non-negative, got {c}")

    ratings: dict[str, tuple[float, float]] = {}  # driver_id → (r, RD)
    last_period_round: int | None = None

    for round_number, records in sorted(all_records, key=lambda item: item[0]):
        sorted_rec = sorted(records, key=lambda r: int(r["position"]))
        ids = [str(r["driver_id"]) for r in sorted_rec]

        if last_period_round is not None:
            elapsed_periods = max(1, round_number - last_period_round)
            for did, (rating, rd) in list(ratings.items()):
                pre_period_rd = min(
                    math.sqrt(rd**2 + c**2 * elapsed_periods),
                    GLICKO_RD_MAX,
                )
                ratings[did] = (rating, pre_period_rd)

        # Ensure all drivers in this round have an initial rating
        for did in ids:
            if did not in ratings:
                ratings[did] = (INITIAL_GLICKO_R, initial_rd)

        # Batch Glicko update: compute all new ratings before applying any
        new_ratings: dict[str, tuple[float, float]] = {}
        for i, did_i in enumerate(ids):
            r_i, rd_i = ratings[did_i]
            # All opponents = all other drivers in this round (all-pairs)
            sum_g = 0.0
            sum_delta = 0.0
            for j, did_j in enumerate(ids):
                if i == j:
                    continue
                r_j, rd_j = ratings[did_j]
                g_rdj = 1.0 / math.sqrt(1.0 + 3.0 * _GLICKO_Q**2 * rd_j**2 / _GLICKO_PI2)
                e_ij = 1.0 / (1.0 + 10.0 ** (-g_rdj * (r_i - r_j) / 400.0))
                s_ij = 1.0 if i < j else 0.0   # i beat j if i has lower position index
                sum_g += g_rdj ** 2 * e_ij * (1.0 - e_ij)
                sum_delta += g_rdj * (s_ij - e_ij)

            d_sq = 1.0 / (_GLICKO_Q ** 2 * sum_g) if sum_g > 0 else 1e12
            factor = _GLICKO_Q / (1.0 / rd_i ** 2 + 1.0 / d_sq)
            new_r = r_i + factor * sum_delta
            new_rd = math.sqrt(1.0 / (1.0 / rd_i ** 2 + 1.0 / d_sq))
            new_ratings[did_i] = (new_r, new_rd)

        ratings.update(new_ratings)
        last_period_round = round_number

    return ratings


# ===========================================================================
# Gaussian pairwise approximation
# ===========================================================================

INITIAL_GP_MU = 25.0
INITIAL_GP_SIGMA = 25.0 / 3.0
DEFAULT_GP_BETA = 25.0 / 6.0
DEFAULT_GP_TAU = 25.0 / 300.0
_GP_K = 3.0


def predict_gaussian_pairwise(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
    beta: float = DEFAULT_GP_BETA,
    tau: float = DEFAULT_GP_TAU,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Custom Gaussian skill ratings via an all-pairs batch approximation.

    This deliberately does not claim standard TrueSkill compatibility.  Each
    qualifying round is decomposed into all pairwise comparisons, then updates
    are accumulated in a single batch.  Conservative score ``mu-k*sigma`` is
    used for ranking.
    """
    evidence_gaps: list[str] = []
    all_records: list[tuple[int, list[dict[str, Any]]]] = []

    for rnd in sorted(completed_rounds, key=lambda r: int(r["round"])):
        rn = int(rnd["round"])
        if rn >= target_round:
            break
        records = _qual_records(rnd)
        if records:
            all_records.append((rn, records))
        else:
            evidence_gaps.append(
                f"round_{rn:02d}_qualifying_missing_for_gaussian_pairwise"
            )

    if not all_records:
        return _empty_result(
            MODEL_ID_GAUSSIAN_PAIRWISE,
            FEATURE_SET_ID_GAUSSIAN_PAIRWISE,
            evidence_gaps + ["no_prior_qualifying_data"],
        )

    gp_ratings = _gaussian_pairwise_ratings(all_records, beta, tau, evidence_gaps)
    # Conservative rank score: mu - k*sigma
    score_map = {d: mu - _GP_K * sigma for d, (mu, sigma) in gp_ratings.items()}
    default_score = INITIAL_GP_MU - _GP_K * INITIAL_GP_SIGMA

    return _rank_by_rating(
        target_round, completed_rounds, score_map,
        model_id=MODEL_ID_GAUSSIAN_PAIRWISE,
        feature_set_id=FEATURE_SET_ID_GAUSSIAN_PAIRWISE,
        default_score=default_score, evidence_gaps=evidence_gaps,
    )


def _gaussian_pairwise_ratings(
    all_records: list[tuple[int, list[dict[str, Any]]]],
    beta: float,
    tau: float,
    evidence_gaps: list[str],
) -> dict[str, tuple[float, float]]:
    """Return dict[driver_id → (mu, sigma)] after processing all records."""
    ratings: dict[str, tuple[float, float]] = {}

    for _, records in all_records:
        sorted_ids = [
            str(r["driver_id"])
            for r in sorted(records, key=lambda r: int(r["position"]))
        ]
        for did in sorted_ids:
            if did not in ratings:
                ratings[did] = (INITIAL_GP_MU, INITIAL_GP_SIGMA)
        _gaussian_pairwise_update(ratings, sorted_ids, beta, tau)

    return ratings


def _gaussian_pairwise_update(
    ratings: dict[str, tuple[float, float]],
    ranked_ids: list[str],
    beta: float,
    tau: float,
) -> None:
    """Apply one all-pairs batch truncated-normal approximation.

    For each pair (i, j) with i finishing ahead of j:
      c   = sqrt(2β² + σᵢ² + σⱼ²)
      t   = (μᵢ - μⱼ) / c
      μᵢ += σᵢ²/c · v(t),  μⱼ -= σⱼ²/c · v(t)
      σᵢ² *= 1 - σᵢ²/c² · w(t),  same for σⱼ²

    All deltas are accumulated before applying to avoid order dependence.
    Dynamics (tau) added to each driver's sigma² after the round.
    """
    n = len(ranked_ids)
    if n < 2:
        return

    mus = [ratings[d][0] for d in ranked_ids]
    sigmas = [ratings[d][1] for d in ranked_ids]

    d_mu = [0.0] * n
    d_var = [0.0] * n

    for i in range(n):
        for j in range(i + 1, n):
            # ids[i] beat ids[j]
            si, sj = sigmas[i], sigmas[j]
            c = math.sqrt(2.0 * beta ** 2 + si ** 2 + sj ** 2)
            if c < 1e-14:
                continue
            t = (mus[i] - mus[j]) / c
            vt = _gp_v(t)
            wt = _gp_w(t, vt)
            d_mu[i] += si ** 2 / c * vt
            d_mu[j] -= sj ** 2 / c * vt
            d_var[i] -= si ** 2 * (si ** 2 / c ** 2) * wt
            d_var[j] -= sj ** 2 * (sj ** 2 / c ** 2) * wt

    for i, did in enumerate(ranked_ids):
        new_mu = mus[i] + d_mu[i]
        new_var = max(sigmas[i] ** 2 + d_var[i], 1e-8) + tau ** 2
        ratings[did] = (new_mu, math.sqrt(new_var))


def _gp_v(t: float) -> float:
    """v(t) = phi(t) / Phi(t) — truncated normal mean correction."""
    phi_t = math.exp(-0.5 * t * t) / math.sqrt(2.0 * math.pi)
    Phi_t = math.erfc(-t / math.sqrt(2.0)) / 2.0
    if Phi_t < 1e-15:
        return max(-t, 0.0)   # limit: v → -t as t → -∞
    return phi_t / Phi_t


def _gp_w(t: float, vt: float) -> float:
    """w(t) = v(t) * (v(t) + t)."""
    return vt * (vt + t)
