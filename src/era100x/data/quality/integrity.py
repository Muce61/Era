from __future__ import annotations
from dataclasses import dataclass
from era100x.data.schema.models import ContractPrice1s, NormalizedTrade


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    index: int
    detail: str


def inspect_trades(rows: list[NormalizedTrade]) -> tuple[list[NormalizedTrade], list[Issue]]:
    seen: dict[tuple[str, int], NormalizedTrade] = {}
    clean = []
    issues = []
    previous_ts = None
    previous_id = None
    for index, row in enumerate(rows):
        key = (row.instrument, row.trade_id)
        if key in seen:
            issues.append(
                Issue(
                    "DUPLICATE_EXACT" if seen[key] == row else "DUPLICATE_CONFLICT", index, str(key)
                )
            )
            continue
        if previous_ts is not None and row.ts_event_ns < previous_ts:
            issues.append(Issue("TIME_REVERSAL", index, str(row.ts_event_ns)))
        if previous_id is not None and row.trade_id > previous_id + 1:
            issues.append(Issue("TRADE_ID_GAP", index, f"{previous_id + 1}-{row.trade_id - 1}"))
        seen[key] = row
        clean.append(row)
        previous_ts = row.ts_event_ns
        previous_id = row.trade_id
    return clean, issues


def inspect_contract_gaps(rows: list[ContractPrice1s]) -> list[Issue]:
    issues = []
    for index, (left, right) in enumerate(zip(rows, rows[1:], strict=False), start=1):
        delta = right.ts_event_ns - left.ts_event_ns
        if delta != 1_000_000_000:
            issues.append(
                Issue("CONTRACT_SECOND_GAP" if delta > 0 else "TIME_REVERSAL", index, str(delta))
            )
    return issues
