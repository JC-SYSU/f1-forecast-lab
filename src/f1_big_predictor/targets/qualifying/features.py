from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from .official_labels import load_officialized_actuals
from .types import (
    EVIDENCE_POLICY,
    FEATURE_SET_ID,
    QualifyingFeatureConfig,
    resolve_weights,
)


DEFAULT_SEASON = 2026
ACTUALS_PATH = Path("data/processed/season_2026_actuals/actuals.json")
GRID_PATH = Path("data/manual/2026_grid.json")
TRACK_PROFILE_PATH = Path("data/manual/track_profile_2026_v1.json")
AGENT_EVIDENCE_PATH = Path("data/manual/agent_evidence_2026_v1.json")
SUBJECTIVE_RESIDUALS_DIR = Path("data/manual/subjective_residuals_2026_v1")
CIRCUIT_HISTORY_DIR = Path("data/processed/circuit_history_2026_v1")
SEAT_CHANGES_PATH = Path("data/manual/seat_changes_2026_v1.json")
MIN_RELIABILITY_STARTS = 3


def required_features() -> tuple[str, ...]:
    return (
        "driver_id",
        "form_score",
        "constructor_score",
        "circuit_fit_score",
        "evidence_score",
        "reliability_score",
    )


def build_qualifying_features(
    *,
    project_root: Path,
    target_round: int,
    season: int = DEFAULT_SEASON,
    config: QualifyingFeatureConfig | None = None,
    officialize_actuals: bool = True,
) -> dict[str, Any]:
    if target_round < 1:
        raise ValueError("target_round must be at least 1")
    config = config or QualifyingFeatureConfig()
    # Unit fixtures can explicitly disable the overlay. Production callers fail
    # closed if the tracked official-label manifest is unavailable.
    actuals = (
        load_officialized_actuals(project_root)
        if officialize_actuals
        else _load_json(project_root / ACTUALS_PATH)
    )
    grid = _load_json(project_root / GRID_PATH)
    rounds = sorted(
        actuals.get("completed_rounds", []), key=lambda item: int(item["round"])
    )
    target_event = _round_by_number(rounds, target_round)
    prior_rounds = [item for item in rounds if int(item["round"]) < target_round]
    prior_window = prior_rounds[-config.form_window :]
    registry = _load_seat_registry(project_root)
    drivers, seat_notes = _apply_seat_overrides(grid, registry, target_round)
    teams = _grid_teams(grid)
    track_profile = _track_profile_for_round(project_root, target_event, target_round)
    resolved_weights = resolve_weights(config.track_profile_method, config.weights)

    feature_gaps: list[str] = []
    form_scores = _form_scores(prior_window, drivers, feature_gaps)
    constructor_scores = _constructor_scores(prior_rounds[-1] if prior_rounds else None)
    circuit_fit_scores = _circuit_fit_scores(project_root, target_round, feature_gaps)
    evidence_scores, evidence_gaps, evidence_exclusion_summary = _evidence_scores(
        project_root=project_root,
        target_round=target_round,
        drivers=drivers,
        config=config,
    )
    reliability_scores, reliability_methods = _reliability_scores(
        prior_rounds, drivers, registry, target_round, feature_gaps
    )
    track_profile_scores = _track_profile_scores(
        project_root=project_root,
        prior_rounds=prior_rounds,
        drivers=drivers,
        target_profile=track_profile,
        config=config,
    )

    rows = []
    for driver in drivers:
        driver_id = str(driver["driver_id"])
        team_id = str(driver["team_id"])
        row_gaps = _component_gaps(
            form_score=form_scores.get(driver_id),
            constructor_score=constructor_scores.get(team_id),
            circuit_fit_score=circuit_fit_scores.get(driver_id),
            evidence_score=evidence_scores.get(driver_id),
            reliability_score=reliability_scores.get(driver_id),
            track_profile_score=track_profile_scores.get(driver_id),
            track_profile_method=config.track_profile_method,
            has_eligible_evidence=bool(
                evidence_exclusion_summary.get("eligible_count", 0)
            ),
        )
        rows.append(
            {
                "feature_set_id": FEATURE_SET_ID,
                "season": season,
                "target_round": target_round,
                "driver_id": driver_id,
                "driver_name": driver["display_name"],
                "constructor_id": team_id,
                "constructor_name": teams.get(team_id, team_id),
                "form_score": form_scores.get(driver_id),
                "constructor_score": constructor_scores.get(team_id),
                "circuit_fit_score": circuit_fit_scores.get(driver_id),
                "evidence_score": evidence_scores.get(driver_id),
                "reliability_score": reliability_scores.get(driver_id),
                "reliability_method": reliability_methods.get(driver_id),
                "seat_note": seat_notes.get(driver_id),
                "track_profile_score": track_profile_scores.get(driver_id),
                "track_profile_method": config.track_profile_method,
                "track_profile": track_profile,
                "evidence_method": config.evidence_method,
                "weights": dict(resolved_weights),
                "component_gaps": row_gaps,
            }
        )

    all_gaps = _unique([*feature_gaps, *evidence_gaps])
    return {
        "feature_set_id": FEATURE_SET_ID,
        "season": season,
        "target_round": target_round,
        "target_event": {
            "round": target_round,
            "race_name": target_event.get("race_name") if target_event else None,
            "circuit_id": target_event.get("circuit_id") if target_event else None,
            "pre_qualifying_cutoff": target_event.get("pre_qualifying_cutoff")
            if target_event
            else None,
        },
        "config": {
            "form_window": config.form_window,
            "evidence_method": config.evidence_method,
            "track_profile_method": config.track_profile_method,
            "weights": dict(resolved_weights),
        },
        "track_profile": track_profile,
        "rows": rows,
        "evidence_policy": EVIDENCE_POLICY,
        "evidence_gaps": all_gaps,
        "evidence_exclusion_summary": evidence_exclusion_summary,
    }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _grid_drivers(grid: dict[str, Any]) -> list[dict[str, Any]]:
    return list(grid.get("drivers", []))


