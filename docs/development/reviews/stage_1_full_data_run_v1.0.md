# Stage 1 Full Data Run v1.0 — Preflight

Status: BLOCKED

| Item | Result |
| --- | ---: |
| Official archive objects | 162 found, 0 missing |
| Compressed Trades estimate | 146,365,241,235 bytes (136.31 GiB) |
| Contract source bytes | 19,488,907,249 bytes |
| Published Parquet estimate | 292,730,482,470 bytes |
| Stream temporary estimate | 15,456,963,696 bytes |
| Repeat-build temporary estimate | 5,152,321,232 bytes |
| Peak estimate | 488,319,764,618 bytes (454.78 GiB) |
| Required with 20% margin | 585,983,717,541 bytes (545.74 GiB) |
| Available | 211,600,764,928 bytes (197.07 GiB) |
| Shortfall | 374,382,952,613 bytes (348.67 GiB) |

Estimated transfer time at 25 MiB/s is 5,583 seconds before normalization/build time. The approved work root was not created. No archive body was downloaded and no cleanup was attempted.

Resume requires resolving OQ-S1-003 and rerunning the same preflight against current disk and official archive metadata.
