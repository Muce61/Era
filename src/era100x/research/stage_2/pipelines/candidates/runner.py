from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import polars as pl

from era100x.research.stage_2.manifests.models import Stage2ExecutionManifest
from era100x.research.stage_2.pipelines.candidates.flow_phase import build_flow_day
from era100x.research.stage_2.pipelines.candidates.io import (
    atomic_json,
    catalog_tree,
    write_partition,
)
from era100x.research.stage_2.pipelines.candidates.price_phase import build_price_day

Instrument = Literal["BTCUSDT", "ETHUSDT"]
Variant = Literal["V1_PRICE", "V1_FLOW"]
INSTRUMENTS: tuple[Instrument, ...] = ("BTCUSDT", "ETHUSDT")
VARIANTS: tuple[Variant, ...] = ("V1_PRICE", "V1_FLOW")
START = date(2020, 1, 1)
END = date(2026, 7, 4)
EXPECTED_EXECUTION_MANIFEST = "84f6fcdd2d4710fd98112dc7a39d798d0f488accb6e7b2a7962f98ba589e3b74"
STAGE2_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")
CONTRACT_ROOT = Path("/Users/muce/1m_data/klines_data_usdm_1s_agg")
TRADES_ROOT = Path(
    "/Volumes/FuckingLife/era100x_stage1/published/stage1-trades-v2/"
    "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
)
LOGICAL_HASHES = {
    "BTCUSDT": "03d437ed9a6c19d92162e5c9dd115df4988e8accce3c8180b749f15cfdcc36a8",
    "ETHUSDT": "6db4d5e411edae3838b352944b83c38ba68915841a1f9c9de8f16ef44c3b8332",
}


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
        if self.manifest.manifest_hash != EXPECTED_EXECUTION_MANIFEST:
            raise ValueError("unlocked or invalid execution Manifest")
        self.manifest_path = manifest_path

    @classmethod
    def preflight(cls, run_id: str, manifest_path: Path) -> CandidateRun:
        run = cls(run_id, manifest_path)
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
            "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "planned": planned,
            "completed": [],
            "failed": [],
            "status": "PREFLIGHT_PASSED",
            "controlled_interruptions": [],
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
        for day in dates():
            key = f"{instrument}:{variant}:{day}"
            if key in checkpoint["completed"]:
                continue
            try:
                if variant == "V1_PRICE":
                    outputs = build_price_day(
                        contract_root=CONTRACT_ROOT,
                        instrument=instrument,
                        day=day,
                        data_run_id=self.manifest.stage1_data_run_id,
                        dataset_logical_hash=LOGICAL_HASHES[instrument],
                        config_hash=self.manifest.config_hash,
                        code_version=checkpoint["code_commit"],
                    )
                else:
                    windows = self._flow_windows(instrument, day)
                    outputs = build_flow_day(
                        stage1_trades_root=TRADES_ROOT,
                        instrument=instrument,
                        day=day,
                        windows=windows,
                    )
                for dataset, records in outputs.items():
                    path = (
                        self.root
                        / "staging"
                        / "data"
                        / f"instrument={instrument}"
                        / f"variant={variant}"
                        / dataset
                        / f"date={day}"
                        / "part-000.parquet"
                    )
                    write_partition(path, records, dataset)
                checkpoint["completed"].append(key)
                completed_this_call += 1
                atomic_json(self.root / "checkpoint.json", checkpoint)
            except Exception as exc:
                checkpoint["failed"].append({"key": key, "error": repr(exc)})
                checkpoint["status"] = "FAILED"
                atomic_json(self.root / "checkpoint.json", checkpoint)
                raise
            if interruption_limit and completed_this_call >= interruption_limit:
                checkpoint["controlled_interruptions"].append(key)
                checkpoint["status"] = "INTERRUPTED_RECOVERABLE"
                atomic_json(self.root / "checkpoint.json", checkpoint)
                raise InterruptedError("controlled interruption")
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

    def _flow_windows(self, instrument: Instrument, day: date) -> list[dict[str, Any]]:
        path = (
            self.root
            / "staging"
            / "data"
            / f"instrument={instrument}"
            / "variant=V1_PRICE"
            / "flow_windows"
            / f"date={day}"
            / "part-000.parquet"
        )
        frame = pl.read_parquet(path)
        if "empty_partition" in frame.columns:
            return []
        return frame.to_dicts()

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
