from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from era100x.research.stage_2.baselines.conditional import receipt_supplement as supplement
from era100x.research.stage_2.baselines.conditional.v14_contracts import canonical_hash


def test_fragment_reader_handles_row_group_boundaries(tmp_path: Path) -> None:
    path = tmp_path / "object.parquet"
    table = pa.table({"value": pa.array(range(12), type=pa.int64())})
    pq.write_table(table, path, row_group_size=3)

    result = supplement._read_fragment(
        pq.ParquetFile(path), row_offset=2, row_count=7, columns=["value"]
    )

    assert result["value"].to_pylist() == list(range(2, 9))


def _write_supplement_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setattr(supplement, "EXPECTED_PARTITION_COUNT", 2)
    monkeypatch.setattr(supplement, "_source_hashes", lambda: {"manifest_sha256": "a" * 64})
    monkeypatch.setattr(supplement, "_module_hash", lambda: "b" * 64)
    cr = tmp_path / "CR-2026-027.md"
    cr.write_text("approved", encoding="utf-8")
    monkeypatch.setattr(supplement, "CR_PATH", cr)
    rows = []
    for index in range(2):
        row = {
            "partition_id": f"{index:064x}",
            "dataset_name": "market_episodes",
            "dataset_version": "group1-v1-price-v1",
            "dataset_spec_hash": "c" * 64,
            "instrument": "BTCUSDT",
            "variant": "V1_PRICE",
            "owner_date": date(2026, 7, index + 1),
            "original_receipt_hash": "d" * 64,
            "original_semantic_sha256": "e" * 64,
            "original_identity_multiset_sha256": "f" * 64,
            "original_payload_association_sha256": "1" * 64,
            "distribution_digests_json": json.dumps(
                {"field.parameter_set_id": "2" * 64}, separators=(",", ":")
            ),
        }
        row["supplement_row_hash"] = supplement._row_hash(row)
        rows.append(row)
    table = pa.Table.from_pylist(rows, schema=supplement.SUPPLEMENT_SCHEMA)
    parquet = tmp_path / "receipt_distribution_supplement.parquet"
    pq.write_table(table, parquet, compression="zstd")
    manifest = {
        "schema_name": "stage2-s2t15-receipt-distribution-supplement",
        "schema_version": "1.0",
        "change_request": "CR-2026-027",
        "task_version": "1.4",
        "source_t10_run_id": supplement.T10_RUN_ID,
        "source_t10_snapshot_id": supplement.T10_SNAPSHOT_ID,
        "source_hashes": {"manifest_sha256": "a" * 64},
        "cr_sha256": supplement.sha256_file(cr),
        "receiver_implementation_sha256": "b" * 64,
        "supplement_parquet_sha256": supplement.sha256_file(parquet),
        "supplement_partition_count": 2,
        "accepted_original_receipt_mutations": 0,
        "source_bytes_modified": False,
        "read_only_receiver": True,
        "status": "PASS",
        "dataset_partition_counts": {"market_episodes@group1-v1-price-v1": 2},
        "validated_object_count": 1,
        "validated_object_bytes": 100,
        "validated_object_rows": 2,
        "validated_objects_root_hash": "3" * 64,
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    root = tmp_path / f"supplement-{manifest['manifest_hash']}"
    root.mkdir()
    parquet.rename(root / parquet.name)
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return root, manifest_path


def test_supplement_verify_is_deterministic_and_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _manifest_path = _write_supplement_fixture(tmp_path, monkeypatch)

    first = supplement.verify_receipt_distribution_supplement(root)
    second = supplement.verify_receipt_distribution_supplement(root)

    assert first == second
    assert first["status"] == "PASS"

    parquet = root / "receipt_distribution_supplement.parquet"
    parquet.write_bytes(parquet.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="Parquet hash mismatch"):
        supplement.verify_receipt_distribution_supplement(root)


def test_symlinked_supplement_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _manifest_path = _write_supplement_fixture(tmp_path, monkeypatch)
    link = tmp_path / "supplement-link"
    link.symlink_to(root, target_is_directory=True)

    with pytest.raises(ValueError, match="unsafe or missing"):
        supplement.verify_receipt_distribution_supplement(link)
