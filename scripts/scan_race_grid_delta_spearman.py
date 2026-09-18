"""Single-factor Spearman ρ analysis for the grid_delta feature family.

Evaluation window: R03–R11 (R02 training-only per project policy).
For each feature variant, reports:
  - pooled Spearman ρ (all rounds combined)
  - per-round ρ (stability)
  - coverage (fraction of driver-slots with a non-None feature value)

Usage:
    python3 scripts/scan_race_grid_delta_spearman.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean, stdev
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from f1_big_predictor.targets.race.grid_delta_features import (
    ALL_VARIANTS,
    VARIANT_RISK,
    compute_grid_delta_features,
)

ACTUALS_PATH = PROJECT_ROOT / "data/processed/season_2026_actuals/actuals.json"
EVAL_ROUNDS  = list(range(3, 12))   # R03–R11


# ---------------------------------------------------------------------------
# Spearman ρ (no external deps)
# ---------------------------------------------------------------------------

def _rank(vals: list[float]) -> list[float]:
    indexed = sorted(enumerate(vals), key=lambda t: t[1])
    ranks = [0.0] * len(vals)
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


def spearman(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 3:
        return float("nan")
    rx, ry = _rank(x), _rank(y)
    xm, ym = sum(rx) / n, sum(ry) / n
    num   = sum((rx[i] - xm) * (ry[i] - ym) for i in range(n))
    denom = (sum((rx[i] - xm) ** 2 for i in range(n)) *
             sum((ry[i] - ym) ** 2 for i in range(n))) ** 0.5
    return num / denom if denom > 0 else float("nan")


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def run_analysis(completed_rounds: list[dict[str, Any]]) -> dict[str, Any]:
    features = ["grid_position"] + ALL_VARIANTS

    # pooled_pairs[feat] = [(feat_val, actual_finish), ...]
    pooled: dict[str, list[tuple[float, float]]] = {f: [] for f in features}
    per_round: dict[str, list[dict]] = {f: [] for f in features}

    for rn in EVAL_ROUNDS:
        rows = compute_grid_delta_features(rn, completed_rounds)
        if not rows:
            continue
        race_name = next(
            (r["race_name"] for r in completed_rounds if int(r["round"]) == rn), f"R{rn:02d}"
        )

        for feat in features:
            pairs = [
                (float(row[feat]), float(row["actual_finish"]))
                for row in rows
                if row.get(feat) is not None and row.get("actual_finish") is not None
            ]
            n_total = sum(1 for row in rows if row.get("actual_finish") is not None)
            rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
            per_round[feat].append({
                "round":    rn,
                "race_name": race_name,
                "n_pairs":  len(pairs),
                "n_total":  n_total,
                "coverage": len(pairs) / n_total if n_total else 0.0,
                "rho":      round(rho, 4) if rho == rho else None,
            })
            pooled[feat].extend(pairs)

    results = []
    for feat in features:
        pp = pooled[feat]
        all_rho = spearman([p[0] for p in pp], [p[1] for p in pp]) if pp else float("nan")
        rho_vals = [r["rho"] for r in per_round[feat] if r["rho"] is not None]
        cov_vals = [r["coverage"] for r in per_round[feat]]
        results.append({
            "feature":       feat,
            "pooled_rho":    round(all_rho, 4) if all_rho == all_rho else None,
            "abs_rho":       abs(all_rho) if all_rho == all_rho else 0.0,
            "mean_coverage": round(mean(cov_vals), 3) if cov_vals else 0.0,
            "rho_mean":      round(mean(rho_vals), 4) if rho_vals else None,
            "rho_std":       round(stdev(rho_vals), 4) if len(rho_vals) >= 2 else None,
            "rho_min":       round(min(rho_vals), 4) if rho_vals else None,
            "rho_max":       round(max(rho_vals), 4) if rho_vals else None,
            "risk":          VARIANT_RISK.get(feat, ""),
            "per_round":     per_round[feat],
        })

    results.sort(key=lambda r: r["abs_rho"], reverse=True)
    return results


def print_summary(results: list[dict]) -> None:
    # Direction note: higher grid → higher finish number (worse) → expected ρ > 0 for grid_position
    #                 higher delta → more overtaking → expected ρ < 0 for delta features
    print("=" * 90)
    print("grid_delta family one-way Spearman ρ analysis  (R03–R09, classified drivers)")
    print("Positive ρ > 0 → higher feature value → worse finish position (grid_position should be positive)")
    print("Negative ρ < 0 → higher feature value → better finish position (delta-style features should be negative)")
    print("=" * 90)
    hdr = f"{'feature':<28} {'pooled_ρ':>9} {'|ρ|':>6} {'cov':>5} {'ρ_mean':>8} {'ρ_std':>7} {'ρ_min':>7} {'ρ_max':>7}  risk"
    print(hdr)
    print("-" * 90)

    null_rho = next((r["pooled_rho"] for r in results if r["feature"] == "grid_position"), None)
    print(f"{'[null] grid_position':<28} {null_rho or 'N/A':>9}  ← baseline")
    print("-" * 90)

    for r in results:
        if r["feature"] == "grid_position":
            continue
        rho_str = f"{r['pooled_rho']:+.4f}" if r["pooled_rho"] is not None else "  None"
        cov_str = f"{r['mean_coverage']:.2f}"
        rmean   = f"{r['rho_mean']:+.4f}" if r["rho_mean"] is not None else "  None"
        rstd    = f"{r['rho_std']:.4f}"   if r["rho_std"]  is not None else "  None"
        rmin    = f"{r['rho_min']:+.4f}"  if r["rho_min"]  is not None else "  None"
        rmax    = f"{r['rho_max']:+.4f}"  if r["rho_max"]  is not None else "  None"
        risk    = ("⚠" + r["risk"][:30]) if r["risk"] else ""
        print(f"{r['feature']:<28} {rho_str:>9} {r['abs_rho']:>6.4f} {cov_str:>5} "
              f"{rmean:>8} {rstd:>7} {rmin:>7} {rmax:>7}  {risk}")


def main() -> None:
    data = json.loads(ACTUALS_PATH.read_text(encoding="utf-8"))
    completed_rounds = sorted(data["completed_rounds"], key=lambda r: int(r["round"]))
    results = run_analysis(completed_rounds)
    print_summary(results)

    # Also save raw JSON for later use
    out_path = PROJECT_ROOT / "outputs/experiments/race/grid_delta_spearman.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nFull results written to: {out_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
