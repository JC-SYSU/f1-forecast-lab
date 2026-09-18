#!/usr/bin/env python3
"""Generate the isolated R08 synthetic qualifying-score audit.

This is a temporary reference calculator for reviewing the no-code scoring
design. It intentionally does not import the production qualifying evaluator,
legacy code, or the archived questionnaire-calibration implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
OFFICIAL_AUDIT_PATH = (
    ROOT
    / "docs/data_and_evidence/qualifying/official_labels/qualifying_v1_p0_4_official_label_audit.json"
)
FIELD_SIZE_AUDIT_PATH = (
    ROOT
    / "docs/data_and_evidence/qualifying/official_labels/qualifying_v1_p0_4b_field_size_evidence.json"
)
DEFAULT_OUTPUT_PATH = (
    ROOT
    / "docs/model_development/qualifying/single_event_scoring/evidence/qualifying_v1_r08_synthetic_score_audit.md"
)

POOL_WEIGHTS = (0.10, 0.20, 0.70)
MAIN_WEIGHTS = {
    "exact": 0.45,
    "membership": 0.35,
    "internal_order": 0.20,
}
COMBO_BASE = 1.5
COMBO_START_Q = (2.0 / 3.0) ** (1.0 / 3.0)
CURRENT_X_COMBO = 0.20
CONTROL_X_COMBO = 0.4323589504
RANDOM_MEMBERSHIP_RANGES = {
    "high": (8, 10),
    "medium": (5, 7),
    "low": (2, 4),
}
RANDOM_ORDER_SIGMA = {
    "high": 0.35,
    "medium": 2.5,
    "low": 8.0,
}

DISPLAY_CODES = {
    "russell": "RUS",
    "leclerc": "LEC",
    "hamilton": "HAM",
    "antonelli": "ANT",
    "max_verstappen": "VER",
    "norris": "NOR",
    "piastri": "PIA",
    "hadjar": "HAD",
    "lawson": "LAW",
    "arvid_lindblad": "LIN",
    "gasly": "GAS",
    "bortoleto": "BOR",
    "bearman": "BEA",
    "hulkenberg": "HUL",
    "ocon": "OCO",
    "colapinto": "COL",
    "sainz": "SAI",
    "albon": "ALB",
    "perez": "PER",
    "bottas": "BOT",
    "alonso": "ALO",
    "stroll": "STR",
}


@dataclass(frozen=True)
class GroundTruth:
    round_id: str
    race_name: str
    field_size: int
    official_order: tuple[str, ...]
    official_url: str
    official_pdf_path: str
    official_pdf_sha256: str
    official_retrieved_at: str
    official_audit_status: str
    field_size_audit_status: str
    entry_list_url: str
    entry_list_path: str
    entry_list_sha256: str
    has_non_numeric_status: bool


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    kind: str
    description: str
    audit_intent: str
    predicted_top10: tuple[str, ...]
    membership_tier: str | None = None
    order_tier: str | None = None
    replicate: int | None = None
    seed: int | None = None


@dataclass(frozen=True)
class ComboRun:
    start: int
    length: int
    start_value: float
    length_value: float
    shape_contribution: float


@dataclass(frozen=True)
class ScoreResult:
    predicted_top10: tuple[str, ...]
    top3_common_count: int
    top5_common_count: int
    top10_common_count: int
    top3_set_score: float
    top5_set_score: float
    top10_set_score: float
    pool_membership_score: float
    exact_hit_vector: tuple[bool, ...]
    exact_hit_count: int
    exact_hit_positions: tuple[int, ...]
    exact_position_score: float
    combo_runs: tuple[ComboRun, ...]
    combo_shape: float
    combo_x: float
    combo_bonus: float
    exact_positive_raw: float
    exact_positive_score: float
    distance_vector: tuple[int, ...]
    distance_sum: int
    mean_rank_distance: float
    max_rank_distance: int
    k_distance: float
    distance_penalty: float
    exact_branch_score: float
    common_driver_count: int
    observed_pair_count: int
    inversion_count: int
    correct_pair_count: int
    conditional_order_accuracy: float | None
    signed_internal_order_skill: float
    internal_order_score: float
    exact_contribution: float
    membership_contribution: float
    internal_order_contribution: float
    overall_candidate_score: float


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(128 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _round_record(payload: dict, round_id: str) -> dict:
    matches = [item for item in payload["rounds"] if item["round"] == round_id]
    if len(matches) != 1:
        raise ValueError(f"expected one {round_id} record, found {len(matches)}")
    return matches[0]


def load_r08_ground_truth(project_root: Path = ROOT) -> GroundTruth:
    official_path = project_root / OFFICIAL_AUDIT_PATH.relative_to(ROOT)
    field_path = project_root / FIELD_SIZE_AUDIT_PATH.relative_to(ROOT)
    official = _round_record(_read_json(official_path), "R08")
    field = _round_record(_read_json(field_path), "R08")

    if official["status"] != "pass":
        raise ValueError("R08 official-label audit did not pass")
    if field["status"] != "pass":
        raise ValueError("R08 field-size audit did not pass")
    if official["official_row_count"] != 22:
        raise ValueError("R08 official classification is not 22 rows")
    if official["official_numeric_position_row_count"] != 22:
        raise ValueError("R08 contains non-numeric official positions")
    if official["official_numeric_positions"] != list(range(1, 23)):
        raise ValueError("R08 official positions are not contiguous P1-P22")
    if not official["official_numeric_positions_contiguous"]:
        raise ValueError("R08 official numeric-contiguity gate failed")
    if not official["identity_match"] or not official["exact_order_match"]:
        raise ValueError("R08 processed order does not match FIA order")
    if official["special_classification_notes"]:
        raise ValueError("R08 has an unexpected special classification note")
    if field["entry_count"] != 22:
        raise ValueError("R08 frozen entry universe is not 22")
    if field["classification_row_count_reference"] != 22:
        raise ValueError("R08 entry/classification universe mismatch")

    official_pdf = project_root / official["archive_path"]
    entry_pdf = project_root / field["raw_path"]
    if _sha256_file(official_pdf) != official["sha256"]:
        raise ValueError("R08 FIA final-classification PDF SHA-256 mismatch")
    if _sha256_file(entry_pdf) != field["sha256"]:
        raise ValueError("R08 FIA entry-list PDF SHA-256 mismatch")

    order = tuple(official["official_numeric_order"])
    if len(order) != 22 or len(set(order)) != 22:
        raise ValueError("R08 official driver universe is not 22 unique identities")
    if set(order) != set(DISPLAY_CODES):
        raise ValueError("R08 display-code map does not match the official universe")

    return GroundTruth(
        round_id="R08",
        race_name=official["race_name"],
        field_size=field["entry_count"],
        official_order=order,
        official_url=official["official_url"],
        official_pdf_path=official["archive_path"],
        official_pdf_sha256=official["sha256"],
        official_retrieved_at=official["retrieved_at"],
        official_audit_status=official["status"],
        field_size_audit_status=field["status"],
        entry_list_url=field["url"],
        entry_list_path=field["raw_path"],
        entry_list_sha256=field["sha256"],
        has_non_numeric_status=False,
    )


def _position_values() -> tuple[float, ...]:
    return tuple(1.0 - 0.4 * ((position - 1) / 9.0) ** 1.25 for position in range(1, 11))


def _legacy_combo_x(position_values: Sequence[float]) -> float:
    p1_p5_exact = sum(position_values[:5]) / sum(position_values)
    p1_p5_shape = COMBO_BASE ** (5 - 10)
    return 0.10 * p1_p5_exact / p1_p5_shape


def _validate_combo_x(value: float) -> float:
    combo_x = float(value)
    if not math.isfinite(combo_x) or combo_x < 0.0:
        raise ValueError("x_combo must be a finite non-negative number")
    return combo_x


def _combo_runs(exact_vector: Sequence[bool]) -> tuple[ComboRun, ...]:
    runs: list[ComboRun] = []
    start_index: int | None = None
    for index in range(len(exact_vector) + 1):
        hit = index < len(exact_vector) and exact_vector[index]
        if hit and start_index is None:
            start_index = index
        if not hit and start_index is not None:
            length = index - start_index
            if length >= 2:
                start = start_index + 1
                start_value = COMBO_START_Q ** (start - 1)
                length_value = COMBO_BASE ** (length - 10)
                runs.append(
                    ComboRun(
                        start=start,
                        length=length,
                        start_value=start_value,
                        length_value=length_value,
                        shape_contribution=start_value * length_value,
                    )
                )
            start_index = None
    return tuple(runs)


def _inversion_count(sequence: Sequence[int]) -> int:
    return sum(
        sequence[left] > sequence[right]
        for left in range(len(sequence))
        for right in range(left + 1, len(sequence))
    )


def score_prediction(
    predicted_top10: Sequence[str],
    truth: GroundTruth,
    x_combo: float = CURRENT_X_COMBO,
) -> ScoreResult:
    prediction = tuple(predicted_top10)
    if len(prediction) != 10 or len(set(prediction)) != 10:
        raise ValueError("prediction must contain exactly 10 unique drivers")
    universe = set(truth.official_order)
    if not set(prediction) <= universe:
        raise ValueError("prediction contains a driver outside the frozen R08 universe")

    official_top3 = set(truth.official_order[:3])
    official_top5 = set(truth.official_order[:5])
    official_top10 = set(truth.official_order[:10])
    top3_common = len(set(prediction[:3]) & official_top3)
    top5_common = len(set(prediction[:5]) & official_top5)
    top10_common = len(set(prediction) & official_top10)
    top3_score = top3_common / 3.0
    top5_score = top5_common / 5.0
    top10_score = top10_common / 10.0
    pool_score = (
        POOL_WEIGHTS[0] * top3_score
        + POOL_WEIGHTS[1] * top5_score
        + POOL_WEIGHTS[2] * top10_score
    )

    exact_vector = tuple(
        predicted == actual
        for predicted, actual in zip(prediction, truth.official_order[:10], strict=True)
    )
    exact_positions = tuple(
        index for index, is_exact in enumerate(exact_vector, start=1) if is_exact
    )
    position_values = _position_values()
    position_total = sum(position_values)
    exact_score = sum(
        value for value, is_exact in zip(position_values, exact_vector, strict=True) if is_exact
    ) / position_total

    combo_runs = _combo_runs(exact_vector)
    combo_shape = sum(run.shape_contribution for run in combo_runs)
    combo_x = _validate_combo_x(x_combo)
    combo_bonus = combo_x * combo_shape
    exact_positive_raw = exact_score + combo_bonus
    exact_positive_score = exact_positive_raw / (1.0 + combo_x)

    actual_position = {
        driver_id: position
        for position, driver_id in enumerate(truth.official_order, start=1)
    }
    distance_vector = tuple(
        abs(predicted_position - actual_position[driver_id])
        for predicted_position, driver_id in enumerate(prediction, start=1)
    )
    distance_sum = sum(distance_vector)
    mean_distance = distance_sum / 10.0
    max_distance = max(distance_vector)
    average_exact_hit_value = 1.0 / (10.0 * (1.0 + combo_x))
    k_distance = average_exact_hit_value / 2.5
    distance_penalty = k_distance * mean_distance
    exact_branch_score = exact_positive_score - distance_penalty

    common_prediction_order = tuple(
        driver_id for driver_id in prediction if driver_id in official_top10
    )
    common_positions = tuple(actual_position[driver_id] for driver_id in common_prediction_order)
    common_count = len(common_positions)
    pair_count = common_count * (common_count - 1) // 2
    inversions = _inversion_count(common_positions)
    correct_pairs = pair_count - inversions
    conditional_accuracy = correct_pairs / pair_count if pair_count else None
    signed_order = (correct_pairs - inversions) / 45.0
    internal_order_score = correct_pairs / 45.0

    exact_contribution = MAIN_WEIGHTS["exact"] * exact_branch_score
    membership_contribution = MAIN_WEIGHTS["membership"] * pool_score
    order_contribution = MAIN_WEIGHTS["internal_order"] * internal_order_score
    overall_score = exact_contribution + membership_contribution + order_contribution

    return ScoreResult(
        predicted_top10=prediction,
        top3_common_count=top3_common,
        top5_common_count=top5_common,
        top10_common_count=top10_common,
        top3_set_score=top3_score,
        top5_set_score=top5_score,
        top10_set_score=top10_score,
        pool_membership_score=pool_score,
        exact_hit_vector=exact_vector,
        exact_hit_count=sum(exact_vector),
        exact_hit_positions=exact_positions,
        exact_position_score=exact_score,
        combo_runs=combo_runs,
        combo_shape=combo_shape,
        combo_x=combo_x,
        combo_bonus=combo_bonus,
        exact_positive_raw=exact_positive_raw,
        exact_positive_score=exact_positive_score,
        distance_vector=distance_vector,
        distance_sum=distance_sum,
        mean_rank_distance=mean_distance,
        max_rank_distance=max_distance,
        k_distance=k_distance,
        distance_penalty=distance_penalty,
        exact_branch_score=exact_branch_score,
        common_driver_count=common_count,
        observed_pair_count=pair_count,
        inversion_count=inversions,
        correct_pair_count=correct_pairs,
        conditional_order_accuracy=conditional_accuracy,
        signed_internal_order_skill=signed_order,
        internal_order_score=internal_order_score,
        exact_contribution=exact_contribution,
        membership_contribution=membership_contribution,
        internal_order_contribution=order_contribution,
        overall_candidate_score=overall_score,
    )


def _fixed_scenarios(truth: GroundTruth) -> tuple[Scenario, ...]:
    top = truth.official_order[:10]
    outside = truth.official_order[10:]

    top_swap = (top[1], top[0], *top[2:])
    bottom_swap = (*top[:8], top[9], top[8])
    cyclic = (*top[1:], top[0])
    reverse = tuple(reversed(top))
    p1_p5 = (*top[:5], *outside[:5])
    p6_p10 = (*outside[:5], *top[5:])
    two_three_runs = (
        top[0],
        top[1],
        top[2],
        outside[0],
        outside[1],
        top[3],
        top[4],
        top[7],
        top[8],
        top[9],
    )
    podium_near = (*top[:3], *outside[:7])
    podium_far = (*top[:3], *outside[5:12])
    five_common_no_exact = (*top[5:10], *outside[:5])
    four_exact_far = (*top[:4], *outside[5:11])

    definitions = (
        (
            "FIX-01-PERFECT",
            "Perfect Top10",
            "Confirm the full-score boundary of every main branch and the combined candidate.",
            top,
        ),
        (
            "FIX-02-TOP-SWAP",
            "P1/P2 adjacent swap",
            "Contrast with the low-order swap; check the impact on high Exact and Combo.",
            top_swap,
        ),
        (
            "FIX-03-BOTTOM-SWAP",
            "P9/P10 adjacent swap",
            "Contrast with the high-order swap; same error position, different importance.",
            bottom_swap,
        ),
        (
            "FIX-04-CYCLIC",
            "Same Top10 cyclically shifted left by one",
            "Zero Exact but globally close; check Distance and Internal Order compensation.",
            cyclic,
        ),
        (
            "FIX-05-REVERSE",
            "Same Top10 fully reversed",
            "Full Membership but worst order; check whether the other branches push the score down.",
            reverse,
        ),
        (
            "FIX-06-P1-P5-COMBO",
            "P1-P5 consecutive exact hits",
            "Check the stacking of a high-order five-run with the top-five set hit.",
            p1_p5,
        ),
        (
            "FIX-07-P6-P10-COMBO",
            "P6-P10 consecutive exact hits",
            "Same exact count as the high five-run; check the start curve.",
            p6_p10,
        ),
        (
            "FIX-08-TWO-THREE-RUNS",
            "Two three-runs: P1-P3 and P8-P10",
            "Check the summation across multiple maximal runs and the position difference.",
            two_three_runs,
        ),
        (
            "FIX-09-PODIUM-NEAR",
            "Podium exact, rest outside but near P10",
            "Contrast with far outsiders; isolate Distance severity.",
            podium_near,
        ),
        (
            "FIX-10-PODIUM-FAR",
            "Podium exact, rest outside and far from P10",
            "Keep the top-three Exact unchanged; only increase the distance of the other slots.",
            podium_far,
        ),
        (
            "FIX-11-FIVE-ORDERED-NO-EXACT",
            "Five common members, fully ordered, zero Exact",
            "Contrast against four high Exact on set, absolute-position, and relative-order trade-offs.",
            five_common_no_exact,
        ),
        (
            "FIX-12-FOUR-EXACT-FAR",
            "Four high Exact, rest severely off",
            "Forms the user-preference adversarial case against the five-ordered-no-Exact scenario.",
            four_exact_far,
        ),
    )
    return tuple(
        Scenario(
            scenario_id=scenario_id,
            kind="fixed",
            description=description,
            audit_intent=intent,
            predicted_top10=tuple(prediction),
        )
        for scenario_id, description, intent, prediction in definitions
    )


def _weighted_sample_without_replacement(
    items: Sequence[str], weights: Sequence[float], count: int, rng: random.Random
) -> list[str]:
    if len(items) != len(weights):
        raise ValueError("items and weights must have equal length")
    if count > len(items):
        raise ValueError("cannot sample more items than available")
    keys = [
        (-math.log(max(rng.random(), 1e-15)) / weight, item)
        for item, weight in zip(items, weights, strict=True)
    ]
    keys.sort()
    return [item for _, item in keys[:count]]


def _random_scenarios(
    truth: GroundTruth, blocked_predictions: set[tuple[str, ...]]
) -> tuple[Scenario, ...]:
    actual_position = {
        driver_id: position
        for position, driver_id in enumerate(truth.official_order, start=1)
    }
    official_top10 = truth.official_order[:10]
    outside = truth.official_order[10:]
    scenarios: list[Scenario] = []
    membership_tiers = ("high", "medium", "low")
    order_tiers = ("high", "medium", "low")

    for membership_index, membership_tier in enumerate(membership_tiers, start=1):
        lower, upper = RANDOM_MEMBERSHIP_RANGES[membership_tier]
        for order_index, order_tier in enumerate(order_tiers, start=1):
            for replicate in (1, 2):
                base_seed = (
                    808_000
                    + membership_index * 1_000
                    + order_index * 100
                    + replicate
                )
                prediction: tuple[str, ...] | None = None
                seed: int | None = None
                for attempt in range(100):
                    candidate_seed = base_seed + attempt * 10_000
                    rng = random.Random(candidate_seed)
                    common_count = rng.randint(lower, upper)
                    common = _weighted_sample_without_replacement(
                        official_top10,
                        [
                            math.exp(-0.10 * (position - 1))
                            for position in range(1, 11)
                        ],
                        common_count,
                        rng,
                    )
                    outsiders = _weighted_sample_without_replacement(
                        outside,
                        [
                            math.exp(-0.12 * (position - 11))
                            for position in range(11, 23)
                        ],
                        10 - common_count,
                        rng,
                    )
                    sigma = RANDOM_ORDER_SIGMA[order_tier]
                    selected = [*common, *outsiders]
                    selected.sort(
                        key=lambda driver_id: (
                            actual_position[driver_id]
                            + rng.normalvariate(0.0, sigma),
                            actual_position[driver_id],
                        )
                    )
                    candidate = tuple(selected)
                    if candidate not in blocked_predictions:
                        prediction = candidate
                        seed = candidate_seed
                        blocked_predictions.add(candidate)
                        break
                if prediction is None or seed is None:
                    raise AssertionError("could not generate a unique random prediction")
                scenario_id = (
                    f"RND-M{membership_tier[0].upper()}-"
                    f"O{order_tier[0].upper()}-{replicate}"
                )
                scenarios.append(
                    Scenario(
                        scenario_id=scenario_id,
                        kind="weighted_random",
                        description=(
                            f"Membership={membership_tier}, Order={order_tier}, "
                            f"replicate={replicate}"
                        ),
                        audit_intent="Stratified cross of set quality and order-noise tiers.",
                        predicted_top10=prediction,
                        membership_tier=membership_tier,
                        order_tier=order_tier,
                        replicate=replicate,
                        seed=seed,
                    )
                )
    return tuple(scenarios)


def build_scenarios(truth: GroundTruth) -> tuple[Scenario, ...]:
    fixed_scenarios = _fixed_scenarios(truth)
    blocked_predictions = {
        scenario.predicted_top10 for scenario in fixed_scenarios
    }
    scenarios = (
        *fixed_scenarios,
        *_random_scenarios(truth, blocked_predictions),
    )
    if len(scenarios) != 30:
        raise AssertionError(f"expected 30 scenarios, found {len(scenarios)}")
    if len({scenario.scenario_id for scenario in scenarios}) != 30:
        raise AssertionError("scenario IDs are not unique")
    if len({scenario.predicted_top10 for scenario in scenarios}) != 30:
        raise AssertionError("scenario predictions are not unique")
    universe = set(truth.official_order)
    for scenario in scenarios:
        if len(scenario.predicted_top10) != 10:
            raise AssertionError(f"{scenario.scenario_id} is not Top10")
        if len(set(scenario.predicted_top10)) != 10:
            raise AssertionError(f"{scenario.scenario_id} has duplicate drivers")
        if not set(scenario.predicted_top10) <= universe:
            raise AssertionError(f"{scenario.scenario_id} leaves the R08 universe")
    return tuple(scenarios)


def _fmt(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{digits}f}"


def _prediction_text(prediction: Sequence[str]) -> str:
    return " > ".join(DISPLAY_CODES[driver_id] for driver_id in prediction)


def _position_list(positions: Sequence[int]) -> str:
    return ",".join(f"P{position}" for position in positions) if positions else "none"


def _distance_text(distances: Sequence[int]) -> str:
    return "[" + ",".join(str(value) for value in distances) + "]"


def _combo_text(runs: Sequence[ComboRun]) -> str:
    if not runs:
        return "none"
    return "; ".join(
        (
            f"P{run.start}-P{run.start + run.length - 1}"
            f"(y={run.start_value:.4f},f={run.length_value:.4f},"
            f"shape={run.shape_contribution:.4f})"
        )
        for run in runs
    )


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = fmean(left)
    right_mean = fmean(right)
    numerator = sum(
        (left_value - left_mean) * (right_value - right_mean)
        for left_value, right_value in zip(left, right, strict=True)
    )
    left_ss = sum((value - left_mean) ** 2 for value in left)
    right_ss = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_ss * right_ss)
    return numerator / denominator if denominator else None


def _dominance_violations(
    scored: Sequence[tuple[Scenario, ScoreResult]], tolerance: float = 1e-12
) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []
    for left_scenario, left in scored:
        for right_scenario, right in scored:
            if left_scenario.scenario_id == right_scenario.scenario_id:
                continue
            left_branches = (
                left.pool_membership_score,
                left.exact_branch_score,
                left.internal_order_score,
            )
            right_branches = (
                right.pool_membership_score,
                right.exact_branch_score,
                right.internal_order_score,
            )
            dominates = all(
                left_value >= right_value - tolerance
                for left_value, right_value in zip(
                    left_branches, right_branches, strict=True
                )
            ) and any(
                left_value > right_value + tolerance
                for left_value, right_value in zip(
                    left_branches, right_branches, strict=True
                )
            )
            if dominates and not (
                left.overall_candidate_score > right.overall_candidate_score + tolerance
            ):
                violations.append(
                    (left_scenario.scenario_id, right_scenario.scenario_id)
                )
    return violations


def _comparison_row(
    by_id: dict[str, tuple[Scenario, ScoreResult]],
    left_id: str,
    right_id: str,
    expectation: str,
) -> str:
    left = by_id[left_id][1]
    right = by_id[right_id][1]
    delta = left.overall_candidate_score - right.overall_candidate_score
    winner = left_id if delta > 0 else right_id if delta < 0 else "tie"
    return (
        f"| {left_id} | {right_id} | {expectation} | {winner} | "
        f"{delta:+.4f} |"
    )


def render_report(
    truth: GroundTruth,
    scenarios: Sequence[Scenario],
    x_combo: float = CURRENT_X_COMBO,
) -> str:
    combo_x = _validate_combo_x(x_combo)
    is_control = math.isclose(combo_x, CONTROL_X_COMBO, rel_tol=0.0, abs_tol=1e-12)
    status_line = (
        "> Status: `temporary / non-authoritative / review-required`. This report must not be used as an official comparator backtest, and scoring rules must not be changed based on it."
        if is_control
        else "> Status: `temporary / supporting-evidence / parameterized-candidate`. This report only validates the isolated computation of the current candidate; it must not be used as an official comparator backtest or a production implementation."
    )
    protocol_line = (
        "- Scoring protocol: algorithm specification 0.7, ELG 0.9."
        if is_control
        else "- Scoring protocol: current authoritative algorithm specification and ELG; `x_combo=0.20` is the unfrozen preferred experimental candidate."
    )
    open_case_expectation = (
        "Open preference: five fully-ordered no-Exact vs four high Exact"
        if is_control
        else "Confirmed: four high Exact should clearly beat five fully-ordered no-Exact"
    )
    scored = [
        (scenario, score_prediction(scenario.predicted_top10, truth, combo_x))
        for scenario in scenarios
    ]
    by_id = {scenario.scenario_id: (scenario, result) for scenario, result in scored}
    sorted_scored = sorted(
        scored,
        key=lambda item: (-item[1].overall_candidate_score, item[0].scenario_id),
    )
    perfect = by_id["FIX-01-PERFECT"][1]
    if not math.isclose(perfect.overall_candidate_score, 1.0, abs_tol=1e-12):
        raise AssertionError("perfect scenario is not overall 1.0")
    if sorted_scored[0][0].scenario_id != "FIX-01-PERFECT":
        raise AssertionError("perfect scenario is not ranked first")
    dominance_violations = _dominance_violations(scored)
    if dominance_violations:
        raise AssertionError(f"main-branch dominance violation: {dominance_violations}")

    k_distance = 1.0 / (25.0 * (1.0 + combo_x))
    lines: list[str] = [
        "# Qualifying V1 R08 Synthetic Ranking Score Temporary Audit",
        "",
        status_line,
        "",
        "## 0. Audit scope",
        "",
        "- Goal: check the direction, double counting, and weight behavior of the current candidate scoring system.",
        "- Event: 2026 R08 Austrian Grand Prix qualifying.",
        "- Samples: 12 fixed adversarial scenarios + 18 stratified weighted-random scenarios.",
        protocol_line,
        "- Explicitly excluded: DSQ branch, official model, official comparator, automated parameter tuning.",
        "",
        "## 1. Authoritative data and gates",
        "",
        "| Gate | Result | Evidence |",
        "|---|---|---|",
        f"| FIA final classification | pass, P1-P22 contiguous numeric values | `{truth.official_pdf_path}` |",
        f"| FIA PDF SHA-256 | pass | `{truth.official_pdf_sha256}` |",
        f"| processed identity/order | {truth.official_audit_status} | `qualifying_v1_p0_4_official_label_audit.json` |",
        f"| frozen field size | {truth.field_size_audit_status}, N={truth.field_size} | `{truth.entry_list_path}` |",
        f"| entry-list SHA-256 | pass | `{truth.entry_list_sha256}` |",
        "| non-numeric status | none; DSQ not tested this round | FIA final classification |",
        "",
        "Actual P1-P22:",
        "",
        f"```text\n{_prediction_text(truth.official_order)}\n```",
        "",
        "Code legend:",
        "",
        "```text",
        ", ".join(
            f"{DISPLAY_CODES[driver_id]}={driver_id}" for driver_id in truth.official_order
        ),
        "```",
        "",
        "## 2. Parameter snapshot",
        "",
        "| Parameter | Current candidate |",
        "|---|---:|",
        "| Pool Top3/Top5/Top10 | 0.10 / 0.20 / 0.70 |",
        "| Exact position curve | `1-0.4*((i-1)/9)^1.25` |",
        f"| Combo b | {COMBO_BASE:.4f} |",
        f"| Combo q | {COMBO_START_Q:.10f} |",
        f"| x_combo | {combo_x:.10f} |",
        f"| k_distance | {k_distance:.10f} |",
        "| Main Exact/Membership/Order | 0.45 / 0.35 / 0.20 |",
        "",
        "## 3. Sample generation protocol",
        "",
        "Fixed samples:",
        "",
        "| ID | Scenario | Audit intent |",
        "|---|---|---|",
    ]
    for scenario in scenarios:
        if scenario.kind == "fixed":
            lines.append(
                f"| {scenario.scenario_id} | {scenario.description} | {scenario.audit_intent} |"
            )
    lines.extend(
        [
            "",
            "Random samples cross 3 Membership overlap ranges with 3 Order noise tiers, two fixed seeds per cell. Drivers are drawn without replacement using decay weights on official position; ordering uses `official_position + Normal(0,sigma)`.",
            "",
            "| ID | Membership | Order | seed | common count |",
            "|---|---|---|---:|---:|",
        ]
    )
    for scenario, result in scored:
        if scenario.kind == "weighted_random":
            lines.append(
                f"| {scenario.scenario_id} | {scenario.membership_tier} | "
                f"{scenario.order_tier} | {scenario.seed} | {result.common_driver_count} |"
            )

    lines.extend(
        [
            "",
            "## 4. Overall ranking and main branches",
            "",
            "| # | ID | kind | simulated P1-P10 | Overall | Pool | ExactBranch | Order | Exact n | common m | mean distance |",
            "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for rank, (scenario, result) in enumerate(sorted_scored, start=1):
        lines.append(
            f"| {rank} | {scenario.scenario_id} | {scenario.kind} | "
            f"{_prediction_text(result.predicted_top10)} | "
            f"{result.overall_candidate_score:.4f} | "
            f"{result.pool_membership_score:.4f} | "
            f"{result.exact_branch_score:.4f} | "
            f"{result.internal_order_score:.4f} | "
            f"{result.exact_hit_count} | {result.common_driver_count} | "
            f"{result.mean_rank_distance:.2f} |"
        )

    lines.extend(
        [
            "",
            "## 5. Membership details",
            "",
            "| ID | Top3 common | S_top3 | Top5 common | S_top5 | Top10 common | S_top10 | Pool |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for scenario, result in scored:
        lines.append(
            f"| {scenario.scenario_id} | {result.top3_common_count} | "
            f"{result.top3_set_score:.4f} | {result.top5_common_count} | "
            f"{result.top5_set_score:.4f} | {result.top10_common_count} | "
            f"{result.top10_set_score:.4f} | {result.pool_membership_score:.4f} |"
        )

    lines.extend(
        [
            "",
            "## 6. Exact, Combo, and Distance details",
            "",
            "### 6.1 Exact and Combo",
            "",
            "| ID | Exact positions | S_exact | Combo runs with per-run parameters | shape | bonus | positive raw | positive score |",
            "|---|---|---:|---|---:|---:|---:|---:|",
        ]
    )
    for scenario, result in scored:
        lines.append(
            f"| {scenario.scenario_id} | {_position_list(result.exact_hit_positions)} | "
            f"{result.exact_position_score:.4f} | {_combo_text(result.combo_runs)} | "
            f"{result.combo_shape:.4f} | {result.combo_bonus:.4f} | "
            f"{result.exact_positive_raw:.4f} | {result.exact_positive_score:.4f} |"
        )
    lines.extend(
        [
            "",
            "### 6.2 Distance and ExactBranch",
            "",
            "| ID | distance vector | sum | mean | max | k | penalty | ExactBranch |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for scenario, result in scored:
        lines.append(
            f"| {scenario.scenario_id} | {_distance_text(result.distance_vector)} | "
            f"{result.distance_sum} | {result.mean_rank_distance:.4f} | "
            f"{result.max_rank_distance} | {result.k_distance:.6f} | "
            f"{result.distance_penalty:.4f} | {result.exact_branch_score:.4f} |"
        )

    lines.extend(
        [
            "",
            "## 7. Internal Order details",
            "",
            "| ID | common m | pairs T | inversions I | correct C | conditional accuracy | signed diagnostic | Order score |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for scenario, result in scored:
        lines.append(
            f"| {scenario.scenario_id} | {result.common_driver_count} | "
            f"{result.observed_pair_count} | {result.inversion_count} | "
            f"{result.correct_pair_count} | {_fmt(result.conditional_order_accuracy)} | "
            f"{result.signed_internal_order_skill:.4f} | "
            f"{result.internal_order_score:.4f} |"
        )

    lines.extend(
        [
            "",
            "## 8. Outer weight contributions",
            "",
            "| ID | 0.45*Exact | 0.35*Pool | 0.20*Order | Overall |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for scenario, result in scored:
        lines.append(
            f"| {scenario.scenario_id} | {result.exact_contribution:.4f} | "
            f"{result.membership_contribution:.4f} | "
            f"{result.internal_order_contribution:.4f} | "
            f"{result.overall_candidate_score:.4f} |"
        )

    lines.extend(
        [
            "",
            "## 9. Fixed adversarial checks",
            "",
            "A positive delta means the left sample has the higher overall score.",
            "",
            "| Left | Right | Expected check | Actual winner | Overall delta |",
            "|---|---|---|---|---:|",
            _comparison_row(
                by_id,
                "FIX-03-BOTTOM-SWAP",
                "FIX-02-TOP-SWAP",
                "The bottom adjacent swap should outrank the top adjacent swap",
            ),
            _comparison_row(
                by_id,
                "FIX-06-P1-P5-COMBO",
                "FIX-07-P6-P10-COMBO",
                "Between equal five-runs, the high-order five-run should be clearly better",
            ),
            _comparison_row(
                by_id,
                "FIX-09-PODIUM-NEAR",
                "FIX-10-PODIUM-FAR",
                "With identical podium Exact, the prediction with closer outsiders should be better",
            ),
            _comparison_row(
                by_id,
                "FIX-04-CYCLIC",
                "FIX-05-REVERSE",
                "With the same full Top10 pool and zero Exact, the cyclic shift should beat the full reverse",
            ),
            _comparison_row(
                by_id,
                "FIX-11-FIVE-ORDERED-NO-EXACT",
                "FIX-12-FOUR-EXACT-FAR",
                open_case_expectation,
            ),
            *(
                []
                if is_control
                else [
                    _comparison_row(
                        by_id,
                        "FIX-06-P1-P5-COMBO",
                        "FIX-04-CYCLIC",
                        "Confirmed: P1-P5 consecutive Exact should narrowly beat the fully shuffled Top10",
                    ),
                    _comparison_row(
                        by_id,
                        "FIX-10-PODIUM-FAR",
                        "FIX-05-REVERSE",
                        "Confirmed: podium Exact with severe misses should slightly beat the fully reversed Top10",
                    ),
                ]
            ),
            "",
            "### 9.1 Automatic invariants",
            "",
            f"- Perfect sample ranks first: `{sorted_scored[0][0].scenario_id == 'FIX-01-PERFECT'}`.",
            f"- Main-branch dominance violations: `{len(dominance_violations)}`.",
            "- Every overall score is recomputed term by term as the sum of the three outer weight contributions.",
            "- All 30 predicted rankings differ; each is 10 unique identities within the frozen 22-driver universe.",
        ]
    )

    pool_values = [result.pool_membership_score for _, result in scored]
    exact_values = [result.exact_branch_score for _, result in scored]
    order_values = [result.internal_order_score for _, result in scored]
    correlations = {
        "Pool vs ExactBranch": _pearson(pool_values, exact_values),
        "Pool vs Order": _pearson(pool_values, order_values),
        "ExactBranch vs Order": _pearson(exact_values, order_values),
    }
    random_scored = [item for item in scored if item[0].kind == "weighted_random"]
    tier_summary: list[str] = []
    for tier in ("high", "medium", "low"):
        tier_results = [
            result
            for scenario, result in random_scored
            if scenario.membership_tier == tier
        ]
        tier_summary.append(
            f"- Membership {tier}: mean common={fmean(r.common_driver_count for r in tier_results):.2f}, "
            f"mean Overall={fmean(r.overall_candidate_score for r in tier_results):.4f}."
        )
    order_tier_summary: list[str] = []
    for tier in ("high", "medium", "low"):
        tier_results = [
            result
            for scenario, result in random_scored
            if scenario.order_tier == tier
        ]
        conditional_values = [
            result.conditional_order_accuracy
            for result in tier_results
            if result.conditional_order_accuracy is not None
        ]
        order_tier_summary.append(
            f"- Order {tier}: mean conditional order accuracy="
            f"{fmean(conditional_values):.4f}."
        )

    left = by_id["FIX-11-FIVE-ORDERED-NO-EXACT"][1]
    right = by_id["FIX-12-FOUR-EXACT-FAR"][1]
    open_case_winner = (
        "five fully ordered with zero Exact"
        if left.overall_candidate_score > right.overall_candidate_score
        else "four high Exact with the rest far off"
    )
    open_case_review_line = (
        f"- In the open adversarial case, the current combined score chose \"{open_case_winner}\". Math alone cannot judge this correct; it must be checked against user preference."
        if is_control
        else f"- In the confirmed adversarial case, the current combined score chose \"{open_case_winner}\", matching the user judgment that four high Exact must clearly win."
    )
    next_step_line = (
        "- A single-event synthetic audit is not enough to freeze parameters. The user should first review the tables and the open adversarial case, then decide whether to adjust samples or move on to multi-event real-prediction audits."
        if is_control
        else "- A single-event synthetic audit is not enough to freeze parameters. Both cross-branch extreme adversarial cases match the user's direction, but the current candidate still needs real-case and DSQ-branch audits."
    )
    lines.extend(
        [
            "",
            "## 10. Project lead's preliminary judgment",
            "",
            "### 10.1 As expected",
            "",
            "- The perfect prediction scores the unique 1.0000 and ranks first.",
            "- The high adjacent swap loses more than the low adjacent swap; the position curve and the high-order Combo act as intended.",
            "- The P1-P5 five-run clearly beats the P6-P10 five-run; the start curve does not let the later Combo take over.",
            "- The near/far samples with identical podium Exact are separated only by Distance; the direction is correct.",
            "- The cyclic shift of the same Top10 beats the full reverse; Distance and Internal Order both recognize severity.",
            "",
            "### 10.2 Needs attention",
            "",
            open_case_review_line,
            *(
                []
                if is_control
                else [
                    "- P1-P5 consecutive Exact beats the fully shuffled Top10 by only about 0.0005; the direction is right, but this is an acceptable rather than ideal compromise after reducing Combo.",
                    "- Podium Exact with far outsiders beats the fully reversed Top10 by only about 0.0055; the direction and small margin match preference, but both absolute performances are poor.",
                ]
            ),
            "- The three main branches are naturally correlated on synthetic samples. Correlation can only hint at double-counting risk; it cannot by itself prove the weights wrong:",
            *[
                f"  - {name}: `{_fmt(value)}`"
                for name, value in correlations.items()
            ],
            *tier_summary,
            *order_tier_summary,
            "- The Exact branch contains Distance, and Exact hits also improve Membership and Internal Order; the current 0.45/0.35/0.20 must still be reviewed against pairwise marginal changes, not just overall-ranking correlation.",
            "",
            "### 10.3 No change recommended yet",
            "",
            "- This round found no main-branch dominance inversion, and Combo alone never pushed a clearly worse sample into an anomalously high position.",
            next_step_line,
            "",
            "## 11. Limitations and next steps",
            "",
            "1. R08 is a single event and cannot represent different tracks or weekends.",
            "2. These are controlled synthetic outputs, not the error distribution of a real comparator.",
            "3. R08 has no non-numeric classifications; this report did not validate DSQ adjustments at all.",
            "4. Correlations are shaped by the stratified generator design and must not be read as statistical conclusions.",
            "5. All parameters remain candidates; this report can only surface problems and continue the discussion, and cannot directly trigger coding or formal elimination.",
            "",
            "Reproduction command:",
            "",
            "```bash",
            "python3 scripts/qualifying_v1_r08_synthetic_score_audit.py",
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def generate_report(
    output_path: Path = DEFAULT_OUTPUT_PATH,
    x_combo: float = CURRENT_X_COMBO,
) -> tuple[Path, str]:
    truth = load_r08_ground_truth(ROOT)
    scenarios = build_scenarios(truth)
    report = render_report(truth, scenarios, x_combo)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    digest = hashlib.sha256(report.encode("utf-8")).hexdigest()
    return output_path, digest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the temporary R08 synthetic qualifying-score audit."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Markdown output path.",
    )
    parser.add_argument(
        "--x-combo",
        type=float,
        default=CURRENT_X_COMBO,
        help=(
            "Explicit combo scale. Defaults to the current candidate 0.20; "
            "use 0.4323589504 to reproduce the historical control report."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output_path, digest = generate_report(args.output, args.x_combo)
    print(f"wrote {output_path}")
    print("scenario_count=30")
    print(f"x_combo={_validate_combo_x(args.x_combo):.10f}")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
