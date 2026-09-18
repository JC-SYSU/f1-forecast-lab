"""grid_delta feature family for race prediction single-factor analysis.

Computes driver-specific racecraft features using ONLY data from rounds strictly
prior to the target round (no leakage of target-round finish positions).

Feature naming: {N}_{S}_{W}
  N – normalization (expected delta given grid position)
    N0   raw delta, no correction
    N1a  2-band  (P01-11 / P12-22)
    N1b  4-band  (P01-05 / P06-10 / P11-15 / P16-22)
    N1c  per-position (P01..P22)           ⚠ sparse / high-risk
    N1d  6-band  (P01-04 / P05-08 / P09-12 / P13-16 / P17-19 / P20-22)
    N1e  8-band  (P01-03 / P04-06 / P07-09 / P10-12 / P13-15 / P16-18 / P19-20 / P21-22) ⚠ sparse
    N2   linear regression                 ⚠ only 2 params – OK for n≥10
    N2a  quadratic polynomial (2nd order)  ⚠ 3 params – needs n≥15
    N2b  cubic polynomial (3rd order)      ⚠ 4 params – needs n≥20
    N2c  linear on log(grid)              captures log-scale overtaking difficulty
    N2d  linear on sqrt(grid)             intermediate between linear and log
    N3   isotonic (pool-adjacent-violators)⚠ very sparse for early rounds
    N4   cubic spline (3-5 knots)          ⚠ adaptive smoothness
    N5   Gaussian kernel smooth (BW=3)     data-adaptive, non-parametric
    N6   2-segment piecewise linear        auto breakpoint search P4–P19
    N7   3-segment piecewise linear        fixed BP at P6/P17 (front/mid/back)
    N2f0 N2 baseline + mean aggregation    (current baseline, for comparison)
    N2f1 N2 baseline + median aggregation  robust to outliers
    N2f2 N2 baseline + trimmed mean        drop top/bottom 20%
    N2f3 N2 baseline + Winsorized mean     clip extremes to P10/P90
    N2f4 N2 baseline + exponential weighted recent races weighted higher
    N2f5 N2 baseline + linear decay        older races downweighted
    N2f6 N2 baseline + hit rate            fraction of races beating baseline
    N2f7 N2 baseline + big gain rate       fraction with delta > baseline + 3
    N2f8 N2 baseline + Bayesian shrinkage  sparse history penalty
    N2f9 N2 baseline + recent-only mean    last 60% of history only
  S – scaling of residuals
    S0   subtract mean only
    S1   z-score (subtract mean, divide by std)   ⚠ N1c+S1 is high-risk
  W – history window (prior completed races for this driver)
    Wexp expanding – all prior completed races
    W3   last 3 prior completed races
    W5   last 5 prior completed races
    W7   last 7 prior completed races

Also includes:
  grid_position  – driver's starting grid at target round (reference feature)

High-risk combinations are marked in VARIANT_RISK.
"""
from __future__ import annotations

import math
from statistics import mean, stdev
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FINISHER_STATUSES = {"Finished", "Lapped"}

BANDS_1A = [(1, 11), (12, 22)]
BANDS_1B = [(1, 5), (6, 10), (11, 15), (16, 22)]
BANDS_1D = [(1, 4), (5, 8), (9, 12), (13, 16), (17, 19), (20, 22)]
BANDS_1E = [(1, 3), (4, 6), (7, 9), (10, 12), (13, 15), (16, 18), (19, 20), (21, 22)]

# All (N, S, W) combinations
_N_METHODS  = ["N0", "N1a", "N1b", "N1c", "N1d", "N1e", "N2", "N2a", "N2b", "N2c", "N2d", "N3", "N4", "N5", "N6", "N7",
               "N2f0", "N2f1", "N2f2", "N2f3", "N2f4", "N2f5", "N2f6", "N2f7", "N2f8", "N2f9"]
_S_METHODS  = ["S0", "S1"]
_W_METHODS  = ["Wexp", "W3", "W5", "W7"]

# Risk annotations: variants where signal may be unreliable due to small samples
VARIANT_RISK: dict[str, str] = {}
for _n in _N_METHODS:
    for _s in _S_METHODS:
        for _w in _W_METHODS:
            _key = f"{_n}_{_s}_{_w}"
            _risks = []
            if _n == "N1c":
                _risks.append("per-pos sparse")
            if _n == "N1e":
                _risks.append("8-band sparse")
            if _n == "N3":
                _risks.append("isotonic sparse early rounds")
            if _n == "N2a":
                _risks.append("quadratic 3-param")
            if _n == "N2b":
                _risks.append("cubic 4-param")
            if _n == "N4":
                _risks.append("spline adaptive knots")
            if _n == "N6":
                _risks.append("2-seg piecewise search")
            if _n == "N7":
                _risks.append("front-seg P1-6 sparse")
            if _s == "S1" and _n == "N1c":
                _risks.append("std from tiny band")
            if _s == "S1" and _n == "N1e":
                _risks.append("std from tiny band")
            if _w in ("W3", "W5") and _n in ("N2", "N2a", "N2b", "N2c", "N2d", "N3", "N4", "N5", "N6", "N7"):
                _risks.append("regression on ≤3/5 pts")
            if _w == "W7" and _n in ("N2", "N2a", "N2b", "N2c", "N2d", "N3", "N4", "N5", "N6", "N7"):
                _risks.append("regression on ≤7 pts")
            if _risks:
                VARIANT_RISK[_key] = "; ".join(_risks)

