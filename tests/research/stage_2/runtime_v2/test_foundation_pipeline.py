from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from era100x.research.stage_2.pipelines.candidates.stage1_catalog import (
    Stage1TradesCatalogIndex,
    Stage1TradesPartition,
    sha256_file,
)
from era100x.research.stage_2.runtime_v2.errors import ContractViolation
from era100x.research.stage_2.runtime_v2.catalog import CatalogPublisherV2
from era100x.research.stage_2.runtime_v2.foundation_pipeline import (
    MAX_INFLIGHT_BYTES,
    FoundationPipelineConfig,
    FoundationSourceReader,
    FeatureFoundationPipeline,
    _InflightBudget,
    planned_packed_object_count,
)
from era100x.research.stage_2.runtime_v2.foundation_sources import (
    ContractPriceInventoryIndex,
    ContractPricePartition,
)
from era100x.research.stage_2.runtime_v2.foundation_specs import (
    feature_foundation_dataset_specs,
)
from era100x.research.stage_2.runtime_v2.manifest_factory import (
    FOUNDATION_CONTEXT_ID,
    FOUNDATION_SETUP_ID,
    FOUNDATION_VARIANTS,
)
from era100x.research.stage_2.runtime_v2.models import (
    MAX_PROCESS_RSS_BYTES,
    DatasetPlan,
    DigestBinding,
    ManifestV2,
)

H = "a" * 64
DAY_NS = 86_400_000_000_000


def _start_ns(owner_date: date) -> int:
    return int(datetime.combine(owner_date, datetime.min.time(), tzinfo=UTC).timestamp()) * 10**9


def _fixture_indexes(
    root: Path,
    dates: tuple[date, ...],
    *,
    reverse_authority: bool = False,
    empty_trades: bool = False,
) -> tuple[Stage1TradesCatalogIndex, ContractPriceInventoryIndex]:
    published = root / "stage1-published"
    contract_root = root / "contract-price"
    trades: list[Stage1TradesPartition] = []
    prices: list[ContractPricePartition] = []
    for owner_date in dates:
        start_ns = _start_ns(owner_date)
        trade_path = (
            published
            / "BTCUSDT"
            / f"archive={owner_date:%Y-%m}"
            / f"date={owner_date.isoformat()}"
            / "part-000.parquet"
        )
        trade_path.parent.mkdir(parents=True, exist_ok=True)
        if empty_trades:
            trades_frame = pl.DataFrame(
                schema={
                    "ts_event_ns": pl.Int64,
                    "quantity": pl.Decimal(38, 18),
                    "aggressor_side": pl.String,
                }
            )
        else:
            trades_frame = pl.DataFrame(
                {
                    "ts_event_ns": [start_ns, start_ns + 999_999_999, start_ns + 1_000_000_000],
                    "quantity": [Decimal("1.25"), Decimal("0.50"), Decimal("2.00")],
                    "aggressor_side": ["BUY", "SELL", "BUY"],
                },
                schema={
                    "ts_event_ns": pl.Int64,
                    "quantity": pl.Decimal(38, 18),
                    "aggressor_side": pl.String,
                },
            )
        trades_frame.write_parquet(trade_path, row_group_size=2, statistics=True)
        trades.append(
            Stage1TradesPartition(
                instrument="BTCUSDT",
                partition_date=owner_date,
                archive_partition=owner_date.strftime("%Y-%m"),
                path=trade_path,
                byte_sha256=sha256_file(trade_path),
                logical_sha256=H,
            )
        )

        price_directory = contract_root / "BTCUSDT_1s_agg"
        price_directory.mkdir(parents=True, exist_ok=True)
        price_path = price_directory / f"BTCUSDT_1s_{owner_date:%Y%m%d}.csv"
        start_us = start_ns // 1_000_000
        price_path.write_text(
            "ts_sec,open,high,low,close,volume\n"
            f"{start_us},1.0,1.1,0.9,1.0,2\n"
            f"{start_us + 1_000},1.0,1.2,0.8,1.1,3\n",
            encoding="utf-8",
        )
        prices.append(
            ContractPricePartition(
                instrument="BTCUSDT",
                partition_date=owner_date,
                path=price_path,
                source_format="CSV",
                byte_size=price_path.stat().st_size,
                byte_sha256=sha256_file(price_path),
            )
        )

    # Distractors prove the builder does not discover input through a glob.
    (published / "BTCUSDT" / "staging").mkdir(parents=True, exist_ok=True)
    (published / "BTCUSDT" / "staging" / "part-000.parquet").write_bytes(b"ignore")
    (contract_root / "BTCUSDT_1s_agg" / "._ignored.csv").write_bytes(b"ignore")
    if reverse_authority:
        trades.reverse()
        prices.reverse()
    trades_index = Stage1TradesCatalogIndex(
        published_root=published,
        partitions=tuple(trades),
    )
    price_index = ContractPriceInventoryIndex(
        root=contract_root,
        partitions=tuple(prices),
        inventory_hash="b" * 64,
        inventory_file_count=len(prices),
    )
    return trades_index, price_index


