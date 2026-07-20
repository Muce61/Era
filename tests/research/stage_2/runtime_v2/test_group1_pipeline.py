from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Literal, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pytest

from era100x.research.stage_2.runtime_v2.catalog import (
    ArtifactStoreV2,
    CatalogCompactorV2,
    CatalogPublisherV2,
    PartitionBatch,
)
from era100x.research.stage_2.runtime_v2.dataset_specs import (
    FLOW_DATASETS,
    PRICE_DATASETS,
    group1_dataset_specs,
)
from era100x.research.stage_2.runtime_v2.errors import ContractViolation
from era100x.research.stage_2.runtime_v2.foundation_pipeline import (
    FoundationShardCheckpoint,
    FoundationSourceBinding,
)
from era100x.research.stage_2.runtime_v2.foundation_specs import (
    feature_foundation_dataset_specs,
)
from era100x.research.stage_2.runtime_v2.group1_feature_builder import Group1Lineage
from era100x.research.stage_2.runtime_v2.group1_pipeline import (
    GROUP1_BINDINGS,
    Group1FeaturePipeline,
    Group1MonthlyDatasetSeal,
    Group1PipelineConfig,
    PackedFoundationFeatureReader,
    _DailyRecordSpool,
    _count_release_distributions,
    _canonical_component_artifacts,
    _distribution_models,
    _load_processing_day_cache,
    _packed_month_windows,
    _write_or_verify_processing_day_cache,
    group1_object_count_observation_threshold,
)
from era100x.research.stage_2.runtime_v2.hashing import canonical_arrow_schema
from era100x.research.stage_2.runtime_v2.manifest_factory import (
    FOUNDATION_CONTEXT_ID,
    FOUNDATION_SETUP_ID,
    FOUNDATION_VARIANTS,
)
from era100x.research.stage_2.runtime_v2.models import (
    MAX_PROCESS_CURRENT_RSS_BYTES,
    MAX_PROCESS_RSS_DELTA_BYTES,
    DatasetPlan,
    DigestBinding,
    LogicalPartitionKey,
    ManifestV2,
    QualityFact,
    ArtifactRef,
)
from era100x.research.stage_2.runtime_v2.memory import ProcessMemoryBudget
from era100x.research.stage_2.runtime_v2 import group1_pipeline as pipeline_module
from era100x.research.stage_2.pipelines.candidates.io import records_logical_hash

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
DAY_NS = 86_400_000_000_000


def _artifact(object_hash: str, dataset_hash: str) -> ArtifactRef:
    return ArtifactRef(
        snapshot_id=H1,
        dataset_spec_hash=dataset_hash,
        object_sha256=object_hash,
        relative_path=f"objects/{object_hash[:2]}/{object_hash}.parquet",
        byte_size=1,
        row_count=1,
        semantic_sha256=H3,
    )


def test_component_artifact_order_follows_consumer_contract_and_rejects_duplicates() -> None:
    # Composite dataset/object ordering yields b,a here and reproduces the
    # production failure fixed by CR-2026-015.
    first = _artifact("b" * 64, "1" * 64)
    second = _artifact("a" * 64, "2" * 64)

    assert tuple(
        item.object_sha256 for item in _canonical_component_artifacts([first, second])
    ) == ("a" * 64, "b" * 64)
    with pytest.raises(ContractViolation, match="duplicate physical artifacts"):
        _canonical_component_artifacts([first, first])


def _start_ns(owner_date: date) -> int:
    return int(datetime.combine(owner_date, datetime.min.time(), tzinfo=UTC).timestamp()) * 10**9


