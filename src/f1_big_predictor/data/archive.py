from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SLUG_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class ArchiveRecord:
    week_id: str
    source_id: str
    dataset: str
    url: str
    params: dict[str, str]
    retrieved_at: str
    status_code: int | None
    content_type: str | None
    payload_sha256: str
    ok: bool
    error: str | None
    data_path: str
    meta_path: str


@dataclass(frozen=True)
class CachedArchivePayload:
    record: ArchiveRecord
    body: bytes


class RawArchive:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def write(
        self,
        *,
        week_id: str,
        source_id: str,
        dataset: str,
        url: str,
        params: dict[str, str] | None,
        payload: bytes | str | dict[str, Any] | list[Any],
        extension: str,
        content_type: str | None,
        status_code: int | None,
        ok: bool,
        error: str | None = None,
    ) -> ArchiveRecord:
        payload_bytes = _payload_to_bytes(payload)
        digest = hashlib.sha256(payload_bytes).hexdigest()
        retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        safe_dataset = _slug(dataset)
        safe_source = _slug(source_id)
        safe_week = _slug(week_id)
        extension = extension.lstrip(".") or "bin"
        filename = f"{retrieved_at}_{safe_dataset}_{digest[:8]}.{extension}"
        directory = self.project_root / "data" / "raw" / safe_week / safe_source
        directory.mkdir(parents=True, exist_ok=True)

        data_path = directory / filename
        meta_path = directory / f"{filename}.meta.json"
        data_path.write_bytes(payload_bytes)

        record = ArchiveRecord(
            week_id=week_id,
            source_id=source_id,
            dataset=dataset,
            url=url,
            params=params or {},
            retrieved_at=retrieved_at,
            status_code=status_code,
            content_type=content_type,
            payload_sha256=digest,
            ok=ok,
            error=error,
            data_path=str(data_path),
            meta_path=str(meta_path),
        )
        meta_path.write_text(
            json.dumps(asdict(record), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return record

    def read_latest(
        self,
        *,
        week_id: str,
        source_id: str,
        dataset: str,
        params: dict[str, str] | None,
        require_ok: bool = True,
    ) -> CachedArchivePayload | None:
        directory = self.project_root / "data" / "raw" / _slug(week_id) / _slug(source_id)
        if not directory.exists():
            return None
        matches: list[CachedArchivePayload] = []
        expected_params = params or {}
        for meta_path in sorted(directory.glob("*.meta.json")):
            cached = self._read_meta_payload(meta_path)
            if cached is None:
                continue
            record = cached.record
            if record.week_id != week_id or record.source_id != source_id:
                continue
            if record.dataset != dataset or record.params != expected_params:
                continue
            if require_ok and not record.ok:
                continue
            matches.append(cached)
        if not matches:
            return None
        return max(matches, key=_cache_sort_key)

    def read_latest_for_request(
        self,
        *,
        week_id: str,
        source_id: str,
        dataset: str,
        params: dict[str, str] | None,
        require_ok: bool = True,
    ) -> CachedArchivePayload | None:
        matches: list[CachedArchivePayload] = []
        for archive_dataset in archive_dataset_keys(source_id, dataset, params):
            cached = self.read_latest(
                week_id=week_id,
                source_id=source_id,
                dataset=archive_dataset,
                params=params,
                require_ok=require_ok,
            )
            if cached is not None:
                matches.append(cached)
        if not matches:
            return None
        return max(matches, key=_cache_sort_key)

    def read_latest_for_request_any_week(
        self,
        *,
        source_id: str,
        dataset: str,
        params: dict[str, str] | None,
        require_ok: bool = True,
    ) -> CachedArchivePayload | None:
        raw_root = self.project_root / "data" / "raw"
        if not raw_root.exists():
            return None
        expected_params = params or {}
        expected_dataset = archive_dataset_key(source_id, dataset, params)
        matches: list[CachedArchivePayload] = []
        for meta_path in sorted(raw_root.glob(f"*/{_slug(source_id)}/*.meta.json")):
            cached = self._read_meta_payload(meta_path)
            if cached is None:
                continue
            record = cached.record
            if record.source_id != source_id:
                continue
            if record.dataset != expected_dataset or record.params != expected_params:
                continue
            if require_ok and not record.ok:
                continue
            matches.append(cached)
        if not matches:
            return None
        return max(matches, key=_cache_sort_key)

    def _read_meta_payload(self, meta_path: Path) -> CachedArchivePayload | None:
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            record = ArchiveRecord(**data)
            payload_path = Path(record.data_path)
            if not payload_path.exists():
                return None
            body = payload_path.read_bytes()
            digest = hashlib.sha256(body).hexdigest()
            if digest != record.payload_sha256:
                return None
            return CachedArchivePayload(record=record, body=body)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None


def _payload_to_bytes(payload: bytes | str | dict[str, Any] | list[Any]) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")


def _cache_sort_key(cached: CachedArchivePayload) -> tuple[str, int]:
    try:
        mtime_ns = Path(cached.record.meta_path).stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    return cached.record.retrieved_at, mtime_ns


def archive_dataset_key(
    source_id: str,
    dataset: str,
    params: dict[str, str] | None,
) -> str:
    params = params or {}
    if source_id == "jolpica":
        return f"{dataset}_round_{params.get('round', 'na')}"
    if source_id == "jolpica_alpha":
        if "session_id" in params:
            return f"{dataset}_{params['session_id']}"
        if "season" in params:
            return f"{dataset}_{params['season']}"
    return dataset


def archive_dataset_keys(
    source_id: str,
    dataset: str,
    params: dict[str, str] | None,
) -> list[str]:
    canonical = archive_dataset_key(source_id, dataset, params)
    if canonical == dataset:
        return [canonical]
    return [canonical, dataset]


def _slug(value: str) -> str:
    slug = SLUG_SAFE.sub("-", value.strip()).strip("-._")
    return slug or "unknown"
