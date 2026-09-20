# Appendix C: Scorecard Index

This appendix lists the directories under `outputs/experiments/` directly related to the C0 scorecards, and documents the field structure of the qualifying `c0_results.json` and how to read it. Dates in the table are the UTC dates of each artifact's `generated_at` field; the two a90bf4ad reruns were generated at 2026-09-17 23:17 UTC, i.e. 2026-09-18 Beijing time; the 2026-09-20 recompute (92076830 / d739e6e0) at 02:55 and 03:11 UTC the same day.

## C.1 Artifact list

| Directory | Line | Rounds covered | Generated | Candidates/models | Status |
| --- | --- | --- | --- | --- | --- |
| c0_roster_r03_r14_92076830 | qualifying | R03-R14 | 2026-09-20 | 31 | Canonical |
| c0_race_r03_r14_d739e6e0 | race | R03-R14 | 2026-09-20 | 2 models | Canonical |
| c0_roster_r03_r12_a90bf4ad | qualifying | R03-R12 | 2026-09-17 | 31 | Retained (superseded by the 92076830 recompute) |
| c0_roster_r13_r14_a90bf4ad | qualifying | R13-R14 | 2026-09-17 | 31 | Retained (superseded by the 92076830 recompute) |
| c0_roster_r03_r12_615232a3 | qualifying | R03-R12 | 2026-09-05 | 31 | Retained (superseded by the a90bf4ad rerun) |
| c0_roster_r13_r14_6a01fdaa | qualifying | R13-R14 | 2026-09-14 | 31 | Retained (superseded by the a90bf4ad rerun) |
| c0_roster_r03_r09_8e7734d7 | qualifying | R03-R09 | 2026-07-20 | 29 | Retained (official historical version) |
| c0_roster_r03_r09_9fcb0e86 | qualifying | R03-R09 | 2026-07-21 | 31 | Retained (official historical version) |
| c0_roster_r02_r09_804df469 | qualifying | R02-R09 | 2026-07-19 | 29 | Retained (development-phase version) |
| c0_roster_r02_r09_bd70b702 | qualifying | R02-R09 | 2026-07-20 | 29 | Retained (development-phase version) |
| r10_c0_replay_2026_belgian | qualifying | R10 (Belgian) | 2026-07-25 | 31 | Retained (July single-round replay) |
| r11_c0_replay_2026_hungarian | qualifying | R11 (Hungarian) | 2026-07-26 | 31 | Retained (July single-round replay) |
| v1_baseline_comparison | qualifying | R02-R09 | 2026-07-09 | 4 configurations | Retained (v1 baseline comparison) |
| v1_remediation_track_profile_comparison | qualifying | R02-R09 | 2026-07-11 | 2 configurations | Retained (v1 remediation comparison) |
| st2_reality_sensitivity | qualifying | R02-R09 | 2026-07-17 (run_id) | 26 protocols | Retained (evidence sensitivity check) |
| c0_race_r03_r12_615232a3 | race | R03-R12 | 2026-09-05 | 2 models | Retained (superseded by the d739e6e0 recompute) |
| c0_race_r13_r14_6a01fdaa | race | R13-R14 | 2026-09-14 | 2 models | Retained (superseded by the d739e6e0 recompute) |
| whatif_upgrade | what-if | — | — | 6+6 variants | Side-branch experiment artifact |
| nsw_racecraft_scan_035117f2 | race | R03–R14 | 2026-09-20 | 204 variants | Formula-slot scan (race.nsw line; decision log, entry 15) |

