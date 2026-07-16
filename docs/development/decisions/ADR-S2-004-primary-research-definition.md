# ADR-S2-004 — Stage 2 Primary Research Definition

- Status: ACCEPTED
- Date: 2026-07-16
- Decision owner: Muce
- Resolves: `OQ-S2-004`
- Applies to: Stage 2 Plan v1.2 preregistration and approved Group 1 Tasks
- Rule status: `BASELINE / RESEARCH`; not `FROZEN`, not optimal

## Context

Stage 2 Plan v1.2 and Group 1 were approved, but execution remained fail-closed because the exact sensitivity timing tuples, preregistered periods, matched-control relaxation, deterministic seeds and Primary failure line were absent. Muce supplied and approved the following definitions on 2026-07-16. This ADR records research configuration only; it does not execute S2-T19, generate events, calculate results or authorize Groups 2～4.

## Decision

### 1. Timing configurations

All time arithmetic uses UTC event-time nanoseconds and left-closed/right-open windows. A fact exactly at the end boundary is excluded. Reclaim timeout starts at `sweep_detection_ts`; Hold starts at `reclaim_available_at_ts`; First-passage horizon starts at the final candidate Episode `available_at_ts`.

| ID | Role | Reclaim timeout | Hold confirmation | First-passage horizon |
| --- | --- | ---: | ---: | ---: |
| T1 | exploratory sensitivity | 15 s | 15 s | 60 s |
| T2 | sole Primary | 30 s | 30 s | 180 s |
| T3 | exploratory sensitivity | 60 s | 30 s | 300 s |
| T4 | exploratory sensitivity | 60 s | 60 s | 600 s |

T1/T3/T4 cannot rescue a failed T2 Primary. None of these tuples may be changed after observing event results.

### 2. Preregistered periods

Periods are UTC left-closed/right-open and Episode membership is determined solely by `available_at_ts`.

| Period | Start inclusive | End exclusive | Covered dates |
| --- | --- | --- | --- |
| P1 | `2020-01-01T00:00:00Z` | `2022-01-01T00:00:00Z` | 2020-01-01 through 2021-12-31 |
| P2 | `2022-01-01T00:00:00Z` | `2024-01-01T00:00:00Z` | 2022-01-01 through 2023-12-31 |
| P3 | `2024-01-01T00:00:00Z` | `2026-07-04T00:00:00Z` | 2024-01-01 through 2026-07-03 |

Each Episode belongs to exactly one period. Controls, purge/embargo and split/fold boundaries cannot cross periods. BTC and ETH are evaluated separately, and combined reporting cannot hide a period failure. P3 ends at the Stage 1 baseline right boundary.

### 3. Matching fields and training-only bins

The following fields are exact and never relaxed: `instrument`, `direction`, `high_timeframe_trend_state`, `pre_registered_period`, and `research_split_or_fold`. Direction is `LONG`; matching cannot cross BTC/ETH, period, trend state, split, validation or holdout boundaries.

Relaxable fields are UTC four-hour bucket, volatility quintile, Trades activity quintile and UTC calendar quarter. UTC buckets are B0 `[00:00,04:00)`, B1 `[04:00,08:00)`, B2 `[08:00,12:00)`, B3 `[12:00,16:00)`, B4 `[16:00,20:00)`, and B5 `[20:00,24:00)`.

Volatility and Trades-activity formulas remain those approved by Plan v1.2 and Task v1.2. Quintile boundaries use only the corresponding training fold, are frozen for validation/holdout/formal runs, are written into the Manifest, and apply deterministic duplicate-boundary handling. Full-sample or future-period re-estimation is prohibited. If five valid bins cannot be formed, the run is `BLOCKED`; no substitute binning is allowed.

### 4. Fixed cumulative relaxation L0～L5

- **L0:** exact match on all non-relaxable fields plus four-hour bucket, volatility quintile, activity quintile and quarter.
- **L1:** retain L0 except activity quintile may be `q-1`, `q`, `q+1`, clipped to 1～5.
- **L2:** retain L1 and also allow volatility quintile `q±1`, clipped to 1～5.
- **L3:** retain L2 and allow current or circularly adjacent four-hour bucket; B0 neighbors B5/B1 and B5 neighbors B4/B0.
- **L4:** retain L3 and relax quarter to any quarter in the same UTC calendar year.
- **L5:** `UNMATCHED`; never backfill from the full market or relax instrument, direction, trend state, period or split/fold.

Relaxation is cumulative and strictly ordered L0→L4. `event_match_level` is the weakest level needed to reach the required control count.

