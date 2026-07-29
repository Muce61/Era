from __future__ import annotations

from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts import audit_stage2_lifecycle_source as audit_script
from era100x.research.stage_2.acceptance.canonical_json import (
    read_canonical_json,
    write_canonical_json_exclusive,
)
from era100x.research.stage_2.lifecycle.models import canonical_hash
from era100x.research.stage_2.lifecycle import production
from era100x.research.stage_2.lifecycle.input_catalog import (
    REQUIRED_INPUT_BINDINGS,
    load_input_catalog,
    write_input_catalog,
)
from era100x.research.stage_2.lifecycle.source_audit import LifecycleSourceAudit


def _passing_audit(tmp_path: Path) -> LifecycleSourceAudit:
    rows = [
        {
            "instrument": instrument,
            "trade_gap_count": 1,
            "trade_gap_second_count": 1,
            "contract_price_gap_seconds_covered": 1,
            "contract_price_zero_volume_gap_seconds": 0,
            "contract_price_duplicate_seconds": 0,
            "contract_price_extreme_beyond_visible_trades_count": 1,
        }
        for instrument in ("BTCUSDT", "ETHUSDT")
    ]
    payload: dict[str, object] = {
        "schema_name": "stage2-lifecycle-source-audit",
        "schema_version": "1.0",
        "status": "PASS",
        "scope_start_date": "2020-01-01",
        "scope_end_date_exclusive": "2020-01-02",
        "contract_price_source_family": "BINANCE_USDM_AGGTRADES_DERIVED_1S_OHLC",
        "canonical_trade_source_family": "BINANCE_USDM_TRADES_ARCHIVES",
        "source_relationship": "DISTINCT_BINANCE_ARCHIVE_FAMILIES",
        "information_status": "SAME_SECOND_RANGE_BOUND_ADDITIONAL_ASSURANCE",
        "contract_price_root": str(tmp_path),
        "canonical_trade_root": str(tmp_path / "trades"),
        "provenance_script_path": str(tmp_path / "provenance.py"),
        "provenance_script_sha256": "a" * 64,
        "source_checkpoint_path": str(tmp_path / "checkpoint.json"),
        "source_checkpoint_sha256": "b" * 64,
        "audits": tuple(rows),
        "forward_filled_seconds_forbidden": True,
        "historical_execution_claim": False,
    }
    payload["audit_hash"] = canonical_hash(payload)
    return LifecycleSourceAudit.model_validate(payload)


def test_contract_price_catalog_hashes_every_instrument_day(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "contract"
    for instrument in ("BTCUSDT", "ETHUSDT"):
        path = (
            root
            / f"{instrument}_1s_agg"
            / f"{instrument}_1s_20200101.parquet"
        )
        path.parent.mkdir(parents=True)
        pq.write_table(
            pa.table(
                {
                    "event_ts_ns": [1],
                    "high": [1.0],
                    "low": [1.0],
                    "volume": [1.0],
                }
            ),
            path,
        )
    monkeypatch.setattr(audit_script, "CONTRACT_PRICE_ROOT", root)
    audit = _passing_audit(tmp_path)
    audit_path = tmp_path / "source-audit.json"
    write_canonical_json_exclusive(audit_path, audit.model_dump(mode="json"))

    catalog_path = audit_script.build_contract_price_catalog(
        audit_path=audit_path,
        audit=audit,
        output_path=tmp_path / "contract-price-catalog.json",
    )

    catalog = read_canonical_json(catalog_path)
    assert catalog["partition_count"] == 2
    assert {row["instrument"] for row in catalog["partitions"]} == {
        "BTCUSDT",
        "ETHUSDT",
    }
    assert all(len(row["sha256"]) == 64 for row in catalog["partitions"])
    assert catalog["scope_start_date"] == date(2020, 1, 1).isoformat()

    entries: dict[str, tuple[Path, str]] = {}
    for role in REQUIRED_INPUT_BINDINGS:
        if role == "contract_price_catalog_hash":
            entries[role] = (catalog_path, str(catalog["catalog_hash"]))
            continue
        evidence = tmp_path / f"{role}.json"
        evidence.write_text(f'{{"role":"{role}"}}\n', encoding="utf-8")
        entries[role] = (evidence, "a" * 64)
    input_path = write_input_catalog(
        path=tmp_path / "input-catalog.json",
        entries=entries,
    )
    monkeypatch.setattr(production, "FULL_END_EXCLUSIVE", date(2020, 1, 2))
    production.validate_full_period_contract_price_catalog(
        load_input_catalog(input_path)
    )

    first_partition = Path(str(catalog["partitions"][0]["path"]))
    first_partition.write_bytes(first_partition.read_bytes() + b"drift")
    with pytest.raises(ValueError, match="partition Hash drift"):
        production.validate_full_period_contract_price_catalog(
            load_input_catalog(input_path)
        )
