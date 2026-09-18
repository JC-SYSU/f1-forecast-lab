# 02 · Research Plan

## 2.1 Research First, Then Build

In domains with sparse samples and shifting distributions, a wrong methodology decision is expensive: an unsuitable architecture may only surface after months of iteration, while the observation budget is one season per year. We therefore established an up-front discipline — the **Research-First Protocol**: before designing a model for a target, a systematic survey must be completed first, covering academic literature, industry practice, and the open-source ecosystem; only after the survey's conclusions pass a feasibility check may modeling begin.

During plan drafting we wrote this discipline, together with two other concepts (dual-track exploration and feasibility gating), into the glossary as the three bottom lines constraining all subsequent work.

## 2.2 The Four-Round Survey Structure

We organized the survey into four progressive rounds, each with explicit trigger conditions and output forms:

| Round | Task | Trigger condition |
| --- | --- | --- |
| Round 1 · Domain scan | Map the method landscape: one column each for F1-specific, general sports prediction, and general ranking | Plan kickoff |
| Round 2 · Paradigm gap-filling | Targeted supplements for the coverage gaps exposed by Round 1 | Fewer than 5 paradigm categories covered in Round 1, or fewer than 10 records in the general-ranking layer |
| Round 3 · In-depth assessment | Read the full text of each candidate method's source; assess transferability and data feasibility | Rounds 1 and 2 complete |
| Round 4 · Implementation references | Add the libraries, APIs, and engineering references needed for implementation | At the end of Round 3, any of the three questions below is still unanswered |

**Stopping rule.** The survey does not run indefinitely. It converges only when it has answered three questions:

1. **Feature list** — which input features, supported by literature or practice, the predictions should use;
2. **Paradigm comparison** — the respective theoretical strengths and weaknesses of the score-based and lap-time-based routes;
3. **Evaluation design** — how to choose backtest windows, and how much credibility each metric has on single-digit sample sizes.

The survey ends when all three questions have evidence-backed answers.

## 2.3 Feasibility Gating

We set a data-feasibility check on every candidate method: the required data must either already be in hand or have a clear acquisition path. Methods that fail the gate are recorded as "not applicable" with the reason noted and are not carried into design — this stops methods that are feasible on paper but not in practice at the entrance, so they cannot contaminate the later architecture.

## 2.4 Order of Progression Across Targets

We did not advance the four targets in parallel: qualifying comes first, for four reasons:

- **Stronger outcome determinism.** Single-lap pace is less exposed to race-day randomness such as retirements and safety cars; of the four targets it is the "cleanest".
- **Unique lap-time output.** Qualifying and sprint qualifying are the only two targets that output lap times; building them first directly tests the value of pace-type features.
- **Input to the race.** Qualifying predictions are themselves a feature source for the race model; a model built well early passes value downstream.
- **Backtest material at hand.** Official qualifying results for multiple consecutive rounds were already available for backtesting; the starting point was not zero.

The race comes second — it can use the qualifying model's outputs directly. The two sprint targets come last: fewer sprint rounds, thinner samples, and a weekend format that differs from the standard one.

## 2.5 Dual-Track Exploration

For targets with lap-time output we do not presuppose a paradigm: **score-based** (aggregate each driver into a score and rank by score) and **lap-time-based** (predict lap times directly and rank by time) are surveyed in parallel and designed in parallel. The final choice, combination, or layering follows the evidence — for example, a score-based ranking skeleton with a lap-time-based conditional layer. Until the evidence arrives, neither line may be locked in.

## 2.6 Executing the Plan

We finalized this plan in early July 2026 and began executing it immediately: the four survey rounds were completed within days and produced a formal methodology-feasibility conclusion (Chapter 03), and the first implementation route was locked in accordingly (Chapter 04). Several methodology-level revisions occurred during execution — each is registered in the "Decision Log" (Chapter 09).
