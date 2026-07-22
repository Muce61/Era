from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from era100x.research.stage_2.baselines.conditional import (
    context_receipt_supplement as supplement,
)
from era100x.research.stage_2.baselines.conditional import receipt_supplement as base
from era100x.research.stage_2.baselines.conditional.v14_contracts import canonical_hash


def _write_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(supplement, "EXPECTED_PARTITION_COUNT", 1)
    monkeypatch.setattr(base, "_source_hashes", lambda: {"manifest_sha256": "a" * 64})
    monkeypatch.setattr(supplement, "_module_hash", lambda: "b" * 64)
    cr = tmp_path / "CR-2026-028.md"
    cr.write_text("approved", encoding="utf-8")
    monkeypatch.setattr(supplement, "CR_PATH", cr)
    row = {
        "partition_id": "1" * 64,
        "dataset_name": "price_triggers",
        "dataset_version": "group1-v1-price-v1",
        "dataset_spec_hash": "c" * 64,
        "instrument": "BTCUSDT",
        "variant": "V1_PRICE",
        "owner_date": date(2026, 7, 1),
        "original_receipt_hash": "d" * 64,
        "original_semantic_sha256": "e" * 64,
        "original_identity_multiset_sha256": "f" * 64,
        "original_payload_association_sha256": "1" * 64,
        "distribution_digests_json": json.dumps(
            {"field.context_model_id": "2" * 64}, separators=(",", ":")
        ),
    }
    row["supplement_row_hash"] = base._row_hash(row)
    table = pa.Table.from_pylist([row], schema=base.SUPPLEMENT_SCHEMA)
    parquet = tmp_path / "context_receipt_distribution_supplement.parquet"
    pq.write_table(table, parquet, compression="zstd")
    manifest = {
        "schema_name": "stage2-s2t15-context-receipt-distribution-supplement",
        "schema_version": "1.0",
        "change_request": "CR-2026-028",
        "task_version": "1.4",
        "source_t10_run_id": base.T10_RUN_ID,
        "source_t10_snapshot_id": base.T10_SNAPSHOT_ID,
        "source_hashes": {"manifest_sha256": "a" * 64},
        "cr_sha256": base.sha256_file(cr),
        "receiver_implementation_sha256": "b" * 64,
        "supplement_parquet_sha256": base.sha256_file(parquet),
        "supplement_partition_count": 1,
        "accepted_original_receipt_mutations": 0,
        "source_bytes_modified": False,
        "read_only_receiver": True,
        "status": "PASS",
        "dataset_partition_counts": {"price_triggers@group1-v1-price-v1": 1},
        "validated_object_count": 1,
        "validated_object_bytes": 100,
        "validated_object_rows": 1,
        "validated_objects_root_hash": "3" * 64,
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    root = tmp_path / f"supplement-{manifest['manifest_hash']}"
    root.mkdir()
    parquet.rename(root / parquet.name)
    (root / "manifest.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return root


def test_context_supplement_verify_is_deterministic_and_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _write_fixture(tmp_path, monkeypatch)

    first = supplement.verify_context_receipt_supplement(root)
    second = supplement.verify_context_receipt_supplement(root)

    assert first == second
    assert first["status"] == "PASS"

    parquet = root / "context_receipt_distribution_supplement.parquet"
    parquet.write_bytes(parquet.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="Parquet hash mismatch"):
        supplement.verify_context_receipt_supplement(root)


def test_context_supplement_rejects_dataset_reconciliation_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _write_fixture(tmp_path, monkeypatch)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["dataset_partition_counts"] = {"price_triggers@group1-v1-price-v1": 2}
    manifest_without_hash = {
        key: value for key, value in manifest.items() if key != "manifest_hash"
    }
    manifest["manifest_hash"] = canonical_hash(manifest_without_hash)
    replacement = tmp_path / f"supplement-{manifest['manifest_hash']}"
    root.rename(replacement)
    (replacement / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="dataset reconciliation drift"):
        supplement.verify_context_receipt_supplement(replacement)
