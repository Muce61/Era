from __future__ import annotations

import inspect
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from scripts import audit_stage2_lifecycle_source

from era100x.research.stage_2.lifecycle.models import canonical_hash
from era100x.research.stage_2.lifecycle.source_audit import (
    LifecycleSourceAudit,
    validate_source_audit_payload,
)


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


def test_v110_prepare_path_never_materializes_trade_price_columns() -> None:
    source = inspect.getsource(audit_stage2_lifecycle_source.build_audit)
    source += inspect.getsource(audit_stage2_lifecycle_source.collect_contract_price_partitions)

    assert "to_pylist" not in source
    assert "_verified_trade_day" not in source
    assert "_audit_instrument" not in source


def test_source_audit_passes_without_requiring_a_new_extreme() -> None:
    audit = LifecycleSourceAudit.model_validate(_payload())
    assert audit.status == "PASS"
    assert all(
        item.contract_price_extreme_beyond_visible_trades_count == 0 for item in audit.audits
    )


def test_source_audit_normalizes_json_arrays_without_relaxing_strict_fields() -> None:
    payload = json.loads(json.dumps(_payload()))

    audit = validate_source_audit_payload(payload)

    assert isinstance(audit.audits, tuple)
    assert isinstance(audit.targeted_reverification, tuple)
    assert isinstance(audit.unverified_or_drifted_sources, tuple)

    payload["historical_execution_claim"] = "false"
    with pytest.raises(ValueError, match="historical_execution_claim"):
        validate_source_audit_payload(payload)


def test_source_audit_v11_binds_only_the_approved_trade_supplement() -> None:
    payload = _payload()
    payload.update(
        {
            "schema_version": "1.1",
            "canonical_trade_overlay_mode": "EXACT_KEY_APPEND_ONLY_SUPPLEMENT_V1",
            "trade_supplement_acceptance_path": "/supplement/acceptance.json",
            "trade_supplement_file_sha256": "c" * 64,
            "trade_supplement_acceptance_hash": "d" * 64,
            "trade_supplement_instrument": "BTCUSDT",
            "trade_supplement_date": "2022-03-01",
            "legacy_stage1_partition_modified": False,
        }
    )
    payload["audit_hash"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "audit_hash"}
    )
    assert LifecycleSourceAudit.model_validate(payload).schema_version == "1.1"

    payload["trade_supplement_date"] = "2022-03-02"
    payload["audit_hash"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "audit_hash"}
    )
    with pytest.raises(ValueError, match="supplement binding drift"):
        LifecycleSourceAudit.model_validate(payload)


def test_trade_supplement_binding_is_scoped_and_restores_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text("{}\n", encoding="utf-8")
    file_hash = hashlib.sha256(acceptance.read_bytes()).hexdigest()
    acceptance_hash = "e" * 64
    monkeypatch.setattr(
        audit_stage2_lifecycle_source,
        "verify_trade_supplement",
        lambda _path: {
            "acceptance_hash": acceptance_hash,
            "instrument": "BTCUSDT",
            "date": "2022-03-01",
            "legacy_partition_modified": False,
        },
    )
    monkeypatch.setenv(
        audit_stage2_lifecycle_source.TRADE_SUPPLEMENT_PATH_ENV,
        "/prior/acceptance.json",
    )
    monkeypatch.setenv(
        audit_stage2_lifecycle_source.TRADE_SUPPLEMENT_HASH_ENV,
        "f" * 64,
    )
    with audit_stage2_lifecycle_source.bound_trade_supplement(
        acceptance_path=acceptance.resolve(),
        acceptance_file_sha256=file_hash,
        acceptance_hash=acceptance_hash,
    ):
        assert os.environ[audit_stage2_lifecycle_source.TRADE_SUPPLEMENT_PATH_ENV] == str(
            acceptance.resolve()
        )
        assert os.environ[audit_stage2_lifecycle_source.TRADE_SUPPLEMENT_HASH_ENV] == file_hash
    assert (
        os.environ[audit_stage2_lifecycle_source.TRADE_SUPPLEMENT_PATH_ENV]
        == "/prior/acceptance.json"
    )
    assert os.environ[audit_stage2_lifecycle_source.TRADE_SUPPLEMENT_HASH_ENV] == "f" * 64


def test_contract_price_catalog_collects_real_csv_layout(tmp_path: Path, monkeypatch) -> None:
    payload = _payload()
    payload["scope_end_date_exclusive"] = "2020-01-02"
    payload["audit_hash"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "audit_hash"}
    )
    audit = LifecycleSourceAudit.model_validate(payload)
    monkeypatch.setattr(
        audit_stage2_lifecycle_source,
        "CONTRACT_PRICE_ROOT",
        tmp_path,
    )
    for instrument in ("BTCUSDT",):
        root = tmp_path / f"{instrument}_1s_agg"
        root.mkdir()
        (root / f"{instrument}_1s_20200101.csv").write_bytes(
            b"ts_sec,open,high,low,close,volume\n1577836800000,1,2,0.5,1.5,3\n"
        )
        pq.write_table(
            pa.table(
                {
                    "open": [9.0],
                    "high": [9.0],
                    "low": [9.0],
                    "close": [9.0],
                    "volume": [9.0],
                    "timestamp": pa.array(
                        [1577836800000000000],
                        type=pa.timestamp("ns"),
                    ),
                }
            ),
            root / f"{instrument}_1s_20200101.parquet",
        )
    parquet_root = tmp_path / "ETHUSDT_1s_agg"
    parquet_root.mkdir()
    pq.write_table(
        pa.table(
            {
                "open": [1.0],
                "high": [2.0],
                "low": [0.5],
                "close": [1.5],
                "volume": [3.0],
                "timestamp": pa.array([1577836800000000000], type=pa.timestamp("ns")),
            }
        ),
        parquet_root / "ETHUSDT_1s_20200101.parquet",
    )
    expected_hashes = {
        instrument: audit_stage2_lifecycle_source.sha256_file(path)
        for instrument, path in {
            "BTCUSDT": (tmp_path / "BTCUSDT_1s_agg/BTCUSDT_1s_20200101.csv"),
            "ETHUSDT": (tmp_path / "ETHUSDT_1s_agg/ETHUSDT_1s_20200101.parquet"),
        }.items()
    }
    monkeypatch.setattr(
        audit_stage2_lifecycle_source,
        "FixedT10Reader",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        audit_stage2_lifecycle_source,
        "_t10_contract_source_hash",
        lambda _reader, *, instrument, owner_date: expected_hashes[instrument],
    )
    monkeypatch.setattr(
        audit_stage2_lifecycle_source,
        "_t10_contract_row_count",
        lambda _reader, *, instrument, owner_date: 1,
    )

    partitions = audit_stage2_lifecycle_source.collect_contract_price_partitions(audit=audit)

    assert len(partitions) == 2
    assert {row["instrument"] for row in partitions} == {"BTCUSDT", "ETHUSDT"}
    assert {row["instrument"]: Path(str(row["path"])).suffix for row in partitions} == {
        "BTCUSDT": ".csv",
        "ETHUSDT": ".parquet",
    }
    assert all(row["row_count"] == 1 for row in partitions)