### 5. Control selection and matching statistics

`controls_per_episode = 5` and `matching_seed = 20260716`. An Episode is `MATCHED` only with five unique valid controls; otherwise it is `UNMATCHED`. Controls may be reused across Episodes, but reuse rate must be reported. A control cannot overlap the target event window, enter its purge/embargo exclusion, or be a registered same-family event Episode.

Candidates are ordered lexicographically by `SHA256(primary_episode_id | candidate_timestamp_ns | matching_seed)` and selected ascending. Matching coverage is `MATCHED eligible episodes / all eligible episodes`. Late-relaxation share is `count(event_match_level in {L3,L4}) / count(MATCHED episodes)`.

The Primary matched baseline is Episode-equal-weighted: first average each Episode's five control `TARGET_FIRST_STRICT` values, then equally average those Episode means. Pooling all controls is prohibited. The Primary metric is `delta_target_first = event_target_first_rate - matched_baseline_target_first_rate`.

### 6. AMBIGUOUS

Primary treats `AMBIGUOUS` as failure. Reports must additionally show the conditional result excluding AMBIGUOUS and the theoretical upper bound treating it as success. Only the failure-treated result may drive Primary Go/No-Go.

### 7. Cluster bootstrap and confidence interval

Primary cluster is `instrument × UTC calendar week`. Resampling unit is the cluster; iterations are 5000; `bootstrap_seed = 20260716`; CI is two-sided 95% percentile bootstrap. BTC and ETH run independently, each period runs separately, and Overall BTC Primary runs separately.

### 8. BTC T2 Primary failure line

All F1～F10 must pass; any failure makes the Primary hypothesis `FAIL`.

- **F1 Overall increment CI:** Overall BTC `delta_target_first` two-sided 95% CI lower bound is strictly greater than zero.
- **F2 Overall sample:** `btc_matched_episode_count >= 1000`.
- **F3 Period samples:** each of P1/P2/P3 has at least 150 BTC MATCHED eligible Episodes.
- **F4 Coverage:** `match_coverage >= 0.80`.
- **F5 Weak matching:** `late_relaxation_share <= 0.50`.
- **F6 Direction consistency:** at least two of three periods have `delta_target_first > 0`.
- **F7 Severe reversal:** no period has `delta_target_first < -0.02`.
- **F8 AMBIGUOUS dependence:** fail if success requires excluding AMBIGUOUS or treating it as success.
- **F9 Determinism:** fail on any mismatch in Episode IDs, event count, matching, config hash, Manifest, Primary metric, fixed-seed bootstrap result or published logical hash.
- **F10 No exploratory rescue:** T1/T3/T4 or other exploratory success cannot rescue failed T2 Primary.

### 9. Exploratory multiplicity

T1/T3/T4 and other preregistered parameter-domain analyses use Benjamini-Hochberg FDR with `q <= 0.10`, reporting raw p-values and adjusted q-values. They cannot alter T2 Primary Go/No-Go.

### 10. ETH Secondary classification

- `REPLICATED`: BTC Primary PASS, ETH Overall `delta_target_first > 0`, and ETH 95% CI lower bound > 0.
- `BTC_ONLY`: BTC Primary PASS, but ETH does not satisfy REPLICATED, has insufficient sample, or its CI includes zero.
- `NOT_REPLICATED`: BTC Primary PASS and ETH Overall `delta_target_first <= 0` or has explicit negative evidence.
- `PRIMARY_FAILED`: BTC Primary FAIL.

ETH cannot rescue BTC, and BTC/ETH samples cannot be merged.

## Invalidation conditions

This decision and dependent preregistration become `INVALIDATED` if any timing tuple or boundary semantics, period boundary/assignment, exact or relaxable matching field, quintile formula/boundary source, L0～L5 order, control count/exclusion/order/seed, AMBIGUOUS treatment, aggregation formula, cluster/CI method or seed, F1～F10 threshold, exploratory multiplicity rule, ETH classification, Stage 1 data baseline/hash, code/config hash, purge/embargo or split definition changes. Such changes require an approved governance change and a new preregistration version before execution; old manifests and evidence remain append-only.

## Consequences

OQ-S2-004 is RESOLVED with blocking scope `NONE`. Stage 2 Plan v1.2 and Group 1 remain `APPROVED / NOT_EXECUTED`; Groups 2～4 remain DRAFT. The first-group execution prompt may now perform its own preflight starting with S2-T19, but this ADR itself does not execute or pass any Task.
