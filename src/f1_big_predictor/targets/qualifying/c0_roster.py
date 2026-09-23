"""Unified C0 replay for the 29 registered qualifying candidates."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any
from zoneinfo import ZoneInfo

from .borda_model import CTOR_UP_WEIGHTS, EQUAL_WEIGHTS
from .c0_scorer import score_qualifying
from .features import (
    ACTUALS_PATH,
    CIRCUIT_HISTORY_DIR,
    GRID_PATH,
    TRACK_PROFILE_PATH,
)
from .official_labels import OFFICIAL_LABELS_PATH, official_records_for_round
from .types import DEFAULT_WEIGHTS, QualifyingFeatureConfig, resolve_weights
from .walk_forward import run_walk_forward
from .walk_forward_baselines import run_walk_forward_baselines
from .walk_forward_borda import run_walk_forward_borda
from .walk_forward_elastic_net import run_walk_forward_elastic_net
from .walk_forward_lambdamart import run_walk_forward_lambdamart
from .walk_forward_prob import (
    run_walk_forward_bradley_terry,
    run_walk_forward_plackett_luce,
)
from .walk_forward_rating import (
    run_walk_forward_colley,
    run_walk_forward_elo,
    run_walk_forward_gaussian_pairwise,
    run_walk_forward_glicko,
    run_walk_forward_keener,
    run_walk_forward_massey,
)
from .walk_forward_ridge import run_walk_forward_ridge
from .walk_forward_slot_ensemble import (
    run_walk_forward_slot_peak,
    run_walk_forward_slot_robust,
)


SCHEMA_VERSION = "qualifying.c0_roster_run.v1"
SCORING_SCHEME_ID = "qualifying.c0.frozen_candidate.2026-07-17"
# R02 has been excluded from the scoring window permanently, by strategic
# decision: its only training source, R01, is a 19-row cold-start data vacuum
# that would contaminate the selection. R02 still exists in the walk-forward
# history as training knowledge for R03, but is never a scored round. The
# scoring window is fixed at R03-R09 (seven rounds, one caliber for all candidates).
EVALUATION_ROUNDS = tuple(range(3, 10))

_TUNED_EXPLAINABLE_WEIGHTS = {
    "form": 0.25,
    "constructor": 0.35,
    "circuit_fit": 0.20,
    "reliability": 0.05,
}

_REQUIRED_INPUT_FILES = (ACTUALS_PATH, OFFICIAL_LABELS_PATH, GRID_PATH)
_OPTIONAL_INPUT_FILES = (TRACK_PROFILE_PATH,)
_OPTIONAL_INPUT_DIRECTORIES = (CIRCUIT_HISTORY_DIR,)


@dataclass(frozen=True)
class CandidateSpec:
    """One uniquely identified candidate configuration in the roster."""

    ordinal: int
    candidate_id: str
    model_id: str
    variant: str
    related_group: str | None
    first_scoring_round: int
    public_config: dict[str, Any]
    runner: Callable[[Path], dict[str, Any]] = field(repr=False, compare=False)

    def public_record(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "candidate_id": self.candidate_id,
            "model_id": self.model_id,
            "variant": self.variant,
            "related_group": self.related_group,
            "first_scoring_round": self.first_scoring_round,
            "expected_scoring_rounds": [
                round_number
                for round_number in EVALUATION_ROUNDS
                if round_number >= self.first_scoring_round
            ],
            "config": self.public_config,
        }


def candidate_registry() -> tuple[CandidateSpec, ...]:
    """Return the frozen-order registry corresponding to roster entries #1-29."""
    default_interaction = QualifyingFeatureConfig(
        track_profile_method="interaction",
        weights=dict(DEFAULT_WEIGHTS),
    )
    tuned_interaction = QualifyingFeatureConfig(
        track_profile_method="interaction",
        weights=dict(_TUNED_EXPLAINABLE_WEIGHTS),
    )
    default_independent = QualifyingFeatureConfig(
        track_profile_method="independent",
        weights=dict(DEFAULT_WEIGHTS),
    )
    tuned_independent = QualifyingFeatureConfig(
        track_profile_method="independent",
        weights=dict(_TUNED_EXPLAINABLE_WEIGHTS),
    )

    specs = (
        _baseline_spec(1, "latest_prior"),
        _baseline_spec(2, "season_to_date"),
        _baseline_spec(3, "constructor_only"),
        _baseline_spec(4, "form_w3", public_config={"window": 3}),
        _spec(
            5,
            "ridge_alpha_10",
            "qualifying.model.stat.ridge",
            "alpha=10.0",
            "stat-ridge-A",
            {"alpha": 10.0},
            partial(run_walk_forward_ridge, alpha=10.0),
        ),
        _spec(
            6,
            "ridge_alpha_5",
            "qualifying.model.stat.ridge",
            "alpha=5.0",
            "stat-ridge-A",
            {"alpha": 5.0},
            partial(run_walk_forward_ridge, alpha=5.0),
        ),
        _spec(
            7,
            "elastic_net_a020_l1_050",
            "qualifying.model.stat.elastic_net",
            "alpha=0.20, l1_ratio=0.50",
            "stat-en-B",
            {"alpha": 0.2, "l1_ratio": 0.5},
            partial(run_walk_forward_elastic_net, alpha=0.2, l1_ratio=0.5),
        ),
        _spec(
            8,
            "elastic_net_a020_l1_070",
            "qualifying.model.stat.elastic_net",
            "alpha=0.20, l1_ratio=0.70",
            "stat-en-B",
            {"alpha": 0.2, "l1_ratio": 0.7},
            partial(run_walk_forward_elastic_net, alpha=0.2, l1_ratio=0.7),
        ),
        _spec(
            9,
            "elastic_net_a001_l1_030",
            "qualifying.model.stat.elastic_net",
            "alpha=0.01, l1_ratio=0.30",
            "stat-en-B",
            {"alpha": 0.01, "l1_ratio": 0.3},
            partial(run_walk_forward_elastic_net, alpha=0.01, l1_ratio=0.3),
        ),
        _explainable_spec(10, "interaction_default", default_interaction),
        _explainable_spec(11, "interaction_tuned", tuned_interaction),
        _explainable_spec(12, "independent_default", default_independent),
        _explainable_spec(13, "independent_tuned", tuned_independent),
        _spec(
            14,
            "borda_equal",
            "qualifying.model.heuristic.borda",
            "equal weights",
            "heuristic-D",
            {"weights": dict(EQUAL_WEIGHTS)},
            partial(run_walk_forward_borda, weights=dict(EQUAL_WEIGHTS)),
        ),
        _spec(
            15,
            "borda_constructor_x2",
            "qualifying.model.heuristic.borda",
            "constructor x2",
            "heuristic-D",
            {"weights": dict(CTOR_UP_WEIGHTS)},
            partial(run_walk_forward_borda, weights=dict(CTOR_UP_WEIGHTS)),
        ),
        _spec(
            16,
            "elo_k16",
            "qualifying.model.rating.elo",
            "K=16",
            "rating-E",
            {"k": 16.0},
            partial(run_walk_forward_elo, k=16.0),
        ),
        _spec(
            17,
            "elo_k32",
            "qualifying.model.rating.elo",
            "K=32",
            "rating-E",
            {"k": 32.0},
            partial(run_walk_forward_elo, k=32.0),
        ),
        _spec(
            18,
            "massey",
            "qualifying.model.rating.massey",
            "default",
            "rating-E",
            {},
            run_walk_forward_massey,
        ),
        _spec(
            19,
            "colley",
            "qualifying.model.rating.colley",
            "default",
            "rating-E",
            {},
            run_walk_forward_colley,
        ),
        _spec(
            20,
            "keener_a025",
            "qualifying.model.rating.keener",
            "alpha=0.25",
            "rating-E",
            {"alpha": 0.25},
            partial(run_walk_forward_keener, alpha=0.25),
        ),
        _spec(
            21,
            "glicko_rd50",
            "qualifying.model.rating.glicko",
            "initial_rd=50, c=30",
            "rating-E",
            {"initial_rd": 50.0, "c": 30.0},
            partial(run_walk_forward_glicko, initial_rd=50.0, c=30.0),
        ),
        _spec(
            22,
            "glicko_rd150",
            "qualifying.model.rating.glicko",
            "initial_rd=150, c=30",
            "rating-E",
            {"initial_rd": 150.0, "c": 30.0},
            partial(run_walk_forward_glicko, initial_rd=150.0, c=30.0),
        ),
        _spec(
            23,
            "gaussian_pairwise_b417_t05",
            "qualifying.model.rating.gaussian_pairwise_approx",
            "beta=4.17, tau=0.5",
            "rating-E",
            {"beta": 4.17, "tau": 0.5},
            partial(run_walk_forward_gaussian_pairwise, beta=4.17, tau=0.5),
        ),
        _spec(
            24,
            "gaussian_pairwise_b8_t0",
            "qualifying.model.rating.gaussian_pairwise_approx",
            "beta=8.0, tau=0.0",
            "rating-E",
            {"beta": 8.0, "tau": 0.0},
            partial(run_walk_forward_gaussian_pairwise, beta=8.0, tau=0.0),
        ),
        _spec(
            25,
            "bradley_terry_delta0",
            "qualifying.model.prob.bradley_terry",
            "delta=0.0",
            "prob-F",
            {"delta": 0.0},
            partial(run_walk_forward_bradley_terry, delta=0.0),
        ),
        _spec(
            26,
            "bradley_terry_delta1",
            "qualifying.model.prob.bradley_terry",
            "delta=1.0",
            "prob-F",
            {"delta": 1.0},
            partial(run_walk_forward_bradley_terry, delta=1.0),
        ),
        _spec(
            27,
            "plackett_luce",
            "qualifying.model.prob.plackett_luce",
            "default",
            "prob-F",
            {},
            run_walk_forward_plackett_luce,
        ),
        _lambdamart_spec(28, 100),
        _lambdamart_spec(29, 200),
        _spec(
            30,
            "slot_ensemble_peak",
            "qualifying.model.ensemble.slot_specialist",
            "ST-6d peak: #9->P1; #28->T3; circuit_T5->T5; #13->T10+order (top_down)",
            "ensemble-H",
            {
                "method": "top_down",
                "slots": {
                    "p1": "elastic_net(alpha=0.01, l1_ratio=0.30)",
                    "t3": "lambdamart(n_estimators=100, leaves=7, lr=0.1)",
                    "t5": "explainable(interaction, circuit_fit=0.35, fw=3)",
                    "t10": "explainable(independent, tuned)",
                    "order": "explainable(independent, tuned)",
                },
                "provenance": "ST-6d knob-grid slot specialist",
            },
            run_walk_forward_slot_peak,
        ),
        _spec(
            31,
            "slot_ensemble_robust",
            "qualifying.model.ensemble.slot_specialist",
            "ST-6d robust: EN_new->P1+T3; circuit_T5->T5; #13->T10+order (set_first)",
            "ensemble-H",
            {
                "method": "set_first",
                "slots": {
                    "p1": "elastic_net(alpha=0.01, l1_ratio=0.70)",
                    "t3": "elastic_net(alpha=0.01, l1_ratio=0.70)",
                    "t5": "explainable(interaction, circuit_fit=0.35, fw=3)",
                    "t10": "explainable(independent, tuned)",
                    "order": "explainable(independent, tuned)",
                },
                "provenance": "ST-6d knob-grid slot specialist",
            },
            run_walk_forward_slot_robust,
        ),
    )
    _validate_registry(specs)
    return specs