def _pipeline(
    root: Path,
    *,
    run_name: str,
    dates: tuple[date, ...],
    reverse_authority: bool = False,
    empty_trades: bool = False,
    reader_type: type[FoundationSourceReader] = FoundationSourceReader,
) -> tuple[FeatureFoundationPipeline, FoundationSourceReader, Path]:
    source_root = root / "sources"
    trades, prices = _fixture_indexes(
        source_root,
        dates,
        reverse_authority=reverse_authority,
        empty_trades=empty_trades,
    )
    external = root / "approved-external"
    external.mkdir(parents=True, exist_ok=True)
    run_root = external / run_name
    config = FoundationPipelineConfig(
        run_root=run_root,
        approved_external_root=external,
    )
    reader = reader_type(trades_index=trades, contract_price_index=prices)
    pipeline = FeatureFoundationPipeline(
        config=config,
        snapshot_id=H,
        trades_index=trades,
        contract_price_index=prices,
        source_reader=reader,
    )
    return pipeline, reader, run_root


def test_cross_month_build_is_causal_complete_and_packed(tmp_path: Path) -> None:
    dates = (date(2020, 1, 31), date(2020, 2, 1))
    pipeline, _reader, run_root = _pipeline(tmp_path, run_name="run-a", dates=dates)

    result = pipeline.build(
        instruments=("BTCUSDT",),
        start=dates[0],
        end_exclusive=dates[-1] + timedelta(days=1),
    )

    assert len(result.checkpoints) == 4
    assert len(result.artifacts) == 4
    assert len(result.receipts) == 8
    assert all(item.storage_role == "PACKED_FINAL" for item in result.checkpoints)
    assert result.trade_decode_counts == (
        ("BTCUSDT", date(2020, 1, 31), 1),
        ("BTCUSDT", date(2020, 2, 1), 1),
    )
    assert result.trade_sha256_verification_counts == (
        ("BTCUSDT", date(2020, 1, 31), 1),
        ("BTCUSDT", date(2020, 2, 1), 1),
    )
    assert result.contract_price_sha256_verification_counts == (
        ("BTCUSDT", date(2020, 1, 31), 1),
        ("BTCUSDT", date(2020, 2, 1), 1),
    )
    assert result.max_inflight_bytes_observed < MAX_INFLIGHT_BYTES
    assert all(
        tuple(receipt.partition.owner_date for receipt in checkpoint.receipts) == dates
        for checkpoint in result.checkpoints
    )

    price_checkpoint = next(
        item for item in result.checkpoints if item.dataset_name == "contract_price_1s"
    )
    assert price_checkpoint.artifact is not None
    price_table = pq.read_table(
        pipeline.config.catalog_root / price_checkpoint.artifact.relative_path
    )
    assert price_table.column("available_at_ns")[0].as_py() == _start_ns(dates[0]) + 1_000_000_000
    assert all(item.terminal_state == "PRESENT" for item in result.receipts)


