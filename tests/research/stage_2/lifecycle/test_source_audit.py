from __future__ import annotations

from era100x.research.stage_2.lifecycle.models import canonical_hash
from era100x.research.stage_2.lifecycle.source_audit import LifecycleSourceAudit


def _payload() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_name": "stage2-lifecycle-source-audit",
        "schema_version": "1.0",
        "status": "PASS",
        "scope_start_date": "2020-01-01",
        "scope_end_date_exclusive": "2020-01-08",
        "contract_price_source_family": "BINANCE_USDM_AGGTRADES_DERIVED_1S_OHLC",
        "canonical_trade_source_family": "BINANCE_USDM_TRADES_ARCHIVES",
        "source_relationship": "DISTINCT_BINANCE_ARCHIVE_FAMILIES",
        "information_status": "SAME_SECOND_RANGE_BOUND_ADDITIONAL_ASSURANCE",
        "contract_price_root": "/contract",
        "canonical_trade_root": "/trades",
        "provenance_script_path": "/script.py",
        "provenance_script_sha256": "a" * 64,
        "source_checkpoint_path": "/checkpoint.json",
        "source_checkpoint_sha256": "b" * 64,
        "audits": tuple(
            {
                "instrument": instrument,
                "trade_gap_count": 2,
                "trade_gap_second_count": 1,
                "contract_price_gap_seconds_covered": 1,
                "contract_price_zero_volume_gap_seconds": 0,
                "contract_price_duplicate_seconds": 0,
                "contract_price_extreme_beyond_visible_trades_count": 0,
            }
            for instrument in ("BTCUSDT", "ETHUSDT")
        ),
        "forward_filled_seconds_forbidden": True,
        "historical_execution_claim": False,
    }
    payload["audit_hash"] = canonical_hash(payload)
    return payload


def test_source_audit_passes_without_requiring_a_new_extreme() -> None:
    audit = LifecycleSourceAudit.model_validate(_payload())
    assert audit.status == "PASS"
    assert all(
        item.contract_price_extreme_beyond_visible_trades_count == 0
        for item in audit.audits
    )
