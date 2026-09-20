#!/usr/bin/env python3
"""Hard check: every round's FP (+SQ) lap archives exist, are non-empty lists,
contain the right session_key, and have >0 valid laps.

Per docs/data_and_evidence/README.md weekly checklist. Read-only; exit 1 on
any failure so it can gate weekly collection.

Note: sessions/laps archives from some countries match two rounds (Spain,
United States) -- session keys are resolved from THIS round's sessions archive
and lap files are matched by content session_key, never by filename.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DUR_MIN, DUR_MAX = 60.0, 240.0


def load_list(fp: str):
    try:
        d = json.load(open(fp))
        return d if isinstance(d, list) else None
    except Exception:
        return None


def session_keys(rn: int, name_filter, race_date: str) -> dict[str, int]:
    """Resolve this round's session keys from the sessions archive, filtered to
    sessions held within 4 days before the race date. Country-name archives
    can cover two rounds (Spain, United States) -- the date window is what
    makes the selection "this round"."""
    from datetime import datetime, timedelta

    race_dt = datetime.fromisoformat(race_date + "T00:00:00+00:00")
    lo = race_dt - timedelta(days=4)
    out = {}
    pat = ROOT / ("data/raw/openf1_sessions_2026_round_%02d/openf1/*sessions*.json" % rn)
    for f in glob.glob(str(pat)):
        if f.endswith(".meta.json"):
            continue
        d = load_list(f)
        if not d:
            continue
        for s in d:
            if not isinstance(s, dict) or name_filter not in str(s.get("session_name", "")):
                continue
            ds = str(s.get("date_start") or "")
            try:
                dt = datetime.fromisoformat(ds)
            except ValueError:
                continue
            if lo <= dt <= race_dt + timedelta(days=1):
                out[s["session_name"]] = s["session_key"]
    return out


def lap_files_by_key(rn: int) -> dict[int, dict]:
    by_key: dict[int, dict] = {}
    pat = ROOT / ("data/raw/openf1_laps_2026_round_%02d/openf1/*.json" % rn)
    for f in glob.glob(str(pat)):
        if f.endswith(".meta.json"):
            continue
        d = load_list(f)
        if not d:
            continue
        sk = d[0].get("session_key")
        valid = sum(
            1
            for x in d
            if not x.get("is_pit_out_lap")
            and isinstance(x.get("lap_duration"), (int, float))
            and DUR_MIN < x["lap_duration"] < DUR_MAX
        )
        by_key[sk] = {"rows": len(d), "valid_laps": valid, "file": Path(f).name}
    return by_key


def main() -> int:
    actuals = json.load(open(ROOT / "data/processed/season_2026_actuals/actuals.json"))
    failures = []
    for r in sorted(actuals["completed_rounds"], key=lambda x: int(x["round"])):
        rn = int(r["round"])
        race_date = str(r.get("race_date"))
        fp_keys = session_keys(rn, "Practice", race_date)
        sq_keys = session_keys(rn, "Sprint Qualifying", race_date)
        by_key = lap_files_by_key(rn)
        required = {"FP": fp_keys, "SQ": sq_keys}
        for tag, keys in required.items():
            for name, sk in keys.items():
                info = by_key.get(sk)
                if info is None:
                    failures.append(f"R{rn:02d} {name} (sk={sk}): laps archive MISSING")
                elif info["valid_laps"] <= 0:
                    failures.append(
                        f"R{rn:02d} {name} (sk={sk}): archive present but 0 valid laps"
                    )
        covered_fp = sum(1 for sk in fp_keys.values() if sk in by_key)
        print(
            f"R{rn:02d}: FP {covered_fp}/{len(fp_keys)}"
            + (f", SQ {sum(1 for sk in sq_keys.values() if sk in by_key)}/{len(sq_keys)}" if sq_keys else ", no SQ (regular weekend)")
        )
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print("  " + f)
        print(f"\nRESULT: FAIL ({len(failures)} missing/empty)")
        return 1
    print("\nRESULT: PASS (all rounds have non-empty FP/SQ lap archives)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
