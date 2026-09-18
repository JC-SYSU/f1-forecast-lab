# predictions/ — all predictions and C0 scores

The final, cleaned form of every prediction this study produced, organized by model line. Two sources of truth were used: the official qualifying scorecards (`c0_roster_r03_r12_a90bf4ad`, `c0_roster_r13_r14_a90bf4ad`) and the official race scorecards (`c0_race_r03_r12_615232a3`, `c0_race_r13_r14_6a01fdaa`) from the private research repository.

## qualifying/

- `predictions.json` — all 31 candidates × R03–R14: each round's predicted top-10, its C0 score, and the scoring status; each candidate also carries its combined mean over R03–R12. Candidates are sorted by combined mean.
- `c0_matrix.csv` — the candidate × round C0 matrix (blank = unscoreable, see the `notes` field).

## race/

- `predictions.json` — R03–R14, two models (grid-order baseline vs the optimized model with weights frozen at 606117e): each round's predicted top-10, the actual top-10, and C0.
- `c0_by_round.csv` — round-by-round C0 for both models.

## experiments/

Scoring-related side experiments cited by the narrative: the two what-if correction experiments (Chapter 09, item 8) and the grid-delta variant correlation data behind the variant-distribution figure (6.6).

## Field notes

- `status: scored` — the prediction received a C0 score. `unscoreable_field_mismatch` — the prediction names a driver who left the seat (R12–R14, candidates #10–#13/#30/#31); the prediction is kept, `c0` is null.
- R14 official qualifying has 20 rows (upstream source missing 2 cars); scoring follows the contract as-is.
- Walk-forward causality: every prediction uses only rounds strictly before its target round.
