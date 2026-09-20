# 01 · Origins

## 1.1 Background and the Nature of the Problem

Pre-race prediction of sports results is one of the long-running active problems in data science: mainstream sports such as football, basketball, and cricket have accumulated systematic methodological traditions, from rating systems to learning-to-rank, each with transferable practice. F1 is a peculiar research subject. A single race weekend contains two prediction tasks of different natures — qualifying is a close-quarters contest decided by one lap, while the race is a nearly two-hour long run spent coexisting with randomness; results are decided jointly by driver, car, and strategy; public data is abundant (official timing, weather records, and steward documents are all obtainable), yet effective samples are extremely sparse — a season holds only twenty-odd events, and independent observations are far fewer than the row count of a data table.

The inherent difficulties of pre-race F1 prediction can be summarized in four points:

- **Few samples.** Each round produces only one event-level observation; the available historical events are counted in single digits to a dozen or so, and any modeling route that needs large samples is constrained here from the start.
- **Distribution shift.** Generational changes in technical regulations, the pace of constructor upgrades, and mid-season driver seat changes all dilute the transfer value of historical data. The 2026 season happens to be a regulation-change year, which makes this point especially prominent.
- **Inherent randomness.** Reliability failures, accidents, safety cars: a substantial share of race results is not decided by speed.
- **The information time boundary.** A rigorous study must restrict inputs to what is knowable pre-race. This is a matter of discipline, and it is also where backtesting most easily breaks down.

## 1.2 Existing Research and Gaps

Before designing methods, we first completed a round of systematic surveying (details in Chapter 03): four rounds of retrieval recorded 74 methods/references in total, of which 45 went through full-text assessment and a feasibility judgment. Several observations that had a decisive influence on the design:

- Methodological accumulation in sports prediction is concentrated in the mainstream sports. Ordinal regression, rating systems (Elo and its variants), and learning-to-rank all have mature applications in college sports and professional leagues, and the transfer path to F1 is clear.
- Existing F1 research centers on race strategy simulation and lap-time modeling; work that directly predicts the final result before the race is comparatively scarce.
- Three widespread gaps. **First, crude evaluation**: a single hit rate hides the ordinal structure of ranking — a systematic review of sports modeling literature that we surveyed notes that 53% of ordinal regression studies did not validate their proportional-odds assumption. **Second, weak validation**: random splits and post-hoc tuning are pervasive, and a protocol of "freeze the model first, then face genuinely unseen data" is missing. **Third, closed processes**: there is almost no prediction research that makes its failures, falsifications, and decision process public together.

## 1.3 This Study

Addressing the gaps above, we began a prediction study that is documented end to end and makes its entire process public (the report you are reading is its public carrier): over the 2026 season we predict, round by round, the top 10 of four kinds of lists — sprint qualifying, sprint race, qualifying, and race (the two qualifying-type targets also output lap time and the relative gap to pole):

| Target | What is predicted | Additional output |
| --- | --- | --- |
| Sprint qualifying | Top 10 | Lap time, relative gap to pole |
| Sprint race | Top 10 | — |
| Qualifying | Top 10 | Lap time, relative gap to pole |
| Race | Top 10 | — |

The four targets are each modeled independently; parameters, feature boundaries, and evaluation gates are not inherited from one another. The only shared pieces are infrastructure such as data loading, archiving, and generic metrics.

The "lap time, relative gap to pole" of the qualifying-type targets in the table is a deferred output: the implementation route placed lap times in a "lap-time layer that requires additional data aggregation" (Chapter 03), and it had not yet landed when this report was written.

The prediction scope is limited to the top 10, for two reasons. First, deliberately narrowing the task's difficulty — prediction and evaluation answer only for the top 10, not for the complete ordering of all 22 drivers (the model still ranks the full field internally, but the outward commitment and the evaluation stop at the top 10). Second, focusing evaluation on the band of positions that is genuinely fought over in a race — the top 10 is exactly the boundary of the points-paying zone, and the leading positions are also where fan and media attention sits.

The study design responds directly to the three gaps above:

1. **as-of discipline**: each prediction is bound to a "time cross-section" (as-of profile) — which rounds had been run at that moment, which materials had been archived, which evidence had been filled in; nothing that happened afterwards may flow back. Evidence is used according to authority level: official sources (FIA, F1) take precedence, and public data sources such as OpenF1 and Jolpica are collection channels, not authority levels. When data is missing, report the gap; do not invent numbers.
2. **A home-grown scoring system**: for the ordinal structure of ranking prediction, we designed and froze a scoring system (called C0 in this report), evaluated along three dimensions — membership, exact position, and internal order (for the design and validation process, see Chapter 05).
3. **The freeze–prospective protocol**: only races held after the model weights are frozen count as a genuine test; planned changes first go into an isolated experiment, and important candidates are adjudicated by a pre-registered blind test.

## 1.4 Main Contributions

1. A publicly run F1 season prediction study: four independent target models, strict anti-leakage procedures, and round-by-round output of predictions and reconciliation.
2. A fully public scoring system for ranking prediction: the full path from expressing subjective demands as constraints through 84 preference questions, to solving for the feasible region of the parameters with a solver, and on through synthetic audit and real-world sensitivity analysis to parameter freezing.
3. A working sample of the "freeze + prospective + pre-registration" validation protocol, including changes that were rejected for missing the gate, and complete records of all failures and falsifications.
4. Reproducible artifacts: code, scoring outputs, decision logs, and the research log.
5. A record of a human–AI collaborative research workflow (Appendix F).

## 1.5 How This Report Is Organized

This report uses "R+number" to denote the rounds of the 2026 season (R01 is the first round, R12 the 12th — Zandvoort, for example). Chapter 02 sets out the research plan and the phase breakdown; Chapter 03 summarizes the survey; Chapter 04 explains methods and data discipline; Chapter 05 details the scoring system; Chapter 06 tells the two model lineages as two separate stories — the qualifying line from its human factors to its 31-candidate field, the race line from the variant family to the formula-slot audit; Chapter 07 presents each line's results in the same order, then the one experiment that crossed both; Chapter 08 discusses limitations and work in progress; Chapter 09 brings together the key decisions. The appendices contain the data documentation, a reproduction guide, a scorecard index, a glossary, the research log, and how the collaboration works.
