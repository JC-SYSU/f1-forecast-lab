# Appendix A: Data and Sources

## A.1 Source tiers

External sources used in this report fall into five tiers. The tier is set by the provenance of the evidence, not by the tool used to fetch it.

| Tier | Role |
|---|---|
| Official | F1, FIA, team websites, stewards' announcements, and official result documents; the final authority for entry lists, penalties, and classifications. |
| Structured | Reproducible data interfaces such as FastF1 and OpenF1, providing structured retrieval of lap times, weather, and results. |
| News | Official news, team announcements, and mainstream motorsport media; only facts that would change a prediction are recorded. |
| Community | Forums, paddock live threads, and the like; used as a low-authority supplementary signal for lap-time and setup trends, with URL, retrieval time, source type, and confidence recorded. |
| Manual fallback | A manual snapshot taken when the API is delayed, a field is missing, or steward penalties are complex; source and time recorded. |

Six source IDs are registered in total; the full registry is `data/source_catalog.json`.

| Source ID | Access | Use | Fallback |
|---|---|---|---|
| formula1_official | HTML scraping of the F1 website | Drivers, constructors, standings, and cross-checks of official news | If the page structure changes, keep the HTML and switch to the FIA entry list or a manual snapshot |
| fia_documents | HTML of FIA event-document pages, parsing PDF links | Entry lists, penalties, stewards' announcements, final classification | Download the PDF manually into the race-week evidence directory and record the source |
| openf1 | JSON/CSV endpoints including sessions, laps, starting_grid, weather, race_control, and others | Locating a session id and joining lap times, weather, and the starting grid | On 401 responses during a live session, switch to Jolpica/FIA/the F1 website |
| jolpica | Ergast-compatible JSON (outer MRData), endpoints including races, results, qualifying, sprint, standings | Race/qualifying/sprint results and standings, and the pole anchor for target circuit history | FIA classification PDF |
| jolpica_alpha | Jolpica alpha JSON, endpoints including schedules, session-entries, laps | Covering sprint qualifying that the Ergast-compatible endpoints do not expose directly | FIA sprint qualifying classification PDF, FastF1/OpenF1 laps |
| fastf1 | Python package returning pandas DataFrames | High-precision lap times, long-run pace, weather, and historical circuit performance; an optional phase-two dependency | Not a core dependency for now; install and cache separately when needed |

## A.2 Archiving and reuse

All external data is written first to `data/raw/<week_id>/<source_id>/`, and cleaned results are generated afterwards. Raw files are not committed to Git, but each must have a matching `.meta.json` with required fields: URL, parameters, retrieval time, HTTP status, content type, SHA-256, success flag, and error message.

Before any fetch, a successful archive is looked up by `week_id + source_id + dataset + params`: on a hit with the SHA-256 verified, it is reused and no network call is made; refetching happens only when an archive is missing, failed, lost, carries corrupted metadata, or the SHA-256 does not match. Season-level actuals collection may enable read-only reuse across `week_id`, provided `source_id + canonical dataset + params` match exactly and verification passes; legacy dataset names are not accepted. OpenF1 401 responses during a live session are archived as evidence of failure in the same way, and the subsequent flow switches to FIA/F1/Jolpica or a manual snapshot. Production flows must fetch data through archive-aware entry points such as the CLI or the `archived_*_client` classes; low-level HTTP adapters are not called directly in the weekly flow.

## A.3 Honest gap list

| Gap | Impact on research | Status |
|---|---|---|
| Tire and lap-level telemetry entirely missing | If the race line needs tire-strategy features, they cannot be backtested; the impact on qualifying prediction is smaller | No tire compound, tire life, or pit-strategy data; lap-level telemetry (brake, throttle, gear) not collected; the OpenF1 `pit`, `stints`, and `car_data` endpoints may provide it but are unverified |
| R01 has no circuit history | When the backtest includes R01, that round can only use the actuals' race/qualifying/standings; no same-circuit history features | Audit marks it as "first round: no same-circuit history requirement, or not collected" |
| R01 has no agent evidence | R01 cannot use pre-race evidence features, and subjective residuals are likewise missing | Listed in the audit gaps together with circuit history |
| R14 Madrid: new circuit, no history | Model features downstream that reference this directory have no anchor this round | madring is a new circuit for 2026; with a 5-year lookback, matched_historical_events=0 — a structural absence, not a collection gap; the 9-18 rerun records gap missing_circuit_history_round_14 as the true state |
| R14 qualifying records 20 rows | Qualifying actuals have 2 fewer rows than the race's 22 | Upstream qualifying total=20; ingested as-is, with no inferred repair |
| R06 judgment-revision time lag | The 2026-09-05 qualifying scorecard ran before the judgment revision was re-collected, so the feature chain from R07 onward had not absorbed the revision | Closed by the 2026-09-18 full rerun; the "R06 judgment-revision re-evaluation" to-do item was completed alongside |

## A.4 Case: re-collection after the R06 ICA judgment revision

During the raw-data catch-up on 2026-09-13 we found that the R06 (Monaco) classification had been revised by the ICA and that upstream Jolpica had already synced the change: Gasly moved from P3 to P7, Hadjar moved up to P3, and the standings points followed — gasly 35→26, hadjar 26→29, piastri 58→60.

Re-collection: the CLI client defaults to `reuse_any_archive=True`, so running it as-is would hit the old 2026-07-04 archive with zero requests, and the output would be indistinguishable from a live fetch. The re-collection instead went through a /tmp helper that fetched with `reuse_any_archive=False`, kept at least 1.3 seconds between requests, and wrote to the new week_id `season_2026_actuals_r06_refresh` (6 files, including the schedule); the old R06 archive was left untouched. The merge used whole-round replacement: `merge_actuals_payload`'s default semantics replace only target fields for a round that already exists and do not update the standings blocks, whereas this revision changed exactly the standings as of R06 — so the update was completed as a whole-round replacement (handled inside that run's helper flow; no mainline code was changed).

Verification of the re-collection: the R06 qualifying payload matched the July source's SHA prefix (3988ac69) — the revision had not touched qualifying. The feature-chain impact of the revision lag was absorbed by the 2026-09-18 full rerun.