def _grid_teams(grid: dict[str, Any]) -> dict[str, str]:
    return {
        str(item["team_id"]): str(item["display_name"])
        for item in grid.get("teams", [])
    }


def _round_by_number(
    rounds: list[dict[str, Any]], target_round: int
) -> dict[str, Any] | None:
    return next((item for item in rounds if int(item["round"]) == target_round), None)


def _form_scores(
    prior_rounds: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
    evidence_gaps: list[str],
) -> dict[str, float | None]:
    if not prior_rounds:
        evidence_gaps.append("no_prior_rounds_for_form")
        return {str(driver["driver_id"]): None for driver in drivers}
    scores: dict[str, list[float]] = {
        str(driver["driver_id"]): [] for driver in drivers
    }
    for round_payload in prior_rounds:
        positions, field_size = _qualifying_positions(round_payload)
        for driver_id, position in positions.items():
            if driver_id in scores and position is not None and field_size > 0:
                scores[driver_id].append((field_size + 1 - position) / field_size)
    return {
        driver_id: mean(values) if values else None
        for driver_id, values in scores.items()
    }


def _qualifying_positions(round_payload: dict[str, Any]) -> tuple[dict[str, int], int]:
    qualifying = round_payload.get("qualifying_results", {})
    race = round_payload.get("race_results", {})
    qualifying_records = qualifying.get("records", []) or []
    race_records = race.get("records", []) or []
    field_size = max(
        int(qualifying.get("row_count") or 0),
        int(race.get("row_count") or 0),
        len(qualifying_records),
        len(race_records),
    )
    positions = {
        str(item["driver_id"]): int(item["position"])
        for item in qualifying_records
        if item.get("driver_id") and item.get("position") is not None
    }
    for item in race_records:
        driver_id = item.get("driver_id")
        grid = item.get("grid")
        if (
            driver_id
            and driver_id not in positions
            and isinstance(grid, int)
            and grid > 0
        ):
            positions[str(driver_id)] = grid
    return positions, field_size


def _constructor_scores(
    round_payload: dict[str, Any] | None,
) -> dict[str, float | None]:
    if round_payload is None:
        return {}
    standings = round_payload.get("constructor_standings", {}).get("records", []) or []
    max_points = max(
        (float(item.get("points") or 0.0) for item in standings), default=0.0
    )
    if max_points <= 0:
        return {
            str(item["constructor_id"]): None
            for item in standings
            if item.get("constructor_id")
        }
    return {
        str(item["constructor_id"]): float(item.get("points") or 0.0) / max_points
        for item in standings
        if item.get("constructor_id")
    }


