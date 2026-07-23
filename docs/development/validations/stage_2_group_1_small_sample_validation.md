# Stage 2 Group 1 Small-Sample Integration Validation

- Conclusion: PASS
- Capability commit: `7200a0f963069064c60916c83aba2bf8c8b34222`
- Execution Manifest: `84f6fcdd2d4710fd98112dc7a39d798d0f488accb6e7b2a7962f98ba589e3b74`
- Config hash: `adb6295e210de66d1e69aa008e6161e8fef1e1fd72001ff812b68597f8c72e3f`

## Fixture integration

The committed end-to-end fixture constructs range-low → arbitration → Sweep → Reclaim → Hold →
G1/G3 → Trades G4 → V1_FLOW MarketEpisode. It also inherits targeted failure/boundary tests for
all S2-T01 through S2-T09 capabilities. The unified quality gate passed with 150 tests.

## Controlled real windows

BTCUSDT and ETHUSDT were read separately for the first complete UTC week of P1/P2/P3, with the
previous UTC day used only as causal warm-up. Each of six windows contained exactly 691,200
Contract Price seconds. Each window deterministically produced 11,461 rolling-1m facts, 2,293
rolling-5m facts and 768/192/48/8 range-low facts at 15m/1H/4H/1D.

Two independent executions produced identical report bytes and logical hash
`25224850e422e259fb2d65a9715b7c71c5156c9bf84debad25c2d29bdf0942b2`; report file SHA-256 is
`73287e72e480d5946db013377c5dafa11810c720968a957a3b2d73c1032abae8`.

## Gate result

S2-T19 and S2-T01 through S2-T09 are PASSED, the execution Manifest is append-only and locked,
and no parameter was changed from the preregistration. S2-T10 full candidate generation is now
authorized. No path label, metric, statistical evidence, H3, F1, PnL or trading action ran.

An earlier execution Manifest `6e4c5f7b...f153c7` contained an incorrectly expanded code commit,
was never used for a run, and is permanently recorded as `INVALIDATED`; append-only replacement
`84f6fcdd...9e3b74` binds the verified commit above.
