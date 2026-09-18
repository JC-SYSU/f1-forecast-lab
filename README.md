[中文版](README.zh-CN.md) | English

# f1-forecast-lab

A forecasting research project on the 2026 Formula 1 season: predicting the top ten of each qualifying session and race, round by round, on a fixed scoring scale with traceable evidence. Predictions, decisions, and failures are all archived in the open.

It is not an "accurate predictions" showcase. It is a worked answer to three harder questions: how a method says "we don't know" when the evidence is thin; how a model behaves once frozen and exposed to real races; and how to put a mistake on the record instead of quietly patching it.

## How it works

1. **Two model lines.** Qualifying: 31 candidates run in parallel on one frozen scoring scale, with rounds outside the tuning window as continuing checks. Race: start from a grid-order baseline, diagnose, redesign, freeze the weights, then let every real round count. The lines are independent; their scores are never compared.
2. **One scale, mined from fan intuition.** Nobody can write down what "a good predicted top-ten list" means — but every fan has an intuition. C0, the in-house score, treats that intuition as data: an 84-question formal interview (every ruling recorded verbatim) turned vague comparisons into explicit statements; a blind questionnaire (question order frozen, model scores never visible) collected preferences; a solver then found the parameters satisfying all stated constraints, with a proof that the feasible set is non-empty. Every weight is the solution to declared preferences, not a tuned number. Full provenance in Chapter 05.
3. **Humans decide.** AI proposes, executes and checks evidence; a human makes every freeze and every rejection. New ideas run as isolated experiments; serious candidates go through pre-registered blind tests; a gain below the threshold never enters the mainline.

## Results so far

- **Race line**: after the freeze, the model beat the grid-order baseline in all three real rounds — 0.6050 vs 0.4669 on means, with uneven margins (+0.15, +0.22, +0.04). In R13 at Monza it put the back-of-grid penalty carrier Antonelli first, and he won.
- **Qualifying line**: on the recomputed combined table, slot ensemble #31 leads at 0.4835 — a mixed-round reference, since #31 is scored on 9 of 12 rounds. Its in-window 0.5103 fell to 0.3898 outside the window.
- **Two rejections on the record**: the constructor-strength correction missed its +0.010 threshold and became a pre-registered blind test; the name-list mechanism was ruled out entirely — patching line-up assumptions would break candidate traceability.

## What it doesn't do

- It never claims reliability. Three prospective race rounds and single-digit samples everywhere; every comparison is descriptive, not significant.
- It has no mechanism for mid-season line-up changes. Six candidates became unscoreable for three rounds and a rookie was invisible to every model — the costs are documented, not patched.
- Full prediction (sprint weekends, lap times) is gated off; the lap-time layer has not started.
- The correction blind test's first trigger (R14) has finished but its ruling is not yet logged — the late logging is itself on the record.

## How to explore

- Results: Chapters [07](research/07-results.md) and [08](research/08-discussion.md). The scoring scale: [Chapter 05](research/05-scoring-system.md). Decisions: [Chapter 09](research/09-decision-log.md).
- Scorecards and scores: [`predictions/`](predictions/README.md). The data layer: [`data/`](data/README.md).

## How to reproduce

Give your agent this block — it reads the reproduction guide and does the work:

```
The source repository is https://github.com/JC-SYSU/f1-forecast-lab. Clone it, read appendix/b-reproduction.md in full, then execute it: verify the data layer, run the frozen race model on a round, rerun the qualifying scorecard scripts, and finally run PYTHONPATH=src python3 -m pytest tests -q. Report the test counts (expect 270 passed, 24 failed — the 24 are end-to-end tests needing the undistributed raw archive). Do not modify anything under src/.
```

To read by hand: [appendix/b-reproduction.md](appendix/b-reproduction.md), with the scorecard field reference in [appendix/c-scorecards.md](appendix/c-scorecards.md).

## Where things live

`research/` nine report chapters · `appendix/` six appendices · `src/ scripts/ tests/` the selected, de-identified code · `data/` the cleaned data layer · `docs/` official-label manifests · `predictions/` every prediction and C0 score · `assets/charts/` the report figures.

## License

Code: MIT ([LICENSE](LICENSE)). Narrative text: CC-BY-4.0 ([LICENSE-docs](LICENSE-docs)).
