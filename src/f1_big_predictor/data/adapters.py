from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


DEFAULT_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class SourcePayload:
    source_id: str
    dataset: str
    url: str
    params: dict[str, str]
    status_code: int | None
    content_type: str | None
    body: bytes
    ok: bool
    error: str | None = None

    def extension(self) -> str:
        content_type = (self.content_type or "").lower()
        if "json" in content_type:
            return "json"
        if "html" in content_type:
            return "html"
        if "pdf" in content_type:
            return "pdf"
        if "csv" in content_type:
            return "csv"
        return "txt"

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


def payload_from_archive_cache(cached: Any, *, dataset: str) -> SourcePayload:
    record = cached.record
    return SourcePayload(
        source_id=record.source_id,
        dataset=dataset,
        url=record.url,
        params=record.params,
        status_code=record.status_code,
        content_type=record.content_type,
        body=cached.body,
        ok=record.ok,
        error=record.error,
    )


class HttpSourceAdapter:
    source_id: str
    base_url: str

    def __init__(self, *, token: str | None = None, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.token = token
        self.timeout = timeout

    def fetch(self, dataset: str, params: dict[str, str] | None = None) -> SourcePayload:
        url = self.build_url(dataset, params or {})
        headers = {"Accept": "application/json", "User-Agent": "f1-big-predictor/0.1"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(url, headers=headers)

        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read()
                return SourcePayload(
                    source_id=self.source_id,
                    dataset=dataset,
                    url=url,
                    params=params or {},
                    status_code=response.status,
                    content_type=response.headers.get("content-type"),
                    body=body,
                    ok=200 <= response.status < 300,
                )
        except HTTPError as exc:
            body = exc.read()
            return SourcePayload(
                source_id=self.source_id,
                dataset=dataset,
                url=url,
                params=params or {},
                status_code=exc.code,
                content_type=exc.headers.get("content-type"),
                body=body,
                ok=False,
                error=f"HTTP {exc.code}: {exc.reason}",
            )
        except URLError as exc:
            return SourcePayload(
                source_id=self.source_id,
                dataset=dataset,
                url=url,
                params=params or {},
                status_code=None,
                content_type=None,
                body=str(exc.reason).encode("utf-8", errors="replace"),
                ok=False,
                error=f"URL error: {exc.reason}",
            )
        except (TimeoutError, OSError) as exc:
            return SourcePayload(
                source_id=self.source_id,
                dataset=dataset,
                url=url,
                params=params or {},
                status_code=None,
                content_type=None,
                body=str(exc).encode("utf-8", errors="replace"),
                ok=False,
                error=f"Network error: {exc}",
            )

    def build_url(self, dataset: str, params: dict[str, str]) -> str:
        raise NotImplementedError


class OpenF1Adapter(HttpSourceAdapter):
    source_id = "openf1"
    base_url = "https://api.openf1.org/v1"
    datasets = {
        "meetings",
        "sessions",
        "drivers",
        "session_result",
        "starting_grid",
        "laps",
        "pit",
        "stints",
        "weather",
        "race_control",
        "position",
        "intervals",
        "car_data",
    }

    def build_url(self, dataset: str, params: dict[str, str]) -> str:
        if dataset not in self.datasets:
            raise ValueError(f"Unsupported OpenF1 dataset: {dataset}")
        return _url_with_params(f"{self.base_url}/{dataset}", params)


class JolpicaAdapter(HttpSourceAdapter):
    source_id = "jolpica"
    base_url = "https://api.jolpi.ca/ergast/f1"
    dataset_routes = {
        "races": "{season}/races.json",
        "drivers": "{season}/drivers.json",
        "constructors": "{season}/constructors.json",
        "driverstandings": "{season}/driverstandings.json",
        "constructorstandings": "{season}/constructorstandings.json",
        "results": "{season}/{round}/results.json",
        "qualifying": "{season}/{round}/qualifying.json",
        "sprint": "{season}/{round}/sprint.json",
        "laps": "{season}/{round}/laps.json",
        "pitstops": "{season}/{round}/pitstops.json",
    }

    def build_url(self, dataset: str, params: dict[str, str]) -> str:
        if dataset not in self.dataset_routes:
            raise ValueError(f"Unsupported Jolpica dataset: {dataset}")
        season = params.get("season", "current")
        round_ = params.get("round", "last")
        if dataset in {"driverstandings", "constructorstandings"} and "round" in params:
            route = f"{season}/{round_}/{dataset}.json"
        else:
            route = self.dataset_routes[dataset].format(season=season, round=round_)
        query = {key: value for key, value in params.items() if key not in {"season", "round"}}
        return _url_with_params(f"{self.base_url}/{route}", query)

    @staticmethod
    def unwrap_mrdata(payload: SourcePayload) -> dict[str, Any]:
        data = payload.json()
        if not isinstance(data, dict) or "MRData" not in data:
            raise ValueError("Jolpica response does not contain MRData")
        return data["MRData"]


class JolpicaAlphaAdapter(HttpSourceAdapter):
    source_id = "jolpica_alpha"
    base_url = "https://api.jolpi.ca/f1/alpha"
    dataset_routes = {
        "schedule": "schedules/{season}/",
        "session": "core/sessions/{session_id}/",
        "session_entries": "core/session-entries/",
        "laps": "core/laps/",
    }

    def build_url(self, dataset: str, params: dict[str, str]) -> str:
        if dataset not in self.dataset_routes:
            raise ValueError(f"Unsupported Jolpica alpha dataset: {dataset}")
        route = self.dataset_routes[dataset].format(
            season=params.get("season", "current"),
            session_id=params.get("session_id", ""),
        )
        query = {
            key: value
            for key, value in params.items()
            if key not in {"season"} and not (dataset == "session" and key == "session_id")
        }
        return _url_with_params(f"{self.base_url}/{route}", query)


class Formula1OfficialAdapter(HttpSourceAdapter):
    source_id = "formula1_official"
    base_url = "https://www.formula1.com"
    routes = {
        "drivers": "/en/drivers",
        "teams": "/en/teams",
        "driver_standings": "/en/results/{season}/drivers",
        "team_standings": "/en/results/{season}/team",
        "news": "/en/latest/all",
    }

    def build_url(self, dataset: str, params: dict[str, str]) -> str:
        if dataset not in self.routes:
            raise ValueError(f"Unsupported Formula1 dataset: {dataset}")
        season = params.get("season", "2026")
        route = self.routes[dataset].format(season=season)
        query = {key: value for key, value in params.items() if key != "season"}
        return _url_with_params(urljoin(self.base_url, route), query)


class FIADocumentsAdapter(HttpSourceAdapter):
    source_id = "fia_documents"
    base_url = "https://www.fia.com"
    season_documents_url = (
        "https://www.fia.com/documents/championships/"
        "fia-formula-one-world-championship-14/season/season-{season}-{season_id}"
    )

    def build_url(self, dataset: str, params: dict[str, str]) -> str:
        if dataset != "decision_documents":
            raise ValueError(f"Unsupported FIA dataset: {dataset}")
        season = params.get("season", "2026")
        season_id = params.get("season_id", "2072")
        query = {key: value for key, value in params.items() if key not in {"season", "season_id"}}
        url = self.season_documents_url.format(season=season, season_id=season_id)
        return _url_with_params(url, query)

    @staticmethod
    def extract_pdf_links(html: str) -> list[str]:
        parser = _DecisionDocumentParser()
        parser.feed(html)
        return parser.links


def get_adapter(source_id: str, *, token: str | None = None) -> HttpSourceAdapter:
    adapters: dict[str, type[HttpSourceAdapter]] = {
        "openf1": OpenF1Adapter,
        "jolpica": JolpicaAdapter,
        "jolpica_alpha": JolpicaAlphaAdapter,
        "formula1_official": Formula1OfficialAdapter,
        "fia_documents": FIADocumentsAdapter,
    }
    if source_id not in adapters:
        raise ValueError(f"Unsupported source: {source_id}")
    return adapters[source_id](token=token)


def _url_with_params(url: str, params: dict[str, str]) -> str:
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


class _DecisionDocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href")
        if not href:
            return
        if "decision-document" in href or href.endswith(".pdf"):
            self.links.append(urljoin(FIADocumentsAdapter.base_url, href))
