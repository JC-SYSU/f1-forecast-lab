import json

from f1_big_predictor.archive import RawArchive, archive_dataset_key
from f1_big_predictor.jolpica import JolpicaClient


def test_raw_archive_writes_payload_and_metadata(tmp_path) -> None:
    record = RawArchive(tmp_path).write(
        week_id="260703a",
        source_id="jolpica",
        dataset="driverstandings",
        url="https://example.test/data.json",
        params={"season": "2026"},
        payload={"ok": True},
        extension="json",
        content_type="application/json",
        status_code=200,
        ok=True,
    )

    assert record.payload_sha256
    assert record.data_path.endswith(".json")

    meta = json.loads(open(record.meta_path, encoding="utf-8").read())
    assert meta["week_id"] == "260703a"
    assert meta["source_id"] == "jolpica"
    assert meta["params"] == {"season": "2026"}
    assert meta["ok"] is True


def test_raw_archive_reuses_latest_matching_successful_payload(tmp_path) -> None:
    archive = RawArchive(tmp_path)
    archive.write(
        week_id="week",
        source_id="jolpica",
        dataset="results_round_5",
        url="https://example.test/old.json",
        params={"season": "2026", "round": "5"},
        payload={"value": "old"},
        extension="json",
        content_type="application/json",
        status_code=200,
        ok=True,
    )
    latest = archive.write(
        week_id="week",
        source_id="jolpica",
        dataset="results_round_5",
        url="https://example.test/new.json",
        params={"season": "2026", "round": "5"},
        payload={"value": "new"},
        extension="json",
        content_type="application/json",
        status_code=200,
        ok=True,
    )

    cached = archive.read_latest(
        week_id="week",
        source_id="jolpica",
        dataset="results_round_5",
        params={"season": "2026", "round": "5"},
    )

    assert cached is not None
    assert cached.record.data_path == latest.data_path
    assert json.loads(cached.body.decode("utf-8")) == {"value": "new"}


def test_archive_dataset_key_is_shared_by_fetch_paths() -> None:
    assert (
        archive_dataset_key(
            "jolpica",
            "results",
            {"season": "2026", "round": "5"},
        )
        == "results_round_5"
    )
    assert (
        archive_dataset_key(
            "jolpica_alpha",
            "session_entries",
            {"session_id": "session_sq3"},
        )
        == "session_entries_session_sq3"
    )


def test_raw_archive_ignores_failed_or_corrupt_payload(tmp_path) -> None:
    archive = RawArchive(tmp_path)
    failed = archive.write(
        week_id="week",
        source_id="jolpica",
        dataset="results_round_5",
        url="https://example.test/fail.json",
        params={"season": "2026", "round": "5"},
        payload={"error": True},
        extension="json",
        content_type="application/json",
        status_code=503,
        ok=False,
        error="HTTP 503",
    )

    assert archive.read_latest(
        week_id="week",
        source_id="jolpica",
        dataset="results_round_5",
        params={"season": "2026", "round": "5"},
    ) is None

    ok = archive.write(
        week_id="week",
        source_id="jolpica",
        dataset="results_round_5",
        url="https://example.test/ok.json",
        params={"season": "2026", "round": "5"},
        payload={"ok": True},
        extension="json",
        content_type="application/json",
        status_code=200,
        ok=True,
    )
    open(ok.data_path, "wb").write(b"corrupt")

    assert archive.read_latest(
        week_id="week",
        source_id="jolpica",
        dataset="results_round_5",
        params={"season": "2026", "round": "5"},
    ) is None
    assert json.loads(open(failed.meta_path, encoding="utf-8").read())["ok"] is False


def test_jolpica_client_uses_archived_payload_before_network(tmp_path) -> None:
    archive = RawArchive(tmp_path)
    archive.write(
        week_id="week",
        source_id="jolpica",
        dataset="results_round_5",
        url="https://example.test/results.json",
        params={"season": "2026", "round": "5"},
        payload={
            "MRData": {
                "RaceTable": {
                    "Races": [
                        {
                            "Results": [
                                {
                                    "position": "1",
                                    "grid": "1",
                                    "points": "25",
                                    "status": "Finished",
                                    "Driver": {
                                        "driverId": "alpha",
                                        "givenName": "Alpha",
                                        "familyName": "Driver",
                                    },
                                    "Constructor": {
                                        "constructorId": "team_a",
                                        "name": "Team A",
                                    },
                                }
                            ]
                        }
                    ]
                }
            }
        },
        extension="json",
        content_type="application/json",
        status_code=200,
        ok=True,
    )

    class FailingAdapter:
        source_id = "jolpica"

        def fetch(self, dataset, params):  # type: ignore[no-untyped-def]
            raise AssertionError("network should not be called")

    results = JolpicaClient(
        adapter=FailingAdapter(),  # type: ignore[arg-type]
        archive=archive,
        archive_week_id="week",
    ).race_results(2026, 5)

    assert results[0].driver_id == "alpha"