def _circuit_fit_scores(
    project_root: Path,
    target_round: int,
    evidence_gaps: list[str],
) -> dict[str, float | None]:
    path = _round_file(project_root / CIRCUIT_HISTORY_DIR, target_round)
    if path is None:
        evidence_gaps.append(f"missing_circuit_history_round_{target_round:02d}")
        return {}
    payload = _load_json(path)
    scores: dict[str, float | None] = {}
    for item in payload.get("driver_history_scores", []) or []:
        driver_id = str(item["driver_id"])
        if int(item.get("coverage_count") or 0) <= 0:
            scores[driver_id] = None
        else:
            scores[driver_id] = _optional_float(item.get("qualifying_score"))
    return scores


def _evidence_scores(
    *,
    project_root: Path,
    target_round: int,
    drivers: list[dict[str, Any]],
    config: QualifyingFeatureConfig,
) -> tuple[dict[str, float | None], list[str], dict[str, Any]]:
    context = _eligible_agent_evidence(project_root, target_round)
    gaps = list(context["gaps"])
    exclusion_summary = dict(context["exclusion_summary"])
    eligible_items = context["eligible_items"]

    if config.evidence_method == "directional":
        values = _target_values_from_items(eligible_items, value_key="direction")
        scores = _scores_from_target_values(values, drivers, ordinal=False)
    elif config.evidence_method == "ordinal":
        residual_path = _round_file(
            project_root / SUBJECTIVE_RESIDUALS_DIR, target_round
        )
        if residual_path is None:
            gaps.append("ordinal_residuals_missing_fallback_directional")
            values = _target_values_from_items(eligible_items, value_key="direction")
            scores = _scores_from_target_values(values, drivers, ordinal=False)
        else:
            residual_entries, residual_gaps, residual_exclusions = (
                _eligible_residual_entries(
                    residual_path,
                    target_round=target_round,
                    cutoff=context["cutoff"],
                    eligible_evidence_ids=set(context["eligible_evidence_ids"]),
                    all_evidence_ids=set(context["all_evidence_ids"]),
                )
            )
            gaps.extend(residual_gaps)
            _merge_counts(exclusion_summary, residual_exclusions)
            values = _target_values_from_items(
                residual_entries, value_key="ordinal_signal"
            )
            scores = _scores_from_target_values(values, drivers, ordinal=True)
    else:  # pragma: no cover - QualifyingFeatureConfig validates this branch.
        raise ValueError(f"unknown evidence_method: {config.evidence_method}")

    if not eligible_items:
        _append_unique(gaps, "no_eligible_qualifying_evidence")
    exclusion_summary["eligible_count"] = len(eligible_items)
    exclusion_summary["eligible_evidence_ids"] = sorted(
        context["eligible_evidence_ids"]
    )
    for reason in sorted(
        key
        for key in exclusion_summary
        if key not in {"eligible_count", "eligible_evidence_ids"}
    ):
        _append_unique(gaps, f"evidence_exclusion_{reason}")
    return scores, _unique(gaps), exclusion_summary


def _eligible_agent_evidence(project_root: Path, target_round: int) -> dict[str, Any]:
    payload = _load_json(project_root / AGENT_EVIDENCE_PATH)
    event = next(
        (
            item
            for item in payload.get("events", [])
            if int(item.get("event_round", -1)) == target_round
        ),
        None,
    )
    if event is None:
        return {
            "cutoff": None,
            "eligible_items": [],
            "eligible_evidence_ids": [],
            "all_evidence_ids": [],
            "gaps": [
                f"no_agent_evidence_round_{target_round:02d}",
                "no_eligible_qualifying_evidence",
            ],
            "exclusion_summary": {"event_missing": 1},
        }

    cutoff = _parse_timestamp(event.get("pre_qualifying_cutoff"))
    gaps: list[str] = []
    exclusion_summary: dict[str, int] = {}
    if cutoff is None:
        gaps.append("invalid_pre_qualifying_cutoff")
        _increment(exclusion_summary, "invalid_pre_qualifying_cutoff")

    eligible_items: list[dict[str, Any]] = []
    eligible_ids: list[str] = []
    all_ids: list[str] = []
    for item in event.get("evidence", []) or []:
        evidence_id = str(item.get("evidence_id") or "")
        if evidence_id:
            all_ids.append(evidence_id)
        reasons: list[str] = []
        if int(item.get("event_round", -1)) != target_round:
            reasons.append("event_round_mismatch")
        published = _parse_timestamp(item.get("published_on"))
        retrieved = _parse_timestamp(item.get("retrieved_on"))
        if published is None:
            reasons.append("invalid_published_timestamp")
        elif cutoff is not None and published > cutoff:
            reasons.append("published_after_cutoff")
        if retrieved is None:
            reasons.append("invalid_retrieved_timestamp")
        elif cutoff is not None and retrieved > cutoff:
            reasons.append("retrieved_after_cutoff")
        if "qualifying" not in (item.get("session_scope") or []):
            reasons.append("qualifying_scope_missing")
        if item.get("model_usage") != "feature":
            reasons.append("model_usage_not_feature")
        if reasons:
            for reason in reasons:
                _increment(exclusion_summary, reason)
            continue
        eligible_items.append(item)
        if evidence_id:
            eligible_ids.append(evidence_id)

    return {
        "cutoff": cutoff,
        "eligible_items": eligible_items,
        "eligible_evidence_ids": eligible_ids,
        "all_evidence_ids": all_ids,
        "gaps": gaps,
        "exclusion_summary": exclusion_summary,
    }