def _foundation_row(dataset: str, instrument: str, owner_date: date) -> dict[str, object]:
    start = _start_ns(owner_date)
    if dataset == "contract_price_1s":
        return {
            "instrument": instrument,
            "event_ts_ns": start,
            "available_at_ns": start + 1_000_000_000,
            "open": Decimal("100"),
            "high": Decimal("101"),
            "low": Decimal("99"),
            "close": Decimal("100"),
            "volume": Decimal("1"),
            "source_file_sha256": H3,
        }
    if dataset == "causal_price_bars":
        return {
            "instrument": instrument,
            "interval_seconds": 60,
            "event_ts_ns": start,
            "available_at_ns": start + 60_000_000_000,
            "open": Decimal("100"),
            "high": Decimal("101"),
            "low": Decimal("99"),
            "close": Decimal("100"),
            "volume": Decimal("1"),
            "source_file_sha256": H3,
        }
    if dataset == "trade_second_primitives":
        return {
            "instrument": instrument,
            "event_ts_ns": start,
            "second_end_ns": start + 1_000_000_000,
            "available_at_ns": start + 1_000_000_000,
            "trade_count": 1,
            "aggressor_buy_count": 1,
            "aggressor_sell_count": 0,
            "aggressor_buy_qty": Decimal("1"),
            "aggressor_sell_qty": Decimal("0"),
            "signed_qty": Decimal("1"),
            "source_logical_hash": H2,
        }
    raise AssertionError(dataset)


def _foundation_checkpoints(
    catalog_root: Path,
    *,
    instruments: tuple[str, ...],
    dates: tuple[date, ...],
) -> tuple[FoundationShardCheckpoint, ...]:
    specs = {
        item.dataset_name: item
        for item in feature_foundation_dataset_specs()
        if item.dataset_name
        in {
            "contract_price_1s",
            "causal_price_bars",
            "trade_second_primitives",
        }
    }
    store = ArtifactStoreV2(catalog_root)
    compactor = CatalogCompactorV2(store)
    checkpoints: list[FoundationShardCheckpoint] = []
    for instrument in instruments:
        for dataset in sorted(specs):
            spec = specs[dataset]
            batches = []
            for owner_date in dates:
                table = pa.Table.from_pylist(
                    [_foundation_row(dataset, instrument, owner_date)],
                    schema=canonical_arrow_schema(spec),
                )
                batches.append(
                    PartitionBatch(
                        key=LogicalPartitionKey(
                            snapshot_id=H1,
                            dataset_name=spec.dataset_name,
                            dataset_version=spec.dataset_version,
                            dataset_spec_hash=spec.spec_hash,
                            setup_id=FOUNDATION_SETUP_ID,
                            context_id=FOUNDATION_CONTEXT_ID,
                            instrument=instrument,
                            variant=FOUNDATION_VARIANTS[dataset],
                            owner_date=owner_date,
                        ),
                        table=table,
                        legacy_hash_algorithm="NOT_APPLICABLE",
                        legacy_logical_sha256=None,
                        quality_facts=(QualityFact(name="source_authority_complete", value=True),),
                    )
                )
            result = compactor.compact(
                spec=spec,
                snapshot_id=H1,
                shard_id=f"fixture-{instrument.lower()}-{dataset.replace('_', '-')}",
                partitions=batches,
            )
            source_kind: Literal["CONTRACT_PRICE", "STAGE1_TRADES"] = (
                "CONTRACT_PRICE"
                if dataset in {"contract_price_1s", "causal_price_bars"}
                else "STAGE1_TRADES"
            )
            bindings = tuple(
                FoundationSourceBinding(
                    owner_date=owner_date,
                    source_kind=source_kind,
                    relative_path=f"instrument={instrument}/date={owner_date.isoformat()}/part",
                    byte_sha256=H3,
                    logical_sha256=None if source_kind == "CONTRACT_PRICE" else H2,
                )
                for owner_date in dates
            )
            checkpoints.append(
                FoundationShardCheckpoint.seal_checkpoint(
                    {
                        "snapshot_id": H1,
                        "dataset_name": dataset,
                        "dataset_spec_hash": spec.spec_hash,
                        "instrument": instrument,
                        "shard_key": (
                            f"{dates[0].isoformat()}_{(dates[-1] + timedelta(days=1)).isoformat()}"
                        ),
                        "storage_role": "PACKED_FINAL",
                        "window_start_date": dates[0],
                        "window_end_date_exclusive": dates[-1] + timedelta(days=1),
                        "source_bindings": bindings,
                        "artifact": result.artifact,
                        "receipts": result.receipts,
                        "fragments": result.fragments,
                        "seal": result.seal,
                        "seal_relative_path": f"seals/{instrument}-{dataset}.json",
                        "seal_file_sha256": H3,
                    }
                )
            )
    return tuple(checkpoints)


