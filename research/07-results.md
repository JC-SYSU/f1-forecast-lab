# 07 · Results

## 7.1 How to Read This Chapter

The preceding chapters recorded how the models were built; this chapter reports the readings. First, two reading rules restated (both appeared in Chapters 05 and 06; they are written out together here):

- **C0 measures how close a prediction came to the outcome**: it tops out at 1 and may go negative (below 0); it is not a win rate (Chapter 05). Scores are comparable only within the same basis — whether a number is a single-round score or a window mean, and which rounds it covers, is annotated alongside the number; single-round scores are noisy and are not used to judge model quality (04.4, 06.4).
- **When the evaluation happened**: every score in this chapter is a post-race evaluation of completed rounds — this research never released a prediction externally before a session; the fixed arrangement of publishing before a session begins only after this report is published.

The chapter unfolds in three parts: **① the full readings for the race line; ② the qualifying line's combined scorecard (a complete post-hoc evaluation of the 31 candidates over R03–R12) and the latest two rounds; ③ a faithful record of prospective validation and the error surface (in which situations the model fails, and how the errors are distributed)** — the qualifying-line scoring fault mentioned in 6.8 is expanded in ② and ③.

One more basis note before we begin: on the race side, the single-round score produces only the total (its scoring implementation is a simplified one, without per-segment detail), so this chapter presents race errors as position-by-position comparison (7.5); the qualifying side's scoring output retains all per-segment detail (the Chapter 05 specification; omitted from the main text, indexed in Appendix C).

## 7.2 The Race Line: Ten Rounds and Three Rounds

The race model's readings over all ten rounds R03–R12 are as follows (C0 single-round scores; the model is the optimized version described in Section 6.7, and the baseline sorts directly by grid position). First, the provenance of one rerun: the early-August breakthrough evaluation printed its results to the screen only and never wrote them to disk (6.5 records that lesson); in September we reran the entire evaluation and persisted it, reproducing the key numbers from that time — a first-seven-rounds model mean of 0.5380 and an R10–R11 two-round mean of 0.5918, consistent with the 0.5380 / 0.5917 reported at the time (a last-digit rounding difference). Each round is still recomputed under the forward constraint — each round's prediction uses only races before that round; the same holds for both the baseline and the model columns:

| Round | Event | Baseline | Model | Diff |
| --- | --- | ---: | ---: | ---: |
| R03 | Japan | 0.6060 | 0.6836 | +0.0776 |
| R04 | Miami | 0.4986 | 0.5133 | +0.0147 |
| R05 | Canada | 0.3967 | 0.4969 | +0.1002 |
| R06 | Monaco | 0.4283 | 0.4150 | **-0.0133** |
| R07 | Barcelona | 0.5160 | 0.5864 | +0.0704 |
| R08 | Austria | 0.6317 | 0.5550 | **-0.0767** |
| R09 | Silverstone | 0.5064 | 0.5160 | +0.0096 |
| R10 | Spa | 0.5160 | 0.6007 | +0.0847 |
| R11 | Hungary | 0.5717 | 0.5828 | +0.0111 |
| R12 | Zandvoort | 0.4614 | 0.6155 | +0.1541 |
| **Ten-round mean** |  | **0.5133** | **0.5565** | **+0.0432** |

*Note: the "ten-round mean" mixes three kinds of window (tuning, test, and the first round after the freeze) and is not meant for direct comparison against any single window's score — its role here is an all-period reference. The R06 (Monaco) actuals were later corrected following an appeal ruling (04.6); the September rerun took place before the actuals were re-collected, using the official classification as it stood before the judgment revision, without retrospective refresh; the size of the change after the correction has not been evaluated (the two bases are reported separately).*

Across the ten rounds the model won eight and lost two. No minimum-difference threshold is set for a "win" — +0.0096 also counts as a win; the count is descriptive, and the magnitude of single-round noise (6.4) means "eight wins, two losses" should not be read as a statistical conclusion. The two losing rounds deserve a separate look: **Monaco** (-0.013) is a street race — little room to overtake, few flips of the finishing order to begin with, and the baseline already close to the true order, so every nudge by the model was more likely a net loss; in **Austria** (-0.077) the baseline posted the ten-round high of 0.6317 — the same logic, amplified. A loss is a loss; both rounds stand on record as they are.

