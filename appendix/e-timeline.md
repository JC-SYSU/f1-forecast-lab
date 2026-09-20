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