For qualifying, the canonical artifact is the 92076830 recompute of 2026-09-20 — one merged R03–R14 run under the seat-rotation policy (decision log, entry 12) — which supersedes the two a90bf4ad products, themselves superseding 615232a3 and 6a01fdaa; the old artifacts are retained. The two r03_r09 directories are official historical versions, and the two r02_r09 directories are development-phase versions. On the race line the d739e6e0 recompute of 2026-09-20 (constructor attribution following the seat registry from R12 on) is canonical and supersedes the two 615232a3/6a01fdaa artifacts, which are retained. Under `race/` there is also 1 json file and 5 loose PNGs — grid-feature exploration charts — which are not listed; under `whatif_upgrade/`, two json files (whatif_upgrade_results.json, gcr_results.json) are side-branch weight-variant comparison artifacts and carry no `generated_at`/`code_commit` fields, and the `fp_signal_corr_d739e6e0` set (fp_corr_stats_race.json, fp_gap_test_D.json, race_ablation_results.json) holds the practice-signal audit and race-side ablation results of the September 20 closure (decision log, entries 13–14).

## C.2 c0_results.json field reference (qualifying version)

The canonical reference is c0_roster_r03_r14_92076830 (schema `qualifying.c0_roster.v2_full_r03_r14`). The superseded a90bf4ad pair used schema `qualifying.c0_roster.v2_merged` (merged) and `qualifying.c0_roster.v2_incremental_r13_r14` (incremental, additionally carrying `continuation_of`, pointing to the artifact it continued); both are field-identical to the current one apart from the summary mean key.

| Field | Meaning |
| --- | --- |
| schema_version | Artifact schema identifier; see above |
| season | Data season: 2026 |
| candidate_registry | Registry entries for the 31 candidates: index, candidate_id, model_id, variant description, first scored round and expected scored rounds, configuration |
| evaluation_rounds | List of scored rounds: R03-R14 for the 92076830 version, R03-R12 for the merged version, R13-R14 for the incremental version |
| label_provenance | Label source per round: R03-R09 official_overlay_manifest (official-label overlay); R10-R11 raw_actuals_verified_equal_to_fia_replay_audit (raw classification verified); from R12 on raw_actuals_pending_fia_overlay (pending FIA overlay) |
| cutoff_semantics | Cutoff semantics: the commit at which weights were frozen, and the rule that feature training uses only data from before the target round |
| run_purpose | Statement of this run's purpose |
| input_snapshot | Input snapshot: paths and SHA-256 of the 25 input files, the list of missing paths, and the combined_sha256 rollup hash |
| summary | Per-candidate mean ranking: candidate_id, index, model_id, variant, n_rounds, mean_c0_r03_r14 in the 92076830 version (mean_c0_r03_r12 merged / mean_c0_r13_r14 incremental in the superseded pair), and per_round round-by-round scores |
| candidates[].rounds | Per-candidate round detail: status (scored, etc.), prediction_top10, label_source, the round's c0 score, and the c0_full breakdown |

The four components of c0_full:

| Component | Meaning |
| --- | --- |
| membership | Set membership: top3/top5/top10 set scores and the candidate-pool score |
| exact | Position-by-position hits: hit vector, hit count and positions, exact_position_score, and the positive score with its normalization |
| combo | Consecutive-run bonus: maximal_runs, each run's start position and length score, combo_shape, and the bonus value |
| distance | Position distance: per-position distance vector, distance sum, mean and maximum distance, and the distance penalty |

In the actual files, c0_full also carries three derived keys — exact_branch, internal_order, overall_candidate — which are qualifying-specific branch-tracking information.

## C.3 How to read the numbers

To find a candidate's merged mean: locate it in the `summary` array by candidate_id and read mean_c0_r03_r14 in the 92076830 version (mean_c0_r03_r12 / mean_c0_r13_r14 in the superseded pair); per_round gives the round-by-round breakdown. To see single-round detail: find the same candidate_id in the `candidates` array; its rounds list status, prediction_top10, and c0 per round, and c0_full's four components can be expanded when attribution is needed. To check the inputs as of the run: take the sha256 for that path in `input_snapshot.files` and compare it against a recomputation over the current file under `data/`, or compare combined_sha256 directly. A mismatch means the inputs have changed; read the numbers against the snapshot inside the artifact.