def test_manifest_partition_contract_accepts_pipeline_catalog(tmp_path: Path) -> None:
    dates = (date(2020, 1, 31), date(2020, 2, 1))
    pipeline, _reader, run_root = _pipeline(tmp_path, run_name="catalog", dates=dates)
    result = pipeline.build(
        instruments=("BTCUSDT",),
        start=dates[0],
        end_exclusive=dates[-1] + timedelta(days=1),
    )
    specs = feature_foundation_dataset_specs()
    receipt_ids_by_spec = {
        spec.spec_hash: tuple(
            sorted(
                receipt.partition.partition_id
                for receipt in result.receipts
                if receipt.partition.dataset_spec_hash == spec.spec_hash
            )
        )
        for spec in specs
    }
    manifest = ManifestV2.seal(
        {
            "snapshot_id": H,
            "stage1_data_run_id": "stage1-fixture",
            "stage1_authorities": (
                DigestBinding(name="contract_price_inventory", sha256="1" * 64),
                DigestBinding(name="stage1_manifest", sha256="2" * 64),
            ),
            "preregistration_manifest_sha256": "3" * 64,
            "config_sha256": "4" * 64,
            "code_tree_sha256": "5" * 64,
            "dataset_specs": specs,
            "dataset_plans": tuple(
                sorted(
                    (
                        DatasetPlan(
                            dataset_spec_hash=spec.spec_hash,
                            expected_partition_ids=receipt_ids_by_spec[spec.spec_hash],
                        )
                        for spec in specs
                    ),
                    key=lambda item: item.dataset_spec_hash,
                )
            ),
            "invalidation_conditions": ("fixture authority changes",),
        }
    )
    for receipt in result.receipts:
        assert receipt.partition.setup_id == FOUNDATION_SETUP_ID
        assert receipt.partition.context_id == FOUNDATION_CONTEXT_ID
        assert receipt.partition.variant == FOUNDATION_VARIANTS[receipt.partition.dataset_name]

    catalog = CatalogPublisherV2(pipeline.config.catalog_root).publish(
        manifest,
        artifacts=result.artifacts,
        receipts=result.receipts,
        fragments=result.fragments,
        seals=result.seals,
    )

    assert catalog.snapshot_id == H
    assert sum(root.partition_count for root in catalog.dataset_roots) == 8


def test_empty_trade_days_publish_receipts_without_empty_objects(tmp_path: Path) -> None:
    dates = (date(2020, 1, 1), date(2020, 1, 2))
    pipeline, _reader, _run_root = _pipeline(
        tmp_path,
        run_name="empty-trades",
        dates=dates,
        empty_trades=True,
    )

    result = pipeline.build(
        instruments=("BTCUSDT",),
        start=dates[0],
        end_exclusive=dates[-1] + timedelta(days=1),
    )

    for name in ("trade_second_primitives", "trade_row_group_index"):
        checkpoint = next(item for item in result.checkpoints if item.dataset_name == name)
        assert checkpoint.artifact is None
        assert checkpoint.fragments == ()
        assert tuple(item.terminal_state for item in checkpoint.receipts) == ("EMPTY", "EMPTY")


def test_resume_skips_sealed_months_and_validates_objects(tmp_path: Path) -> None:
    dates = (date(2020, 1, 31), date(2020, 2, 1))
    first, _reader, _run_root = _pipeline(tmp_path, run_name="resume", dates=dates)
    first_result = first.build(
        instruments=("BTCUSDT",),
        start=dates[0],
        end_exclusive=dates[-1] + timedelta(days=1),
    )

    second, _second_reader, _ = _pipeline(tmp_path, run_name="resume", dates=dates)
    second_result = second.build(
        instruments=("BTCUSDT",),
        start=dates[0],
        end_exclusive=dates[-1] + timedelta(days=1),
    )

    assert second_result.trade_decode_counts == ()
    assert second_result.trade_sha256_verification_counts == ()
    assert second_result.contract_price_sha256_verification_counts == ()
    assert tuple(item.checkpoint_hash for item in first_result.checkpoints) == tuple(
        item.checkpoint_hash for item in second_result.checkpoints
    )
    assert tuple(item.object_sha256 for item in first_result.artifacts) == tuple(
        item.object_sha256 for item in second_result.artifacts
    )


class _FailOnFebruaryReader(FoundationSourceReader):
    def read_price(self, instrument: str, owner_date: date):  # type: ignore[override,no-untyped-def]
        if owner_date.month == 2:
            raise InterruptedError("controlled month-boundary interruption")
        return super().read_price(instrument, owner_date)  # type: ignore[arg-type]


def test_month_checkpoint_resume_does_not_rescan_completed_stage1_days(tmp_path: Path) -> None:
    dates = (date(2020, 1, 31), date(2020, 2, 1))
    failing, failing_reader, run_root = _pipeline(
        tmp_path,
        run_name="interrupted",
        dates=dates,
        reader_type=_FailOnFebruaryReader,
    )
    with pytest.raises(InterruptedError, match="controlled month-boundary"):
        failing.build(
            instruments=("BTCUSDT",),
            start=dates[0],
            end_exclusive=dates[-1] + timedelta(days=1),
        )
    assert failing_reader.trade_decode_counts == (("BTCUSDT", date(2020, 1, 31), 1),)
    assert failing_reader.trade_sha256_verification_counts == (("BTCUSDT", date(2020, 1, 31), 1),)
    assert len(tuple((run_root / "staging" / "foundation" / "checkpoints").rglob("*.json"))) == 4

    resumed, resumed_reader, _ = _pipeline(tmp_path, run_name="interrupted", dates=dates)
    result = resumed.build(
        instruments=("BTCUSDT",),
        start=dates[0],
        end_exclusive=dates[-1] + timedelta(days=1),
    )
    assert resumed_reader.trade_decode_counts == (("BTCUSDT", date(2020, 2, 1), 1),)
    assert resumed_reader.trade_sha256_verification_counts == (("BTCUSDT", date(2020, 2, 1), 1),)
    assert len(result.checkpoints) == 4