![Race model round by round](../assets/charts/race-by-round.svg)

*Figure: round-by-round scores for the race model and the grid-position baseline (R03–R14; from R12 onward these are prospective rounds under the frozen weights).*

After the weight freeze (6.8), the three rounds R12–R14 against the baseline (again single-round scores):

| Round | Event | Baseline | Model | Diff |
| --- | --- | ---: | ---: | ---: |
| R12 | Zandvoort | 0.4614 | 0.6155 | +0.1541 |
| R13 | Monza | 0.4464 | 0.6672 | +0.2208 |
| R14 | Madrid | 0.4928 | 0.5322 | +0.0394 |
| **Three-round mean** |  | **0.4669** | **0.6050** | **+0.1381** |

Three wins in three, though the margins are uneven: +0.15, +0.22, +0.04 (model score minus baseline score, in the R12, R13, R14 order). **The large R13 margin has a concrete origin**: at Monza, Antonelli was penalized to the back of the grid for a full power-unit change — the baseline (sorting by grid position) had him nowhere in its top ten, while the model ranked him P1 — and he won that race. The design assumption that "strong teams at the back will recover" (6.7) played out at Monza in its most extreme form.

**The R14 (Madrid) margin narrowed, and we record it as it is**: +0.0394 is the smallest of the three gaps; under the freeze discipline of 6.8, single-round movement is not grounds for changing weights — this observation goes on record, to be revisited when more prospective rounds exist. One more reading caution: the three-round baseline mean (0.4669) is well below the ten-round mean (0.5133) — these three races saw more shuffling of positions than a typical round, and the model's value lies precisely in "shuffle-heavy" races (7.5); part of the jump from +0.0432 to +0.1381 may come from this — a three-round sample supports no firm conclusion.

## 7.3 The Qualifying Line: The Combined Scorecard and the Latest Two Rounds

The qualifying line's official scorecard covers R03–R12, all of it post-hoc evaluation. Sorting the 31 candidates by combined mean, the top eight:

| Rank | Candidate | Combined mean | First seven rounds (R03–R09) | Late window | Rounds scored |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | #31 Slot Ensemble · Robust | **0.4835** | 0.5103 | 0.3898 | 9 |
| 2 | #30 Slot Ensemble · Peak | **0.4689** | 0.4992 | 0.3629 | 9 |
| 3 | #15 Borda (constructor double-weighted) | 0.4560 | 0.4617 | 0.4428 | 10 |
| 4 | #9 Elastic Net | 0.4500 | 0.4510 | 0.4476 | 10 |
| 5 | #13 Explainable score (tuned) | 0.4493 | 0.4702 | 0.3759 | 9 |
| 6 | #11 Explainable score (interaction) | 0.4458 | 0.4658 | 0.3759 | 9 |
| 7 | #7 Elastic Net | 0.4423 | 0.4390 | 0.4501 | 10 |
| 8 | #14 Borda (equal weights) | 0.4397 | 0.4475 | 0.4215 | 10 |

*Note 1 (basis): this table is the scorecard after the 2026-09-18 rerun, superseding the early-September version. The rerun was triggered by inconsistent run conditions: for "circuit history", one of the qualifying features, the data files for R10–R12 were missing in the early-September rerun (candidates effectively went in one reference short), while the two single-round replays of July (6.4) generated data on the spot under different conditions — their R10/R11 figures are therefore not comparable, and this table recomputes both under the same "complete data" condition. The rerun also absorbed one post-race judgment revision for R06 (the FIA revised the race classification and, with it, the standings; this had not entered the early-September version). R12 scores belong only to those candidates in this batch that remain scoreable.*