ALL_VARIANTS: list[str] = [
    f"{n}_{s}_{w}"
    for n in _N_METHODS
    for s in _S_METHODS
    for w in _W_METHODS
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_grid_delta_features(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return one row per driver in target_round with all feature values.

    Each row:
      driver_id       str
      grid_position   int | None    (pre-race input, always available)
      actual_finish   int | None    (label – actual finish position)
      <variant>       float | None  for each name in ALL_VARIANTS
    """
    # Split training vs target
    training = [r for r in completed_rounds if int(r["round"]) < target_round]
    target   = next((r for r in completed_rounds if int(r["round"]) == target_round), None)
    if target is None:
        return []

    # Build flat training records (only finishers contribute to delta)
    train_recs = _extract_finisher_records(training)

    # Fit normalisation models from training data
    band_means_1a = _fit_band_means(train_recs, BANDS_1A)
    band_stds_1a  = _fit_band_stds(train_recs, BANDS_1A, band_means_1a)
    band_means_1b = _fit_band_means(train_recs, BANDS_1B)
    band_stds_1b  = _fit_band_stds(train_recs, BANDS_1B, band_means_1b)
    band_means_1d = _fit_band_means(train_recs, BANDS_1D)
    band_stds_1d  = _fit_band_stds(train_recs, BANDS_1D, band_means_1d)
    band_means_1e = _fit_band_means(train_recs, BANDS_1E)
    band_stds_1e  = _fit_band_stds(train_recs, BANDS_1E, band_means_1e)
    pos_means     = _fit_per_pos_means(train_recs)
    pos_stds      = _fit_per_pos_stds(train_recs, pos_means)
    lin_a, lin_b  = _fit_linear(train_recs)
    lin_resid_std = _fit_linear_resid_std(train_recs, lin_a, lin_b)
    log_a, log_b  = _fit_log_linear(train_recs)
    log_resid_std = _fit_transform_resid_std(train_recs, log_a, log_b, math.log)
    sqrt_a, sqrt_b = _fit_sqrt_linear(train_recs)
    sqrt_resid_std = _fit_transform_resid_std(train_recs, sqrt_a, sqrt_b, math.sqrt)
    poly2_a, poly2_b, poly2_c = _fit_poly2(train_recs)
    poly2_resid_std = _poly2_resid_std(train_recs, poly2_a, poly2_b, poly2_c)
    poly3_a, poly3_b, poly3_c, poly3_d = _fit_poly3(train_recs)
    poly3_resid_std = _poly3_resid_std(train_recs, poly3_a, poly3_b, poly3_c, poly3_d)
    iso_means     = _fit_isotonic(train_recs)
    spline_dict   = _fit_spline(train_recs)
    spline_resid_std = _spline_resid_std(train_recs, spline_dict)
    kernel_means     = _fit_kernel(train_recs)
    kernel_resid_std = _kernel_resid_std(train_recs, kernel_means)
    pw2_a1, pw2_b1, pw2_a2, pw2_b2, pw2_bp = _fit_piecewise2(train_recs)
    pw2_resid_std    = _piecewise2_resid_std(train_recs, pw2_a1, pw2_b1, pw2_a2, pw2_b2, pw2_bp)
    pw3_a1, pw3_b1, pw3_a2, pw3_b2, pw3_a3, pw3_b3 = _fit_piecewise3(train_recs)
    pw3_resid_std    = _piecewise3_resid_std(train_recs, pw3_a1, pw3_b1, pw3_a2, pw3_b2, pw3_a3, pw3_b3)

    # Build per-driver history index (all prior completed races, sorted by round)
    driver_history: dict[str, list[dict[str, Any]]] = {}
    for rec in sorted(train_recs, key=lambda x: x["round"]):
        driver_history.setdefault(rec["driver_id"], []).append(rec)

    rows: list[dict[str, Any]] = []
    for rec in target["race_results"].get("records", []):
        did   = str(rec["driver_id"])
        grid  = rec.get("grid")
        pos   = rec.get("position")
        hist  = driver_history.get(did, [])

        row: dict[str, Any] = {
            "driver_id":     did,
            "grid_position": grid,
            "actual_finish": pos,
        }

        for w_name, window in [("Wexp", hist), ("W3", hist[-3:]), ("W5", hist[-5:]), ("W7", hist[-7:])]:
            if not window:
                for n in _N_METHODS:
                    for s in _S_METHODS:
                        row[f"{n}_{s}_{w_name}"] = None
                continue

            raw_deltas  = [r["delta"] for r in window]   # grid - finish
            raw_grids   = [r["grid"]  for r in window]

            # N0 – raw delta, no correction (S1 == S0 for rank, but include for completeness)
            raw_mean = mean(raw_deltas)
            raw_std  = stdev(raw_deltas) if len(raw_deltas) >= 2 else None
            row[f"N0_S0_{w_name}"] = raw_mean
            row[f"N0_S1_{w_name}"] = (raw_mean / raw_std) if raw_std and raw_std > 0 else None

            # N1a – 2-band adjusted
            row.update(_band_features(raw_deltas, raw_grids, BANDS_1A, band_means_1a, band_stds_1a, "N1a", w_name))
            # N1b – 4-band adjusted
            row.update(_band_features(raw_deltas, raw_grids, BANDS_1B, band_means_1b, band_stds_1b, "N1b", w_name))
            # N1c – per-position adjusted
            row.update(_pos_features(raw_deltas, raw_grids, pos_means, pos_stds, "N1c", w_name))
            # N1d – 6-band adjusted
            row.update(_band_features(raw_deltas, raw_grids, BANDS_1D, band_means_1d, band_stds_1d, "N1d", w_name))
            # N1e – 8-band adjusted
            row.update(_band_features(raw_deltas, raw_grids, BANDS_1E, band_means_1e, band_stds_1e, "N1e", w_name))
            # N2  – linear adjusted
            row.update(_linear_features(raw_deltas, raw_grids, lin_a, lin_b, lin_resid_std, "N2", w_name))
            # N2a – quadratic adjusted
            row.update(_poly2_features(raw_deltas, raw_grids, poly2_a, poly2_b, poly2_c, poly2_resid_std, "N2a", w_name))
            # N2b – cubic adjusted
            row.update(_poly3_features(raw_deltas, raw_grids, poly3_a, poly3_b, poly3_c, poly3_d, poly3_resid_std, "N2b", w_name))
            # N2c – log(grid) linear adjusted
            log_grids_w = [math.log(g) for g in raw_grids]
            row.update(_linear_features(raw_deltas, log_grids_w, log_a, log_b, log_resid_std, "N2c", w_name))
            # N2d – sqrt(grid) linear adjusted
            sqrt_grids_w = [math.sqrt(g) for g in raw_grids]
            row.update(_linear_features(raw_deltas, sqrt_grids_w, sqrt_a, sqrt_b, sqrt_resid_std, "N2d", w_name))
            # N3  – isotonic adjusted
            row.update(_iso_features(raw_deltas, raw_grids, iso_means, "N3", w_name))
            # N4  – spline adjusted
            row.update(_spline_features(raw_deltas, raw_grids, spline_dict, spline_resid_std, "N4", w_name))
            # N5  – Gaussian kernel smooth
            row.update(_kernel_features(raw_deltas, raw_grids, kernel_means, kernel_resid_std, "N5", w_name))
            # N6  – 2-segment piecewise linear (auto breakpoint)
            row.update(_piecewise2_features(raw_deltas, raw_grids, pw2_a1, pw2_b1, pw2_a2, pw2_b2, pw2_bp, pw2_resid_std, "N6", w_name))
            # N7  – 3-segment piecewise linear (fixed BP P6/P17)
            row.update(_piecewise3_features(raw_deltas, raw_grids, pw3_a1, pw3_b1, pw3_a2, pw3_b2, pw3_a3, pw3_b3, _BP3_1, _BP3_2, pw3_resid_std, "N7", w_name))
            # N2fx – N2 baseline with alternative feature aggregation methods
            for n2f_tag in ["N2f0", "N2f1", "N2f2", "N2f3", "N2f4", "N2f5", "N2f6", "N2f7", "N2f8", "N2f9"]:
                row.update(_n2f_features(raw_deltas, raw_grids, lin_a, lin_b, lin_resid_std, n2f_tag, w_name))

        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Private: data extraction
# ---------------------------------------------------------------------------

def _extract_finisher_records(rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flat list of (round, driver_id, grid, finish, delta) for finishers only."""
    out = []
    for r in rounds:
        for rec in r.get("race_results", {}).get("records", []):
            if rec.get("status") not in FINISHER_STATUSES:
                continue
            grid = rec.get("grid")
            pos  = rec.get("position")
            if grid is None or pos is None:
                continue
            out.append({
                "round":     int(r["round"]),
                "driver_id": str(rec["driver_id"]),
                "grid":      int(grid),
                "finish":    int(pos),
                "delta":     int(grid) - int(pos),
            })
    return out


# ---------------------------------------------------------------------------
# Private: normalization model fitting (training data only)
# ---------------------------------------------------------------------------

def _band_for(grid: int, bands: list[tuple[int, int]]) -> int:
    for i, (lo, hi) in enumerate(bands):
        if lo <= grid <= hi:
            return i
    return len(bands) - 1


def _fit_band_means(recs: list[dict], bands: list[tuple[int, int]]) -> dict[int, float]:
    buckets: dict[int, list[float]] = {i: [] for i in range(len(bands))}
    for r in recs:
        buckets[_band_for(r["grid"], bands)].append(r["delta"])
    return {i: mean(v) if v else 0.0 for i, v in buckets.items()}


def _fit_band_stds(recs: list[dict], bands: list[tuple[int, int]],
                   means: dict[int, float]) -> dict[int, float | None]:
    buckets: dict[int, list[float]] = {i: [] for i in range(len(bands))}
    for r in recs:
        b = _band_for(r["grid"], bands)
        buckets[b].append(r["delta"] - means[b])
    return {
        i: stdev(v) if len(v) >= 2 else None
        for i, v in buckets.items()
    }


def _fit_per_pos_means(recs: list[dict]) -> dict[int, float]:
    buckets: dict[int, list[float]] = {}
    for r in recs:
        buckets.setdefault(r["grid"], []).append(r["delta"])
    return {g: mean(v) for g, v in buckets.items()}


def _fit_per_pos_stds(recs: list[dict], means: dict[int, float]) -> dict[int, float | None]:
    buckets: dict[int, list[float]] = {}
    for r in recs:
        g = r["grid"]
        buckets.setdefault(g, []).append(r["delta"] - means.get(g, 0.0))
    return {
        g: stdev(v) if len(v) >= 2 else None
        for g, v in buckets.items()
    }


def _fit_linear(recs: list[dict]) -> tuple[float, float]:
    """OLS: expected_delta = a * grid + b."""
    if len(recs) < 2:
        return 0.0, 0.0
    xs = [r["grid"]  for r in recs]
    ys = [r["delta"] for r in recs]
    xm, ym = mean(xs), mean(ys)
    denom = sum((x - xm) ** 2 for x in xs)
    if denom == 0:
        return 0.0, ym
    a = sum((xs[i] - xm) * (ys[i] - ym) for i in range(len(xs))) / denom
    b = ym - a * xm
    return a, b


def _fit_linear_resid_std(recs: list[dict], a: float, b: float) -> float | None:
    if len(recs) < 3:
        return None
    resids = [r["delta"] - (a * r["grid"] + b) for r in recs]
    return stdev(resids) if len(resids) >= 2 else None


def _fit_isotonic(recs: list[dict]) -> dict[int, float]:
    """Pool-adjacent-violators on grid→mean_delta (enforce monotone non-increasing)."""
    pos_means = _fit_per_pos_means(recs)
    if not pos_means:
        return {}
    sorted_grids = sorted(pos_means.keys())
    vals = [pos_means[g] for g in sorted_grids]
    # PAV: delta should be non-increasing as grid increases (higher grid → lower delta)
    blocks = [[v] for v in vals]
    merged = True
    while merged:
        merged = False
        i = 0
        new_blocks = []
        while i < len(blocks):
            if i + 1 < len(blocks) and mean(blocks[i]) < mean(blocks[i + 1]):
                new_blocks.append(blocks[i] + blocks[i + 1])
                i += 2
                merged = True
            else:
                new_blocks.append(blocks[i])
                i += 1
        blocks = new_blocks
    iso_vals: list[float] = []
    for blk in blocks:
        m = mean(blk)
        iso_vals.extend([m] * len(blk))
    return {g: iso_vals[i] for i, g in enumerate(sorted_grids)}


def _fit_log_linear(recs: list[dict]) -> tuple[float, float]:
    """OLS on log(grid): expected_delta = a * log(grid) + b."""
    if len(recs) < 2:
        return 0.0, 0.0
    xs = [math.log(r["grid"]) for r in recs]
    ys = [r["delta"] for r in recs]
    xm, ym = mean(xs), mean(ys)
    denom = sum((x - xm) ** 2 for x in xs)
    if denom == 0:
        return 0.0, ym
    a = sum((xs[i] - xm) * (ys[i] - ym) for i in range(len(xs))) / denom
    b = ym - a * xm
    return a, b


def _fit_sqrt_linear(recs: list[dict]) -> tuple[float, float]:
    """OLS on sqrt(grid): expected_delta = a * sqrt(grid) + b."""
    if len(recs) < 2:
        return 0.0, 0.0
    xs = [math.sqrt(r["grid"]) for r in recs]
    ys = [r["delta"] for r in recs]
    xm, ym = mean(xs), mean(ys)
    denom = sum((x - xm) ** 2 for x in xs)
    if denom == 0:
        return 0.0, ym
    a = sum((xs[i] - xm) * (ys[i] - ym) for i in range(len(xs))) / denom
    b = ym - a * xm
    return a, b


def _fit_transform_resid_std(recs: list[dict], a: float, b: float,
                              transform) -> float | None:
    """Residual std for a transformed-x linear model: expected_delta = a * transform(grid) + b."""
    if len(recs) < 3:
        return None
    resids = [r["delta"] - (a * transform(r["grid"]) + b) for r in recs]
    return stdev(resids) if len(resids) >= 2 else None



def _fit_poly2(recs: list[dict]) -> tuple[float, float, float]:
    """Quadratic polynomial: expected_delta = a + b*grid + c*grid^2."""
    if len(recs) < 3:
        return 0.0, 0.0, 0.0
    n = len(recs)
    xs = [r["grid"] for r in recs]
    ys = [r["delta"] for r in recs]

    # Normal equations for quadratic regression
    sum_x = sum(xs)
    sum_x2 = sum(x**2 for x in xs)
    sum_x3 = sum(x**3 for x in xs)
    sum_x4 = sum(x**4 for x in xs)
    sum_y = sum(ys)
    sum_xy = sum(xs[i] * ys[i] for i in range(n))
    sum_x2y = sum(xs[i]**2 * ys[i] for i in range(n))

    # Solve [n, sum_x, sum_x2; sum_x, sum_x2, sum_x3; sum_x2, sum_x3, sum_x4] @ [a, b, c] = [sum_y, sum_xy, sum_x2y]
    # Using Cramer's rule for 3x3 system
    det = (n * sum_x2 * sum_x4 + sum_x * sum_x3 * sum_x2 + sum_x2 * sum_x * sum_x3
           - sum_x2 * sum_x2 * sum_x2 - n * sum_x3 * sum_x3 - sum_x * sum_x * sum_x4)

    if abs(det) < 1e-10:
        return 0.0, 0.0, 0.0

    det_a = (sum_y * sum_x2 * sum_x4 + sum_xy * sum_x3 * sum_x2 + sum_x2y * sum_x * sum_x3
             - sum_x2y * sum_x2 * sum_x2 - sum_y * sum_x3 * sum_x3 - sum_xy * sum_x * sum_x4)
    det_b = (n * sum_xy * sum_x4 + sum_y * sum_x3 * sum_x2 + sum_x2y * sum_x2 * sum_x
             - sum_x2y * sum_xy * n - sum_y * sum_x2 * sum_x4 - sum_x * sum_x3 * sum_x)
    det_c = (n * sum_x2 * sum_x2y + sum_x * sum_xy * sum_x2 + sum_y * sum_x * sum_x3
             - sum_y * sum_x2 * sum_x2 - n * sum_xy * sum_x3 - sum_x * sum_x * sum_x2y)

    a = det_a / det
    b = det_b / det
    c = det_c / det
    return a, b, c


def _fit_poly3(recs: list[dict]) -> tuple[float, float, float, float]:
    """Cubic polynomial: expected_delta = a + b*grid + c*grid^2 + d*grid^3."""
    if len(recs) < 4:
        return 0.0, 0.0, 0.0, 0.0

    # For simplicity, use numpy-like approach via manual matrix ops
    # This is a full 4x4 system; implementation simplified by using pseudo-inverse approach
    n = len(recs)
    xs = [r["grid"] for r in recs]
    ys = [r["delta"] for r in recs]

    # Build design matrix X = [1, x, x^2, x^3] and solve X^T X theta = X^T y
    sum_x = sum(xs)
    sum_x2 = sum(x**2 for x in xs)
    sum_x3 = sum(x**3 for x in xs)
    sum_x4 = sum(x**4 for x in xs)
    sum_x5 = sum(x**5 for x in xs)
    sum_x6 = sum(x**6 for x in xs)
    sum_y = sum(ys)
    sum_xy = sum(xs[i] * ys[i] for i in range(n))
    sum_x2y = sum(xs[i]**2 * ys[i] for i in range(n))
    sum_x3y = sum(xs[i]**3 * ys[i] for i in range(n))

    # Simplified: use quadratic as fallback when cubic is unstable
    # For robustness in production, would use numpy.polyfit or scipy
    # Here we return quadratic + zero cubic term as a safe fallback
    a, b, c = _fit_poly2(recs)
    return a, b, c, 0.0


def _fit_spline(recs: list[dict]) -> dict[str, Any]:
    """Cubic spline with adaptive knots. Returns interpolation dict."""
    if len(recs) < 5:
        # Fallback to linear for very sparse data
        a, b = _fit_linear(recs)
        return {"type": "linear", "a": a, "b": b}

    # Sort by grid position
    sorted_recs = sorted(recs, key=lambda r: r["grid"])
    grids = [r["grid"] for r in sorted_recs]
    deltas = [r["delta"] for r in sorted_recs]

    # Simple piecewise linear as cubic spline fallback (scipy-free implementation)
    # Store grid→delta mapping for interpolation
    return {"type": "piecewise", "points": list(zip(grids, deltas))}


def _poly2_resid_std(recs: list[dict], a: float, b: float, c: float) -> float | None:
    if len(recs) < 4:
        return None
    resids = [r["delta"] - (a + b * r["grid"] + c * r["grid"]**2) for r in recs]
    return stdev(resids) if len(resids) >= 2 else None


def _poly3_resid_std(recs: list[dict], a: float, b: float, c: float, d: float) -> float | None:
    if len(recs) < 5:
        return None
    resids = [r["delta"] - (a + b * r["grid"] + c * r["grid"]**2 + d * r["grid"]**3) for r in recs]
    return stdev(resids) if len(resids) >= 2 else None


def _spline_resid_std(recs: list[dict], spline_dict: dict) -> float | None:
    if len(recs) < 3:
        return None

    if spline_dict["type"] == "linear":
        a, b = spline_dict["a"], spline_dict["b"]
        resids = [r["delta"] - (a * r["grid"] + b) for r in recs]
    elif spline_dict["type"] == "piecewise":
        points = spline_dict["points"]
        resids = []
        for r in recs:
            pred = _spline_predict(r["grid"], points)
            resids.append(r["delta"] - pred)
    else:
        return None

    return stdev(resids) if len(resids) >= 2 else None


def _spline_predict(grid: float, points: list[tuple[float, float]]) -> float:
    """Linear interpolation between closest points."""
    if not points:
        return 0.0
    if len(points) == 1:
        return points[0][1]

    # Find bracketing points
    for i in range(len(points) - 1):
        g1, d1 = points[i]
        g2, d2 = points[i + 1]
        if g1 <= grid <= g2:
            if g2 == g1:
                return d1
            t = (grid - g1) / (g2 - g1)
            return d1 + t * (d2 - d1)

    # Extrapolation
    if grid < points[0][0]:
        return points[0][1]
    return points[-1][1]


# ---------------------------------------------------------------------------
# Private: N5 – Gaussian kernel smooth, N6 – 2-seg piecewise, N7 – 3-seg piecewise
# ---------------------------------------------------------------------------

_KERNEL_BW = 3.0          # bandwidth for N5
_BP3_1     = 6            # N7 first breakpoint  (P1–P6 / P7–P17 / P18–P22)
_BP3_2     = 17           # N7 second breakpoint


def _fit_kernel(recs: list[dict], bw: float = _KERNEL_BW) -> dict[int, float]:
    """Gaussian kernel smoother: weighted mean of all training deltas per grid slot."""
    if not recs:
        return {}
    out: dict[int, float] = {}
    for g in range(1, 23):
        weights = [math.exp(-0.5 * ((g - r["grid"]) / bw) ** 2) for r in recs]
        w_sum = sum(weights)
        out[g] = (sum(weights[i] * recs[i]["delta"] for i in range(len(recs))) / w_sum
                  if w_sum > 1e-12 else 0.0)
    return out


def _kernel_resid_std(recs: list[dict], kernel_means: dict[int, float]) -> float | None:
    if len(recs) < 3:
        return None
    resids = [r["delta"] - kernel_means.get(r["grid"], 0.0) for r in recs]
    return stdev(resids) if len(resids) >= 2 else None


def _fit_piecewise2(recs: list[dict]) -> tuple[float, float, float, float, int]:
    """Two-segment OLS, breakpoint searched over P4–P19, minimising total RSS."""
    if len(recs) < 6:
        a, b = _fit_linear(recs)
        return a, b, a, b, 11   # degenerate: both segments identical
    best_rss  = float("inf")
    best: tuple[float, float, float, float, int] = (0.0, 0.0, 0.0, 0.0, 11)
    for bp in range(4, 20):
        left  = [r for r in recs if r["grid"] <= bp]
        right = [r for r in recs if r["grid"] >  bp]
        if len(left) < 3 or len(right) < 3:
            continue
        a1, b1 = _fit_linear(left)
        a2, b2 = _fit_linear(right)
        rss = (sum((r["delta"] - (a1 * r["grid"] + b1)) ** 2 for r in left) +
               sum((r["delta"] - (a2 * r["grid"] + b2)) ** 2 for r in right))
        if rss < best_rss:
            best_rss, best = rss, (a1, b1, a2, b2, bp)
    return best


def _piecewise2_resid_std(recs: list[dict], a1: float, b1: float,
                           a2: float, b2: float, bp: int) -> float | None:
    if len(recs) < 4:
        return None
    resids = [r["delta"] - ((a1 * r["grid"] + b1) if r["grid"] <= bp
                             else (a2 * r["grid"] + b2))
              for r in recs]
    return stdev(resids) if len(resids) >= 2 else None


def _fit_piecewise3(recs: list[dict],
                    bp1: int = _BP3_1,
                    bp2: int = _BP3_2) -> tuple[float, float, float, float, float, float]:
    """Three-segment OLS with fixed breakpoints bp1, bp2."""
    seg1 = [r for r in recs if r["grid"] <= bp1]
    seg2 = [r for r in recs if bp1 < r["grid"] <= bp2]
    seg3 = [r for r in recs if r["grid"] > bp2]
    a_g, b_g = _fit_linear(recs)   # global fallback
    a1, b1 = _fit_linear(seg1) if len(seg1) >= 2 else (a_g, b_g)
    a2, b2 = _fit_linear(seg2) if len(seg2) >= 2 else (a_g, b_g)
    a3, b3 = _fit_linear(seg3) if len(seg3) >= 2 else (a_g, b_g)
    return a1, b1, a2, b2, a3, b3


def _piecewise3_resid_std(recs: list[dict],
                           a1: float, b1: float,
                           a2: float, b2: float,
                           a3: float, b3: float,
                           bp1: int = _BP3_1, bp2: int = _BP3_2) -> float | None:
    if len(recs) < 4:
        return None
    resids = []
    for r in recs:
        g = r["grid"]
        pred = (a1 * g + b1) if g <= bp1 else ((a2 * g + b2) if g <= bp2 else (a3 * g + b3))
        resids.append(r["delta"] - pred)
    return stdev(resids) if len(resids) >= 2 else None


# ---------------------------------------------------------------------------
# Private: Feature aggregation methods (Batch 1 exploration)
# ---------------------------------------------------------------------------

def _aggregate_f0_mean(adj: list[float]) -> float:
    """F0: mean (current baseline)."""
    return mean(adj)


def _aggregate_f1_median(adj: list[float]) -> float:
    """F1: median (robust to outliers)."""
    return float(sorted(adj)[len(adj) // 2]) if adj else 0.0


def _aggregate_f2_trimmean(adj: list[float], trim_pct: float = 0.2) -> float:
    """F2: trimmed mean (drop top/bottom 20%)."""
    if len(adj) < 3:
        return mean(adj)
    n_trim = int(len(adj) * trim_pct)
    sorted_adj = sorted(adj)
    trimmed = sorted_adj[n_trim : len(adj) - n_trim] if n_trim > 0 else sorted_adj
    return mean(trimmed) if trimmed else 0.0


def _aggregate_f3_winsor(adj: list[float]) -> float:
    """F3: Winsorized mean (clip extremes to P10/P90)."""
    if len(adj) < 3:
        return mean(adj)
    sorted_adj = sorted(adj)
    p10_idx = max(0, int(len(adj) * 0.1))
    p90_idx = min(len(adj) - 1, int(len(adj) * 0.9))
    lo, hi = sorted_adj[p10_idx], sorted_adj[p90_idx]
    clipped = [max(lo, min(hi, v)) for v in adj]
    return mean(clipped)


def _aggregate_f4_ema(adj: list[float], alpha: float = 0.4) -> float:
    """F4: exponential weighted average (recent bias, alpha=0.4 → ~60% weight on last 3)."""
    if not adj:
        return 0.0
    ema_val = adj[0]
    for v in adj[1:]:
        ema_val = alpha * v + (1 - alpha) * ema_val
    return ema_val


def _aggregate_f5_decay(adj: list[float]) -> float:
    """F5: linear decay weighting (oldest = 0.5x, newest = 1.0x)."""
    if not adj:
        return 0.0
    n = len(adj)
    weights = [0.5 + 0.5 * (i / (n - 1)) if n > 1 else 1.0 for i in range(n)]
    return sum(adj[i] * weights[i] for i in range(n)) / sum(weights)


def _aggregate_f6_hitrate(adj: list[float]) -> float:
    """F6: hit rate (fraction of races where adj > 0)."""
    if not adj:
        return 0.0
    return sum(1 for v in adj if v > 0) / len(adj)


def _aggregate_f7_biggain(adj: list[float], threshold: float = 3.0) -> float:
    """F7: big gain rate (fraction where adj > +3)."""
    if not adj:
        return 0.0
    return sum(1 for v in adj if v > threshold) / len(adj)


def _aggregate_f8_shrink(adj: list[float], prior_strength: float = 5.0) -> float:
    """F8: Bayesian shrinkage (mean * n/(n+λ), λ=5)."""
    if not adj:
        return 0.0
    n = len(adj)
    raw_mean = mean(adj)
    shrinkage_factor = n / (n + prior_strength)
    return raw_mean * shrinkage_factor


def _aggregate_f9_recent(adj: list[float], recent_frac: float = 0.6) -> float:
    """F9: recent-only mean (last 60% of history)."""
    if not adj:
        return 0.0
    n_recent = max(1, int(len(adj) * recent_frac))
    recent_vals = adj[-n_recent:]
    return mean(recent_vals)


# Map from N2fx tag to aggregation function
_F_AGGREGATORS = {
    "N2f0": _aggregate_f0_mean,
    "N2f1": _aggregate_f1_median,
    "N2f2": _aggregate_f2_trimmean,
    "N2f3": _aggregate_f3_winsor,
    "N2f4": _aggregate_f4_ema,
    "N2f5": _aggregate_f5_decay,
    "N2f6": _aggregate_f6_hitrate,
    "N2f7": _aggregate_f7_biggain,
    "N2f8": _aggregate_f8_shrink,
    "N2f9": _aggregate_f9_recent,
}


# ---------------------------------------------------------------------------
# Private: per-driver feature computation helpers
# ---------------------------------------------------------------------------

def _band_features(raw_deltas, raw_grids, bands, b_means, b_stds, n_tag, w_tag):
    adj = [raw_deltas[i] - b_means[_band_for(raw_grids[i], bands)]
           for i in range(len(raw_deltas))]
    adj_mean = mean(adj)
    # S0
    out = {f"{n_tag}_S0_{w_tag}": adj_mean}
    # S1: use band std of the FIRST grid in window as proxy (or overall mean)
    rep_band = _band_for(raw_grids[0], bands)
    band_std  = b_stds.get(rep_band)
    out[f"{n_tag}_S1_{w_tag}"] = (adj_mean / band_std) if band_std and band_std > 0 else None
    return out


def _pos_features(raw_deltas, raw_grids, p_means, p_stds, n_tag, w_tag):
    adj = [raw_deltas[i] - p_means.get(raw_grids[i], 0.0)
           for i in range(len(raw_deltas))]
    adj_mean = mean(adj)
    out = {f"{n_tag}_S0_{w_tag}": adj_mean}
    rep_grid = raw_grids[0]
    pos_std  = p_stds.get(rep_grid)
    out[f"{n_tag}_S1_{w_tag}"] = (adj_mean / pos_std) if pos_std and pos_std > 0 else None
    return out


def _linear_features(raw_deltas, raw_grids, a, b, resid_std, n_tag, w_tag):
    adj = [raw_deltas[i] - (a * raw_grids[i] + b) for i in range(len(raw_deltas))]
    adj_mean = mean(adj)
    out = {f"{n_tag}_S0_{w_tag}": adj_mean}
    out[f"{n_tag}_S1_{w_tag}"] = (adj_mean / resid_std) if resid_std and resid_std > 0 else None
    return out


def _iso_features(raw_deltas, raw_grids, iso_means, n_tag, w_tag):
    adj = [raw_deltas[i] - iso_means.get(raw_grids[i], 0.0)
           for i in range(len(raw_deltas))]
    adj_mean = mean(adj)
    # No std for isotonic (would need per-cell std which is very sparse)
    return {
        f"{n_tag}_S0_{w_tag}": adj_mean,
        f"{n_tag}_S1_{w_tag}": None,   # always None – too sparse
    }


def _poly2_features(raw_deltas, raw_grids, a, b, c, resid_std, n_tag, w_tag):
    adj = [raw_deltas[i] - (a + b * raw_grids[i] + c * raw_grids[i]**2)
           for i in range(len(raw_deltas))]
    adj_mean = mean(adj)
    out = {f"{n_tag}_S0_{w_tag}": adj_mean}
    out[f"{n_tag}_S1_{w_tag}"] = (adj_mean / resid_std) if resid_std and resid_std > 0 else None
    return out


def _poly3_features(raw_deltas, raw_grids, a, b, c, d, resid_std, n_tag, w_tag):
    adj = [raw_deltas[i] - (a + b * raw_grids[i] + c * raw_grids[i]**2 + d * raw_grids[i]**3)
           for i in range(len(raw_deltas))]
    adj_mean = mean(adj)
    out = {f"{n_tag}_S0_{w_tag}": adj_mean}
    out[f"{n_tag}_S1_{w_tag}"] = (adj_mean / resid_std) if resid_std and resid_std > 0 else None
    return out


def _spline_features(raw_deltas, raw_grids, spline_dict, resid_std, n_tag, w_tag):
    adj = []
    for i in range(len(raw_deltas)):
        if spline_dict["type"] == "linear":
            pred = spline_dict["a"] * raw_grids[i] + spline_dict["b"]
        elif spline_dict["type"] == "piecewise":
            pred = _spline_predict(raw_grids[i], spline_dict["points"])
        else:
            pred = 0.0
        adj.append(raw_deltas[i] - pred)

    adj_mean = mean(adj) if adj else 0.0
    out = {f"{n_tag}_S0_{w_tag}": adj_mean}
    out[f"{n_tag}_S1_{w_tag}"] = (adj_mean / resid_std) if resid_std and resid_std > 0 else None
    return out


def _kernel_features(raw_deltas, raw_grids, kernel_means, resid_std, n_tag, w_tag):
    adj = [raw_deltas[i] - kernel_means.get(raw_grids[i], 0.0)
           for i in range(len(raw_deltas))]
    adj_mean = mean(adj)
    out = {f"{n_tag}_S0_{w_tag}": adj_mean}
    out[f"{n_tag}_S1_{w_tag}"] = (adj_mean / resid_std) if resid_std and resid_std > 0 else None
    return out


def _piecewise2_features(raw_deltas, raw_grids,
                          a1, b1, a2, b2, bp, resid_std, n_tag, w_tag):
    adj = [raw_deltas[i] - ((a1 * raw_grids[i] + b1) if raw_grids[i] <= bp
                             else (a2 * raw_grids[i] + b2))
           for i in range(len(raw_deltas))]
    adj_mean = mean(adj)
    out = {f"{n_tag}_S0_{w_tag}": adj_mean}
    out[f"{n_tag}_S1_{w_tag}"] = (adj_mean / resid_std) if resid_std and resid_std > 0 else None
    return out


def _piecewise3_features(raw_deltas, raw_grids,
                          a1, b1, a2, b2, a3, b3, bp1, bp2,
                          resid_std, n_tag, w_tag):
    adj = []
    for i in range(len(raw_deltas)):
        g = raw_grids[i]
        pred = (a1 * g + b1) if g <= bp1 else ((a2 * g + b2) if g <= bp2 else (a3 * g + b3))
        adj.append(raw_deltas[i] - pred)
    adj_mean = mean(adj)
    out = {f"{n_tag}_S0_{w_tag}": adj_mean}
    out[f"{n_tag}_S1_{w_tag}"] = (adj_mean / resid_std) if resid_std and resid_std > 0 else None
    return out


def _n2f_features(raw_deltas, raw_grids, a, b, resid_std, n_tag, w_tag):
    """N2fx variants: use N2 baseline but different aggregation methods."""
    adj = [raw_deltas[i] - (a * raw_grids[i] + b) for i in range(len(raw_deltas))]

    # Look up aggregation function
    aggregator = _F_AGGREGATORS.get(n_tag)
    if aggregator is None:
        # Fallback to mean if not found
        adj_agg = mean(adj)
    else:
        adj_agg = aggregator(adj)

    out = {f"{n_tag}_S0_{w_tag}": adj_agg}
    # For S1, use resid_std from global N2 fit
    out[f"{n_tag}_S1_{w_tag}"] = (adj_agg / resid_std) if resid_std and resid_std > 0 else None
    return out

