from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from f1_big_predictor.targets.qualifying.c0_scorer import score_qualifying
from f1_big_predictor.targets.qualifying.official_labels import (
    ACTUALS_PATH,
    OFFICIAL_LABELS_PATH,
    apply_official_qualifying_labels,
    load_official_qualifying_labels,
    load_officialized_actuals,
    official_records_for_round,
    validate_official_qualifying_labels,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_manifest_makes_r02_to_r09_c0_scoreable() -> None:
    manifest = load_official_qualifying_labels(PROJECT_ROOT)

    assert [item["round"] for item in manifest["rounds"]] == list(range(1, 10))
    assert manifest["rounds"][0]["training_eligible"] is True
    assert manifest["rounds"][0]["c0_scoreable"] is False
    assert all(item["c0_scoreable"] for item in manifest["rounds"][1:])
    assert all(item["field_size"] == 22 for item in manifest["rounds"])


def test_r04_hadjar_is_dsq_without_numeric_position() -> None:
    records, field_size = official_records_for_round(PROJECT_ROOT, 4)
    hadjar = next(record for record in records if record["driver_id"] == "hadjar")

    assert field_size == 22
    assert len(records) == field_size
    assert hadjar == {
        "driver_id": "hadjar",
        "position": None,
        "classification_status": "DSQ",
    }
    assert [
        record["position"] for record in records if record["position"] is not None
    ] == list(range(1, 22))


def test_r01_fails_closed_for_c0_but_remains_available_for_training() -> None:
    with pytest.raises(ValueError, match="not C0-scoreable"):
        official_records_for_round(PROJECT_ROOT, 1)

    records, field_size = official_records_for_round(
        PROJECT_ROOT,
        1,
        require_c0_scoreable=False,
    )
    assert len(records) == 19
    assert field_size == 22


def test_official_overlay_replaces_collector_p22_with_dsq() -> None:
    collected = json.loads((PROJECT_ROOT / ACTUALS_PATH).read_text(encoding="utf-8"))
    original = deepcopy(collected)
    manifest = load_official_qualifying_labels(PROJECT_ROOT)

    overlaid = apply_official_qualifying_labels(collected, manifest)
    r04 = next(item for item in overlaid["completed_rounds"] if item["round"] == 4)
    hadjar = next(
        record
        for record in r04["qualifying_results"]["records"]
        if record["driver_id"] == "hadjar"
    )

    assert hadjar["position"] is None
    assert hadjar["classification_status"] == "DSQ"
    assert r04["qualifying_results"]["field_size"] == 22
    assert r04["qualifying_results"]["numeric_position_count"] == 21
    assert r04["qualifying_results"]["non_numeric_count"] == 1
    assert collected == original


def test_default_actuals_loader_always_applies_official_overlay() -> None:
    actuals = load_officialized_actuals(PROJECT_ROOT)
    r04 = next(item for item in actuals["completed_rounds"] if item["round"] == 4)
    hadjar = next(
        record
        for record in r04["qualifying_results"]["records"]
        if record["driver_id"] == "hadjar"
    )

    assert actuals["qualifying_official_label_manifest"] == str(OFFICIAL_LABELS_PATH)
    assert hadjar["position"] is None


def test_r04_official_truth_is_accepted_by_c0() -> None:
    records, field_size = official_records_for_round(PROJECT_ROOT, 4)
    predicted_top10 = [
        record["driver_id"]
        for record in records
        if record["position"] is not None and record["position"] <= 10
    ]
    result = score_qualifying(predicted_top10, records, field_size=field_size)

    assert result["overall_candidate"]["overall_candidate_score"] == pytest.approx(1.0)
    assert result["distance"]["status_branch_trace"] == [
        f"slot_{position}:{driver_id}=P{position}→dist0"
        for position, driver_id in enumerate(predicted_top10, start=1)
    ]


def test_manifest_rejects_unreviewed_non_numeric_status() -> None:
    manifest = load_official_qualifying_labels(PROJECT_ROOT)
    broken = deepcopy(manifest)
    r04 = broken["rounds"][3]
    hadjar = next(
        record for record in r04["official_records"] if record["driver_id"] == "hadjar"
    )
    hadjar["classification_status"] = "NO_TIME"

    with pytest.raises(ValueError, match="unsupported non-numeric status"):
        validate_official_qualifying_labels(broken)
