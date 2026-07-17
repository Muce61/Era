from __future__ import annotations

import json
import hashlib
from datetime import date
from pathlib import Path

import pytest

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.runtime_v2.source_authority import (
    ContractPriceInventoryEntryV2,
    ContractPriceInventoryManifestV2,
    Stage1ResolvedSourceIndexV2,
    Stage1TradesResolvedEntryV2,
)
from era100x.research.stage_2.runtime_v2.transition import (
    freeze_run_a_protection,
    freeze_v2_migration_manifest,
    sha256_file,
    verify_run_a_protection,
)

H = "a" * 64
E = "b" * 64


def _json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _published_run(root: Path) -> tuple[Path, Path]:
    execution = root / "manifests" / "execution.json"
    supplement = root / "manifests" / "supplement.json"
    _json(
        execution,
        {
            "manifest_hash": H,
            "preregistration_manifest_hash": E,
            "config_hash": H,
            "stage1_data_run_id": "stage1-run",
            "stage1_logical_hashes": {"BTCUSDT": H, "ETHUSDT": E},
        },
    )
    _json(
        supplement,
        {
            "manifest_hash": E,
            "generator_commit": "c" * 40,
        },
    )
    _json(
        root / "checkpoint.json",
        {
            "status": "PUBLISHED",
            "planned": list(range(9508)),
            "completed": list(range(9508)),
            "failed": [],
            "release_supplement_hash": E,
        },
    )
    _json(root / "logs" / "release-state.json", {"phase": "PUBLISHED"})
    _json(
        root / "manifests" / "catalog.json",
        {
            "entries": [{"index": index} for index in range(61776)],
            "logical_hash": H,
            "physical_hash": E,
        },
    )
    _json(root / "reports" / "quality-report.json", {"status": "PASS"})
    _json(root / "reports" / "count-summary.json", {"status": "PASS"})
    _json(
        root / "reports" / "release-analysis.json",
        {
            "catalog_logical_hash": H,
            "catalog_physical_hash": E,
            "quality": {"status": "PASS"},
        },
    )
    (root / "published" / "data").mkdir(parents=True)
    return execution, supplement


def _source_manifests(root: Path) -> tuple[Path, Path]:
    price_entries = tuple(
        ContractPriceInventoryEntryV2(
            instrument=instrument,
            partition_date=date(2020, 1, 1),
            relative_path=f"{instrument}_1s_agg/{instrument}_1s_20200101.csv",
            source_format="CSV",
            byte_size=1,
            byte_sha256=("1" if instrument == "BTCUSDT" else "2") * 64,
            canonical_for_date=True,
        )
        for instrument in ("BTCUSDT", "ETHUSDT")
    )
    legacy_hash = hashlib.sha256(
        canonical_json([item.legacy_record() for item in price_entries]).encode()
    ).hexdigest()
    price_manifest = ContractPriceInventoryManifestV2.seal(
        {
            "root_authority": str(root / "contract-price"),
            "start_date": date(2020, 1, 1),
            "end_exclusive": date(2020, 1, 2),
            "entries": price_entries,
            "inventory_file_count": 2,
            "canonical_partition_count": 2,
            "legacy_inventory_sha256": legacy_hash,
        }
    )
    trade_entries = tuple(
        Stage1TradesResolvedEntryV2(
            instrument=instrument,
            partition_date=date(2020, 1, 1),
            archive_partition="2020-01",
            relative_path=(f"{instrument}/archive=2020-01/date=2020-01-01/part-000.parquet"),
            byte_sha256=("3" if instrument == "BTCUSDT" else "4") * 64,
            logical_sha256=("5" if instrument == "BTCUSDT" else "6") * 64,
        )
        for instrument in ("BTCUSDT", "ETHUSDT")
    )
    trades_manifest = Stage1ResolvedSourceIndexV2.seal(
        {
            "published_root_authority": str(root / "stage1-published"),
            "data_run_id": "stage1-run",
            "dataset_version": "stage1-trades-v2",
            "canonical_manifest_sha256": "7" * 64,
            "physical_manifest_sha256": "8" * 64,
            "catalog_sha256s": {"BTCUSDT": "9" * 64, "ETHUSDT": "a" * 64},
            "instrument_logical_hashes": {
                "BTCUSDT": "5" * 64,
                "ETHUSDT": "6" * 64,
            },
            "start_date": date(2020, 1, 1),
            "end_exclusive": date(2020, 1, 2),
            "entries": trade_entries,
            "resolved_partition_count": 2,
        }
    )
    price_path = root / "manifests" / "contract-price-inventory.json"
    trades_path = root / "manifests" / "stage1-resolved-index.json"
    _json(price_path, price_manifest.model_dump(mode="json"))
    _json(trades_path, trades_manifest.model_dump(mode="json"))
    return price_path, trades_path


