# Appendix D · Glossary

Terms are explained as they are actually used in the main text; the chapter where each term is first described in detail is given at the end of the entry.

## D.1 Scoring and Evaluation

| Term | Explanation | Chapter |
| --- | --- | --- |
| C0 | A scoring scale of our own devising: a score for a single session that tops out at 1 and may go negative | 05 |
| C0 mean | C0 averaged with equal weight across rounds; tops out at 1, and the single criterion once scoring was unified | 06 |
| membership segment | One of C0's three segments (35%): how many got in, counted through the Top3/5/10 intersections | 05 |
| exact-position segment | One of C0's three segments (45%, the largest weight): predicted versus actual position, compared slot by slot | 05 |
| combo bonus (consecutive-hit run) | A bonus inside the exact-position segment for consecutive-hit runs; longer runs are amplified | 05 |
| distance penalty | A deduction by the gap between predicted and actual position; can pull C0 below zero | 05 |
| internal-order segment | C0's third segment (20%): how many of the 45 pairwise orderings inside the predicted list are recovered | 05 |
| evaluation window | A fixed set of evaluation rounds, hard-set to R03–R09; results must not influence additions or removals | 04 |
| first seven rounds | The R03–R09 block of the scorecard; the window in which candidates were tuned and selected | 07 |
| latter segment | The out-of-window block of the scorecard: R10–R11 in the nine-round row, R10–R12 in the ten-round row | 07 |
| LOEO | Leave-one-event-out validation (the main text calls it leave-one-out validation): each of the seven rounds is held out once, in turn, to re-check the gain | 06 |
| isolated experiment | A new idea does not enter the model directly; it first runs in a side branch, compared head-to-head with the current version | 09 |
| pre-registration | For any promise to "verify later", the criteria are locked before the data is looked at, to guard against picking the data afterwards | 09 |
| quantitative threshold | The bar requiring a gain to reach a preset value (+0.010) before a decision can be revisited | 09 |

## D.2 Models and Features

| Term | Explanation | Chapter |
| --- | --- | --- |
| candidate | A competing method implemented as a runnable model and registered under a number, e.g. #1–#31 | 06 |
| registry | The candidate registration system, which makes every score traceable to a number and a configuration | 09 |
| family | The 8-family grouping of the candidates; same-family members are near-variants and cannot be counted as independent models | 06 |
| related group | The decision log's name for the same grouping; identical in referent to "family" | 09 |
| slot ensemble | Splitting by position band and taking each band's ordering from the strongest candidate for that band (#30/#31) | 06 |
| recent form (form) | The average score of a driver's three most recent qualifying results; final weight 3.0 on the race line | 06 |
| recovery rate (racecraft) | A driver's historical rate of finishing better than grid-position expectation | 06 |
| constructor strength | Team points divided by the leading team's points, ranging from 0 to 1 | 06 |
| circuit fit | A single item: historical qualifying results on the same circuit over the past five years | 06 |
| reliability | A finishing-rate feature; in use on the qualifying line, it never actually took part in prediction on the race line | 06, 07 |
| track profile | Features attached by circuit type; two approaches exist — a standalone item, or adjusting the weights of other items | 06 |
| interaction / independent (two variants) | The former lets circuit type adjust the weights of other items; the latter enters as a standalone item | 06 |
| the monotone-transform problem | Every feature correlates strongly with grid position, so a linearly weighted sum cannot move the ordering | 06 |
| scoring universe | The driver roster used for scoring and prediction, frozen as the season-opening list | 05 |
| elastic net | A regression with mixed Ridge and Lasso regularization, outputting strength scores | 06 |
| LambdaMART | A learning-to-rank method that optimizes the ranking objective directly | 06 |
| Borda count | Turns several ranking signals into scores by position and combines them into one overall ranking | 06 |
| Plackett–Luce | A probabilistic ranking model of "who finishes ahead of whom" | 06 |

## D.3 Data and Operations

| Term | Explanation | Chapter |
| --- | --- | --- |
| R numbering | "R + number" denotes a round of the 2026 season; R01 is the first | 01 |
| replay | A post-race simulation rerun using only data from before that round; not a prediction published before the session | 06 |
| out-of-window evidence | Races from R10 onward are examined as a separate line and do not flow back into the tuning window | 06 |
| the third window | The race phase after the race weights were frozen: no preset endpoint, and every round counts | 06 |
| freeze | Once weights or conventions are fixed, any change is a new experiment, and old scores are never rewritten retroactively | 04 |
| prospective validation | Round-by-round real testing after the freeze; reported as it is, with no pass line | 06 |
| actuals | The stored records of each round's official results; the object of scoring comparison | 04 |
| official-label overlay | When actuals are loaded, the official label list (DSQ, judgment revisions) is forcibly overlaid | Appendix B |
| circuit history | The archive of historical qualifying results on the same circuit; a missing file there once triggered a full rerun | 07 |
| run manifest | The machine-readable record of every experiment: configuration, as-of cross-section, inputs and outputs, and gaps | 04 |
| as-of | A time cross-section: the list of material knowable at prediction time; only material inside the cross-section may be cited | 04 |
| input snapshot | The field in run artifacts that records input SHA-256 hashes, for reproduction and comparison | Appendix B |
