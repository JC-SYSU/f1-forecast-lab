# Appendix F · Research Process and Collaboration

The working arrangements that the main text mentions only in passing are set out here once: how the division of labor is drawn, where the records live, what constrains quality, and how failures are archived. Everything below is practice that was actually carried out; no methodological claims are made.

## F.1 Division of Labor

The human carries three kinds of work: setting the research direction (the scoring scale first; lap times kept as a conditional layer); making every freeze and veto decision (the qualifying iteration freeze, the race weight freeze, the veto of two mechanisms); and acceptance — the conclusion of every deliverable is adopted only after the human has checked it. The AI carries execution and checking: data retrieval and archiving, code implementation and experiment runs, evidence verification and audit, and document drafting. Section 9.2 records how a decision reaches paper: the AI produces a decision record with options and grounds, and the human rules on it.

## F.2 Traceability Mechanisms

Four.

- **Git commit discipline.** One commit per completed, self-contained task; the commit message states the scope, the result, and the verification performed (the Result / Verification sections). Vague messages of the `wip` kind are not accepted; a commit contains only files relevant to the task at hand, and raw scraped data and generated outputs stay out of the repository.
- **Decision records.** Major rulings have versioned documents: each of the ten entries in the Chapter 09 log states the question at the time, the evidence relied on, the decision made, and what followed from it.
- **Self-describing scorecards.** Every scorecard artifact carries an `input_snapshot` field recording the SHA-256 of its inputs and the code commit at generation time, so any score can be checked against the conditions that produced it; the reproduction steps in Appendix B rely on this field.
- **Transactional state files.** Changes to the project state are executed through a command that carries the expected revision number; the file is never hand-edited, and the command refuses to run when the revision number does not match.

## F.3 Quality Practices

At the level of models and methods, three practices recur (9.2): the isolated experiment — a new idea first runs in a side branch, compared head-to-head with the current version, and does not enter the main line unless it clears the bar; pre-registration — for every "verify later" promise, the criteria are locked before the data is looked at; the quantitative threshold — "feels useful" is replaced by a proposition that evidence can refute (+0.010).

The writing period added one more: each chapter draft went to independent reviewers with no prior context, who ran a fact check (whether numbers, dates, and cross-references match the source draft) and a language check, kept as two separate passes, and the chapter was finalized only after revision. All nine chapters of the main text went through this process.

## F.4 The Record of Failures and Falsifications

Principle: results that went unadopted, and results that were falsified, are archived just the same. Three instances. The constructor-strength correction mechanism fell short of the +0.010 threshold in two rounds of isolated experiments and did not enter the main line; its mechanism definition and both experiment rounds are archived in full, and the idea was converted into a blind-test pre-registration (Chapter 09, entry 8). During the scoring unification, one preference anchor accepted a compromise — the blending coefficient stepped back from 0.432 to 0.20, and the two costs that came with it are on record (5.4). The race weight freeze left no separate ruling document, so its date can only be fixed by the main text's narrative; this is logged as a counter-example to the record-keeping habit (Chapter 09, entry 7).