def _pipeline(
    tmp_path: Path,
    *,
    run_name: str,
    checkpoints: tuple[FoundationShardCheckpoint, ...],
) -> tuple[Group1FeaturePipeline, PackedFoundationFeatureReader, Path]:
    external = tmp_path / "external"
    external.mkdir(exist_ok=True)
    run_root = external / run_name
    foundation_root = run_root / "staging" / "snapshot"
    reader = PackedFoundationFeatureReader(
        snapshot_id=H1,
        catalog_root=foundation_root,
        checkpoints=checkpoints,
    )
    lineage = {
        "BTCUSDT": Group1Lineage(
            data_run_id="stage1-fixture",
            dataset_logical_hash=H1,
            config_hash=H2,
            code_version="abcdef0",
        ),
        "ETHUSDT": Group1Lineage(
            data_run_id="stage1-fixture",
            dataset_logical_hash=H2,
            config_hash=H2,
            code_version="abcdef0",
        ),
    }
    config = Group1PipelineConfig(
        run_root=run_root,
        foundation_catalog_root=foundation_root,
        approved_external_root=external,
    )
    pipeline = Group1FeaturePipeline(
        config=config,
        snapshot_id=H1,
        foundation_checkpoints=checkpoints,
        lineage_by_instrument=lineage,  # type: ignore[arg-type]
        foundation_reader=reader,
    )
    return pipeline, reader, run_root


def test_explicit_foundation_reader_uses_fixed_causal_halo_across_midnight(
    tmp_path: Path,
) -> None:
    dates = tuple(date(2020, 1, 29) + timedelta(days=offset) for offset in range(5))
    root = tmp_path / "external" / "reader" / "staging" / "foundation" / "catalog"
    checkpoints = _foundation_checkpoints(root, instruments=("BTCUSDT",), dates=dates)
    reader = PackedFoundationFeatureReader(
        snapshot_id=H1,
        catalog_root=root,
        checkpoints=tuple(reversed(checkpoints)),
    )

    window = reader.read_window(
        instrument="BTCUSDT",
        owner_start=date(2020, 1, 31),
        owner_end_exclusive=date(2020, 2, 2),
    )

    assert window.contract_price_1s.num_rows == 5  # D-2 through the forward-halo day.
    assert window.causal_price_bars.num_rows == 4  # D-2 through the final owner day.
    assert window.trade_second_primitives.num_rows == 3  # D-1 through final owner day.
    assert min(window.contract_price_1s["event_ts_ns"].to_pylist()) == _start_ns(dates[0])
    assert max(window.contract_price_1s["event_ts_ns"].to_pylist()) == _start_ns(dates[-1])
    assert all(count == 1 for count in reader.read_counts.values())


def test_foundation_sliding_cache_reuses_adjacent_owner_day_fragments(tmp_path: Path) -> None:
    dates = tuple(date(2020, 1, 27) + timedelta(days=offset) for offset in range(7))
    root = tmp_path / "external" / "cache" / "staging" / "snapshot"
    checkpoints = _foundation_checkpoints(root, instruments=("BTCUSDT",), dates=dates)
    reader = PackedFoundationFeatureReader(
        snapshot_id=H1,
        catalog_root=root,
        checkpoints=checkpoints,
    )

    reader.read_window(
        instrument="BTCUSDT",
        owner_start=date(2020, 1, 30),
        owner_end_exclusive=date(2020, 1, 31),
    )
    reader.read_window(
        instrument="BTCUSDT",
        owner_start=date(2020, 1, 31),
        owner_end_exclusive=date(2020, 2, 1),
    )

    assert sum(reader.cache_hits.values()) >= 6
    assert all(count == 1 for count in reader.read_counts.values())
    assert len(reader._partition_cache) <= 9  # noqa: SLF001 - bounded-cache contract.


