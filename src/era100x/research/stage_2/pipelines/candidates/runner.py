from __future__ import annotations

import json
import os
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import polars as pl

from era100x.research.stage_2.manifests.models import (
    Stage2ExecutionManifest,
    Stage2PreregistrationManifest,
)
from era100x.research.stage_2.pipelines.candidates.flow_phase import build_flow_day
from era100x.research.stage_2.pipelines.candidates.io import (
    atomic_json,
    catalog_tree,
    write_partition,
)
from era100x.research.stage_2.pipelines.candidates.price_phase import build_price_day
from era100x.research.stage_2.pipelines.candidates.stage1_catalog import (
    Stage1CatalogAuthority,
    Stage1TradesCatalogIndex,
    Stage1TradesPartition,
)

Instrument = Literal["BTCUSDT", "ETHUSDT"]
Variant = Literal["V1_PRICE", "V1_FLOW"]
INSTRUMENTS: tuple[Instrument, ...] = ("BTCUSDT", "ETHUSDT")
VARIANTS: tuple[Variant, ...] = ("V1_PRICE", "V1_FLOW")
START = date(2020, 1, 1)
END = date(2026, 7, 4)
STAGE1_RUN_ID = "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
EXPECTED_PREREGISTRATION_MANIFEST = (
    "6b0f66e4007b86e08b58a9b366170eeee952199baa203d7f174b2ca69478c1f9"
)
EXPECTED_CONFIG_HASH = "adb6295e210de66d1e69aa008e6161e8fef1e1fd72001ff812b68597f8c72e3f"
STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
CONTRACT_ROOT = Path("/Users/muce/1m_data/klines_data_usdm_1s_agg")
STAGE1_PUBLISHED_ROOT = Path(
    "/Volumes/FuckingLife/era100x_stage1/published/stage1-trades-v2/"
    "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
)
STAGE1_CATALOG_ROOT = Path(
    "/Volumes/FuckingLife/era100x_stage1/catalog/runs/"
    "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
)
PREREGISTRATION_MANIFEST_PATH = (
    STAGE2_ROOT
    / "runs"
    / "stage2-g1-preregistration-v1.0"
    / "manifests"
    / f"{EXPECTED_PREREGISTRATION_MANIFEST}.json"
)
FAILED_RUN_ID = "stage2-g1-full-a-20260716-4c15e46"
LOGICAL_HASHES = {
    "BTCUSDT": "03d437ed9a6c19d92162e5c9dd115df4988e8accce3c8180b749f15cfdcc36a8",
    "ETHUSDT": "6db4d5e411edae3838b352944b83c38ba68915841a1f9c9de8f16ef44c3b8332",
}


def _execute_partition(
    run_root: Path,
    instrument: Instrument,
    variant: Variant,
    day: date,
    data_run_id: str,
    config_hash: str,
    code_commit: str,
    trade_partitions: tuple[Stage1TradesPartition, ...] = (),
) -> str:
    key = f"{instrument}:{variant}:{day}"
    marker = run_root / "staging" / "status" / instrument / variant / f"{day}.json"
    if marker.exists():
        return key
    if variant == "V1_PRICE":
        outputs = build_price_day(
            contract_root=CONTRACT_ROOT,
            instrument=instrument,
            day=day,
            data_run_id=data_run_id,
            dataset_logical_hash=LOGICAL_HASHES[instrument],
            config_hash=config_hash,
            code_version=code_commit,
        )
    else:
        window_path = (
            run_root
            / "staging"
            / "data"
            / f"instrument={instrument}"
            / "variant=V1_PRICE"
            / "flow_windows"
            / f"date={day}"
            / "part-000.parquet"
        )
        frame = pl.read_parquet(window_path)
        windows = [] if "empty_partition" in frame.columns else frame.to_dicts()
        trade_paths = Stage1TradesCatalogIndex.select_for_windows(trade_partitions, windows)
        outputs = build_flow_day(trade_paths=trade_paths, instrument=instrument, windows=windows)
    for dataset, records in outputs.items():
        path = (
            run_root
            / "staging"
            / "data"
            / f"instrument={instrument}"
            / f"variant={variant}"
            / dataset
            / f"date={day}"
            / "part-000.parquet"
        )
        write_partition(path, records, dataset)
    atomic_json(marker, {"key": key, "status": "COMPLETE"})
    return key


def dates() -> list[date]:
    result = []
    current = START
    while current < END:
        result.append(current)
        current += timedelta(days=1)
    return result


