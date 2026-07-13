# Stage 1 Full Data Run v1.0 — Preflight

Status: PASS

Current work root: `/Volumes/FuckingLife/era100x_stage1`

Superseded root: `/Users/muce/1m_data/era100x_stage1` (must not be used)

| Item | Result |
| --- | ---: |
| Write probe | PASS; created, read and deleted |
| Official archive objects | 162 found, 0 missing |
| Compressed Trades estimate | 146,365,241,235 bytes (136.31 GiB) |
| Contract source bytes | 19,488,907,249 bytes |
| Published Parquet estimate | 292,730,482,470 bytes |
| Stream temporary estimate | 15,456,963,696 bytes |
| Repeat-build temporary estimate | 5,152,321,232 bytes |
| Peak estimate | 488,319,764,618 bytes (454.78 GiB) |
| Required with 20% margin | 585,983,717,541 bytes (545.74 GiB) |
| Available | 3,454,299,275,264 bytes (3,217.07 GiB) |
| Surplus above safety gate | 2,868,315,557,723 bytes (2,671.33 GiB) |

Estimated transfer time at 25 MiB/s is 5,583 seconds before normalization/build time.

The approved layout is `raw/trades`, `staging`, `published`, `catalog`, and `tmp`. Raw archives and published runs are immutable; resumable checkpoints are per symbol/date; staging failures remain unpublished; cleanup is manual-only and audited. The root remained empty after preflight. No archive body was downloaded.

Previous internal-disk attempt is retained in Git history at commit `fcb3c42`; it failed with 197.07 GiB available. The approved external-root rerun supersedes that capacity result without changing estimation rules.