def test_transition_binds_published_run_without_mutating_it(tmp_path: Path) -> None:
    run_a = tmp_path / "runs" / "run-a"
    execution, supplement = _published_run(run_a)
    before = sha256_file(run_a / "checkpoint.json")
    transition = tmp_path / "runs" / "transition"

    supersession, protection = freeze_run_a_protection(
        run_a_root=run_a,
        transition_run_root=transition,
        execution_manifest_path=execution,
        release_supplement_path=supplement,
        approved_at="2026-07-17T12:00:00+00:00",
    )

    assert supersession.legacy_run_b_status == "NOT_CREATED"
    assert protection.catalog_entry_count == 61776
    assert protection.computed_hash() == protection.manifest_hash
    assert sha256_file(run_a / "checkpoint.json") == before
    assert not (run_a / "reports" / "orchestration-supersession.json").exists()
    assert (transition / "manifests" / f"{protection.manifest_hash}.json").exists()

    price_manifest_path, trades_index_path = _source_manifests(transition)
    migration = freeze_v2_migration_manifest(
        protection=protection,
        transition_run_root=transition,
        destination_run_id="stage2-g1-v2-b-test",
        destination_root=tmp_path / "runs" / "stage2-g1-v2-b-test",
        v2_code_commit="d" * 40,
        v2_code_tree_hash=H,
        contract_price_inventory_manifest_path=price_manifest_path,
        stage1_resolved_source_index_path=trades_index_path,
        recorded_at="2026-07-17T12:01:00+00:00",
    )
    assert migration.run_a_artifact_reuse_allowed is False
    assert migration.computed_hash() == migration.manifest_hash
    verify_run_a_protection(
        protection=protection,
        run_a_root=run_a,
        execution_manifest_path=execution,
        release_supplement_path=supplement,
    )
    _json(run_a / "reports" / "quality-report.json", {"status": "FAIL"})
    with pytest.raises(ValueError, match="protected Run A artifact changed"):
        verify_run_a_protection(
            protection=protection,
            run_a_root=run_a,
            execution_manifest_path=execution,
            release_supplement_path=supplement,
        )


def test_transition_refuses_false_not_created_assertion(tmp_path: Path) -> None:
    run_a = tmp_path / "runs" / "run-a"
    execution, supplement = _published_run(run_a)
    legacy_b = tmp_path / "runs" / "legacy-b"
    legacy_b.mkdir(parents=True)

    with pytest.raises(ValueError, match="legacy Run B exists"):
        freeze_run_a_protection(
            run_a_root=run_a,
            transition_run_root=tmp_path / "runs" / "transition",
            execution_manifest_path=execution,
            release_supplement_path=supplement,
            legacy_run_b_paths=(legacy_b,),
        )


def test_transition_fails_closed_before_publication(tmp_path: Path) -> None:
    run_a = tmp_path / "runs" / "run-a"
    execution, supplement = _published_run(run_a)
    _json(run_a / "checkpoint.json", {"status": "IN_PROGRESS"})

    with pytest.raises(ValueError, match="not terminal PUBLISHED"):
        freeze_run_a_protection(
            run_a_root=run_a,
            transition_run_root=tmp_path / "runs" / "transition",
            execution_manifest_path=execution,
            release_supplement_path=supplement,
        )
