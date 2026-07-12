from __future__ import annotations
from collections import defaultdict
from decimal import Decimal
from era100x.data.schema.models import ContractBar, NormalizedTrade


def aggregate_trade_bars(
    rows: list[NormalizedTrade], interval_seconds: int = 1
) -> list[ContractBar]:
    if interval_seconds <= 0:
        raise ValueError("interval must be positive")
    if not rows:
        return []
    if len({r.instrument for r in rows}) != 1:
        raise ValueError("mixed instruments")
    width = interval_seconds * 1_000_000_000
    groups: dict[int, list[NormalizedTrade]] = defaultdict(list)
    for row in rows:
        groups[(row.ts_event_ns // width) * width].append(row)
    result = []
    for bucket, group in sorted(groups.items()):
        ordered = sorted(group, key=lambda r: (r.ts_event_ns, r.trade_id))
        prices = [r.price for r in ordered]
        result.append(
            ContractBar(
                instrument=ordered[0].instrument,
                source_type="TRADE",
                interval_seconds=interval_seconds,
                bucket_start_ns=bucket,
                open=prices[0],
                high=max(prices),
                low=min(prices),
                close=prices[-1],
                volume=sum((r.quantity for r in ordered), Decimal("0")),
            )
        )
    return result
