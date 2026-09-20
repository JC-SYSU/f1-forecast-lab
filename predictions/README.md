# predictions/ — all predictions and C0 scores

The final, cleaned form of every prediction this study produced, organized by model line. Two sources of truth were used: the official qualifying scorecard (`c0_roster_r03_r14_92076830`) and the official race scorecard (`c0_race_r03_r14_d739e6e0`) from the private research repository. Both are the 2026-09-20 recompute under the seat-rotation policy (decision log, entry 12); they supersede the previous caliber (`c0_roster_r03_r12/r13_r14_a90bf4ad`, `c0_race_r03_r12_615232a3`, `c0_race_r13_r14_6a01fdaa`), which remains archived in the private repository.

## qualifying/

- `predictions.json` — all 31 candidates × R03–R14: each round's predicted top-10, its C0 score, and the scoring status; each candidate also carries its combined mean over R03–R14. Candidates are sorted by combined mean.
- `c0_matrix.csv` — the candidate × round C0 matrix (blank = unscoreable, see the `notes` field).

## race/

- `predictions.json` — R03–R14, two models (grid-order baseline vs the optimized model with weights frozen at 606117e): each round's predicted top-10, the actual top-10, and C0. From R12 on, constructor attribution follows the seat registry (lawson at red_bull).
- `c0_by_round.csv` — round-by-round C0 for both models.

## experiments/

Scoring-related side experiments cited by the narrative: the two what-if correction experiments (Chapter 09, item 8) and the grid-delta variant correlation data behind the variant-distribution figure (6.6).

## Field notes

- `status: scored` — the prediction received a C0 score. Under the seat-rotation policy every candidate-round cell (372 of 372 on the qualifying line) is scored: from R12 on, exited drivers are excluded from predictions and the incoming driver (tsunoda) carries no historical parameters. The superseded caliber carried `unscoreable_field_mismatch` cells instead (R12–R14, candidates #10–#13/#30/#31); those predictions and the reason for the change are kept on record (decision log, entries 8 and 12).
- R14 official qualifying has 20 rows (upstream source missing 2 cars); scoring follows the contract as-is.
- Walk-forward causality: every prediction uses only rounds strictly before its target round.
