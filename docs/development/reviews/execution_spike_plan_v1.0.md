# Execution Capability Spike Plan v1.0

Status: OFFLINE_SKELETON_ONLY

Stage 0 validates only that IOC, Algo creation, ALGO_UPDATE, UNKNOWN, restart, and exit-race scenarios can be expressed through a deterministic port and mock. It makes no Binance API call, sends no testnet or live order, reads no account, and stores no credential.

| Capability | Stage 0 evidence | Current status | Future consumer |
| --- | --- | --- | --- |
| IOC protocol | deterministic mock scenario | UNKNOWN for venue behavior | Stage 6 |
| Algo create/query/cancel | deterministic mock scenario | U-002/U-003 OPEN | Stage 6 |
| ALGO_UPDATE | deterministic mock scenario | U-002 OPEN | Stage 5/6 |
| UNKNOWN/restart/race | deterministic mock scenario | UNKNOWN for venue behavior | Stage 6 |

Any network spike requires a separately approved Task version and explicit authorization. U-001～U-003 remain OPEN and BLOCKED for their documented downstream scopes.