def run_c0_roster(
    project_root: Path,
    *,
    candidates: Sequence[CandidateSpec] | None = None,
) -> dict[str, Any]:
    """Replay registered candidates and isolate candidate/round failures."""
    project_root = project_root.resolve()
    specs = tuple(candidates) if candidates is not None else candidate_registry()
    _validate_registry(specs, require_full_roster=candidates is None)
    input_snapshot = build_input_snapshot(project_root)

    candidate_results = [_run_candidate(project_root, spec) for spec in specs]
    scored_count = sum(
        round_result["status"] == "scored"
        for candidate in candidate_results
        for round_result in candidate["rounds"]
    )
    failed_count = sum(
        candidate["status"] == "failed" for candidate in candidate_results
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "target_id": "qualifying",
        "season": 2026,
        "run_purpose": "historical_development_replay_not_production_evidence",
        "cutoff_semantics": {
            "training": "only rounds strictly before each target round",
            "target_field": "official target-round entry/classification universe",
            "labels": "revealed to C0 only after each model prediction is produced",
            "independence_limit": (
                "R02-R09 are development data; only a future prediction frozen before "
                "the result can provide prospective evidence"
            ),
        },
        "scoring_scheme_id": SCORING_SCHEME_ID,
        "evaluation_rounds": list(EVALUATION_ROUNDS),
        "input_snapshot": input_snapshot,
        "candidate_registry": [spec.public_record() for spec in specs],
        "summary": {
            "candidate_count": len(specs),
            "completed_candidate_count": len(specs) - failed_count,
            "failed_candidate_count": failed_count,
            "scored_prediction_count": scored_count,
            "expected_scoring_opportunity_count": sum(
                len(spec.public_record()["expected_scoring_rounds"]) for spec in specs
            ),
        },
        "candidates": candidate_results,
    }


