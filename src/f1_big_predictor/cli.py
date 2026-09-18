from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from .data.actuals import collect_completed_season_actuals, merge_actuals_payload
from .data.adapters import get_adapter, payload_from_archive_cache
from .data.archive import RawArchive, archive_dataset_key
from .data.circuit_history import collect_circuit_history
from .experiments import TargetRunSpec, build_run_manifest, run_target, write_run_manifest
from .targets.qualifying import QualifyingTargetConfig, QualifyingTargetInputs, predict_qualifying_target
from .targets.qualifying.evaluate import evaluate_qualifying_target
from .targets.qualifying.search_space import search_space as qualifying_search_space
from .targets.race import RaceTargetConfig, RaceTargetInputs, predict_race_target
from .targets.race.evaluate import evaluate_race_target
from .targets.race.search_space import search_space as race_search_space
from .targets.sprint_qualifying import (
    SprintQualifyingTargetConfig,
    SprintQualifyingTargetInputs,
    predict_sprint_qualifying_target,
)
from .targets.sprint_qualifying.evaluate import evaluate_sprint_qualifying_target
from .targets.sprint_qualifying.search_space import search_space as sprint_qualifying_search_space
from .targets.sprint_race import (
    SprintRaceAsOfProfile,
    SprintRaceTargetConfig,
    SprintRaceTargetInputs,
    predict_sprint_race_target,
)
from .targets.sprint_race.evaluate import evaluate_sprint_race_target
from .targets.sprint_race.search_space import search_space as sprint_race_search_space


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    project_root = Path(args.project_root).resolve()

    if args.command == "source-catalog":
        return _print(_load_source_catalog(project_root), args.print_json)
    if args.command == "fetch-source":
        return _fetch_source(args, project_root)
    if args.command == "collect-season-actuals":
        if args.merge_existing and not args.output:
            raise ValueError("--merge-existing requires --output")
        if args.merge_existing and not (args.target_rounds or args.targets):
            raise ValueError("--merge-existing requires --round or --target")
        if (
            args.merge_existing
            and (
                not args.output.exists()
                or args.output.stat().st_size == 0
            )
        ):
            raise ValueError("--merge-existing requires an existing non-empty --output")
        if (
            args.output
            and args.output.exists()
            and args.output.stat().st_size > 0
            and not args.merge_existing
            and (args.target_rounds or args.targets)
        ):
            raise ValueError(
                "targeted generation would overwrite an existing output; "
                "use --merge-existing or choose a new --output path"
            )

        payload = collect_completed_season_actuals(
            season=args.season,
            as_of_date=date.fromisoformat(args.as_of_date),
            project_root=project_root,
            archive_week_id=args.archive_week_id,
            output_path=None if args.merge_existing else args.output,
            target_rounds=args.target_rounds,
            targets=args.targets,
        )
        if args.merge_existing:
            existing_payload = json.loads(args.output.read_text(encoding="utf-8"))
            payload = merge_actuals_payload(
                existing_payload,
                payload,
                target_rounds=args.target_rounds,
                targets=args.targets,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return _print(payload, args.print_json)
    if args.command == "collect-circuit-history":
        payload = collect_circuit_history(
            season=args.season,
            target_round=args.target_round,
            project_root=project_root,
            lookback_years=args.lookback_years,
            archive_week_id=args.archive_week_id,
            output_path=args.output,
        )
        return _print(payload, args.print_json)
    if args.command == "write-run-manifest":
        manifest = build_run_manifest(
            run_id=args.run_id,
            target_id=args.target_id,
            model_id=args.model_id,
            model_config=_json_object(args.model_config),
            feature_set_id=args.feature_set_id,
            search_space_id=args.search_space_id,
            as_of_profile=_json_object(args.as_of_profile),
            evaluation_window=_json_object(args.evaluation_window),
            input_assets=_json_list(args.input_assets),
            output_files=args.output_file,
            evidence_gaps=args.evidence_gap,
            validation_commands=args.validation_command,
        )
        path = write_run_manifest(project_root=project_root, manifest=manifest, overwrite=args.overwrite)
        return _print({"manifest_path": str(path), "manifest": manifest}, args.print_json)
    if args.command == "search-target":
        return _print(_target_search_space(args.target_id), args.print_json)
    if args.command == "evaluate-target":
        evaluation = _evaluate_target(args)
        return _print(asdict(evaluation), args.print_json)
    if args.command == "run-target":
        result = _run_target_command(args, project_root)
        return _print(
            {
                "target_id": result.target_id,
                "run_id": result.run_id,
                "run_dir": str(result.run_dir),
                "manifest_path": str(result.manifest_path),
                "output_files": result.output_files,
            },
            args.print_json,
        )

    parser.error(f"unknown command: {args.command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="f1-predict")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    source_catalog = subparsers.add_parser("source-catalog")
    source_catalog.add_argument("--print-json", action="store_true")

    fetch = subparsers.add_parser("fetch-source")
    fetch.add_argument("--week-id", required=True)
    fetch.add_argument("--source", required=True)
    fetch.add_argument("--dataset", required=True)
    fetch.add_argument("--param", action="append", default=[])
    fetch.add_argument("--token")
    fetch.add_argument("--print-json", action="store_true")

    actuals = subparsers.add_parser("collect-season-actuals")
    actuals.add_argument("--season", type=int, required=True)
    actuals.add_argument("--as-of-date", required=True)
    actuals.add_argument("--archive-week-id")
    actuals.add_argument("--output", type=Path)
    actuals.add_argument(
        "--round",
        dest="target_rounds",
        type=int,
        action="append",
        help="Limit generation to one or more championship rounds; repeat the flag.",
    )
    actuals.add_argument(
        "--target",
        dest="targets",
        action="append",
        choices=("qualifying", "race", "sprint", "sprint_qualifying"),
        help="Generate one or more actual targets; repeat the flag.",
    )
    actuals.add_argument(
        "--merge-existing",
        action="store_true",
        help="Merge selected rounds/targets into an existing --output instead of replacing it.",
    )
    actuals.add_argument("--print-json", action="store_true")

    history = subparsers.add_parser("collect-circuit-history")
    history.add_argument("--season", type=int, required=True)
    history.add_argument("--target-round", type=int, required=True)
    history.add_argument("--lookback-years", type=int, default=5)
    history.add_argument("--archive-week-id")
    history.add_argument("--output", type=Path)
    history.add_argument("--print-json", action="store_true")

    manifest = subparsers.add_parser("write-run-manifest")
    manifest.add_argument("--target-id", required=True)
    manifest.add_argument("--run-id", required=True)
    manifest.add_argument("--model-id", required=True)
    manifest.add_argument("--model-config", default="{}")
    manifest.add_argument("--feature-set-id", required=True)
    manifest.add_argument("--search-space-id")
    manifest.add_argument("--as-of-profile", required=True)
    manifest.add_argument("--evaluation-window", required=True)
    manifest.add_argument("--input-assets", default="[]")
    manifest.add_argument("--output-file", action="append", default=[])
    manifest.add_argument("--evidence-gap", action="append", default=[])
    manifest.add_argument("--validation-command", action="append", default=[])
    manifest.add_argument("--overwrite", action="store_true")
    manifest.add_argument("--print-json", action="store_true")

    search_target = subparsers.add_parser("search-target")
    search_target.add_argument("--target-id", required=True)
    search_target.add_argument("--print-json", action="store_true")

    evaluate_target = subparsers.add_parser("evaluate-target")
    evaluate_target.add_argument("--target-id", required=True)
    evaluate_target.add_argument("--predicted-driver-id", action="append", required=True)
    evaluate_target.add_argument("--actual-driver-id", action="append", required=True)
    evaluate_target.add_argument("--lap-time-mae", type=float)
    evaluate_target.add_argument("--print-json", action="store_true")

    run = subparsers.add_parser("run-target")
    run.add_argument("--target-id", required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--input-json", type=Path, required=True)
    run.add_argument("--model-id")
    run.add_argument("--as-of-profile", required=True)
    run.add_argument("--evaluation-window", required=True)
    run.add_argument("--validation-command", action="append", default=[])
    run.add_argument("--overwrite", action="store_true")
    run.add_argument("--print-json", action="store_true")

    return parser


def _fetch_source(args: argparse.Namespace, project_root: Path) -> int:
    params = _params(args.param)
    archive = RawArchive(project_root)
    cached = archive.read_latest_for_request(
        week_id=args.week_id,
        source_id=args.source,
        dataset=args.dataset,
        params=params,
    )
    if cached is not None:
        payload = payload_from_archive_cache(cached, dataset=args.dataset)
        return _print({**asdict(cached.record), "reused_archive": True, "ok": payload.ok}, args.print_json)

    adapter = get_adapter(args.source, token=args.token)
    payload = adapter.fetch(args.dataset, params)
    record = archive.write(
        week_id=args.week_id,
        source_id=payload.source_id,
        dataset=archive_dataset_key(payload.source_id, args.dataset, params),
        url=payload.url,
        params=params,
        payload=payload.body,
        extension=payload.extension(),
        content_type=payload.content_type,
        status_code=payload.status_code,
        ok=payload.ok,
        error=payload.error,
    )
    return _print({**asdict(record), "reused_archive": False}, args.print_json)


def _load_source_catalog(project_root: Path) -> dict[str, Any]:
    return json.loads((project_root / "data" / "source_catalog.json").read_text(encoding="utf-8"))


def _params(items: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--param must be key=value, got {item!r}")
        key, value = item.split("=", 1)
        params[key] = value
    return params


def _json_object(value: str) -> dict[str, Any]:
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def _json_list(value: str) -> list[dict[str, Any]]:
    data = json.loads(value)
    if not isinstance(data, list):
        raise ValueError("expected JSON list")
    if not all(isinstance(item, dict) for item in data):
        raise ValueError("expected JSON list of objects")
    return data


def _run_target_command(args: argparse.Namespace, project_root: Path):  # type: ignore[no-untyped-def]
    payload = _json_object_file(args.input_json)
    as_of_profile = _json_object(args.as_of_profile)
    config, inputs, predict_fn, search_space = _target_components(args.target_id, payload, args.model_id, as_of_profile)
    spec = TargetRunSpec(
        project_root=project_root,
        target_id=args.target_id,
        run_id=args.run_id,
        model_id=config.model_id,
        model_config=asdict(config),
        feature_set_id=config.feature_set_id,
        search_space_id=config.search_space_id,
        as_of_profile=as_of_profile,
        evaluation_window=_json_object(args.evaluation_window),
        input_assets=[{"path": str(args.input_json)}],
        validation_commands=args.validation_command,
    )
    return run_target(
        spec=spec,
        predict_fn=predict_fn,
        inputs=inputs,
        config=config,
        search_space=search_space,
        overwrite=args.overwrite,
    )


def _target_components(target_id: str, payload: dict[str, Any], model_id: str | None, as_of_profile: dict[str, Any]):  # type: ignore[no-untyped-def]
    if target_id == "race":
        config = RaceTargetConfig(model_id=model_id or RaceTargetConfig().model_id)
        return config, RaceTargetInputs(driver_features=_driver_features(payload), evidence_gaps=_evidence_gaps(payload)), predict_race_target, race_search_space()
    if target_id == "qualifying":
        config = QualifyingTargetConfig(model_id=model_id or QualifyingTargetConfig().model_id)
        return config, QualifyingTargetInputs(driver_features=_driver_features(payload), evidence_gaps=_evidence_gaps(payload)), predict_qualifying_target, qualifying_search_space()
    if target_id == "sprint_qualifying":
        config = SprintQualifyingTargetConfig(model_id=model_id or SprintQualifyingTargetConfig().model_id)
        return (
            config,
            SprintQualifyingTargetInputs(
                driver_features=_driver_features(payload),
                is_sprint_weekend=_sprint_weekend_flag(as_of_profile),
                evidence_gaps=_evidence_gaps(payload),
            ),
            predict_sprint_qualifying_target,
            sprint_qualifying_search_space(),
        )
    if target_id == "sprint_race":
        config = SprintRaceTargetConfig(model_id=model_id or SprintRaceTargetConfig().model_id)
        payload_profile = payload.get("as_of_profile")
        if payload_profile is not None and payload_profile != as_of_profile:
            raise ValueError("sprint_race input as_of_profile must match --as-of-profile")
        profile = as_of_profile
        if not isinstance(profile, dict):
            raise ValueError("sprint_race input as_of_profile must be an object")
        return (
            config,
            SprintRaceTargetInputs(
                driver_features=_driver_features(payload),
                as_of_profile=SprintRaceAsOfProfile(
                    is_sprint_weekend=_sprint_weekend_flag(profile),
                    sprint_qualifying_available=bool(profile.get("sprint_qualifying_available", False)),
                    notes=tuple(profile.get("notes", ())),
                ),
                evidence_gaps=_evidence_gaps(payload),
            ),
            predict_sprint_race_target,
            sprint_race_search_space(),
        )
    raise ValueError(f"unsupported target_id: {target_id}")


def _target_search_space(target_id: str) -> dict[str, object]:
    if target_id == "race":
        return race_search_space()
    if target_id == "qualifying":
        return qualifying_search_space()
    if target_id == "sprint_qualifying":
        return sprint_qualifying_search_space()
    if target_id == "sprint_race":
        return sprint_race_search_space()
    raise ValueError(f"unsupported target_id: {target_id}")


def _evaluate_target(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    predicted = args.predicted_driver_id
    actual = args.actual_driver_id
    if args.target_id == "race":
        return evaluate_race_target(predicted_driver_ids=predicted, actual_driver_ids=actual)
    if args.target_id == "sprint_race":
        return evaluate_sprint_race_target(predicted_driver_ids=predicted, actual_driver_ids=actual)
    if args.target_id == "qualifying":
        return evaluate_qualifying_target(predicted_driver_ids=predicted, actual_driver_ids=actual, lap_time_mae=args.lap_time_mae)
    if args.target_id == "sprint_qualifying":
        return evaluate_sprint_qualifying_target(predicted_driver_ids=predicted, actual_driver_ids=actual, lap_time_mae=args.lap_time_mae)
    raise ValueError(f"unsupported target_id: {args.target_id}")


def _json_object_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected JSON object file")
    return data


def _driver_features(payload: dict[str, Any]) -> list[dict[str, Any]]:
    features = payload.get("driver_features", payload.get("features", []))
    if not isinstance(features, list) or not all(isinstance(item, dict) for item in features):
        raise ValueError("target input driver_features must be a list of objects")
    return features


def _evidence_gaps(payload: dict[str, Any]) -> list[str]:
    gaps = payload.get("evidence_gaps", [])
    if not isinstance(gaps, list) or not all(isinstance(item, str) for item in gaps):
        raise ValueError("evidence_gaps must be a string list")
    return gaps


def _sprint_weekend_flag(as_of_profile: dict[str, Any]) -> bool:
    if "is_sprint_weekend" not in as_of_profile:
        raise ValueError("sprint target as_of_profile.is_sprint_weekend is required")
    return bool(as_of_profile["is_sprint_weekend"])


def _print(payload: dict[str, Any], print_json: bool) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2 if not print_json else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
