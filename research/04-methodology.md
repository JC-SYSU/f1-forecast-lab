# 04 · Methods and Data Discipline

## 4.1 Leakage Prevention: Making 'What Was Known Then' Checkable

The credibility of a forecast rests, first of all, on temporal honesty. But the statement "we use only pre-session information" is not itself checkable — anyone can say it. The only way to make it checkable is to record what the state of knowledge was at the time. For this purpose we set up three recording points.

Each time we run a prediction, we first write down an **as-of profile**: which rounds have been completed at this moment, which materials have been archived, which manually curated evidence has been filled in. The prediction is allowed to cite only the materials listed in the profile. At the same time, the run must explicitly declare its **reference data scope**; information outside that boundary may not enter. Finally, every experiment leaves behind a **run manifest**: the target, model configuration, as-of profile, feature set, evaluation window, input assets, output files, and known data gaps.

A concrete example: when predicting R12 (Zandvoort), the latest race the model could see was R11 (Hungary) — even though the result of R12 had long since been settled in the eyes of whoever wrote that profile. The order of events is the order of events.

Taken together, the three recording points guarantee one thing: any historical prediction can be reconstructed. Whether the same inputs reproduce the same outputs is a question that can be tested by hand, not one that has to be taken on trust.

## 4.2 Backtest: Event-Grouped Forward Validation

Our backtest uses event-grouped expanding walk-forward validation: races are ordered in time, and when predicting round N the model uses only data from the preceding N−1 rounds. This reproduces the real situation — a prediction made before a round can only ever use the past, with no exceptions.

Two practices are explicitly forbidden within this backtest.

The first is random splitting of same-weekend data. Over one race weekend, 22 drivers run on the same circuit, in the same day's weather, under the same equipment conditions — their performances are correlated. Randomly assigning data from the same round to a training set and a test set amounts to letting the model see the exam paper before the exam: scores would be inflated, and by an amount that cannot be estimated. Existing research likewise argues for temporal validation rather than random cross-validation in sports prediction<sup>[1]</sup>.

The second is "looking at the results first, then picking the window". Once a set of evaluation rounds is fixed, it is frozen: results may not drive rounds into or out of the window, still less influence model selection. If a round that happened to score especially well were added to the next month's evaluation scope, the evaluation would lose its meaning. Every change to the window is logged on record, stating the timing of the change and the reason for it.

## 4.3 Grading of Data and Evidence

Not all data is equally trustworthy. Our source hierarchy starts with official materials (public documents from the FIA, F1, and the teams), passes through structured data sources (public race APIs), news media, and community content, and ends with manual snapshots as the fallback. The higher the tier, the closer to the fact itself; the lower the tier, the closer to someone else's retelling.

One boundary here is easy to overlook: **the tier of a source is determined by the provenance of the evidence, not by the tool used to fetch it**. A public API is the pipe through which we obtain data, not an authoritative source. The same set of lap times is one thing when it comes from the official timing system and another when it comes from a forum post — even if both were scraped by the same script, their tiers differ. The original provenance, access parameters, and known limitations of every source are recorded alongside the data.

When collecting data we follow "check before fetching": before reaching for the network we look in the archive — if the same data has already been stored and the hash matches, we reuse it and do not go online. Every archive entry carries a set of metadata: URL, retrieval time, parameters, HTTP status code, content type, content hash. Failed accesses are archived as well — if a data source refuses service while a race is in progress, that failure is an objective record, kept, not deleted. The next time someone asks "why was this data missing at the time", the answer is in the archive.

## 4.4 Statistical Stance Under a Small Sample

Our sample is small, and we say so plainly: roughly 10 races, 22 drivers per round. The data tables hold more than two hundred rows, but the number of independent "events" is only about ten — every metric carries substantial random variation. Three positions follow from this.

We make only descriptive comparisons. It is fair to say "A's top-ten hit rate over the first eight rounds is 60%, B's is 55%, and leave-one-out analysis puts A's range of variation within plus or minus 15 percentage points"; it is not fair to say "A is significantly better than B". The first is an honest description; the second is a claim a small sample cannot support.

Robustness is tested with leave-one-event sensitivity and bootstrap resampling rather than p-values; existing designs for comparing the stability of ranking methods are also available to draw on<sup>[2]</sup>. Finally, every number must carry its specification — window, model version, candidate set. A number without its specification is not allowed into a conclusion.

## 4.5 Why the Four Models Are Independent of One Another

The four targets share one setting — the race weekend — but what they predict differs in kind. Qualifying is the product of single laps and tire windows; the race adds strategy, pit stops, and reliability on top. From this we established an isolation principle: each target's parameters, feature boundaries, fallback behavior, and evaluation gates are fully independent; the only things that may be shared are infrastructure, such as entity tables, data loading, archiving, generic metrics, and generic ranking utilities.

Strict isolation exists to prevent contamination. That a parameter works for qualifying does not mean it works for the race; moving it over automatically amounts to injecting qualifying's noise into the race. Any cross-target reuse must be backed by evidence and registered item by item.

## 4.6 Traceability and Engineering Habits

Several engineering habits underpin the discipline above. Every experiment corresponds to one commit, whose message states the scope, the result, and how it was verified; the data itself does not enter version control — what enters is its hash and metadata; and the output of every prediction can be traced back to three things — the as-of profile at the time, the hashes of the input assets at the time, and the code commit at the time.

There is also an agreement about wording. "Frozen" has a precise meaning in this research: once weights, parameters, or an evaluation specification are frozen, any change afterwards is a new experiment, and history must not be silently rewritten. This rule has been put to a real test: the actuals for R06 (Monaco) were later corrected following an appeal ruling, and the affected rounds had their data re-collected, but the old scores already on record were not retroactively refreshed — the transition point is marked as it happened, and the old numbers are reported under the old specification.

These disciplines predate any model. They do not produce predictions, but they determine whether a prediction's numbers deserve to be believed. The next chapter turns to the most home-grown, and most heavily examined, part of this research: **the scoring system**.

## References

1. *A machine learning framework for sport result prediction*. ScienceDirect. https://www.sciencedirect.com/science/article/pii/S2210832717301485
2. *A Forward-Looking Approach to Compare Ranking Methods for Sports*. MDPI Information. https://www.mdpi.com/2078-2489/13/5/232