def test_cross_month_pipeline_emits_thirteen_bindings_and_resumes_without_source_reads(
    tmp_path: Path,
) -> None:
    dates = tuple(date(2020, 1, 29) + timedelta(days=offset) for offset in range(5))
    run_root = tmp_path / "external" / "run-a"
    foundation_root = run_root / "staging" / "snapshot"
    checkpoints = _foundation_checkpoints(
        foundation_root,
        instruments=("BTCUSDT",),
        dates=dates,
    )
    pipeline, first_reader, _run_root = _pipeline(
        tmp_path,
        run_name="run-a",
        checkpoints=checkpoints,
    )
    first = pipeline.build(
        instruments=("BTCUSDT",),
        start=date(2020, 1, 31),
        end_exclusive=date(2020, 2, 2),
    )

    assert len(first.monthly_checkpoints) == 2
    assert all(
        tuple((item.variant, item.dataset) for item in checkpoint.datasets) == GROUP1_BINDINGS
        for checkpoint in first.monthly_checkpoints
    )
    assert len(first.receipts) == 2 * 13
    assert len(first.object_counts) == 13
    assert first.packed_aggregate.total_object_count == len(first.artifacts)
    assert first.packed_aggregate.receipt_count == 26
    assert first.max_inflight_bytes_observed < 1 << 30
    assert first_reader.read_counts
    aggregate_path = run_root / "staging" / "group1" / "packed-aggregate.json"
    aggregate_bytes = aggregate_path.read_bytes()

    resumed_pipeline, resumed_reader, _ = _pipeline(
        tmp_path,
        run_name="run-a",
        checkpoints=tuple(reversed(checkpoints)),
    )
    resumed = resumed_pipeline.build(
        instruments=("BTCUSDT",),
        start=date(2020, 1, 31),
        end_exclusive=date(2020, 2, 2),
    )

    assert resumed.monthly_checkpoints == first.monthly_checkpoints
    assert resumed.packed_aggregate == first.packed_aggregate
    assert aggregate_path.read_bytes() == aggregate_bytes
    assert resumed_reader.read_counts == {}