def test_same_size_stage1_trade_tamper_fails_before_decode(tmp_path: Path) -> None:
    owner_date = date(2020, 1, 31)
    pipeline, reader, _run_root = _pipeline(
        tmp_path,
        run_name="tampered-source",
        dates=(owner_date,),
    )
    partition = reader.trade_partition("BTCUSDT", owner_date)
    original = partition.path.read_bytes()
    replacement = bytes([original[0] ^ 1]) + original[1:]
    assert len(replacement) == len(original)
    partition.path.write_bytes(replacement)

    with pytest.raises(ValueError, match="physical byte hash changed"):
        pipeline.build(
            instruments=("BTCUSDT",),
            start=owner_date,
            end_exclusive=owner_date + timedelta(days=1),
        )

    assert reader.trade_sha256_verification_counts == (("BTCUSDT", owner_date, 1),)
    assert reader.trade_decode_counts == ()


def test_same_size_contract_price_tamper_fails_on_first_consumption(tmp_path: Path) -> None:
    owner_date = date(2020, 1, 31)
    pipeline, reader, _run_root = _pipeline(
        tmp_path,
        run_name="tampered-price-source",
        dates=(owner_date,),
    )
    partition = reader.price_partition("BTCUSDT", owner_date)
    original = partition.path.read_bytes()
    replacement = bytes([original[0] ^ 1]) + original[1:]
    assert len(replacement) == len(original)
    partition.path.write_bytes(replacement)

    with pytest.raises(ValueError, match="bytes changed after inventory approval"):
        pipeline.build(
            instruments=("BTCUSDT",),
            start=owner_date,
            end_exclusive=owner_date + timedelta(days=1),
        )

    assert reader.contract_price_sha256_verification_counts == (("BTCUSDT", owner_date, 1),)
    assert reader.trade_sha256_verification_counts == ()


def test_partial_resume_verifies_trade_bytes_before_row_group_footer(tmp_path: Path) -> None:
    owner_date = date(2020, 1, 31)
    first, first_reader, run_root = _pipeline(
        tmp_path,
        run_name="row-group-partial-resume",
        dates=(owner_date,),
    )
    first.build(
        instruments=("BTCUSDT",),
        start=owner_date,
        end_exclusive=owner_date + timedelta(days=1),
    )
    monthly_checkpoint = (
        run_root
        / "staging"
        / "foundation"
        / "checkpoints"
        / "instrument=BTCUSDT"
        / "feature=trade_row_group_index"
        / "shard=2020-01.json"
    )
    monthly_checkpoint.unlink()
    partition = first_reader.trade_partition("BTCUSDT", owner_date)
    original = partition.path.read_bytes()
    partition.path.write_bytes(bytes([original[0] ^ 1]) + original[1:])

    resumed, resumed_reader, _ = _pipeline(
        tmp_path,
        run_name="row-group-partial-resume",
        dates=(owner_date,),
    )
    # _pipeline recreates the authoritative fixture file.  Re-apply the
    # same-size corruption after its Catalog binding has been frozen.
    resumed_partition = resumed_reader.trade_partition("BTCUSDT", owner_date)
    resumed_original = resumed_partition.path.read_bytes()
    resumed_partition.path.write_bytes(bytes([resumed_original[0] ^ 1]) + resumed_original[1:])
    with pytest.raises(ValueError, match="physical byte hash changed"):
        resumed.build(
            instruments=("BTCUSDT",),
            start=owner_date,
            end_exclusive=owner_date + timedelta(days=1),
        )

    assert resumed_reader.trade_sha256_verification_counts == (("BTCUSDT", owner_date, 1),)
    assert resumed_reader.trade_decode_counts == ()


