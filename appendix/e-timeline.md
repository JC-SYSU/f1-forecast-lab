# Appendix E · Research Log

This appendix collects the project's main events across its whole run, in date order, with entries kept brief; the background and rulings behind each decision are in Chapter 09. Dates and commit hashes are taken from the git history of the original repository.

## E.1 July: From Trial Runs to Two Model Lines

**07-03** Project initialized; same-day trial runs of the predecessor model on the Canadian Grand Prix sprint weekend and on the Austrian backtest (1df53ea, 027d633).

**07-04** Predecessor v1.6 full prediction report and several calibration modules generated (7981f28).

**07-05** The prediction project's baseline reset; sprint qualifying, sprint race, qualifying, and race established as four independent prediction targets (970319e, 478fa7b).

**07-08** Four rounds of research — a domain scan, paradigm gap-filling, an assessment of deep learning, and implementation references — all completed the same day; ruled that the scoring scale comes first and that deep networks stay out of version one (dd49fe0, e014de6, aea4e9c, b1bab76).

**07-17** The candidate registry put on record; 29 first-batch candidates registered in numbered batches, and the old calibration moved out of the run path the same day (a706701, d6cbe36).

**07-18** The repository governance system, the authoritative project state, and the project map established (9c460c6, 2644343).

**07-19** Official labels through R09 accepted; the 29 candidates replayed under uniform C0 (08d9540, 804df46).

**07-20** Scoring conventions unified: the C0 mean becomes the single criterion, MAE/NDCG retired, the evaluation window frozen at R03–R09; the tuning sweep over the three families rating/prob/ltr completed the same day (dedd44a, 8e7734d, 077f127).

**07-21** The ST-6d slot-ensemble candidates #30/#31 merged into the registry (29 becomes 31); the qualifying tuning iteration frozen the same day (9fcb0e8, d7f7c44).

**07-25** The R10 raw-data backfill plan archived; the ownership inventory mechanism retired the same day (71d3b2a, bc4fd6c).

**07-28** Single-session C0 replays for R10 and R11 written to disk, the first test of going out-of-window (bd0ada7, ed2517c).

## E.2 August: Breakthrough and Freeze

**08-02** Raw race evidence for R10 and R11 archived (d2a3098).

**08-02** Actuals for R10 and R11 processed into the store (d1b4536).

**08-02** The race model changed design: standardization plus a single interaction term breaks the monotone-transform trap; the R10–R11 test score rose from 0.5438 to 0.5917 (606117e).

**08-08** The working summary of the race-prediction breakthrough archived (fe85a1d).

**Final week of August** The race weights (recent form 3.0, recovery rate 2.0, rear-grid interaction 3.0) and the formula were all frozen, and "the third window" was established. No separate ruling document was left this time (Chapter 09, entry 7).

**08-23** The R12 race at Zandvoort — the first unseen round after the freeze.

## E.3 September: Prospective Testing, Judgment Revisions, and the Rerun

**09-04** The six-piece R12 race raw archive completed, along with R13 historical data (673f139, 615232a).

**09-04** The race working point closed off; work turned to multi-factor prospective validation (01aea52).

**09-05** The six-variant constructor-strength correction experiment falsified; the gated impression-refresh experiment falsified in turn. Neither mechanism enters the main line, and the blind-test pre-registration was locked in (a0f6947, 974624b).

**09-05** The R03–R13 archive of major events in constructor-strength ranking movement, v1.1, archived (f50662f, 10a1d7f).

**09-06** The R13 race at Monza.

**09-13** The R06 qualifying classification was revised by the FIA (judgment revision); actuals were re-collected into the store, R13 actuals entered the store the same day, and published scorecards are not refreshed retroactively (3c069ed).

**09-13** The R14 race in Madrid.

**09-14** The R13/R14 continued collection closed out; 96 items archived into the store (b4bac44).

**09-14** Incremental prospective evaluation on both lines written to disk: the race line won both rounds against the baseline, and qualifying #30/#31 hit consecutive field_mismatch (a90bf4a).

**09-17** The writing repository f1-forecast-lab initialized; report writing started (54b6006).

**09-18** The qualifying C0 scorecard fully rerun after the circuit-history archive was completed, absorbing the R06 judgment revision; #31 rose to first in the merged scorecard at 0.4835 (41d97d7).

**09-20** The seat-rotation policy unlocked (decision log, entry 12), reversing the September 5 no-mechanism ruling: a manual seat-event registry, three-way parameter attribution, split reliability, and a slot entry filter landed in code (55076e4 through 9207683).

**09-20** Both lines recomputed in full over R03–R14 under the policy: qualifying #31 first at 0.4785 with every candidate-round cell scored (a166623); race model mean 0.5581 vs baseline 0.5071, R13 corrected 0.6672 → 0.5864 on the registry's constructor attribution (4ef473b).

**09-20** FP relative-pace modeling plan drafted, then shelved (EXP-001 v1.1); replaced by a two-question correlation design with the fp_score algorithm frozen before any model score was read (CORR-001 §1.1, SQ pooling included), plus a weekly FP/SQ coverage hard check (`scripts/check_fp_sq_laps_coverage.py`).

