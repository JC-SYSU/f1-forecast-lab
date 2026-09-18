"""Learning-to-Rank model for qualifying: LightGBM LambdaMART.

Uses LightGBM's ``lambdarank`` objective (LambdaMART) — the first model in the
roster with an external runtime dependency (lightgbm).  Each prior qualifying
round is a query group; features are the shared stat.v1 set (10 features);
graded relevance is event-relative on a fixed 0..20 scale (pole = 20,
last classified position = 0).

Training window excludes R02 by convention: LTR relies on features, and R02's
only prior round (R01, 19 rows) is too thin to fit a tree ensemble — the same
cold-start weakness seen in Ridge/EN.  Predictions still cover R02 when asked,
but the walk-forward harness starts scoring from R03.
"""
from __future__ import annotations

from typing import Any

from .feature_matrix import build_feature_matrix
from .ridge_model import STAT_FEATURES

TARGET_ID = "qualifying"
MODEL_ID = "qualifying.model.ltr.lambdamart"
FEATURE_SET_ID = "qualifying.features.stat.v1"   # reuse Ridge/EN feature set
FALLBACK_POLICY = "training_column_median_for_missing_features"
TOP10_SIZE = 10


def predict_lambdamart(
    target_round: int,
    completed_rounds: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Train a LambdaMART ranker on rounds < target_round; rank target field.

    params: optional LightGBM overrides (n_estimators, num_leaves, learning_rate,
    min_child_samples).  Defaults are tuned for the small-sample regime.
    """
    import lightgbm as lgb  # local import: optional heavy dependency

    evidence_gaps: list[str] = []
    cfg = _resolve_params(params)

    # ---- Assemble training groups (one group per prior round) --------------
    X_train_raw: list[list[float | None]] = []
    y_train: list[int] = []
    group_sizes: list[int] = []

    for rnd in sorted(completed_rounds, key=lambda r: int(r["round"])):
        rn = int(rnd["round"])
        if rn >= target_round:
            break
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
        if not actual_pos:
            continue
        group_rows = 0
        for row in build_feature_matrix(rn, completed_rounds):
            did = row["driver_id"]
            if did not in actual_pos:
                continue
            X_train_raw.append([row.get(f) for f in STAT_FEATURES])
            y_train.append(_event_relevance(actual_pos[did], field_size))
            group_rows += 1
        if group_rows > 0:
            group_sizes.append(group_rows)

    if len(group_sizes) < 1 or not X_train_raw:
        return _empty(evidence_gaps + ["no_training_groups"]), []

    feature_medians = _fit_feature_medians(X_train_raw, evidence_gaps)
    X_train = _impute_rows(X_train_raw, feature_medians)

    # ---- Target field ------------------------------------------------------
    test_rows = build_feature_matrix(target_round, completed_rounds)
    if not test_rows:
        return _empty(evidence_gaps + ["target_round_field_missing"]), []
    X_test_raw = [[row.get(f) for f in STAT_FEATURES] for row in test_rows]
    X_test = _impute_rows(X_test_raw, feature_medians)
    test_ids = [row["driver_id"] for row in test_rows]

    # ---- Fit LambdaMART ----------------------------------------------------
    ranker = lgb.LGBMRanker(
        objective="lambdarank",
        n_estimators=cfg["n_estimators"],
        num_leaves=cfg["num_leaves"],
        learning_rate=cfg["learning_rate"],
        min_child_samples=cfg["min_child_samples"],
        min_split_gain=0.0,
        importance_type="gain",
        random_state=cfg["random_state"],
        n_jobs=1,
        verbose=-1,
    )
    try:
        ranker.fit(X_train, y_train, group=group_sizes)
        scores = list(ranker.predict(X_test))
    except Exception as exc:  # pragma: no cover - defensive
        return _empty(evidence_gaps + [f"lambdamart_fit_failed:{type(exc).__name__}"]), []

    # ---- Rank and package --------------------------------------------------
    ranked = sorted(zip(test_ids, scores), key=lambda t: (-t[1], t[0]))
    full_ranking = [
        {"driver_id": did, "position": pos, "score": round(float(sc), 6)}
        for pos, (did, sc) in enumerate(ranked, start=1)
    ]
    if len(full_ranking) >= TOP10_SIZE:
        entries, status = full_ranking[:TOP10_SIZE], "ok"
    else:
        entries, status = [], "evidence_issue"
        evidence_gaps.append("insufficient_drivers_for_top10")

    return {
        "target_id": TARGET_ID, "model_id": MODEL_ID,
        "feature_set_id": FEATURE_SET_ID, "fallback_policy": FALLBACK_POLICY,
        "status": status, "entries": entries, "evidence_gaps": evidence_gaps,
    }, full_ranking


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _event_relevance(position: int, field_size: int) -> int:
    """Map an event rank to an integer 0..20 relevance scale."""
    if field_size < 2:
        raise ValueError(f"field_size must be at least 2, got {field_size}")
    if not 1 <= position <= field_size:
        raise ValueError(f"position must be within 1..{field_size}, got {position}")
    return round(20 * (field_size - position) / (field_size - 1))


def _fit_feature_medians(
    rows: list[list[float | None]],
    evidence_gaps: list[str],
) -> list[float]:
    """Fit column medians from training rows only."""
    from statistics import median

    medians: list[float] = []
    for index, feature_name in enumerate(STAT_FEATURES):
        values = [float(row[index]) for row in rows if row[index] is not None]
        if values:
            medians.append(float(median(values)))
        else:
            medians.append(0.0)
            evidence_gaps.append(f"feature_{feature_name}_has_no_training_values")
    return medians


def _impute_rows(
    rows: list[list[float | None]],
    medians: list[float],
) -> list[list[float]]:
    """Fill missing values with medians learned from the training window."""
    return [
        [float(value) if value is not None else medians[index]
         for index, value in enumerate(row)]
        for row in rows
    ]


def _resolve_params(params: dict[str, Any] | None) -> dict[str, Any]:
    cfg = {
        "n_estimators": 100,
        "num_leaves": 7,          # shallow: small sample
        "learning_rate": 0.1,
        "min_child_samples": 5,
        "random_state": 42,
    }
    if params:
        cfg.update(params)
    return cfg


def _empty(gaps: list[str]) -> dict[str, Any]:
    return {
        "target_id": TARGET_ID, "model_id": MODEL_ID,
        "feature_set_id": FEATURE_SET_ID, "fallback_policy": FALLBACK_POLICY,
        "status": "evidence_issue", "entries": [], "evidence_gaps": gaps,
    }
