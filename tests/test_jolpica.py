from f1_big_predictor.jolpica import extract_race_schedule


def test_extract_race_schedule_reads_circuit_identity() -> None:
    schedule = extract_race_schedule(
        {
            "RaceTable": {
                "Races": [
                    {
                        "season": "2026",
                        "round": "5",
                        "raceName": "Canadian Grand Prix",
                        "date": "2026-05-24",
                        "Circuit": {
                            "circuitId": "villeneuve",
                            "circuitName": "Circuit Gilles Villeneuve",
                        },
                    }
                ]
            }
        }
    )

    assert schedule[0].race_name == "Canadian Grand Prix"
    assert schedule[0].circuit_id == "villeneuve"
    assert schedule[0].circuit_name == "Circuit Gilles Villeneuve"
