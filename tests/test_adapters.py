import f1_big_predictor.adapters as adapters_module
from f1_big_predictor.adapters import (
    FIADocumentsAdapter,
    JolpicaAdapter,
    JolpicaAlphaAdapter,
    OpenF1Adapter,
)


def test_openf1_url_building_encodes_params() -> None:
    adapter = OpenF1Adapter()
    url = adapter.build_url(
        "sessions",
        {"country_name": "Great Britain", "year": "2026"},
    )

    assert url == "https://api.openf1.org/v1/sessions?country_name=Great+Britain&year=2026"


def test_jolpica_url_building_uses_season_and_round_path() -> None:
    adapter = JolpicaAdapter()
    url = adapter.build_url(
        "sprint",
        {"season": "2026", "round": "12", "limit": "100"},
    )

    assert url == "https://api.jolpi.ca/ergast/f1/2026/12/sprint.json?limit=100"


def test_jolpica_standings_url_can_be_round_scoped() -> None:
    adapter = JolpicaAdapter()
    url = adapter.build_url(
        "driverstandings",
        {"season": "2026", "round": "7"},
    )

    assert url == "https://api.jolpi.ca/ergast/f1/2026/7/driverstandings.json"


def test_http_adapter_wraps_network_disconnect(monkeypatch) -> None:
    def raise_disconnect(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise OSError("remote disconnected")

    monkeypatch.setattr(adapters_module, "urlopen", raise_disconnect)

    payload = JolpicaAdapter().fetch("races", {"season": "2026"})

    assert payload.ok is False
    assert payload.status_code is None
    assert payload.error == "Network error: remote disconnected"


def test_jolpica_alpha_url_building_keeps_session_filter() -> None:
    adapter = JolpicaAlphaAdapter()
    url = adapter.build_url(
        "session_entries",
        {"session_id": "session_abc"},
    )

    assert url == "https://api.jolpi.ca/f1/alpha/core/session-entries/?session_id=session_abc"


def test_jolpica_alpha_schedule_url_consumes_season_path_param() -> None:
    adapter = JolpicaAlphaAdapter()
    url = adapter.build_url("schedule", {"season": "2026"})

    assert url == "https://api.jolpi.ca/f1/alpha/schedules/2026/"


def test_fia_extract_pdf_links_normalizes_relative_paths() -> None:
    html = '<a href="/system/files/decision-document/test_entry_list.pdf">Entry List</a>'

    assert FIADocumentsAdapter.extract_pdf_links(html) == [
        "https://www.fia.com/system/files/decision-document/test_entry_list.pdf"
    ]
