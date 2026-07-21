"""Pure S2-T11 extraction from already-authorized historical facts."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from era100x.data.schema.models import ContractPrice1s, NormalizedTrade
from era100x.research.stage_2.contracts.models import MarketEpisode

from .models import (
    ExtractedHistoricalPath,
    H1PathPoint,
    H2PathPoint,
    PathGap,
    PathSource,
    _canonical_json,
)

SECOND_NS = 1_000_000_000
PROHIBITED_EXECUTION_FIELDS = (
    "bid",
    "ask",
    "spread_bps",
    "ts_recv_ns",
    "receive_latency_ms",
    "queue_position",
    "partial_fill",
    "actual_slippage_bps",
    "real_return",
)


def _h1_point(row: ContractPrice1s) -> H1PathPoint:
    content = {
        "instrument": row.instrument,
        "ts_event_ns": row.ts_event_ns,
        "open": row.open,
        "high": row.high,
        "low": row.low,
        "close": row.close,
        "volume": row.volume,
        "source_encoding": row.source_encoding,
    }
    source_row_hash = hashlib.sha256(_canonical_json(content).encode()).hexdigest()
    return H1PathPoint.model_validate({**content, "source_row_hash": source_row_hash})


def _h2_point(row: NormalizedTrade) -> H2PathPoint:
    return H2PathPoint.model_validate(row.model_dump(mode="python"))


def extract_historical_path(
    *,
    episode: MarketEpisode,
    h1_rows: Iterable[ContractPrice1s],
    h2_rows: Iterable[NormalizedTrade],
    h1_source: PathSource,
    h2_source: PathSource,
    window_start_ns: int,
    window_end_ns: int,
) -> ExtractedHistoricalPath:
    """Extract a deterministic H1/H2 sequence without assigning outcomes or returns."""

    if episode.episode_status != "CANDIDATE":
        raise ValueError("only CANDIDATE MarketEpisode facts can be extracted")
    if window_end_ns <= window_start_ns:
        raise ValueError("path window must be non-empty")
    if window_start_ns < episode.available_at_ts:
        raise ValueError("path cannot begin before the MarketEpisode is available")
    if h1_source.evidence_level != "H1" or h2_source.evidence_level != "H2":
        raise ValueError("path sources must be H1 then H2")

    h1_input = tuple(h1_rows)
    h2_input = tuple(h2_rows)
    if any(row.instrument != episode.instrument for row in h1_input) or any(
        row.instrument != episode.instrument for row in h2_input
    ):
        raise ValueError("BTC and ETH path facts must be extracted separately")

    selected_h1 = [
        _h1_point(row) for row in h1_input if window_start_ns <= row.ts_event_ns < window_end_ns
    ]
    selected_h2 = [
        _h2_point(row) for row in h2_input if window_start_ns <= row.ts_event_ns < window_end_ns
    ]

    h1_unique: dict[tuple[int, str], H1PathPoint] = {}
    for h1_point in selected_h1:
        h1_unique[(h1_point.ts_event_ns, h1_point.source_row_hash)] = h1_point
    h1_points = tuple(
        sorted(h1_unique.values(), key=lambda row: (row.ts_event_ns, row.source_row_hash))
    )

    h2_unique: dict[tuple[str, str], H2PathPoint] = {}
    for h2_point in selected_h2:
        identity = (h2_point.instrument, h2_point.canonical_trade_id)
        previous = h2_unique.get(identity)
        if previous is not None and previous != h2_point:
            raise ValueError("canonical historical fact identity has conflicting payloads")
        h2_unique[identity] = h2_point
    h2_points = tuple(
        sorted(
            h2_unique.values(),
            key=lambda row: (row.ts_event_ns, row.venue_trade_id, row.canonical_trade_id),
        )
    )

    gaps: list[PathGap] = []
    if not h1_points:
        missing = (window_end_ns - window_start_ns) // SECOND_NS
        if missing > 0:
            gaps.append(
                PathGap(
                    evidence_level="H1",
                    reason_code="H1_MISSING_SECONDS",
                    preceding_ts_event_ns=window_start_ns,
                    following_ts_event_ns=window_end_ns,
                    missing_count=missing,
                )
            )
    else:
        leading_missing = (h1_points[0].ts_event_ns - window_start_ns) // SECOND_NS
        if leading_missing > 0:
            gaps.append(
                PathGap(
                    evidence_level="H1",
                    reason_code="H1_MISSING_SECONDS",
                    preceding_ts_event_ns=window_start_ns,
                    following_ts_event_ns=h1_points[0].ts_event_ns,
                    missing_count=leading_missing,
                )
            )
    for h1_left, h1_right in zip(h1_points, h1_points[1:], strict=False):
        missing = (h1_right.ts_event_ns - h1_left.ts_event_ns) // SECOND_NS - 1
        if missing > 0:
            gaps.append(
                PathGap(
                    evidence_level="H1",
                    reason_code="H1_MISSING_SECONDS",
                    preceding_ts_event_ns=h1_left.ts_event_ns,
                    following_ts_event_ns=h1_right.ts_event_ns,
                    missing_count=missing,
                )
            )
    if h1_points:
        trailing_missing = (window_end_ns - h1_points[-1].ts_event_ns) // SECOND_NS - 1
        if trailing_missing > 0:
            gaps.append(
                PathGap(
                    evidence_level="H1",
                    reason_code="H1_MISSING_SECONDS",
                    preceding_ts_event_ns=h1_points[-1].ts_event_ns,
                    following_ts_event_ns=window_end_ns,
                    missing_count=trailing_missing,
                )
            )

    time_ordered_h2 = sorted(
        h2_unique.values(),
        key=lambda row: (row.ts_event_ns, row.venue_trade_id, row.canonical_trade_id),
    )
    for h2_left, h2_right in zip(time_ordered_h2, time_ordered_h2[1:], strict=False):
        if h2_right.venue_trade_id > h2_left.venue_trade_id + 1:
            gaps.append(
                PathGap(
                    evidence_level="H2",
                    reason_code="H2_VENUE_TRADE_ID_GAP",
                    preceding_ts_event_ns=h2_left.ts_event_ns,
                    following_ts_event_ns=h2_right.ts_event_ns,
                    missing_count=h2_right.venue_trade_id - h2_left.venue_trade_id - 1,
                    preceding_venue_trade_id=h2_left.venue_trade_id,
                    following_venue_trade_id=h2_right.venue_trade_id,
                )
            )
        elif h2_right.venue_trade_id < h2_left.venue_trade_id:
            gaps.append(
                PathGap(
                    evidence_level="H2",
                    reason_code="H2_VENUE_TRADE_ID_REVERSAL",
                    preceding_ts_event_ns=h2_left.ts_event_ns,
                    following_ts_event_ns=h2_right.ts_event_ns,
                    missing_count=h2_left.venue_trade_id - h2_right.venue_trade_id,
                    preceding_venue_trade_id=h2_left.venue_trade_id,
                    following_venue_trade_id=h2_right.venue_trade_id,
                )
            )

    ambiguity: set[str] = set()
    h1_by_second: dict[int, set[str]] = {}
    for point in h1_points:
        h1_by_second.setdefault(point.ts_event_ns, set()).add(point.source_row_hash)
    if any(len(hashes) > 1 for hashes in h1_by_second.values()):
        ambiguity.add("H1_CONFLICTING_SAME_SECOND")
    if any(point.identity_status == "CONFLICTING_VENUE_ID" for point in h2_points):
        ambiguity.add("H2_CONFLICTING_VENUE_ID")
    if any(gap.reason_code == "H2_VENUE_TRADE_ID_REVERSAL" for gap in gaps):
        ambiguity.add("H2_EVENT_TIME_VENUE_REVERSAL")

    has_gaps = bool(gaps)
    has_ambiguity = bool(ambiguity)
    if has_gaps and has_ambiguity:
        quality = "WITH_GAPS_AND_AMBIGUITY"
    elif has_gaps:
        quality = "WITH_GAPS"
    elif has_ambiguity:
        quality = "AMBIGUOUS"
    else:
        quality = "COMPLETE"

    return ExtractedHistoricalPath.seal(
        {
            "instrument": episode.instrument,
            "market_episode_id": episode.market_episode_id,
            "canonical_candidate_id": episode.canonical_candidate_id,
            "candidate_version_id": episode.candidate_version_id,
            "canonical_payload_hash": episode.canonical_payload_hash,
            "parameter_set_id": episode.parameter_set_id,
            "episode_available_at_ns": episode.available_at_ts,
            "window_start_ns": window_start_ns,
            "window_end_ns": window_end_ns,
            "h1_source": h1_source,
            "h2_source": h2_source,
            "h1_points": h1_points,
            "h2_points": h2_points,
            "gaps": tuple(gaps),
            "ambiguity_codes": tuple(sorted(ambiguity)),
            "h1_input_count": len(h1_input),
            "h2_input_count": len(h2_input),
            "h1_outside_window_count": len(h1_input) - len(selected_h1),
            "h2_outside_window_count": len(h2_input) - len(selected_h2),
            "h1_duplicate_count": len(selected_h1) - len(h1_points),
            "h2_duplicate_count": len(selected_h2) - len(h2_points),
            "quality_status": quality,
            "prohibited_execution_fields": PROHIBITED_EXECUTION_FIELDS,
        }
    )