**09-20** Correlation report: practice rank vs same-round qualifying ρ=0.886 (14/14 positive); sprint rounds 5/5 improved under SQ pooling (0.842 → 0.901); redundant with recent form (0.876); no explanation of #31's errors (ρ=-0.027) Artifacts: `fp_signal_corr_d739e6e0` (raw JSON in the private archive, not distributed).

**09-20** Replacement ablation: all 7 combinations (into recent form / constructor strength / circuit fit, alone or combined) below the +0.010 bar across 217 candidate-cells; only R-ctor +0.0072 (noise band), registered as a candidate-evolution observation. Artifacts: `fp_ablation_*_035117f2` and `fp_ablation_circuit_fit_279780c6` (private archive).

**09-20** The FP feature line for qualifying is declared closed ("strongly correlated but redundant, no model increment"); constructor-level × race-line, the review-lens use and the data pipeline are retained, with reopening conditions recorded.


**09-20** Provenance audit of the practice-signal proposal: the September 5 what-if had never been answered rather than rejected — it was the last message of a session that ended four minutes later, which is why it sat unaddressed until the seat-rotation work of this day.

**09-20** Race-side audit: fleet-level practice rank tracks the constructors' race order at ρ=0.779 (driver version 0.661, both 14/14); redundancy with racecraft 0.578, far below the qualifying side; the residual correlation is significant and corrective — the grid-anchored race model overestimates practice-fast drivers and teams (driver -0.291 over 93 observations, fleet -0.604 over 69). Artifact: `fp_corr_stats_race.json` in the `fp_signal_corr_d739e6e0` set (raw JSON in the private archive, not distributed).

**09-20** Block D gap test: the mean-reversion framing is falsified — the sign points the other way: the race continues the qualifying-versus-practice deviation rather than reverting from it (pooled ρ=-0.2695 over 308 driver-rounds, negative in 11/14 rounds). Artifact: `fp_gap_test_D.json` (private archive).

**09-20** Race-side ablation and full closure: the GAP correction gains +0.0006 (λ*=5 selected on the dev rounds, gone in the prospective R10–R14) and FP-DIRECT weighting selects λ*=0 — both far below the +0.010 bar, so the practice-feature line is closed on both lines (closure record v1.1). Artifact: `race_ablation_results.json` (private archive).

**09-20** The race model's variant family audited at the formula slot: a parallel new-model line chartered with a pre-registered succession rule (full-window gain and a prospective lead ≥ +0.010 sustained for three forward rounds; the frozen model untouched as incumbent). All 204 usable combinations (26 × 2 × 4 = 208; the rescaling axis collapses under the formula's own field standardization) scored over R03–R14 — the incumbent's hit-rate source ranks first at 0.5581, baseline verified to under 1e-6 per round; the only prospective-gate pass (+0.018) loses −0.028 over the full window and fails the succession rule; the reserved form-source stage never triggers. Line closed for the cycle. Artifact: `nsw_scan.json` in `nsw_racecraft_scan_035117f2` (private archive).

**09-20** The pre-race evidence term's season-long zero explained: the anti-leakage gate requires retrieval into the archive before each round's cutoff, and every historical evidence entry was back-filled in a single July session — all 20 correctly refused, the mechanism never fed. Ruling: fix the process, not the code; a weekly pre-cutoff collection step starts at R15 (Baku), the first live run of the term. Historical rounds stand as they are.

**09-20** Blind test, first trigger reading (McLaren event, trigger round R14), computed under the current caliber: exactly zero movement on every carrier metric — the correction-on arm raises McLaren's strength value (+0.112) yet flips no donor ranking; Δ = 0.0000 against the +0.010 bar. The final verdict falls at R15 (the Aston Martin regime's trigger round, September 26), the last clean sample inside the pre-registered frame; the verdict script prepared in advance.

**09-20** R15 readiness: the weekly collection checklist gains a pre-cutoff evidence step; the blind-test verdict script is in place; the round is the first forward test of the seat-rotation policy, the evidence term, and the blind test at once.

**09-23** The evidence term's fate resolved by reconstruction: entry 15's "fix the process" ruling revised into survey-first order — the official reports cannot be held by the v1 schema, and practice pace itself was the line just closed; what remained was reliability failures, upgrade declarations and factual team statements. R01–R14 collected under mechanical-inclusion and existence-proof rules: 143 archived sources, FIA's per-round car-presentation submissions giving machine-parsable part counts, 57 structured events, stepped quantization (±0.1 per part, ±0.2 per closed-dictionary event) under six standing rules.

**09-23** Three-stage evaluation and closure: the upgrade-part count is the only correlating value (ρ≈0.157) and is undone by near-identical redundancy with the constructors' standing (−0.160); the events dimension correlates with nothing; the ablation over all 31 candidates gives #31 a paired top-ten difference of +2 against the pre-registered +3 bar and ΔC0 = +0.000013 — no statistically discernible increment. The component is retired from the main line (~700-line removal), verified as an equivalence transform (372/372 predictions identical; re-issued artifact `c0_roster_r03_r14_c579e6d0` bit-identical to the official `92076830`), which stands. Artifacts: `evidence_recon_corr_001`, `evidence_recon_ablation_001` (private archive, not distributed).