*Note 2 (round counts): the "combined mean" covers nine rounds, R03–R11, for the six entries and ten rounds, R03–R12, for the rest; the "first seven rounds" column is R03–R09 throughout; the "late window" is the two-round mean of R10–R11 for nine-round rows and the three-round mean of R10–R12 for ten-round rows. Scores spanning different round counts are indicative only and form no strict ranking.*

Three readings need explanation. First, **why there are nine-round rows**: before R12, Hadjar vacated his seat through injury — and six candidates happened to have him in their prediction lists, so those six candidates could not receive an R12 score (the six are #10–#13 and #30, #31; of these, four — #30, #31, #13 and #11 — sit in this table's top eight). Second, **the leaders' quality has to be read in two segments**: #31 and #30 led clearly over the first seven rounds (the window in which they were selected and tuned), at 0.510 and 0.517, but fell back to 0.390 and 0.363 over the out-of-window stretch (the two rounds R10–R11) — the lead inside the window did not fully carry outside it, and the drop is larger than the earlier basis showed; over the same rounds #9 and #7 (the two Elastic Net entries) were steady instead (0.448, 0.450). Third, among the candidates scored on the full ten rounds, the constructor double-weighted Borda (#15) is the strongest — what separates it from #14 is that the "constructor standings only" signal carries double weight while the other three are equal. Also, in the late-window column #13 and #11 are exactly equal (0.3759) — they produced the same predicted ordering in those two rounds, another instance of "near-duplicate variants" (6.2); #31's late window after the rerun (0.3898) no longer coincides with theirs, because while its T10/order slots share an origin with #13, its P1/T3 slots trace their own path.

The incremental evaluation over R13 and R14 moves the readings one step further (two-round means):

- **Among the 25 candidates eligible for these two rounds, the leader is a previously mid-table model**: #27 (Plackett-Luce, a probabilistic ranking model) — it ranks 26/31 on the combined scorecard (0.4043) yet tops these two rounds at 0.3972 (R13 Monza 0.3433, R14 Madrid 0.4512); behind it come #20 (Keener, 0.3929; running the α=0.25 configuration as registered — what 6.3 rejected was a different α=0.10 tuning; the two are not the same parameter set) and #7 (Elastic Net, 0.3878).
- The six candidates (including #30, #31) remain unscoreable in these two rounds — as long as the driver list changes mid-season, this fault will recur.
- Both rounds ran hard overall: nearly every classical candidate fell below its own combined mean (by roughly 0.05–0.10). Part of this can be pinned down: R13's actual top ten included Tsunoda — a new driver outside the season-start scoring universe, so every scoreable candidate necessarily missed that seat (the membership-segment loss alone is about 0.035). What caused the rest cannot be separated on the available sample. What this means is taken up in 7.4, where the two lines are placed side by side.

### Appendix: The Full Roster of 31 Candidates

The top-eight table covered only the leading part; the full picture of all 31 candidates in the registry follows (parameters are the configurations frozen at registration; the assembly details of #30, #31 are in 6.3):

| No. | Candidate | Family | Mechanism and key settings |
| ---: | --- | --- | --- |
| 1 | `latest_prior` | Simple baseline | Directly carries over the previous race's qualifying result |
| 2 | `season_to_date` | Simple baseline | Cumulative season-to-date qualifying positions |
| 3 | `constructor_only` | Simple baseline | Sorts by constructor only |
| 4 | `form_w3` | Simple baseline | Mean of the last three races' qualifying results only |
| 5 | `ridge_alpha_10` | Linear regression | Ridge regression α=10 |
| 6 | `ridge_alpha_5` | Linear regression | Ridge regression α=5 |
| 7 | `elastic_net_a020_l1_050` | Linear regression | Elastic net α=0.20, L1 ratio 0.50 |
| 8 | `elastic_net_a020_l1_070` | Linear regression | Elastic net α=0.20, L1 ratio 0.70 |
| 9 | `elastic_net_a001_l1_030` | Linear regression | Elastic net α=0.01, L1 ratio 0.30 |
| 10 | `explainable_interaction_default` | Explainable score | Track-type-adjusted weights · default configuration |
| 11 | `explainable_interaction_tuned` | Explainable score | Track-type-adjusted weights · tuned configuration |
| 12 | `explainable_independent_default` | Explainable score | Track profile as an independent term · default configuration |
| 13 | `explainable_independent_tuned` | Explainable score | Track profile as an independent term · tuned configuration |
| 14 | `borda_equal` | Borda count | Four ranking signals combined with equal weights |
| 15 | `borda_constructor_x2` | Borda count | Constructor signal double-weighted, the others equal |
| 16 | `elo_k16` | Head-to-head rating | Elo, K=16 |
| 17 | `elo_k32` | Head-to-head rating | Elo, K=32 |
| 18 | `massey` | Head-to-head rating | Massey least-squares rating |
| 19 | `colley` | Head-to-head rating | Colley least-squares rating |
| 20 | `keener_a025` | Head-to-head rating | Keener rating α=0.25 |
| 21 | `glicko_rd50` | Head-to-head rating | Glicko, initial uncertainty 50 |
| 22 | `glicko_rd150` | Head-to-head rating | Glicko, initial uncertainty 150 |
| 23 | `gaussian_pairwise_b417_t05` | Head-to-head rating | Gaussian pairwise approximation β=4.17, τ=0.5 |
| 24 | `gaussian_pairwise_b8_t0` | Head-to-head rating | Gaussian pairwise approximation β=8, τ=0 |
| 25 | `bradley_terry_delta0` | Probabilistic ranking | Bradley–Terry δ=0 |
| 26 | `bradley_terry_delta1` | Probabilistic ranking | Bradley–Terry δ=1 |
| 27 | `plackett_luce` | Probabilistic ranking | Plackett–Luce |
| 28 | `lambdamart_n100` | Learning-to-rank | LambdaMART, 100 trees |
| 29 | `lambdamart_n200` | Learning-to-rank | LambdaMART, 200 trees |
| 30 | `slot_ensemble_peak` | Slot ensemble | #9→P1 slot, #28→T3, circuit version→T5, #13→T10 and order (taken top-down) |
| 31 | `slot_ensemble_robust` | Slot ensemble | Elastic net→P1 and T3, circuit version→T5, #13→T10 and order (first come, first served) |

## 7.4 Prospective Validation in Practice

Set 7.2 and 7.3 side by side and the two lines turn out to give two different shapes of evidence:

- **The race line**: three wins in three rounds after the freeze (model 0.6050, baseline 0.4669, three-round means) — this is what the "freeze, then prospect" protocol wants to see: weights fixed at the freeze, results earned after it. To be clear, this protocol sets no pass line — what it requires is that post-freeze performance be reported as it is, not that success be declared; the judgment is left to a person (the decision-log mechanism of Chapter 09).
- **The qualifying line**: the two strongest in-window candidates fell back out of the window, the R13/R14 lead passed to a different candidate (a model ranked 26th on the combined table), and six candidates were absent round after round because of a roster change. The qualifying line has no corresponding "freeze" move — its shape is candidates running in parallel, tested continuously; what we see here is one real form of that approach meeting a mid-season roster change (nothing in this speaks to which line is more credible).

The explanation promised in 7.3 belongs here: R13 and R14 ran hard for the qualifying candidates overall (generally 0.05–0.10 below combined means), in the same direction as the race-line signal — both events swapped positions more than a typical round does (the race-side baseline over the same rounds was low too). "Heavy-shuffle" scenarios get harder for every method at once; this is an observation on a two-round sample, not a conclusion.

The six candidates' absence has no "resolution" mechanism — as long as the roster state is unchanged they stay unscoreable (that roster changes get no mechanism is a settled ruling, Chapter 09); this is itself one of the limits of "leading inside the window".

Neither line comes close to licensing "the model is reliable" (the 04.4 stance): three race rounds and two qualifying rounds are both single-digit samples. Read together, the three-round record holds one textbook pass (R13's extreme recovery caught), one narrowing (R14's +0.0394), and one scoring fault permanently on the books — different weights (two are single-round samples; one is an unsolved mechanism problem), but all laid out here as they are.

## 7.5 The Error Surface: Two Lost Rounds and One Case Study

**The two losing rounds** (listed in 7.2): Monaco and Austria. The former is a structural scenario (a street race leaves little room for position flips); in the latter the baseline posted the ten-round high (0.6317), leaving little to improve in the first place. Both point the same way: the model's value is highest in races where the order shuffles, and lowest in races where the order already hugs the grid. One caveat here: we have no independent metric for "degree of shuffle" — only a post-hoc proxy for now (a low baseline score for the round means the finishing order diverged far from the grid); whether it can be estimated before a session, the available material cannot answer — it goes into Chapter 08's open questions.

**One case study: the full R12 breakdown.** Zandvoort scored well on the total (0.6155), and this time the total can be taken apart: the exact-position segment took 0.1800 on 4/10, the membership segment 0.2450 on 7/10, and the internal-order segment 0.1905 with 40/42 pairs consistent — the three segments combine to exactly 0.6155, reproducible by rerunning the frozen scorer (rechecked while writing this report). The shape of the error:

| Position | Model prediction | Actual result | Correct? |
| ---: | --- | --- | --- |
| P1–P4 | Norris / Antonelli / Russell / Hamilton | Norris / Antonelli / Russell / Hamilton | All correct |
| P5–P6 | Piastri / Leclerc | Leclerc / Piastri | The two swap positions |
| P7 | Verstappen | Lawson | Wrong |
| P8–P10 | Lawson / Lindblad / Bortoleto | Hulkenberg / Alonso / Gasly | All three wrong |

The scoring comparison is simple: the two lists are matched cell by cell, each cell judged once. The three errors each have their own cause. P5–P6 is a **slot misplacement** — Leclerc and Piastri both made the actual top ten (no list members lost), but the model put the two in each other's slots (predicted P5/P6, actual P6/P5). The P7 prediction was Verstappen — he retired from this race and is not in the official classification; the official P7 slot is Lawson, so that cell is judged wrong. (Lawson occupies P8 in the model's list, set against the official P8 Hulkenberg — that is another cell's error.) P8–P10 is the model's clearest systematic gap — **too little recovery thrust from the back**: Hulkenberg climbed P13 to P8, Alonso P18 to P9, Gasly P11 to P10 — all three made the actual top ten, while the model filled P8–P10 with Lawson, Lindblad and Bortoleto — the names did not match. "How much thrust is enough" is not quantified (that requires first turning "recovery depth" into a scoreable quantity); no new experiment targeting it has been run either — under the freeze discipline, if it is run, it goes through an isolated experiment with pre-registration first (6.8). In this round's total, exact position and internal order both sit near their ceilings, and the gap at the back is masked by the points earned at the front.

**A documentation gap.** The first version in 6.1 carried a "reliability" item (worth 0.10) — that is the qualifying line's scoring, and the qualifying-side reliability feature is still in use today; the race-line situation we only pinned down by tracing the code: the first-version race model listed reliability in its feature spec and did read the value, but its combination formula distributed weight across four other items (recent form, constructor strength, circuit fit, pre-race evidence) and left none for reliability — that is, reliability never actually took part in a race-line prediction; the August standardization rewrite (6.7) stopped reading it, which only made the fact visible. No explicit decision to drop it can be found in the session records, and there is now a more concrete account: not "a working feature lost in the rewrite" but "a feature that, from the first version on, existed only on paper, quietly leaving the stage". But the process gap it exposed is real — the feature spec said it was used and the formula did not use it, and nothing in the record flagged that inconsistency (the lesson is recorded in the later discipline). The gap itself stays marked as it stands; it connects directly to the Verstappen example above — had reliability ever actually entered the model, "who might retire" would at least have been part of the prediction's considerations.

**A standing fault: the knock-on effects of a roster change.** One driver roster change around R12 (Hadjar stood down through injury; Lawson replaced him at Red Bull, and Tsunoda returned to the grid in Lawson's place) set off three layers of knock-on effects in this research, all recorded as they happened.

- **Cannot rank**: the six candidates (the #10–#13 explainable-score family and the two assembly versions derived from it) build their predictions by walking the season-start registration list — Hadjar had stood down, but on the list he still carries his historical results, gets scored, and lands in the top ten. Not scoring the round at all is what the scoring spec requires (if a prediction contains a driver not on the entry list it must raise an error; no silent substitution or proxy is allowed).
- **Invisible**: Tsunoda is not in the season-start scoring universe (the season-start roster does not have him) — no candidate built features for him, so he cannot appear in any prediction. When he finished 10th at R13, all 25 scoreable candidates necessarily missed that seat.
- **Mismatch**: after Lawson switched teams, his recent form and recovery history travel with the driver, but the "constructor strength" basis switched to Red Bull — the aggregation semantics of constructor points drift after a switch, and the model has no mechanism for that break.

We built no mechanism for any of the three layers — the shortest reason is in the Chapter 09 decision log: patching around roster assumptions would shake the design foundation that "every candidate stays traceable end to end". This is a known open item, and one of the largest problems the research has not yet begun to solve.

**One extra variable**: R14's Madrid is a circuit entering the calendar for the first time this year — same-circuit history starts from zero. Why it is listed here: it leaves the "same-circuit history" feature line absent at Madrid across the board, a structural gap for the qualifying systems that depend on it (the final race formula does not include that item, so its direct exposure is limited).

## 7.6 The Limits of These Numbers

Every comparison in this chapter rests on single-digit to low-teens counts of race rounds (the 04.4 basis: the independent sample is the race), none sufficient to support any claim of being "significantly better"; the race line's "eight wins, two losses" and "three wins in three" are descriptive statements, not proof of reliability (the two counts cover different rounds: "eight wins, two losses" is R03–R12, "three wins in three" is R12–R14 — R12 appears in both stretches). This research sets no "reliability line" either — 04.4 and 7.4 both said so: no declaration that "the model is reliable", and none that it is "unreliable"; the judgment is a human ruling over all the evidence together (Chapter 09), and this report's task is to lay the evidence in order.

Where the open items recorded in this chapter go: **the narrowed R14 margin and the insufficient back-of-field thrust** — on record, to be revisited (the freeze discipline of 6.8); **the scoring system's roster fault** — filed as an open item; **the Madrid variable** — to be re-evaluated when more "first running" rounds exist (when such a round appears is not ours to decide). The positive readings (R13's extreme recovery caught, R12's perfect top four, #27's two-round lead) do not enter the "where things go" list, because they need no follow-up action — they are in the record, awaiting the natural test of more rounds.

Before entering the discussion of Chapter 08, 7.7 first puts the full picture of the two lines together for a look.

## 7.7 The Full Picture: Versions and Candidates

Before the discussion, the full picture of both lines, side by side.

**The race line: a three-step ladder of versions.** On the test window (R10–R11), the scores of the three versions form a three-step ladder:

![Race version lineage](../assets/charts/race-version-ladder.svg)

*Figure: version iteration on the race line. The chart's annotation states each generation's change points; the middle, standardized version reported only a mean and left no round-by-round scores.*

The round-by-round distributions of the baseline and the final version, side by side (12 rounds each, R03–R14):

![Race version box plots](../assets/charts/race-version-box.svg)

*Figure: round-by-round distributions for the baseline and the final version. The final version's median and interquartile range sit above the baseline's as a whole.*

**The qualifying line: all 31 candidates.** In descending order of combined mean:

![Qualifying candidates, bar chart](../assets/charts/qualifying-bars.svg)

*Figure: combined means of the 31 candidates; #30, #31 (in red) are the two final assembly versions, their configurations in 6.3.*

![Qualifying candidates, box plots](../assets/charts/qualifying-box.svg)

*Figure: each candidate's single-round score distribution over its own scoreable rounds; the box is the interquartile range, the center line the median, the whiskers the extremes.*

Two reading notes for the charts. First, the top of the qualifying line still has a small break: #31 and #30 (0.4835, 0.4689) lead third place by about 0.013 — the gap is narrower than on the pre-rerun basis, and, as 7.3 said, this lead shrinks more visibly out of window, so read the charts with that note in hand. Second, in the lower half of the box plots some candidates' distributions extend below 0 — C0 may go negative (the reading rule of 7.1; one concrete instance: in R11 the constructor-only #3 took -0.0266, 6.4).

### Appendix: Single-Round C0 Detail, 31 Candidates × 12 Rounds

The table below is the complete data behind the box plots: each cell is the candidate's single-round C0 in that round; "—" means not scoreable. Six entries — #10–#13 and #30, #31 — are unscoreable in the three rounds R12, R13, R14: after the roster change their prediction lists contain a withdrawn driver, and the scoring contract allows no score (7.3); the remaining candidates are scoreable at R14 as usual, even though that round's qualifying record itself carries only 20 rows (the upstream data source is missing 2 cars) — the gap is kept on record.

| Candidate | R03 | R04 | R05 | R06 | R07 | R08 | R09 | R10 | R11 | R12 | R13 | R14 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| #01 | 0.5241 | 0.3431 | 0.2847 | 0.2350 | 0.3748 | 0.5094 | 0.5860 | 0.4303 | 0.3388 | 0.4165 | 0.4004 | 0.2826 |
| #02 | 0.3446 | 0.3830 | 0.4131 | 0.3962 | 0.3564 | 0.4816 | 0.5298 | 0.4060 | 0.3786 | 0.5047 | 0.3758 | 0.3967 |
| #03 | 0.3206 | 0.4707 | 0.4232 | 0.4235 | 0.3184 | 0.4215 | 0.4931 | 0.3609 | 0.3431 | 0.5192 | 0.3704 | 0.4031 |
| #04 | 0.3446 | 0.3830 | 0.3778 | 0.3828 | 0.3555 | 0.4702 | 0.5673 | 0.3663 | 0.4543 | 0.4454 | 0.3024 | 0.3750 |
| #05 | 0.3236 | 0.3906 | 0.4232 | 0.4280 | 0.3756 | 0.5133 | 0.5349 | 0.3588 | 0.5127 | 0.4002 | 0.3389 | 0.3879 |
| #06 | 0.3236 | 0.3145 | 0.4491 | 0.4280 | 0.3184 | 0.5089 | 0.5349 | 0.3588 | 0.5127 | 0.4713 | 0.3174 | 0.3879 |
| #07 | 0.4629 | 0.3981 | 0.4491 | 0.4235 | 0.3208 | 0.4890 | 0.5298 | 0.4060 | 0.5127 | 0.4315 | 0.3389 | 0.4368 |
| #08 | 0.4629 | 0.3831 | 0.4305 | 0.4235 | 0.3208 | 0.4890 | 0.5298 | 0.4060 | 0.5127 | 0.4359 | 0.3389 | 0.4019 |
| #09 | 0.4629 | 0.3981 | 0.4232 | 0.4280 | 0.3711 | 0.5133 | 0.5601 | 0.3588 | 0.5127 | 0.4713 | 0.3389 | 0.4083 |
| #10 | 0.4243 | 0.4089 | 0.3883 | 0.4025 | 0.3711 | 0.6014 | 0.4639 | 0.3353 | 0.4832 | — | — | — |
| #11 | 0.4243 | 0.4525 | 0.3958 | 0.4737 | 0.3970 | 0.5763 | 0.5409 | 0.3442 | 0.4076 | — | — | — |
| #12 | 0.4769 | 0.4089 | 0.3853 | 0.3418 | 0.3756 | 0.6014 | 0.4639 | 0.3353 | 0.4832 | — | — | — |
| #13 | 0.4769 | 0.4525 | 0.3958 | 0.4737 | 0.3756 | 0.5763 | 0.5409 | 0.3442 | 0.4076 | — | — | — |
| #14 | 0.3416 | 0.3832 | 0.4319 | 0.4313 | 0.4317 | 0.5503 | 0.5624 | 0.4195 | 0.4742 | 0.3707 | 0.3389 | 0.3284 |
| #15 | 0.3739 | 0.3862 | 0.4319 | 0.4528 | 0.4317 | 0.5933 | 0.5624 | 0.4060 | 0.4727 | 0.4496 | 0.3389 | 0.3805 |
| #16 | 0.4453 | 0.3134 | 0.3461 | 0.3498 | 0.4392 | 0.4702 | 0.4743 | 0.4239 | 0.4158 | 0.3883 | 0.3069 | 0.4019 |
| #17 | 0.4849 | 0.3136 | 0.4092 | 0.2956 | 0.4126 | 0.5005 | 0.5358 | 0.4195 | 0.3848 | 0.3958 | 0.2699 | 0.3085 |
| #18 | 0.4513 | 0.4204 | 0.4131 | 0.3917 | 0.3564 | 0.4816 | 0.5298 | 0.4060 | 0.3786 | 0.4772 | 0.3758 | 0.3967 |
| #19 | 0.3446 | 0.4204 | 0.4131 | 0.3962 | 0.3564 | 0.4816 | 0.5298 | 0.4060 | 0.3786 | 0.4772 | 0.3758 | 0.3967 |
| #20 | 0.4438 | 0.3830 | 0.3828 | 0.3962 | 0.4141 | 0.5325 | 0.5624 | 0.4060 | 0.3202 | 0.4062 | 0.3818 | 0.4039 |
| #21 | 0.4453 | 0.3830 | 0.3461 | 0.3828 | 0.4738 | 0.4702 | 0.4743 | 0.4195 | 0.4158 | 0.3883 | 0.3069 | 0.4019 |
| #22 | 0.4453 | 0.3830 | 0.3461 | 0.3843 | 0.4317 | 0.4702 | 0.4743 | 0.4195 | 0.4158 | 0.3958 | 0.3069 | 0.4019 |
| #23 | 0.3461 | 0.2566 | 0.4432 | 0.3633 | 0.4053 | 0.5409 | 0.4263 | 0.4943 | 0.2864 | 0.4439 | 0.3535 | 0.3975 |
| #24 | 0.3902 | 0.2522 | 0.4388 | 0.3999 | 0.4355 | 0.5830 | 0.4338 | 0.3514 | 0.2687 | 0.4713 | 0.3026 | 0.4263 |
| #25 | 0.4453 | 0.4204 | 0.4131 | 0.3962 | 0.3579 | 0.4816 | 0.5298 | 0.4060 | 0.3786 | 0.4648 | 0.3758 | 0.3967 |
| #26 | 0.4378 | 0.3830 | 0.4131 | 0.3962 | 0.3579 | 0.4816 | 0.5601 | 0.4060 | 0.3786 | 0.4678 | 0.3758 | 0.3967 |
| #27 | 0.2978 | 0.4788 | 0.4131 | 0.3513 | 0.3461 | 0.4158 | 0.5023 | 0.4074 | 0.3505 | 0.4797 | 0.3433 | 0.4512 |
| #28 | 0.2792 | 0.3859 | 0.3622 | 0.6033 | 0.4231 | 0.4770 | 0.3405 | 0.2737 | 0.2699 | 0.4418 | 0.2586 | 0.3214 |
| #29 | 0.2822 | 0.3859 | 0.4050 | 0.6303 | 0.4187 | 0.4047 | 0.3714 | 0.2737 | 0.2773 | 0.3623 | 0.2556 | 0.3139 |
| #30 | 0.4029 | 0.4525 | 0.4912 | 0.6323 | 0.4949 | 0.5980 | 0.4225 | 0.3183 | 0.4076 | — | — | — |
| #31 | 0.5155 | 0.4525 | 0.4658 | 0.5269 | 0.5502 | 0.5763 | 0.4846 | 0.3183 | 0.4614 | — | — | — |

The two full pictures end here; the limitations, work in flight, and open questions they raise are all in Chapter 08.