def test_jolpica_client_can_reuse_legacy_raw_dataset_archive(tmp_path) -> None:
    archive = RawArchive(tmp_path)
    archive.write(
        week_id="week",
        source_id="jolpica",
        dataset="results",
        url="https://example.test/results.json",
        params={"season": "2026", "round": "5"},
        payload={
            "MRData": {
                "RaceTable": {
                    "Races": [
                        {
                            "Results": [
                                {
                                    "position": "1",
                                    "grid": "1",
                                    "points": "25",
                                    "status": "Finished",
                                    "Driver": {
                                        "driverId": "legacy",
                                        "givenName": "Legacy",
                                        "familyName": "Driver",
                                    },
                                    "Constructor": {
                                        "constructorId": "team_l",
                                        "name": "Team L",
                                    },
                                }
                            ]
                        }
                    ]
                }
            }
        },
        extension="json",
        content_type="application/json",
        status_code=200,
        ok=True,
    )

    class FailingAdapter:
        source_id = "jolpica"

        def fetch(self, dataset, params):  # type: ignore[no-untyped-def]
            raise AssertionError("network should not be called")

    results = JolpicaClient(
        adapter=FailingAdapter(),  # type: ignore[arg-type]
        archive=archive,
        archive_week_id="week",
    ).race_results(2026, 5)

    assert results[0].driver_id == "legacy"


def test_request_cache_picks_latest_across_canonical_and_legacy_keys(tmp_path) -> None:
    archive = RawArchive(tmp_path)
    archive.write(
        week_id="week",
        source_id="jolpica",
        dataset="results_round_5",
        url="https://example.test/canonical.json",
        params={"season": "2026", "round": "5"},
        payload={"value": "canonical"},
        extension="json",
        content_type="application/json",
        status_code=200,
        ok=True,
    )
    archive.write(
        week_id="week",
        source_id="jolpica",
        dataset="results",
        url="https://example.test/legacy.json",
        params={"season": "2026", "round": "5"},
        payload={"value": "legacy"},
        extension="json",
        content_type="application/json",
        status_code=200,
        ok=True,
    )

    cached = archive.read_latest_for_request(
        week_id="week",
        source_id="jolpica",
        dataset="results",
        params={"season": "2026", "round": "5"},
    )

    assert cached is not None
    assert json.loads(cached.body.decode("utf-8")) == {"value": "legacy"}


def test_request_cache_can_reuse_matching_payload_from_any_week(tmp_path) -> None:
    archive = RawArchive(tmp_path)
    old = archive.write(
        week_id="old_week",
        source_id="jolpica",
        dataset="results_round_5",
        url="https://example.test/results.json",
        params={"season": "2026", "round": "5"},
        payload={"value": "old"},
        extension="json",
        content_type="application/json",
        status_code=200,
        ok=True,
    )

    cached = archive.read_latest_for_request_any_week(
        source_id="jolpica",
        dataset="results",
        params={"season": "2026", "round": "5"},
    )

    assert cached is not None
    assert cached.record.meta_path == old.meta_path


def test_request_cache_rejects_legacy_dataset_key_across_weeks(tmp_path) -> None:
    archive = RawArchive(tmp_path)
    archive.write(
        week_id="old_week",
        source_id="jolpica",
        dataset="results",
        url="https://example.test/results.json",
        params={"season": "2026", "round": "5"},
        payload={"value": "legacy"},
        extension="json",
        content_type="application/json",
        status_code=200,
        ok=True,
    )

    cached = archive.read_latest_for_request_any_week(
        source_id="jolpica",
        dataset="results",
        params={"season": "2026", "round": "5"},
    )

    assert cached is None


def test_jolpica_client_can_reuse_archive_from_any_week_before_network(tmp_path) -> None:
    archive = RawArchive(tmp_path)
    archive.write(
        week_id="old_week",
        source_id="jolpica",
        dataset="results_round_5",
        url="https://example.test/results.json",
        params={"season": "2026", "round": "5"},
        payload={
            "MRData": {
                "RaceTable": {
                    "Races": [
                        {
                            "Results": [
                                {
                                    "position": "1",
                                    "grid": "1",
                                    "points": "25",
                                    "status": "Finished",
                                    "Driver": {
                                        "driverId": "global",
                                        "givenName": "Global",
                                        "familyName": "Driver",
                                    },
                                    "Constructor": {
                                        "constructorId": "team_g",
                                        "name": "Team G",
                                    },
                                }
                            ]
                        }
                    ]
                }
            }
        },
        extension="json",
        content_type="application/json",
        status_code=200,
        ok=True,
    )

    class FailingAdapter:
        source_id = "jolpica"

        def fetch(self, dataset, params):  # type: ignore[no-untyped-def]
            raise AssertionError("network should not be called")

    results = JolpicaClient(
        adapter=FailingAdapter(),  # type: ignore[arg-type]
        archive=archive,
        archive_week_id="new_week",
        reuse_any_archive=True,
    ).race_results(2026, 5)

    assert results[0].driver_id == "global"