def _eligible_residual_entries(
    path: Path,
    *,
    target_round: int,
    cutoff: datetime | None,
    eligible_evidence_ids: set[str],
    all_evidence_ids: set[str],
) -> tuple[list[dict[str, Any]], list[str], dict[str, int]]:
    payload = _load_json(path)
    exclusions: dict[str, int] = {}
    gaps: list[str] = []
    if int(payload.get("event_round", -1)) != target_round:
        return (
            [],
            ["residual_event_round_mismatch"],
            {"residual_event_round_mismatch": 1},
        )

    valid: list[dict[str, Any]] = []
    for entry in payload.get("entries", []) or []:
        reasons: list[str] = []
        if entry.get("event_round", target_round) != target_round:
            reasons.append("residual_event_round_mismatch")
        if payload.get("frozen") is not True:
            reasons.append("residual_not_frozen")
        frozen_at = _parse_timestamp(payload.get("frozen_at"))
        if frozen_at is None:
            reasons.append("invalid_residual_frozen_at")
        elif cutoff is not None and frozen_at > cutoff:
            reasons.append("residual_frozen_after_cutoff")
        if "qualifying" not in (entry.get("session_scope") or []):
            reasons.append("residual_scope_missing")
        references = entry.get("evidence_ids")
        if not isinstance(references, list) or not references:
            reasons.append("unresolved_evidence_reference")
        else:
            for reference in references:
                reference_id = str(reference)
                if reference_id not in all_evidence_ids:
                    reasons.append("unresolved_evidence_reference")
                elif reference_id not in eligible_evidence_ids:
                    reasons.append("ineligible_evidence_reference")
        if reasons:
            for reason in set(reasons):
                _increment(exclusions, reason)
            continue
        valid.append(entry)

    if not valid:
        gaps.append("no_eligible_qualifying_residual")
    for reason in sorted(exclusions):
        _append_unique(gaps, f"residual_exclusion_{reason}")
    return valid, gaps, exclusions


def _target_values_from_items(
    items: list[dict[str, Any]], *, value_key: str
) -> dict[tuple[str, str], list[float]]:
    values: dict[tuple[str, str], list[float]] = {}
    for item in items:
        target = item.get("applies_to") or item.get("target") or {}
        target_type = target.get("type")
        ids = target.get("ids") or []
        confidence = float(item.get("confidence") or 0.0)
        raw_value = item.get(value_key)
        value = (
            _direction_value(raw_value)
            if value_key == "direction"
            else _optional_float(raw_value)
        )
        if target_type not in {"driver", "team"} or value is None:
            continue
        for target_id in ids:
            values.setdefault((str(target_type), str(target_id)), []).append(
                value * confidence
            )
    return values


def _scores_from_target_values(
    values: dict[tuple[str, str], list[float]],
    drivers: list[dict[str, Any]],
    *,
    ordinal: bool,
) -> dict[str, float | None]:
    denominator = 4.0 if ordinal else 2.0
    scores: dict[str, float | None] = {}
    for driver in drivers:
        driver_id = str(driver["driver_id"])
        team_id = str(driver["team_id"])
        driver_values = [
            *values.get(("driver", driver_id), []),
            *values.get(("team", team_id), []),
        ]
        if not driver_values:
            scores[driver_id] = None
            continue
        scores[driver_id] = _clamp(
            0.5 + (sum(driver_values) / len(driver_values)) / denominator
        )
    return scores


def _load_seat_registry(project_root: Path) -> dict[str, Any]:
    path = project_root / SEAT_CHANGES_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"seat registry missing: {path} (fail-closed per "
            "DEC-CONTROL-SEAT-ROTATION-UNLOCK-001)"
        )
    return _load_json(path)


