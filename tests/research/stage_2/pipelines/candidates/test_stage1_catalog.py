from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from era100x.research.stage_2.manifests.models import Stage2PreregistrationManifest
from era100x.research.stage_2.pipelines.candidates.flow_phase import build_flow_day
from era100x.research.stage_2.pipelines.candidates.stage1_catalog import (
    Stage1CatalogAuthority,
    Stage1TradesCatalogIndex,
    sha256_file,
)

INSTRUMENTS = ("BTCUSDT", "ETHUSDT")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def catalog_fixture(
    tmp_path: Path,
    *,
    dates: tuple[date, ...] = (date(2020, 1, 1),),
    reverse: bool = False,
    duplicate: bool = False,
    full_archive_relative: str | None = None,
    create_partition: bool = True,
    run_id: str = "stage1-run",
) -> tuple[Path, Path, Stage1CatalogAuthority]:
    catalog_root = tmp_path / "catalog" / run_id
    published_root = tmp_path / "published" / "stage1-trades-v2" / run_id
    symbols: dict[str, Any] = {}
    catalog_hashes: dict[str, str] = {}
    logical_hashes: dict[str, str] = {}
    for instrument in INSTRUMENTS:
        entries = []
        for partition_date in dates:
            stamp = partition_date.isoformat()
            relative = full_archive_relative or f"date={stamp}/part-000.parquet"
            entry = {
                "instrument": instrument,
                "date": stamp,
                "relative_path": relative,
                "byte_sha256": hashlib.sha256(f"{instrument}-{stamp}".encode()).hexdigest(),
                "logical_sha256": hashlib.sha256(
                    f"logical-{instrument}-{stamp}".encode()
                ).hexdigest(),
            }
            entries.append(entry)
            if create_partition:
                physical_relative = (
                    Path(relative)
                    if relative.startswith("archive=")
                    else Path(f"archive={stamp[:7]}") / relative
                )
                physical = published_root / instrument / physical_relative
                physical.parent.mkdir(parents=True, exist_ok=True)
                physical.write_bytes(b"fixture")
        if reverse:
            entries.reverse()
        if duplicate:
            entries.append(dict(entries[0]))
        logical_hash = hashlib.sha256(f"catalog-{instrument}".encode()).hexdigest()
        catalog = {
            "status": "READY_TO_PUBLISH",
            "logical_data_hash": logical_hash,
            "entries": entries,
        }
        catalog_path = catalog_root / f"{instrument}.catalog.json"
        _write_json(catalog_path, catalog)
        catalog_hashes[instrument] = sha256_file(catalog_path)
        logical_hashes[instrument] = logical_hash
        symbols[instrument] = {"logical_data_hash": logical_hash, "entries": entries}
    manifest_payload = {
        "run_id": run_id,
        "dataset_version": "stage1-trades-v2",
        "symbols": symbols,
    }
    canonical_hash = hashlib.sha256(
        json.dumps(manifest_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest = dict(manifest_payload, manifest_sha256=canonical_hash)
    manifest_path = catalog_root / "manifest.json"
    _write_json(manifest_path, manifest)
    authority = Stage1CatalogAuthority(
        data_run_id=run_id,
        dataset_version="stage1-trades-v2",
        canonical_manifest_sha256=canonical_hash,
        physical_manifest_sha256=sha256_file(manifest_path),
        catalog_sha256s=catalog_hashes,  # type: ignore[arg-type]
        logical_hashes=logical_hashes,  # type: ignore[arg-type]
    )
    return catalog_root, published_root, authority


def load_fixture(tmp_path: Path, **kwargs: Any) -> Stage1TradesCatalogIndex:
    catalog_root, published_root, authority = catalog_fixture(tmp_path, **kwargs)
    return Stage1TradesCatalogIndex.load(
        catalog_run_root=catalog_root,
        published_root=published_root,
        authority=authority,
    )


def test_single_and_multiple_archive_months_are_catalog_authoritative(tmp_path: Path) -> None:
    index = load_fixture(tmp_path, dates=(date(2020, 1, 31), date(2020, 2, 1)))
    paths = [item.path.as_posix() for item in index.partitions if item.instrument == "BTCUSDT"]
    assert paths == sorted(paths)
    assert "/archive=2020-01/date=2020-01-31/" in paths[0]
    assert "/archive=2020-02/date=2020-02-01/" in paths[1]


def test_daily_archive_partition_is_supported_without_glob(tmp_path: Path) -> None:
    index = load_fixture(
        tmp_path,
        dates=(date(2026, 7, 1),),
        full_archive_relative="archive=2026-07-01/date=2026-07-01/part-000.parquet",
    )
    partition = index.partitions_around("BTCUSDT", date(2026, 7, 1))[0]
    assert partition.archive_partition == "2026-07-01"


def test_btc_and_eth_are_separate_and_decoy_paths_are_ignored(tmp_path: Path) -> None:
    index = load_fixture(tmp_path)
    decoy = index.published_root / "BTCUSDT" / "date=2020-01-01" / "part-000.parquet"
    decoy.parent.mkdir(parents=True)
    decoy.write_bytes(b"direct-date-decoy")
    staging = tmp_path / "staging" / "BTCUSDT" / "archive=2020-01" / "date=2020-01-01"
    staging.mkdir(parents=True)
    (staging / "part-000.parquet").write_bytes(b"staging-decoy")
    btc = index.partitions_around("BTCUSDT", date(2020, 1, 1))
    eth = index.partitions_around("ETHUSDT", date(2020, 1, 1))
    assert len(btc) == len(eth) == 1
    assert btc[0].instrument == "BTCUSDT" and eth[0].instrument == "ETHUSDT"
    assert btc[0].path != decoy.resolve()


def test_archive_month_must_equal_partition_month(tmp_path: Path) -> None:
    catalog_root, published_root, authority = catalog_fixture(
        tmp_path,
        full_archive_relative="archive=2020-02/date=2020-01-01/part-000.parquet",
    )
    with pytest.raises(ValueError, match="archive month/date mismatch"):
        Stage1TradesCatalogIndex.load(
            catalog_run_root=catalog_root,
            published_root=published_root,
            authority=authority,
        )


def test_catalog_registered_path_must_exist(tmp_path: Path) -> None:
    catalog_root, published_root, authority = catalog_fixture(tmp_path, create_partition=False)
    with pytest.raises(FileNotFoundError, match="Catalog-registered"):
        Stage1TradesCatalogIndex.load(
            catalog_run_root=catalog_root,
            published_root=published_root,
            authority=authority,
        )


def test_exact_duplicate_is_deduplicated_but_conflict_fails(tmp_path: Path) -> None:
    index = load_fixture(tmp_path / "exact", duplicate=True)
    assert len(index.partitions) == 2

    catalog_root, published_root, authority = catalog_fixture(tmp_path / "conflict")
    for instrument in INSTRUMENTS:
        catalog_path = catalog_root / f"{instrument}.catalog.json"
        catalog = json.loads(catalog_path.read_text())
        conflict = dict(catalog["entries"][0], logical_sha256="f" * 64)
        catalog["entries"].append(conflict)
        _write_json(catalog_path, catalog)
        manifest_path = catalog_root / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["symbols"][instrument]["entries"] = catalog["entries"]
        payload = dict(manifest)
        payload.pop("manifest_sha256")
        manifest["manifest_sha256"] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        _write_json(manifest_path, manifest)
    authority = Stage1CatalogAuthority(
        data_run_id=authority.data_run_id,
        dataset_version=authority.dataset_version,
        canonical_manifest_sha256=json.loads((catalog_root / "manifest.json").read_text())[
            "manifest_sha256"
        ],
        physical_manifest_sha256=sha256_file(catalog_root / "manifest.json"),
        catalog_sha256s={
            instrument: sha256_file(catalog_root / f"{instrument}.catalog.json")
            for instrument in INSTRUMENTS
        },  # type: ignore[arg-type]
        logical_hashes=authority.logical_hashes,
    )
    with pytest.raises(ValueError, match="conflicting Stage 1 Catalog partition"):
        Stage1TradesCatalogIndex.load(
            catalog_run_root=catalog_root,
            published_root=published_root,
            authority=authority,
        )


def test_catalog_order_does_not_change_index_hash(tmp_path: Path) -> None:
    dates = (date(2020, 1, 31), date(2020, 2, 1))
    forward = load_fixture(tmp_path / "forward", dates=dates)
    reverse = load_fixture(tmp_path / "reverse", dates=dates, reverse=True)
    assert forward.logical_hash == reverse.logical_hash


def test_data_run_and_logical_hash_mismatch_fail(tmp_path: Path) -> None:
    catalog_root, published_root, authority = catalog_fixture(tmp_path)
    wrong_run = Stage1CatalogAuthority(
        data_run_id="other-run",
        dataset_version=authority.dataset_version,
        canonical_manifest_sha256=authority.canonical_manifest_sha256,
        physical_manifest_sha256=authority.physical_manifest_sha256,
        catalog_sha256s=authority.catalog_sha256s,
        logical_hashes=authority.logical_hashes,
    )
    with pytest.raises(ValueError, match="Data Run ID mismatch"):
        Stage1TradesCatalogIndex.load(
            catalog_run_root=catalog_root,
            published_root=published_root,
            authority=wrong_run,
        )
    wrong_hashes = dict(authority.logical_hashes)
    wrong_hashes["BTCUSDT"] = "0" * 64
    wrong_logical = Stage1CatalogAuthority(
        data_run_id=authority.data_run_id,
        dataset_version=authority.dataset_version,
        canonical_manifest_sha256=authority.canonical_manifest_sha256,
        physical_manifest_sha256=authority.physical_manifest_sha256,
        catalog_sha256s=authority.catalog_sha256s,
        logical_hashes=wrong_hashes,  # type: ignore[arg-type]
    )
    with pytest.raises(ValueError, match="BTCUSDT logical hash mismatch"):
        Stage1TradesCatalogIndex.load(
            catalog_run_root=catalog_root,
            published_root=published_root,
            authority=wrong_logical,
        )


def test_cross_month_window_selects_both_catalog_partitions(tmp_path: Path) -> None:
    index = load_fixture(tmp_path, dates=(date(2020, 1, 31), date(2020, 2, 1)))
    candidates = index.partitions_around("BTCUSDT", date(2020, 2, 1))
    boundary = int(datetime(2020, 2, 1, tzinfo=UTC).timestamp() * 1_000_000_000)
    paths = index.select_for_windows(
        candidates,
        [{"window_start_ts": boundary - 1, "window_end_ts": boundary + 1}],
    )
    assert [path.parent.parent.name for path in paths] == ["archive=2020-01", "archive=2020-02"]


def test_complete_coverage_is_strict(tmp_path: Path) -> None:
    index = load_fixture(tmp_path)
    index.assert_coverage(date(2020, 1, 1), date(2020, 1, 2))
    with pytest.raises(FileNotFoundError, match="coverage missing"):
        index.assert_coverage(date(2020, 1, 1), date(2020, 1, 3))


REAL_PREREGISTRATION = Path(
    "/Volumes/FuckingLife/era100x_stage2/runs/stage2-g1-preregistration-v1.0/manifests/"
    "6b0f66e4007b86e08b58a9b366170eeee952199baa203d7f174b2ca69478c1f9.json"
)


@pytest.mark.skipif(
    not REAL_PREREGISTRATION.exists(), reason="frozen external baseline unavailable"
)
def test_real_first_flow_partition_uses_archive_layout() -> None:
    preregistration = Stage2PreregistrationManifest.model_validate_json(
        REAL_PREREGISTRATION.read_bytes()
    )
    baseline = preregistration.stage1
    authority = Stage1CatalogAuthority(
        data_run_id=baseline.data_run_id,
        dataset_version="stage1-trades-v2",
        canonical_manifest_sha256=baseline.canonical_manifest_sha256,
        physical_manifest_sha256=baseline.physical_manifest_sha256,
        catalog_sha256s={
            "BTCUSDT": baseline.btc_catalog_sha256,
            "ETHUSDT": baseline.eth_catalog_sha256,
        },
        logical_hashes={
            "BTCUSDT": baseline.btc_trades_logical_hash,
            "ETHUSDT": baseline.eth_trades_logical_hash,
        },
    )
    root = Path("/Volumes/FuckingLife/era100x_stage1")
    index = Stage1TradesCatalogIndex.load(
        catalog_run_root=root / "catalog" / "runs" / baseline.data_run_id,
        published_root=root / "published" / "stage1-trades-v2" / baseline.data_run_id,
        authority=authority,
    )
    partition = index.partitions_around("BTCUSDT", date(2020, 1, 1))[0]
    assert "/archive=2020-01/date=2020-01-01/" in partition.path.as_posix()
    end_ns = 1_577_923_196_200_000_000
    result = build_flow_day(
        trade_paths=(partition.path,),
        instrument="BTCUSDT",
        windows=[
            {
                "window_start_ts": end_ns - 5_000_000_000,
                "window_end_ts": end_ns,
                "trigger_id": "real-first-partition-smoke",
                "event_parameter_set_id": "G1-PRIMARY-V1",
                "market_episode_id": "real-first-partition-smoke",
                "canonical_candidate_id": "1" * 64,
                "candidate_version_id": "1" * 64,
                "canonical_payload_hash": "2" * 64,
                "direction": "LONG",
                "canonical_key_level_id": "3" * 64,
                "sweep_id": "4" * 64,
                "reclaim_id": "5" * 64,
                "hold_id": "6" * 64,
                "time_combination_id": "T2",
                "data_run_id": baseline.data_run_id,
                "dataset_logical_hash": baseline.btc_trades_logical_hash,
                "config_hash": preregistration.config_hash,
                "code_version": "abcdef0",
                "venue": "BINANCE_USDM",
                "sweep_start_ns": end_ns - 10_000_000_000,
            }
        ],
    )
    assert len(result["flow_features"]) == 1
