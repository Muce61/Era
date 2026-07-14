from __future__ import annotations
from dataclasses import dataclass
from era100x.data.schema.models import ContractPrice1s, NormalizedTrade


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    index: int
    detail: str


def inspect_trades(rows: list[NormalizedTrade]) -> tuple[list[NormalizedTrade], list[Issue]]:
    seen: set[tuple[str, str]] = set()
    venue_groups: dict[tuple[str, int], set[str]] = {}
    clean: list[NormalizedTrade] = []
    issues = []
    previous_ts = None
    previous_id = None
    for index, row in enumerate(rows):
        canonical_key = (row.instrument, row.canonical_trade_id)
        venue_key = (row.instrument, row.venue_trade_id)
        if canonical_key in seen:
            issues.append(Issue("DUPLICATE_EXACT", index, str(canonical_key)))
            continue
        seen.add(canonical_key)
        venue_groups.setdefault(venue_key, set()).add(row.canonical_trade_id)
        if previous_ts is not None and row.ts_event_ns < previous_ts:
            issues.append(Issue("TIME_REVERSAL", index, str(row.ts_event_ns)))
        if previous_id is not None and row.venue_trade_id > previous_id + 1:
            issues.append(
                Issue("TRADE_ID_GAP", index, f"{previous_id + 1}-{row.venue_trade_id - 1}")
            )
        clean.append(row)
        previous_ts = row.ts_event_ns
        previous_id = row.venue_trade_id
    conflicting = {key for key, identities in venue_groups.items() if len(identities) > 1}
    marked = []
    for row in clean:
        key = (row.instrument, row.venue_trade_id)
        if key in conflicting:
            group = f"{row.instrument}:{row.venue_trade_id}"
            marked.append(
                row.model_copy(
                    update={
                        "identity_status": "CONFLICTING_VENUE_ID",
                        "venue_trade_id_conflict_group": group,
                    }
                )
            )
        else:
            marked.append(row)
    issues.extend(
        Issue("VENUE_ID_CONFLICT", 0, f"{key[0]}:{key[1]}") for key in sorted(conflicting)
    )
    return marked, issues


def inspect_contract_gaps(rows: list[ContractPrice1s]) -> list[Issue]:
    issues = []
    for index, (left, right) in enumerate(zip(rows, rows[1:], strict=False), start=1):
        delta = right.ts_event_ns - left.ts_event_ns
        if delta != 1_000_000_000:
            issues.append(
                Issue("CONTRACT_SECOND_GAP" if delta > 0 else "TIME_REVERSAL", index, str(delta))
            )
    return issues