def test_authority_order_does_not_change_packed_hashes(tmp_path: Path) -> None:
    dates = (date(2020, 1, 31), date(2020, 2, 1))
    first, _reader, _ = _pipeline(tmp_path / "one", run_name="run", dates=dates)
    second, _reader_two, _ = _pipeline(
        tmp_path / "two",
        run_name="run",
        dates=dates,
        reverse_authority=True,
    )

    first_result = first.build(
        instruments=("BTCUSDT",),
        start=dates[0],
        end_exclusive=dates[-1] + timedelta(days=1),
    )
    second_result = second.build(
        instruments=("BTCUSDT",),
        start=dates[0],
        end_exclusive=dates[-1] + timedelta(days=1),
    )

    assert tuple(item.object_sha256 for item in first_result.artifacts) == tuple(
        item.object_sha256 for item in second_result.artifacts
    )
    assert tuple(item.semantic_receipt_sha256 for item in first_result.receipts) == tuple(
        item.semantic_receipt_sha256 for item in second_result.receipts
    )


def test_resume_rejects_tampered_object_and_changed_authority(tmp_path: Path) -> None:
    dates = (date(2020, 1, 1),)
    pipeline, _reader, run_root = _pipeline(tmp_path, run_name="tamper", dates=dates)
    result = pipeline.build(
        instruments=("BTCUSDT",),
        start=dates[0],
        end_exclusive=dates[0] + timedelta(days=1),
    )
    checkpoint = next(item for item in result.checkpoints if item.artifact is not None)
    assert checkpoint.artifact is not None
    object_path = pipeline.config.catalog_root / checkpoint.artifact.relative_path
    object_path.write_bytes(object_path.read_bytes() + b"tamper")

    retry, _retry_reader, _ = _pipeline(tmp_path, run_name="tamper", dates=dates)
    with pytest.raises(ContractViolation, match="sealed Foundation object changed"):
        retry.build(
            instruments=("BTCUSDT",),
            start=dates[0],
            end_exclusive=dates[0] + timedelta(days=1),
        )

    # Restore a separate run and then change only the Catalog logical authority.
    authority, _reader_two, authority_root = _pipeline(tmp_path, run_name="authority", dates=dates)
    authority.build(
        instruments=("BTCUSDT",),
        start=dates[0],
        end_exclusive=dates[0] + timedelta(days=1),
    )
    source_root = tmp_path / "sources"
    trades, prices = _fixture_indexes(source_root, dates)
    changed = Stage1TradesCatalogIndex(
        published_root=trades.published_root,
        partitions=tuple(replace(item, logical_sha256="c" * 64) for item in trades.partitions),
    )
    changed_reader = FoundationSourceReader(
        trades_index=changed,
        contract_price_index=prices,
    )
    changed_pipeline = FeatureFoundationPipeline(
        config=FoundationPipelineConfig(
            run_root=authority_root,
            approved_external_root=tmp_path / "approved-external",
        ),
        snapshot_id=H,
        trades_index=changed,
        contract_price_index=prices,
        source_reader=changed_reader,
    )
    with pytest.raises(ContractViolation, match="authority changed"):
        changed_pipeline.build(
            instruments=("BTCUSDT",),
            start=dates[0],
            end_exclusive=dates[0] + timedelta(days=1),
        )


def test_fixed_resource_and_global_object_budget() -> None:
    assert (
        planned_packed_object_count(
            start=date(2020, 1, 1),
            end_exclusive=date(2026, 7, 4),
            instrument_count=2,
        )
        == 164
    )
    with pytest.raises(ValidationError):
        FoundationPipelineConfig.model_validate(
            {
                "run_root": Path("/tmp/not-used/run"),
                "approved_external_root": Path("/tmp/not-used"),
                "compute_worker_count": 4,
            }
        )


def test_process_rss_gate_accepts_exact_limit_and_rejects_one_byte_over() -> None:
    at_limit = _InflightBudget(
        MAX_INFLIGHT_BYTES,
        rss_limit=MAX_PROCESS_RSS_BYTES,
        rss_reader=lambda: MAX_PROCESS_RSS_BYTES,
    )
    at_limit.check(())
    assert at_limit.rss_observed == MAX_PROCESS_RSS_BYTES

    over_limit = _InflightBudget(
        MAX_INFLIGHT_BYTES,
        rss_limit=MAX_PROCESS_RSS_BYTES,
        rss_reader=lambda: MAX_PROCESS_RSS_BYTES + 1,
    )
    with pytest.raises(MemoryError, match="process RSS"):
        over_limit.check(())


def test_production_pipeline_contains_no_row_materialization_or_recursive_glob() -> None:
    source = Path("src/era100x/research/stage_2/runtime_v2/foundation_pipeline.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("to_dicts(", "iter_rows(", "json.dumps(", ".rglob(", "os.walk("):
        assert forbidden not in source