def _apply_seat_overrides(
    grid: dict[str, Any],
    registry: dict[str, Any],
    target_round: int,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Project the manual seat registry onto the season-start grid snapshot.

    Returns the driver rows valid at ``target_round`` (exits removed,
    transfers moved, entries appended) plus per-driver seat notes for
    row-level audit. Event semantics come from the manual registry, which is
    the authority; the field-diff cross-check lives in the collection layer.
    """
    grid_drivers = _grid_drivers(grid)
    by_id = {str(d["driver_id"]): dict(d) for d in grid_drivers}
    notes: dict[str, str] = {}
    for event in registry.get("events", []):
        if int(event["round"]) > target_round:
            continue
        did = str(event["driver_id"])
        etype = str(event["type"])
        if etype == "exit":
            by_id.pop(did, None)
            notes[did] = f"exit@R{event['round']}"
        elif etype == "transfer":
            row = by_id.get(did)
            if row is None:
                raise ValueError(f"seat transfer for unknown driver {did}")
            row["team_id"] = str(event["to_constructor"])
            notes[did] = f"transfer@R{event['round']}->{row['team_id']}"
        elif etype == "entry":
            if did in by_id:
                raise ValueError(f"seat entry for already-present driver {did}")
            if not event.get("display_name"):
                raise ValueError(f"seat entry {did} lacks display_name")
            by_id[did] = {
                "driver_id": did,
                "display_name": str(event["display_name"]),
                "team_id": str(event["to_constructor"]),
            }
            notes[did] = f"entry@R{event['round']}->{by_id[did]['team_id']}"
        else:
            raise ValueError(f"unknown seat event type {etype}")
    kept = [by_id[str(d["driver_id"])] for d in grid_drivers if str(d["driver_id"]) in by_id]
    new_ids = {str(d["driver_id"]) for d in grid_drivers}
    kept += [row for did, row in by_id.items() if did not in new_ids]
    return kept, notes


def _previous_constructors(registry: dict[str, Any], target_round: int) -> dict[str, str]:
    """driver_id -> most recent constructor before the current seat (<= target)."""
    prev: dict[str, str] = {}
    for event in registry.get("events", []):
        if int(event["round"]) > target_round:
            continue
        etype = str(event["type"])
        if etype in {"exit", "transfer"} and event.get("from_constructor"):
            prev[str(event["driver_id"])] = str(event["from_constructor"])
    return prev


def _reliability_scores(
    prior_rounds: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
    registry: dict[str, Any],
    target_round: int,
    evidence_gaps: list[str],
) -> tuple[dict[str, float | None], dict[str, str]]:
    """Finish rate per (driver, constructor) over the full prior season.

    Seat-rotation semantics (DEC-CONTROL-SEAT-ROTATION-UNLOCK-001): the score
    means "this driver at this team". Direct value requires >=3 starts at the
    current team; below that the value is scaled from the previous team as
    ``team_rate_cur * (driver_rate_prev / team_rate_prev)`` with full-season
    windows on both sides. Drivers without a previous team return None.
    """
    methods: dict[str, str] = {}
    if not prior_rounds:
        evidence_gaps.append("no_prior_rounds_for_reliability")
        return {str(d["driver_id"]): None for d in drivers}, methods
    starts: dict[tuple[str, str], int] = {}
    failures: dict[tuple[str, str], int] = {}
    for round_payload in prior_rounds:
        for item in round_payload.get("race_results", {}).get("records", []) or []:
            did = str(item.get("driver_id") or "")
            cid = str(item.get("constructor_id") or "")
            if not did or not cid:
                continue
            key = (did, cid)
            starts[key] = starts.get(key, 0) + 1
            if _is_non_finish(item.get("status")):
                failures[key] = failures.get(key, 0) + 1

    def _rate(keys: list[tuple[str, str]]) -> tuple[float | None, int]:
        total = sum(starts.get(k, 0) for k in keys)
        fails = sum(failures.get(k, 0) for k in keys)
        return ((1.0 - fails / total), total) if total else (None, 0)

    def _team_keys(cid: str) -> list[tuple[str, str]]:
        return [key for key in starts if key[1] == cid]

    prev_ctors = _previous_constructors(registry, target_round)
    scores: dict[str, float | None] = {}
    for driver in drivers:
        did = str(driver["driver_id"])
        cur = str(driver["team_id"])
        cur_rate, cur_starts = _rate([(did, cur)])
        if cur_starts >= MIN_RELIABILITY_STARTS:
            scores[did] = cur_rate
            methods[did] = "direct"
            continue
        prev = prev_ctors.get(did)
        if prev is None:
            evidence_gaps.append(f"reliability_no_prev_team_{did}")
            scores[did] = None
            methods[did] = "missing_no_prev_team"
            continue
        team_cur_rate, _ = _rate(_team_keys(cur))
        driver_prev_rate, _ = _rate([(did, prev)])
        team_prev_rate, _ = _rate(_team_keys(prev))
        if (
            team_cur_rate is None
            or driver_prev_rate is None
            or not team_prev_rate
        ):
            evidence_gaps.append(f"reliability_scale_unavailable_{did}")
            scores[did] = None
            methods[did] = "missing_scale_unavailable"
            continue
        scores[did] = _clamp(team_cur_rate * (driver_prev_rate / team_prev_rate))
        methods[did] = "scaled"
    return scores, methods


def _track_profile_scores(
    *,
    project_root: Path,
    prior_rounds: list[dict[str, Any]],
    drivers: list[dict[str, Any]],
    target_profile: dict[str, Any] | None,
    config: QualifyingFeatureConfig,
) -> dict[str, float | None]:
    if config.track_profile_method == "interaction":
        return {str(driver["driver_id"]): None for driver in drivers}
    if config.track_profile_method != "independent":
        raise ValueError(f"unknown track_profile_method: {config.track_profile_method}")
    if not target_profile or not target_profile.get("speed_type"):
        return {str(driver["driver_id"]): None for driver in drivers}
    speed_type = str(target_profile["speed_type"])
    profiles = _track_profiles(project_root)
    matching_rounds = [
        item
        for item in prior_rounds
        if (_track_profile_for_event(item, profiles) or {}).get("speed_type")
        == speed_type
    ]
    return _form_scores(matching_rounds, drivers, evidence_gaps=[])


def _track_profile_for_round(
    project_root: Path,
    target_event: dict[str, Any] | None,
    target_round: int,
) -> dict[str, Any] | None:
    if target_event is None:
        circuit_path = _round_file(project_root / CIRCUIT_HISTORY_DIR, target_round)
        if circuit_path is None:
            return None
        target_event = _load_json(circuit_path)
    return _track_profile_for_event(target_event, _track_profiles(project_root))


def _track_profiles(project_root: Path) -> list[dict[str, Any]]:
    profiles_payload = _load_json(project_root / TRACK_PROFILE_PATH)
    return list(profiles_payload.get("profiles", []) or [])


def _track_profile_for_event(
    event: dict[str, Any],
    profiles: list[dict[str, Any]],
) -> dict[str, Any] | None:
    circuit_id = event.get("circuit_id")
    race_name = event.get("race_name")
    for profile in profiles:
        if circuit_id and profile.get("circuit_id") == circuit_id:
            return dict(profile)
        if race_name and profile.get("race_name") == race_name:
            return dict(profile)
    return None


def _round_file(directory: Path, target_round: int) -> Path | None:
    matches = sorted(directory.glob(f"round_{target_round:02d}_*.json"))
    return matches[0] if matches else None


def _component_gaps(
    *,
    form_score: float | None,
    constructor_score: float | None,
    circuit_fit_score: float | None,
    evidence_score: float | None,
    reliability_score: float | None,
    track_profile_score: float | None,
    track_profile_method: str,
    has_eligible_evidence: bool,
) -> list[str]:
    gaps: list[str] = []
    if form_score is None:
        gaps.append("missing_form_score")
    if constructor_score is None:
        gaps.append("missing_constructor_score")
    if circuit_fit_score is None:
        gaps.append("no_same_circuit_history")
    if evidence_score is None:
        gaps.append(
            "missing_qualifying_evidence_signal"
            if has_eligible_evidence
            else "no_eligible_qualifying_evidence"
        )
    if reliability_score is None:
        gaps.append("missing_reliability_score")
    if track_profile_method == "independent" and track_profile_score is None:
        gaps.append("no_same_track_profile_history")
    return gaps


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _direction_value(value: Any) -> float | None:
    if value == "positive":
        return 1.0
    if value == "negative":
        return -1.0
    if value == "neutral":
        return 0.0
    return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_non_finish(status: Any) -> bool:
    text = str(status or "").strip().lower()
    if text == "finished" or text.startswith("+") or text == "lapped":
        return False
    return True


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _increment(mapping: dict[str, int], key: str) -> None:
    mapping[key] = mapping.get(key, 0) + 1


def _merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + value


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