def build_input_snapshot(project_root: Path) -> dict[str, Any]:
    """Hash the complete file set consumed by the current roster."""
    records: list[dict[str, str]] = []
    missing: list[str] = []
    seen: set[Path] = set()

    for relative_path in _REQUIRED_INPUT_FILES:
        path = project_root / relative_path
        if not path.is_file():
            raise FileNotFoundError(
                f"required C0 roster input missing: {relative_path}"
            )
        _append_file_hash(project_root, path, records, seen)

    for relative_path in _OPTIONAL_INPUT_FILES:
        path = project_root / relative_path
        if path.is_file():
            _append_file_hash(project_root, path, records, seen)
        else:
            missing.append(relative_path.as_posix())

    for relative_directory in _OPTIONAL_INPUT_DIRECTORIES:
        directory = project_root / relative_directory
        if not directory.is_dir():
            missing.append(relative_directory.as_posix())
            continue
        for path in sorted(
            item for item in directory.rglob("*.json") if item.is_file()
        ):
            _append_file_hash(project_root, path, records, seen)

    records.sort(key=lambda item: item["path"])
    combined_payload = {"files": records, "missing_paths": sorted(missing)}
    return {
        **combined_payload,
        "combined_sha256": _json_sha256(combined_payload),
    }


def write_run_artifacts(
    project_root: Path,
    output_directory: Path,
    results: dict[str, Any],
) -> dict[str, Path]:
    """Write deterministic results plus a provenance-bearing run manifest."""
    output_directory.mkdir(parents=True, exist_ok=True)
    results_path = output_directory / "c0_results.json"
    results_bytes = _pretty_json(results).encode("utf-8")
    results_path.write_bytes(results_bytes)

    commit = _git_output(project_root, "rev-parse", "HEAD")
    status = _git_output(
        project_root, "status", "--porcelain", "--untracked-files=normal"
    )
    manifest = {
        "schema_version": "qualifying.c0_roster_manifest.v1",
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(
            timespec="seconds"
        ),
        "code_commit": commit,
        "working_tree_clean": not bool(status),
        "working_tree_status": status.splitlines(),
        "results_path": results_path.name,
        "results_sha256": hashlib.sha256(results_bytes).hexdigest(),
        "input_snapshot_sha256": results["input_snapshot"]["combined_sha256"],
        "candidate_count": results["summary"]["candidate_count"],
        "evaluation_rounds": results["evaluation_rounds"],
        "scoring_scheme_id": results["scoring_scheme_id"],
    }
    manifest_path = output_directory / "run_manifest.json"
    manifest_path.write_text(_pretty_json(manifest), encoding="utf-8")
    return {"results": results_path, "manifest": manifest_path}