class CandidateRun:
    def __init__(self, run_id: str, manifest_path: Path) -> None:
        self.run_id = run_id
        self.root = STAGE2_ROOT / "runs" / run_id
        self.manifest = Stage2ExecutionManifest.model_validate_json(manifest_path.read_bytes())
        if self.manifest.manifest_hash != self.manifest.computed_hash():
            raise ValueError("unlocked or invalid execution Manifest")
        self.manifest_path = manifest_path
        self.preregistration: Stage2PreregistrationManifest | None = None
        self.stage1_index: Stage1TradesCatalogIndex | None = None
        if self.manifest.stage1_data_run_id == STAGE1_RUN_ID:
            self._load_production_authority()

    def _load_production_authority(self) -> None:
        if self.manifest.preregistration_manifest_hash != EXPECTED_PREREGISTRATION_MANIFEST:
            raise ValueError("Stage 2 preregistration Manifest changed")
        if self.manifest.config_hash != EXPECTED_CONFIG_HASH:
            raise ValueError("Stage 2 preregistered config hash changed")
        if self.manifest.recovery is None:
            raise ValueError("CR-2026-003 recovery metadata is required")
        recovery = self.manifest.recovery
        if (
            recovery.recovery_of_run_id != FAILED_RUN_ID
            or recovery.supersedes_failed_run_id != FAILED_RUN_ID
            or recovery.change_request != "CR-2026-003"
            or recovery.reused_price_staging
        ):
            raise ValueError("invalid CR-2026-003 recovery metadata")
        preregistration = Stage2PreregistrationManifest.model_validate_json(
            PREREGISTRATION_MANIFEST_PATH.read_bytes()
        )
        if preregistration.manifest_hash != self.manifest.preregistration_manifest_hash:
            raise ValueError("preregistration Manifest hash mismatch")
        if preregistration.config_hash != self.manifest.config_hash:
            raise ValueError("execution/preregistration config hash mismatch")
        baseline = preregistration.stage1
        if baseline.data_run_id != self.manifest.stage1_data_run_id:
            raise ValueError("execution/preregistration Stage 1 Data Run mismatch")
        if self.manifest.stage1_logical_hashes != {
            "BTCUSDT": baseline.btc_trades_logical_hash,
            "ETHUSDT": baseline.eth_trades_logical_hash,
        }:
            raise ValueError("execution/preregistration Stage 1 logical hash mismatch")
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
        self.preregistration = preregistration
        self.stage1_index = Stage1TradesCatalogIndex.load(
            catalog_run_root=STAGE1_CATALOG_ROOT,
            published_root=STAGE1_PUBLISHED_ROOT,
            authority=authority,
        )

    @classmethod
    def preflight(cls, run_id: str, manifest_path: Path) -> CandidateRun:
        run = cls(run_id, manifest_path)
        current_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        if run.manifest.stage1_data_run_id == STAGE1_RUN_ID:
            if current_commit != run.manifest.code_commit:
                raise ValueError("execution Manifest code commit does not match current HEAD")
            if run.stage1_index is None:
                raise ValueError("Stage 1 Catalog index unavailable")
            run.stage1_index.assert_coverage(START, END)
            failed_root = STAGE2_ROOT / "runs" / FAILED_RUN_ID
            failed_checkpoint = json.loads((failed_root / "checkpoint.json").read_text())
            if (
                failed_checkpoint.get("status") != "FAILED"
                or (failed_root / "published" / "data").exists()
            ):
                raise ValueError("failed predecessor run state changed")
        if run.root.exists():
            raise FileExistsError("append-only run_id already exists")
        for name in ("staging", "published", "manifests", "reports", "logs", "tmp"):
            (run.root / name).mkdir(parents=True, exist_ok=False)
        shutil.copy2(manifest_path, run.root / "manifests" / manifest_path.name)
        probe = run.root / "tmp" / ".write-probe"
        probe.write_bytes(b"stage2-group1\n")
        probe.unlink()
        planned = [
            f"{instrument}:{variant}:{day}"
            for instrument in INSTRUMENTS
            for variant in VARIANTS
            for day in dates()
        ]
        checkpoint = {
            "run_id": run_id,
            "execution_manifest_hash": run.manifest.manifest_hash,
            "code_commit": current_commit,
            "planned": planned,
            "completed": [],
            "failed": [],
            "status": "PREFLIGHT_PASSED",
            "controlled_interruptions": [],
            "recovery": None
            if run.manifest.recovery is None
            else run.manifest.recovery.model_dump(mode="json"),
            "stage1_partition_index_hash": None
            if run.stage1_index is None
            else run.stage1_index.logical_hash,
            "reused_price_staging": False,
        }
        atomic_json(run.root / "checkpoint.json", checkpoint)
        return run

    def execute(self, instrument: Instrument, variant: Variant, *, resume: bool) -> None:
        checkpoint = self._checkpoint()
        if checkpoint["execution_manifest_hash"] != self.manifest.manifest_hash:
            raise ValueError("resume Manifest mismatch")
        if variant == "V1_FLOW" and not self._variant_complete(instrument, "V1_PRICE", checkpoint):
            raise ValueError("V1_FLOW requires completed V1_PRICE windows")
        interruption_limit = int(os.environ.get("ERA_STAGE2_INTERRUPT_AFTER_PARTITIONS", "0"))
        completed_this_call = 0
        checkpoint["status"] = "IN_PROGRESS"
        atomic_json(self.root / "checkpoint.json", checkpoint)
        pending = [
            day for day in dates() if f"{instrument}:{variant}:{day}" not in checkpoint["completed"]
        ]
        if interruption_limit:
            for day in pending:
                key = _execute_partition(
                    self.root,
                    instrument,
                    variant,
                    day,
                    self.manifest.stage1_data_run_id,
                    self.manifest.config_hash,
                    checkpoint["code_commit"],
                    self._trade_partitions(instrument, variant, day),
                )
                checkpoint["completed"].append(key)
                completed_this_call += 1
                atomic_json(self.root / "checkpoint.json", checkpoint)
                if completed_this_call >= interruption_limit:
                    checkpoint["controlled_interruptions"].append(key)
                    checkpoint["status"] = "INTERRUPTED_RECOVERABLE"
                    atomic_json(self.root / "checkpoint.json", checkpoint)
                    raise InterruptedError("controlled interruption")
            return
        workers = int(os.environ.get("ERA_STAGE2_WORKERS", "6" if variant == "V1_PRICE" else "3"))
        if workers == 1:
            for day in pending:
                key = f"{instrument}:{variant}:{day}"
                try:
                    completed_key = _execute_partition(
                        self.root,
                        instrument,
                        variant,
                        day,
                        self.manifest.stage1_data_run_id,
                        self.manifest.config_hash,
                        checkpoint["code_commit"],
                        self._trade_partitions(instrument, variant, day),
                    )
                    if completed_key not in checkpoint["completed"]:
                        checkpoint["completed"].append(completed_key)
                    atomic_json(self.root / "checkpoint.json", checkpoint)
                except Exception as exc:
                    checkpoint["failed"].append({"key": key, "error": repr(exc)})
                    checkpoint["status"] = "FAILED"
                    atomic_json(self.root / "checkpoint.json", checkpoint)
                    raise
            if self._all_complete(checkpoint):
                self._publish(checkpoint)
            else:
                checkpoint["status"] = "PARTIAL_COMPLETE"
                atomic_json(self.root / "checkpoint.json", checkpoint)
            return
        futures = {}
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for day in pending:
                future = pool.submit(
                    _execute_partition,
                    self.root,
                    instrument,
                    variant,
                    day,
                    self.manifest.stage1_data_run_id,
                    self.manifest.config_hash,
                    checkpoint["code_commit"],
                    self._trade_partitions(instrument, variant, day),
                )
                futures[future] = day
            for future in as_completed(futures):
                day = futures[future]
                key = f"{instrument}:{variant}:{day}"
                try:
                    completed_key = future.result()
                    if completed_key not in checkpoint["completed"]:
                        checkpoint["completed"].append(completed_key)
                    atomic_json(self.root / "checkpoint.json", checkpoint)
                except Exception as exc:
                    checkpoint["failed"].append({"key": key, "error": repr(exc)})
                    checkpoint["status"] = "FAILED"
                    atomic_json(self.root / "checkpoint.json", checkpoint)
                    for remaining in futures:
                        remaining.cancel()
                    raise
        if self._all_complete(checkpoint):
            self._publish(checkpoint)
        else:
            checkpoint["status"] = "PARTIAL_COMPLETE"
            atomic_json(self.root / "checkpoint.json", checkpoint)

    def verify(self) -> dict[str, Any]:
        published = self.root / "published" / "data"
        if not published.exists():
            raise ValueError("run is not published")
        catalog = catalog_tree(published)
        existing = json.loads((self.root / "manifests" / "catalog.json").read_text())
        if catalog != existing:
            raise ValueError("published Catalog/logical hash mismatch")
        return catalog

    def _checkpoint(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads((self.root / "checkpoint.json").read_text()))

    def _trade_partitions(
        self, instrument: Instrument, variant: Variant, day: date
    ) -> tuple[Stage1TradesPartition, ...]:
        if variant == "V1_PRICE" or self.stage1_index is None:
            return ()
        return self.stage1_index.partitions_around(instrument, day)

    def _variant_complete(
        self, instrument: Instrument, variant: Variant, checkpoint: dict[str, Any]
    ) -> bool:
        return all(f"{instrument}:{variant}:{day}" in checkpoint["completed"] for day in dates())

    def _all_complete(self, checkpoint: dict[str, Any]) -> bool:
        return (
            set(checkpoint["completed"]) == set(checkpoint["planned"]) and not checkpoint["failed"]
        )

    def _publish(self, checkpoint: dict[str, Any]) -> None:
        staging_data = self.root / "staging" / "data"
        published_data = self.root / "published" / "data"
        if published_data.exists():
            raise FileExistsError("published output is append-only")
        catalog = catalog_tree(staging_data)
        atomic_json(self.root / "manifests" / "catalog.json", catalog)
        os.replace(staging_data, published_data)
        checkpoint["status"] = "PUBLISHED"
        checkpoint["published_logical_hash"] = catalog["logical_hash"]
        atomic_json(self.root / "checkpoint.json", checkpoint)
