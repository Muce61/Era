# R2 Factor Monotonicity Report

event_count: 1278
factor_count: 17
horizons: [1, 4, 8, 16, 32]

## Candidate Status Counts

|   candidate_for_validation |   weak_candidate |   invalid_or_sparse |
|---------------------------:|-----------------:|--------------------:|
|                         68 |               12 |                   5 |

## Blocking Rules For Next Stages

- R3 stability must pass before any factor can enter strategy composition.
- R4 random baseline must use `(1+count)/(N+1)` percentile formulas.
- R5-R7 must standardize Bootstrap, risk sizing, and manual audit before any OOS claim.
- Without new unseen data, R8 cannot return an A-type OOS-ready conclusion.