def _run_candidate(project_root: Path, spec: CandidateSpec) -> dict[str, Any]:
    public_record = spec.public_record()
    try:
        history = spec.runner(project_root)
        per_round = history.get("per_round")
        if not isinstance(per_round, list):
            raise ValueError("candidate history must contain a per_round list")
        history_by_round: dict[int, dict[str, Any]] = {}
        for item in per_round:
            round_number = int(item["round"])
            if round_number in history_by_round:
                raise ValueError(f"duplicate history round R{round_number:02d}")
            history_by_round[round_number] = item
        runner_gaps = [str(item) for item in history.get("evidence_gaps", [])]
    except Exception as exc:
        return {
            **public_record,
            "status": "failed",
            "failure": {"type": type(exc).__name__, "message": str(exc)},
            "runner_evidence_gaps": [],
            "rounds": _failed_rounds(spec, "candidate_runner_exception"),
            "summary": _candidate_summary(
                _failed_rounds(spec, "candidate_runner_exception")
            ),
        }

    round_results: list[dict[str, Any]] = []
    for round_number in EVALUATION_ROUNDS:
        if round_number < spec.first_scoring_round:
            round_results.append(
                {
                    "round": round_number,
                    "status": "expected_exclusion",
                    "reason": "preregistered_model_cold_start_exclusion",
                    "prediction_top10": None,
                    "c0": None,
                }
            )
            continue

        history_round = history_by_round.get(round_number)
        if history_round is None:
            round_results.append(
                {
                    "round": round_number,
                    "status": "failed",
                    "reason": _round_gap_reason(runner_gaps, round_number),
                    "prediction_top10": None,
                    "c0": None,
                }
            )
            continue

        prediction = history_round.get("top10_predicted_driver_ids")
        try:
            official_records, field_size = official_records_for_round(
                project_root, round_number
            )
            c0_result = score_qualifying(prediction, official_records, field_size)
        except Exception as exc:
            round_results.append(
                {
                    "round": round_number,
                    "race_name": history_round.get("race_name"),
                    "status": "failed",
                    "reason": "c0_scoring_error",
                    "failure": {"type": type(exc).__name__, "message": str(exc)},
                    "prediction_top10": prediction,
                    "c0": None,
                }
            )
            continue

        round_results.append(
            {
                "round": round_number,
                "race_name": history_round.get("race_name"),
                "status": "scored",
                "prediction_top10": prediction,
                "training_rounds": history_round.get("training_rounds"),
                "prediction_evidence_gaps": history_round.get(
                    "prediction_evidence_gaps", []
                ),
                "c0": c0_result,
            }
        )

    summary = _candidate_summary(round_results)
    return {
        **public_record,
        "status": "failed" if summary["failed_round_count"] else "completed",
        "failure": None,
        "runner_evidence_gaps": runner_gaps,
        "rounds": round_results,
        "summary": summary,
    }


