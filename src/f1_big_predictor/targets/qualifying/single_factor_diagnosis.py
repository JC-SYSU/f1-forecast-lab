"""Single-factor diagnosis for qualifying prediction features.

For each feature in FEATURE_NAMES, this module computes:
  - coverage   : fraction of (driver, round) pairs with a non-None value
  - direction  : expected sign of correlation with qualifying position
  - pooled_rho : Spearman ρ between feature and actual qualifying position,
                 pooled across all evaluation rounds (with sign convention:
                 positive rho = feature correlates with *worse* position,
                 so a "lower_better" feature should have rho > 0)
  - per_round  : per-round Spearman ρ and coverage
  - stability  : mean / std / min / max of per-round rho values

No new dependencies — Spearman correlation is computed from first principles.
"""
from __future__ import annotations

from typing import Any

from .feature_matrix import FEATURE_DIRECTION, FEATURE_NAMES, build_feature_matrix

FIRST_ROUND = 2
LAST_ROUND = 9


def run_single_factor_diagnosis(
    completed_rounds: list[dict[str, Any]],
    first_round: int = FIRST_ROUND,
    last_round: int = LAST_ROUND,
) -> dict[str, Any]:
    """Run single-factor diagnosis for every feature over the evaluation window.

    Returns a dict with keys:
      ``season``      int
      ``rounds``      list of ints in the window
      ``features``    list of per-feature diagnostic dicts (see below)
      ``summary``     short coverage + correlation table for quick reading
    """
    completed_by_round = {int(r["round"]): r for r in completed_rounds}

    eval_rounds = [
        rn for rn in range(first_round, last_round + 1)
        if rn in completed_by_round
        and completed_by_round[rn].get("qualifying_results", {}).get("status") == "ok"
    ]

    # Gather (feature_value, actual_pos) pairs per feature per round
    per_round_data: dict[str, list[dict[str, Any]]] = {f: [] for f in FEATURE_NAMES}
    pooled: dict[str, list[tuple[float, float]]] = {f: [] for f in FEATURE_NAMES}

    for rn in eval_rounds:
        rnd_payload = completed_by_round[rn]
        actual_pos = {
            str(r["driver_id"]): int(r["position"])
            for r in rnd_payload.get("qualifying_results", {}).get("records", [])
            if r.get("driver_id") and r.get("position") is not None
        }
        matrix = build_feature_matrix(rn, completed_rounds)

        for feat in FEATURE_NAMES:
            pairs: list[tuple[float, float]] = []
            for row in matrix:
                val = row.get(feat)
                did = row["driver_id"]
                if val is not None and did in actual_pos:
                    pairs.append((float(val), float(actual_pos[did])))
            rho = _spearman_rho([p[0] for p in pairs], [p[1] for p in pairs])
            per_round_data[feat].append({
                "round": rn,
                "race_name": rnd_payload.get("race_name"),
                "coverage": len(pairs) / len(matrix) if matrix else 0.0,
                "n_pairs": len(pairs),
                "spearman_rho": round(rho, 4) if rho == rho else None,  # nan guard
            })
            pooled[feat].extend(pairs)

    features_out: list[dict[str, Any]] = []
    for feat in FEATURE_NAMES:
        all_pairs = pooled[feat]
        all_rho = _spearman_rho([p[0] for p in all_pairs], [p[1] for p in all_pairs])
        per_rnd = per_round_data[feat]
        rho_values = [r["spearman_rho"] for r in per_rnd if r["spearman_rho"] is not None]
        total_obs = sum(r["n_pairs"] for r in per_rnd)
        total_possible = sum(
            len(build_feature_matrix(rn, completed_rounds)) for rn in eval_rounds
        )
        coverage = total_obs / total_possible if total_possible > 0 else 0.0

        features_out.append({
            "feature": feat,
            "expected_direction": FEATURE_DIRECTION[feat],
            "coverage": round(coverage, 4),
            "total_observations": total_obs,
            "pooled_spearman_rho": round(all_rho, 4) if all_rho == all_rho else None,
            "per_round": per_rnd,
            "stability": _stability(rho_values),
        })

    return {
        "rounds": eval_rounds,
        "round_count": len(eval_rounds),
        "features": features_out,
        "summary": _summary_table(features_out),
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _spearman_rho(x: list[float], y: list[float]) -> float:
    """Spearman rank correlation via Pearson on ranks; returns nan on degenerate input."""
    n = len(x)
    if n < 3:
        return float("nan")
    rx = _rank_values(x)
    ry = _rank_values(y)
    xb = sum(rx) / n
    yb = sum(ry) / n
    num = sum((rx[i] - xb) * (ry[i] - yb) for i in range(n))
    denom_sq = sum((rx[i] - xb) ** 2 for i in range(n)) * sum((ry[i] - yb) ** 2 for i in range(n))
    if denom_sq <= 0:
        return float("nan")
    return num / denom_sq ** 0.5


def _rank_values(values: list[float]) -> list[float]:
    """Average-rank ties."""
    indexed = sorted(enumerate(values), key=lambda t: t[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = avg
        i = j
    return ranks


def _stability(rho_values: list[float]) -> dict[str, Any]:
    if not rho_values:
        return {"n_rounds": 0, "mean": None, "std": None, "min": None, "max": None}
    n = len(rho_values)
    mean = sum(rho_values) / n
    variance = sum((v - mean) ** 2 for v in rho_values) / n
    return {
        "n_rounds": n,
        "mean": round(mean, 4),
        "std": round(variance ** 0.5, 4),
        "min": round(min(rho_values), 4),
        "max": round(max(rho_values), 4),
    }


def _summary_table(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One-line summary per feature, sorted by |pooled_rho| descending."""
    rows = []
    for f in features:
        rho = f["pooled_spearman_rho"]
        rows.append({
            "feature": f["feature"],
            "coverage": f["coverage"],
            "pooled_rho": rho,
            "abs_rho": abs(rho) if rho is not None else 0.0,
            "direction_consistent": (
                _direction_consistent(f["expected_direction"], rho)
                if rho is not None else None
            ),
            "stability_std": f["stability"]["std"],
        })
    return sorted(rows, key=lambda r: r["abs_rho"], reverse=True)


def _direction_consistent(expected: str, rho: float) -> bool:
    """Check if observed correlation sign matches expected direction.

    For a "lower_better" feature (e.g. standings_pos = 1 is best),
    a positive rho means higher feature value → higher (worse) actual pos,
    which is the expected direction.  For "higher_better", we expect rho < 0.
    """
    if expected == "lower_better":
        return rho > 0
    return rho < 0
