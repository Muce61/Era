# ADR-S2-005 — Stage 2 Group 1 Event Construction Baseline

- Status: ACCEPTED
- Date: 2026-07-16
- Decision owner: Muce
- Change request: `CR-2026-002`
- Applies to: Stage 2 Plan v1.2 and Group 1 Task v1.3
- Rule status: `BASELINE / RESEARCH`; not `FROZEN`, not optimal

## Context

Group 1 requires exact causal formulas and one immutable run interface before implementation.
This ADR supplies those definitions without changing the V1.3.4 FROZEN MarketEpisode identity
or authorizing path labels, statistical evidence, H3, F1, PnL or trading.

## Key-level sources and arbitration

- `rolling_low_1m`: minimum low of the latest 60 closed one-minute Contract Price bars.
- `rolling_low_5m`: minimum low of the latest 12 closed five-minute Contract Price bars.
- `range_low`: low of the immediately preceding closed 15m, 1H, 4H and 1D Contract Price bar;
  each timeframe is an independent source fact.
- Causal availability is the source bar/window close. No right-side confirmation is permitted.
- Priority is 1D, 4H, 1H, 15m, rolling 5m, rolling 1m. A newly closed same-source fact
  supersedes the active prior fact while retaining the full source history.
- Merge tolerance is 5/10/15 bps with 10 bps Primary. Arbitration follows V1.3.4: priority,
  earliest formation time, then smallest stable hash. All member source IDs remain recorded.

## Event definitions

- A LONG Sweep begins on the first strict crossing below an available canonical level.
- Sweep confirmation requires depth at least 2 bps in Primary. The preregistered Sweep axis is
  2/5/10/15/25 bps. Depth above 25 bps invalidates the episode.
- Reclaim is the first reference price at or above `level + reclaim_buffer`; buffers are
  0/1/2/3 bps with 1 bp Primary. T1-T4 timeout semantics are inherited from ADR-S2-004.
- Hold starts at `reclaim_available_at_ts`. It passes only if every observed Contract Price fact
  in the T1-T4 left-closed/right-open window remains at or above
  `level - hold_failure_buffer`; buffers are 0/1/2/3 bps with 1 bp Primary.
- Episode maximum duration is 120 seconds. Minimum episode gap is 60/300/900 seconds with
  300 seconds Primary. Re-arm above the level is 300/900/1800 seconds with 900 seconds Primary.
- Sweep, Reclaim and Hold are decided only from facts available through their own detection
  boundary and are never rewritten by downstream success.

## Context, price and flow gates

- G1 uses the last closed 1H close and a causal EMA20 computed only from closed 1H closes.
  Close above EMA is `UP`, below is `DOWN`, equality is `FLAT`; only `UP` allows LONG.
- G3 searches the 30 seconds after Hold and accepts the first second close `t` for which both
  `close[t] > close[t-1s]` and `close[t] > close[t-5s]`, provided no new structural low occurred
  from Hold through `t`. The window is left-closed/right-open.
- G4 uses Stage 1 Trades in `[t-5s,t)`. It requires signed-quantity imbalance
  `(buy_qty-sell_qty)/(buy_qty+sell_qty) > 0` and the latest one-second trade count strictly
  greater than the previous four seconds' per-second mean. Missing valid Trades or zero total
  quantity is `UNAVAILABLE`.
- `V1_PRICE` does not consume G4. `V1_FLOW` requires G4. No Bid, Ask, Spread, L2, receive latency,
  queue, partial fill, actual slippage or private flow field may be synthesized.

## Parameter sets

The sole Primary is T2, merge 10 bps, gap 300 seconds, re-arm 900 seconds, Sweep 2 bps,
reclaim buffer 1 bp and Hold failure buffer 1 bp. The preregistered family has 20 OFAT sets:
Primary; T1/T3/T4; merge 5/15; gap 60/900; re-arm 300/1800; Sweep 5/10/15/25;
reclaim 0/2/3; Hold buffer 0/2/3. Each sensitivity set changes exactly one axis. Cartesian
combinations are prohibited.

## Identity and run interface

`market_episode_id` remains the V1.3.4 FROZEN hash of venue, instrument,
canonical key-level ID and sweep start nanoseconds. Strategy, configuration, trigger, flow,
data and code versions are bound in a separate deterministic `candidate_version_id` and cannot
reset consumption identity. Research inclusion is not an EntryIntent and does not consume a live
episode.

The only full candidate interface is:

```text
uv run python scripts/run_stage2_group1_candidates.py {preflight,run,resume,verify}
```

`preflight` creates the run ID and locks the execution manifest; `run` requires manifest,
instrument and variant and accepts no threshold override; `resume` requires an existing run and
identical manifest/config/data hashes; `verify` is read-only and may compare two complete runs.

## Invalidation conditions

The preregistration and dependent evidence are invalid if any source formula, close/availability
semantics, priority, threshold, T1-T4 definition, OFAT membership, G1/G3/G4 formula,
MarketEpisode identity, candidate-version identity, Stage 1 baseline/hash, Contract Price
inventory, CLI contract, checkpoint/publication rule or code/config hash changes. A new approved
L3 change and manifest version are required; prior manifests, reports and invalidation records
remain append-only.