def _failed_rounds(spec: CandidateSpec, reason: str) -> list[dict[str, Any]]:
    return [
        {
            "round": round_number,
            "status": (
                "expected_exclusion"
                if round_number < spec.first_scoring_round
                else "failed"
            ),
            "reason": (
                "preregistered_model_cold_start_exclusion"
                if round_number < spec.first_scoring_round
                else reason
            ),
            "prediction_top10": None,
            "c0": None,
        }
        for round_number in EVALUATION_ROUNDS
    ]


def _candidate_summary(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [
        float(item["c0"]["overall_candidate"]["overall_candidate_score"])
        for item in rounds
        if item["status"] == "scored"
    ]
    return {
        "scored_round_count": len(scores),
        "failed_round_count": sum(item["status"] == "failed" for item in rounds),
        "expected_exclusion_count": sum(
            item["status"] == "expected_exclusion" for item in rounds
        ),
        "overall_candidate_scores": scores,
    }


def _round_gap_reason(gaps: list[str], round_number: int) -> str:
    prefix = f"round_{round_number:02d}_"
    matching = [gap for gap in gaps if gap.startswith(prefix)]
    return ";".join(matching) if matching else "missing_candidate_round_output"


def _spec(
    ordinal: int,
    slug: str,
    model_id: str,
    variant: str,
    related_group: str | None,
    public_config: dict[str, Any],
    runner: Callable[[Path], dict[str, Any]],
    *,
    first_scoring_round: int = 3,
) -> CandidateSpec:
    return CandidateSpec(
        ordinal=ordinal,
        candidate_id=f"qv1-{ordinal:03d}-{slug}",
        model_id=model_id,
        variant=variant,
        related_group=related_group,
        first_scoring_round=first_scoring_round,
        public_config=public_config,
        runner=runner,
    )


def _baseline_spec(
    ordinal: int,
    name: str,
    *,
    public_config: dict[str, Any] | None = None,
) -> CandidateSpec:
    return _spec(
        ordinal,
        name,
        f"qualifying.model.baseline.{name}",
        "default",
        None,
        public_config or {},
        partial(_run_baseline_history, name),
    )


def _run_baseline_history(name: str, project_root: Path) -> dict[str, Any]:
    return run_walk_forward_baselines(project_root)["baselines"][name]


def _explainable_spec(
    ordinal: int,
    slug: str,
    config: QualifyingFeatureConfig,
) -> CandidateSpec:
    resolved = resolve_weights(config.track_profile_method, config.weights)
    return _spec(
        ordinal,
        f"explainable_{slug}",
        "qualifying.model.v1.explainable_score",
        slug,
        "exp-C",
        {
            "form_window": config.form_window,
            "track_profile_method": config.track_profile_method,
            "resolved_weights": resolved,
        },
        partial(run_walk_forward, config=config),
    )


def _lambdamart_spec(ordinal: int, n_estimators: int) -> CandidateSpec:
    params = {
        "n_estimators": n_estimators,
        "num_leaves": 7,
        "learning_rate": 0.1,
        "min_child_samples": 5,
        "random_state": 42,
    }
    return _spec(
        ordinal,
        f"lambdamart_n{n_estimators}",
        "qualifying.model.ltr.lambdamart",
        f"n_estimators={n_estimators}, leaves=7, lr=0.1",
        "ltr-G",
        params,
        partial(run_walk_forward_lambdamart, params=dict(params)),
        first_scoring_round=3,
    )


def _validate_registry(
    specs: Sequence[CandidateSpec],
    *,
    require_full_roster: bool = False,
) -> None:
    if require_full_roster and len(specs) != 31:
        raise ValueError(
            f"full candidate registry must contain 31 entries, got {len(specs)}"
        )
    ordinals = [spec.ordinal for spec in specs]
    if require_full_roster and ordinals != list(range(1, 32)):
        raise ValueError("candidate registry ordinals must be contiguous 1..31")
    if len(ordinals) != len(set(ordinals)):
        raise ValueError("candidate registry ordinals must be unique")
    candidate_ids = [spec.candidate_id for spec in specs]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError("candidate registry candidate_id values must be unique")
    if any(spec.first_scoring_round not in EVALUATION_ROUNDS for spec in specs):
        raise ValueError("candidate first_scoring_round must be within R03-R09")


def _append_file_hash(
    project_root: Path,
    path: Path,
    records: list[dict[str, str]],
    seen: set[Path],
) -> None:
    resolved = path.resolve()
    if resolved in seen:
        return
    seen.add(resolved)
    records.append(
        {
            "path": resolved.relative_to(project_root).as_posix(),
            "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
        }
    )


def _git_output(project_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(project_root), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout.strip()


def _json_sha256(payload: Any) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _pretty_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
