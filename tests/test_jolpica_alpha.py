from f1_big_predictor.jolpica_alpha import (
    AlphaLap,
    AlphaSessionEntry,
    build_sprint_qualifying_classification,
    extract_round_sessions,
)


def test_extract_round_sessions_reads_nested_schedule_blocks() -> None:
    payload = {
        "data": {
            "events": [
                {
                    "round": {"id": "round_5", "number": 5, "name": "Canadian Grand Prix"},
                    "schedule": [
                        {
                            "sessions": [
                                {
                                    "id": "session_sq3",
                                    "number": 4,
                                    "type": "SQ3",
                                    "type_display": "Sprint Qualifying Three",
                                }
                            ]
                        }
                    ],
                }
            ]
        }
    }

    sessions = extract_round_sessions(payload, 5)

    assert sessions[0].session_id == "session_sq3"
    assert sessions[0].session_type == "SQ3"
    assert sessions[0].round_name == "Canadian Grand Prix"


def test_build_sprint_qualifying_classification_combines_segments_and_lap_times() -> None:
    sq1 = [
        _entry("bearman", "Haas", "SQ1", 15, "e_bearman_sq1"),
        _entry("perez", "Cadillac", "SQ1", 16, "e_perez_sq1"),
    ]
    sq2 = [
        _entry("norris", "McLaren", "SQ2", 1, "e_norris_sq2"),
        _entry("bearman", "Haas", "SQ2", 11, "e_bearman_sq2"),
    ]
    sq3 = [
        _entry("norris", "McLaren", "SQ3", 1, "e_norris_sq3"),
        _entry("russell", "Mercedes", "SQ3", 2, "e_russell_sq3"),
    ]
    laps = [
        AlphaLap("lap_1", "e_norris_sq3", 1, "1:13.000", 73000, False),
        AlphaLap("lap_2", "e_norris_sq3", 2, "1:12.900", 72900, True),
        AlphaLap("lap_3", "e_russell_sq3", 2, "1:12.950", 72950, True),
    ]

    classification = build_sprint_qualifying_classification(
        sq1=sq1,
        sq2=sq2,
        sq3=sq3,
        sq3_laps=laps,
        driver_ids_by_name={
            "norris": "norris",
            "russell": "russell",
            "bearman": "bearman",
            "perez": "perez",
        },
        constructor_ids_by_team={
            "mclaren": "mclaren",
            "mercedes": "mercedes",
            "haas": "haas",
            "cadillac": "cadillac",
        },
    )

    assert [entry.driver_id for entry in classification] == [
        "norris",
        "russell",
        "bearman",
        "perez",
    ]
    assert [entry.position for entry in classification] == [1, 2, 3, 4]
    assert classification[0].lap_time == "1:12.900"
    assert classification[1].constructor_id == "mercedes"


def _entry(
    driver_name: str,
    team_name: str,
    session_type: str,
    position: int,
    entry_id: str,
) -> AlphaSessionEntry:
    return AlphaSessionEntry(
        entry_id=entry_id,
        session_id=f"session_{session_type.lower()}",
        session_type=session_type,
        position=position,
        driver_name=driver_name,
        team_name=team_name,
        points=0,
        status="Finished",
    )