def test_processing_day_cache_eliminates_cross_month_duplicate_compute(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = tuple(date(2020, 1, 29) + timedelta(days=offset) for offset in range(5))
    foundation_root = tmp_path / "external" / "once" / "staging" / "snapshot"
    checkpoints = _foundation_checkpoints(
        foundation_root,
        instruments=("BTCUSDT",),
        dates=dates,
    )
    pipeline, _reader, _run_root = _pipeline(
        tmp_path,
        run_name="once",
        checkpoints=checkpoints,
    )
    original = pipeline_module.build_price_processing_day_from_features
    calls: list[date] = []

    def counted(**kwargs: object) -> dict[str, list[dict[str, object]]]:
        calls.append(cast(date, kwargs["processing_date"]))
        return original(**kwargs)  # type: ignore[arg-type,return-value]

    monkeypatch.setattr(
        pipeline_module,
        "build_price_processing_day_from_features",
        counted,
    )

    pipeline.build(
        instruments=("BTCUSDT",),
        start=date(2020, 1, 31),
        end_exclusive=date(2020, 2, 2),
    )

    assert calls == [date(2020, 1, 30), date(2020, 1, 31), date(2020, 2, 1)]
    assert len(set(calls)) == len(calls)


def test_month_scheduler_keeps_three_spawn_futures_in_flight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dates = tuple(date(2020, 1, 1) + timedelta(days=offset) for offset in range(5))
    foundation_root = tmp_path / "external" / "parallel" / "staging" / "snapshot"
    checkpoints = _foundation_checkpoints(
        foundation_root,
        instruments=("BTCUSDT",),
        dates=dates,
    )
    pipeline, _reader, _run_root = _pipeline(
        tmp_path,
        run_name="parallel",
        checkpoints=checkpoints,
    )
    pipeline._allow_process_workers = True  # noqa: SLF001 - scheduler contract.
    events: list[tuple[str, str]] = []

    class ImmediateFuture:
        def __init__(self, value: object) -> None:
            self.value = value

        def result(self) -> object:
            events.append(("result", cast(str, self.value)))
            return self.value

        def cancel(self) -> bool:
            return True

    class FakePool:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["max_workers"] == 3

        def submit(self, _function: object, work: object) -> ImmediateFuture:
            month = cast(pipeline_module.Group1MonthWorkItemV1, work).utc_month
            events.append(("submit", month))
            return ImmediateFuture(month)

        def shutdown(self, *, wait: bool, cancel_futures: bool = False) -> None:
            events.append(("shutdown", f"{wait}:{cancel_futures}"))

    monkeypatch.setattr(pipeline_module, "ProcessPoolExecutor", FakePool)
    results = list(
        pipeline._iter_month_results(  # noqa: SLF001 - deterministic scheduler contract.
            ("BTCUSDT",),
            date(2020, 1, 1),
            date(2020, 5, 1),
        )
    )

    assert results == ["2020-01", "2020-02", "2020-03", "2020-04"]
    assert events[:4] == [
        ("submit", "2020-01"),
        ("submit", "2020-02"),
        ("submit", "2020-03"),
        ("result", "2020-01"),
    ]


def test_processing_day_cache_concurrent_same_payload_is_write_once(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    run_root = external / "cache-race"
    config = Group1PipelineConfig(
        run_root=run_root,
        foundation_catalog_root=run_root / "staging" / "snapshot",
        approved_external_root=external,
    )
    lineage = Group1Lineage(
        data_run_id="stage1-fixture",
        dataset_logical_hash=H1,
        config_hash=H2,
        code_version="abcdef0",
    )
    attempts = ({"canonical_candidate_id": "candidate", "available_at_ts": 1},)
    kwargs = {
        "config": config,
        "snapshot_id": H1,
        "instrument": "BTCUSDT",
        "processing_date": date(2020, 1, 31),
        "attempts": attempts,
        "foundation_authority": (H3,),
        "lineage": lineage,
    }

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = tuple(
            future.result()
            for future in (
                pool.submit(_write_or_verify_processing_day_cache, **kwargs),  # type: ignore[arg-type]
                pool.submit(_write_or_verify_processing_day_cache, **kwargs),  # type: ignore[arg-type]
            )
        )

    assert receipts[0] == receipts[1]
    assert (
        _load_processing_day_cache(
            config=config,
            snapshot_id=H1,
            instrument="BTCUSDT",
            processing_date=date(2020, 1, 31),
            expected_foundation_authority=(H3,),
            lineage=lineage,
        )
        == attempts
    )


def test_streaming_component_build_matches_compatibility_graph_and_resumes(
    tmp_path: Path,
) -> None:
    dates = tuple(date(2020, 1, 29) + timedelta(days=offset) for offset in range(5))
    compatibility_root = tmp_path / "external" / "compat" / "staging" / "snapshot"
    compatibility_checkpoints = _foundation_checkpoints(
        compatibility_root,
        instruments=("BTCUSDT",),
        dates=dates,
    )
    compatibility, _reader, _ = _pipeline(
        tmp_path,
        run_name="compat",
        checkpoints=compatibility_checkpoints,
    )
    expected = compatibility.build(
        instruments=("BTCUSDT",),
        start=date(2020, 1, 31),
        end_exclusive=date(2020, 2, 2),
    )

    streaming_root = tmp_path / "external" / "stream" / "staging" / "snapshot"
    streaming_checkpoints = _foundation_checkpoints(
        streaming_root,
        instruments=("BTCUSDT",),
        dates=dates,
    )
    streaming, first_reader, run_root = _pipeline(
        tmp_path,
        run_name="stream",
        checkpoints=streaming_checkpoints,
    )
    components = []
    actual = streaming.build_streaming_components(
        instruments=("BTCUSDT",),
        start=date(2020, 1, 31),
        end_exclusive=date(2020, 2, 2),
        component_sink=components.append,
    )

    assert [(item.instrument, item.variant) for item in components] == [
        ("BTCUSDT", "V1_PRICE"),
        ("BTCUSDT", "V1_FLOW"),
    ]
    actual_receipts = tuple(
        sorted(
            (receipt for component in components for receipt in component.receipts),
            key=lambda item: item.partition.semantic_order_key(),
        )
    )
    assert tuple(item.semantic_receipt_sha256 for item in actual_receipts) == tuple(
        item.semantic_receipt_sha256 for item in expected.receipts
    )
    assert actual.packed_aggregate == expected.packed_aggregate
    assert (
        len(
            tuple((run_root / "staging" / "group1" / "monthly-dataset-checkpoints").rglob("*.json"))
        )
        == 26
    )
    assert first_reader.read_counts

    resumed, resumed_reader, _ = _pipeline(
        tmp_path,
        run_name="stream",
        checkpoints=tuple(reversed(streaming_checkpoints)),
    )
    resumed_components = []
    resumed_result = resumed.build_streaming_components(
        instruments=("BTCUSDT",),
        start=date(2020, 1, 31),
        end_exclusive=date(2020, 2, 2),
        component_sink=resumed_components.append,
    )
    assert resumed_result.packed_aggregate == actual.packed_aggregate
    assert resumed_components == components
    assert resumed_reader.read_counts == {}


def test_foundation_checkpoint_input_order_does_not_change_group1_semantics(
    tmp_path: Path,
) -> None:
    dates = tuple(date(2020, 1, 29) + timedelta(days=offset) for offset in range(5))
    left_root = tmp_path / "external" / "left" / "staging" / "snapshot"
    left_checkpoints = _foundation_checkpoints(left_root, instruments=("BTCUSDT",), dates=dates)
    left, _reader, _ = _pipeline(tmp_path, run_name="left", checkpoints=left_checkpoints)
    left_result = left.build(
        instruments=("BTCUSDT",),
        start=date(2020, 1, 31),
        end_exclusive=date(2020, 2, 2),
    )

    right_root = tmp_path / "external" / "right" / "staging" / "snapshot"
    right_checkpoints = _foundation_checkpoints(right_root, instruments=("BTCUSDT",), dates=dates)
    right, _reader, _ = _pipeline(
        tmp_path,
        run_name="right",
        checkpoints=tuple(reversed(right_checkpoints)),
    )
    right_result = right.build(
        instruments=("BTCUSDT",),
        start=date(2020, 1, 31),
        end_exclusive=date(2020, 2, 2),
    )

    left_semantics = tuple(
        (item.partition.cross_run_partition_id, item.semantic_receipt_sha256)
        for item in left_result.receipts
    )
    right_semantics = tuple(
        (item.partition.cross_run_partition_id, item.semantic_receipt_sha256)
        for item in right_result.receipts
    )
    assert left_semantics == right_semantics
    assert tuple(item.object_sha256 for item in left_result.artifacts) == tuple(
        item.object_sha256 for item in right_result.artifacts
    )


@dataclass(frozen=True)
class _SizedArtifact:
    byte_size: int


@dataclass(frozen=True)
class _SizedMonth:
    artifact: _SizedArtifact


def test_large_binding_is_split_by_deterministic_128_to_512_mib_boundaries() -> None:
    mib = 1 << 20
    synthetic = tuple(_SizedMonth(_SizedArtifact(100 * mib)) for _ in range(6))

    windows = _packed_month_windows(
        cast(tuple[Group1MonthlyDatasetSeal, ...], synthetic),
        target_bytes=256 * mib,
        min_bytes=128 * mib,
        max_bytes=512 * mib,
    )

    assert tuple(len(item) for item in windows) == (3, 3)
    assert all(
        128 * mib
        <= sum(cast(_SizedMonth, month).artifact.byte_size for month in window)
        <= 512 * mib
        for window in windows
    )

    for sizes in ((100, 450), (127, 400)):
        edge = tuple(_SizedMonth(_SizedArtifact(item * mib)) for item in sizes)
        edge_windows = _packed_month_windows(
            cast(tuple[Group1MonthlyDatasetSeal, ...], edge),
            target_bytes=256 * mib,
            min_bytes=128 * mib,
            max_bytes=512 * mib,
        )
        assert tuple(len(item) for item in edge_windows) == (1, 1)
        assert all(
            sum(cast(_SizedMonth, month).artifact.byte_size for month in window) <= 512 * mib
            for window in edge_windows
        )

    oversized = (_SizedMonth(_SizedArtifact(513 * mib)),)
    oversized_windows = _packed_month_windows(
        cast(tuple[Group1MonthlyDatasetSeal, ...], oversized),
        target_bytes=256 * mib,
        min_bytes=128 * mib,
        max_bytes=512 * mib,
    )
    assert oversized_windows == (cast(tuple[Group1MonthlyDatasetSeal, ...], oversized),)


def test_release_distribution_counts_use_v1_key_value_normalization() -> None:
    from collections import Counter

    counter: Counter[tuple[str, str]] = Counter()
    record = {
        "ownership_status": "OWNED",
        "research_role": "PRIMARY",
        "time_combination_id": "T2",
        "event_parameter_set_id": "G1-PRIMARY-V1",
        "reason_code": "CANONICAL_INCLUDED",
        "primary_eligible": True,
    }
    _count_release_distributions(
        counter,
        [record],
        dataset="market_episodes",
        variant="V1_PRICE",
    )
    result = {(item.name, item.value): item.count for item in _distribution_models(counter)}

    for field in (
        "ownership_status",
        "research_role",
        "time_combination_id",
        "parameter_set_id",
        "reason_code",
    ):
        assert sum(count for (name, _value), count in result.items() if name == field) == 1
    assert result[("primary_eligible", "true")] == 1
    assert result[("candidate_variant_id", "V1_PRICE")] == 1


def test_thirty_day_spool_proxy_preserves_legacy_hash_with_bounded_daily_state(
    tmp_path: Path,
) -> None:
    external = tmp_path / "external"
    external.mkdir()
    run_root = external / "spool"
    config = Group1PipelineConfig(
        run_root=run_root,
        foundation_catalog_root=run_root / "staging" / "snapshot",
        approved_external_root=external,
    )
    for offset in range(30):
        owner_date = date(2020, 1, 1) + timedelta(days=offset)
        records = [
            {
                "key_level_id": f"{offset:02d}-{ordinal:05d}",
                "normalization_group": "fixture-group",
                "member_key_level_ids": [f"member-{ordinal:05d}"],
                "reason_code": "PRIORITY_WINNER",
                "event_parameter_set_id": "G1-PRIMARY-V1",
            }
            for ordinal in range(2_500)
        ]
        spool = _DailyRecordSpool(
            config=config,
            snapshot_id=H1,
            instrument="BTCUSDT",
            dataset="arbitration",
            owner_date=owner_date,
            memory_budget=ProcessMemoryBudget(),
        )
        for record in records:
            spool.add(record)
        prepared = spool.finish()

        assert prepared.row_count == len(records)
        assert prepared.legacy_logical_sha256 == records_logical_hash(records, "arbitration")
    assert not tuple((run_root / "staging" / "group1" / "partials").rglob("*.partial"))


def test_binding_registry_is_exactly_ten_price_plus_three_flow() -> None:
    assert GROUP1_BINDINGS == tuple(
        [("V1_PRICE", item) for item in PRICE_DATASETS]
        + [("V1_FLOW", item) for item in FLOW_DATASETS]
    )
    assert len(GROUP1_BINDINGS) == 13


def test_group1_object_count_threshold_is_observational() -> None:
    assert group1_object_count_observation_threshold(164) == 36


def test_group1_memory_thresholds_are_independent_and_audit_only(tmp_path: Path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    run_root = external / "rss-gate"
    config = Group1PipelineConfig(
        run_root=run_root,
        foundation_catalog_root=run_root / "staging" / "snapshot",
        approved_external_root=external,
    )
    assert config.max_process_current_rss_bytes == MAX_PROCESS_CURRENT_RSS_BYTES
    assert config.max_process_rss_delta_bytes == MAX_PROCESS_RSS_DELTA_BYTES

    current_values = iter((1_700_000_000, 1_700_000_000))
    peak_values = iter((1_700_000_000, 1_700_000_000 + MAX_PROCESS_RSS_DELTA_BYTES))
    budget = ProcessMemoryBudget(
        current_limit_bytes=MAX_PROCESS_CURRENT_RSS_BYTES,
        delta_limit_bytes=MAX_PROCESS_RSS_DELTA_BYTES,
        current_reader=lambda: next(current_values),
        peak_reader=lambda: next(peak_values),
    )
    assert (
        pipeline_module._require_rss_within_limit(
            config,
            budget,
            phase="fixture",
        )
        == 1_700_000_000 + MAX_PROCESS_RSS_DELTA_BYTES
    )

    current_values = iter((100, MAX_PROCESS_CURRENT_RSS_BYTES + 1))
    over_current = ProcessMemoryBudget(
        current_limit_bytes=MAX_PROCESS_CURRENT_RSS_BYTES,
        delta_limit_bytes=MAX_PROCESS_RSS_DELTA_BYTES,
        current_reader=lambda: next(current_values),
        peak_reader=lambda: 100,
    )
    pipeline_module._require_rss_within_limit(
        config,
        over_current,
        phase="fixture",
    )
    assert over_current.anomalies[0].metric_name == "CURRENT_RSS_BYTES"

    over_arrow = ProcessMemoryBudget(current_reader=lambda: 100, peak_reader=lambda: 100)
    pipeline_module._require_rss_within_limit(
        config,
        over_arrow,
        phase="fixture",
        arrow_inflight_bytes=config.max_inflight_bytes + 1,
    )
    assert over_arrow.anomalies[0].metric_name == "ARROW_INFLIGHT_BYTES"


def test_group1_rss_diagnostic_cli_is_explicitly_non_production() -> None:
    root = Path(__file__).parents[4]
    script = root / "scripts" / "diagnose_stage2_v2_group1_rss.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "DIAGNOSTIC_ONLY" in completed.stdout
    assert "prep" in completed.stdout
    assert "measure" in completed.stdout
    assert "paths" in completed.stdout


def test_foundation_and_group1_publish_as_one_catalog_without_a_count_gate(
    tmp_path: Path,
) -> None:
    dates = tuple(date(2020, 1, 29) + timedelta(days=offset) for offset in range(5))
    run_root = tmp_path / "external" / "merged"
    snapshot_root = run_root / "staging" / "snapshot"
    checkpoints = _foundation_checkpoints(
        snapshot_root,
        instruments=("BTCUSDT",),
        dates=dates,
    )
    pipeline, _reader, _ = _pipeline(
        tmp_path,
        run_name="merged",
        checkpoints=checkpoints,
    )
    group1 = pipeline.build(
        instruments=("BTCUSDT",),
        start=date(2020, 1, 31),
        end_exclusive=date(2020, 2, 2),
    )
    foundation_artifacts = tuple(item.artifact for item in checkpoints if item.artifact is not None)
    foundation_receipts = tuple(receipt for item in checkpoints for receipt in item.receipts)
    foundation_fragments = tuple(fragment for item in checkpoints for fragment in item.fragments)
    foundation_seals = tuple(item.seal for item in checkpoints)
    all_receipts = (*foundation_receipts, *group1.receipts)
    foundation_specs = tuple(
        item
        for item in feature_foundation_dataset_specs()
        if item.dataset_name
        in {"contract_price_1s", "causal_price_bars", "trade_second_primitives"}
    )
    all_specs = tuple(
        sorted((*foundation_specs, *group1_dataset_specs()), key=lambda item: item.spec_hash)
    )
    manifest = ManifestV2.seal(
        {
            "snapshot_id": H1,
            "stage1_data_run_id": "stage1-fixture",
            "stage1_authorities": (DigestBinding(name="stage1_manifest", sha256=H1),),
            "preregistration_manifest_sha256": H2,
            "config_sha256": H2,
            "code_tree_sha256": H3,
            "dataset_specs": all_specs,
            "dataset_plans": tuple(
                sorted(
                    (
                        DatasetPlan(
                            dataset_spec_hash=spec.spec_hash,
                            expected_partition_ids=tuple(
                                sorted(
                                    receipt.partition.partition_id
                                    for receipt in all_receipts
                                    if receipt.partition.dataset_spec_hash == spec.spec_hash
                                )
                            ),
                        )
                        for spec in all_specs
                    ),
                    key=lambda item: item.dataset_spec_hash,
                )
            ),
            "invalidation_conditions": ("fixture source changes",),
        }
    )
    artifacts = (*foundation_artifacts, *group1.artifacts)
    seals = (*foundation_seals, *group1.seals)

    catalog = CatalogPublisherV2(snapshot_root).publish(
        manifest,
        artifacts=artifacts,
        receipts=all_receipts,
        fragments=(*foundation_fragments, *group1.fragments),
        seals=seals,
    )

    assert catalog.objects_index.row_count == len(artifacts)
    assert len(catalog.seals) == len(seals)
    assert sum(item.partition_count for item in catalog.dataset_roots) == len(all_receipts)
