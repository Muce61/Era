from typing import Literal
from era100x.data.schema.models import HistoricalEvidenceRow


def historical_evidence(
    level: Literal["H1", "H2"], reference: Literal["CONTRACT", "TRADE"], **unavailable: object
) -> HistoricalEvidenceRow:
    allowed = {
        "reference_ask",
        "bid",
        "spread_bps",
        "ts_recv_ns",
        "receive_latency_ms",
        "queue_position",
        "partial_fill",
        "actual_slippage_bps",
    }
    unknown = set(unavailable) - allowed
    if unknown:
        raise ValueError(f"unknown historical evidence fields: {sorted(unknown)}")
    illegal = {k: v for k, v in unavailable.items() if v is not None}
    if illegal:
        raise ValueError(f"historical execution fields must be NULL: {sorted(illegal)}")
    return HistoricalEvidenceRow(evidence_level=level, reference_price_type=reference)
