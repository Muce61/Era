from __future__ import annotations

import json
import os
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import polars as pl

from era100x.research.stage_2.manifests.models import (
    Stage2ExecutionManifest,
    Stage2PreregistrationManifest,
)
from era100x.research.stage_2.pipelines.candidates.flow_phase import build_flow_day
from era100x.research.stage_2.pipelines.candidates.candidate_finalizer import (
    CandidateIdentityConflict,
    audit_logical_hash,
    finalize_candidate_attempts,
    owner_partition,
)
from era100x.research.stage_2.pipelines.candidates.io import (
    atomic_json,
    catalog_tree,
    write_partition,
    write_or_verify_partition,
)
from era100x.research.stage_2.pipelines.candidates.price_phase import build_price_day
from era100x.research.stage_2.pipelines.candidates.release import analyze_release
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
INVALIDATED_RUN_ID = "stage2-g1-full-a-20260716-93a6016"
RUN_A_REQUIRED_FREE_BYTES = 2_018_047_426_560
RUN_B_REQUIRED_FREE_BYTES = 1_345_364_951_040
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
        _verify_completed_partition(run_root, marker)
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
        outputs = build_flow_day(
            trade_paths=trade_paths,
            instrument=instrument,
            windows=windows,
            processing_partition=day.isoformat(),
        )
    written = []
    for dataset, records in outputs.items():
        base = run_root / "staging" / ("work" if dataset == "candidate_attempts" else "data")
        path = (
            base
            / f"instrument={instrument}"
            / f"variant={variant}"
            / dataset
            / f"date={day}"
            / "part-000.parquet"
        )
        metadata = write_partition(path, records, dataset)
        written.append({"relative_path": str(path.relative_to(run_root)), **metadata})
    atomic_json(marker, {"key": key, "status": "COMPLETE", "outputs": written})
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
            or recovery.identity_change_request != "CR-2026-004"
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
        if self.manifest.quality_gate_evidence_hash is None or not self.manifest.tool_versions:
            raise ValueError("production execution Manifest lacks quality/tool evidence")
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
            run._assert_production_preflight(current_commit)
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
        planned.extend(
            f"{instrument}:{variant}:FINALIZE" for instrument in INSTRUMENTS for variant in VARIANTS
        )
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

    def _assert_production_preflight(self, current_commit: str) -> None:
        branch = subprocess.check_output(["git", "branch", "--show-current"], text=True).strip()
        if branch != "stage/2-event-construction":
            raise ValueError("S2-T10 requires stage/2-event-construction")
        if subprocess.check_output(["git", "status", "--porcelain"], text=True).strip():
            raise ValueError("S2-T10 preflight requires a clean worktree")
        stage1_commit = subprocess.check_output(
            ["git", "rev-list", "-n", "1", "stage-1-v1.0-passed"], text=True
        ).strip()
        if stage1_commit != "b7d4ff3d18dcfc515feb8892659cb0b186cd68f8":
            raise ValueError("Stage 1 tag/baseline commit changed")
        root = Path(__file__).resolve().parents[6]
        oq_text = (root / "docs/development/OPEN_QUESTIONS.md").read_text()
        for oq in ("OQ-S2-001", "OQ-S2-002", "OQ-S2-004"):
            line = next((item for item in oq_text.splitlines() if f"| {oq} |" in item), "")
            if "| RESOLVED |" not in line:
                raise ValueError(f"unresolved prerequisite: {oq}")
        cr_text = (root / "docs/development/changes/CR-2026-004.md").read_text()
        if not all(
            marker in cr_text
            for marker in (
                "- status: RESOLVED",
                "- implementation_status: IMPLEMENTED",
                "- validation_status: PASS",
            )
        ):
            raise ValueError("CR-2026-004 is not resolved/implemented/validated")
        self._assert_quality_evidence(current_commit)
        invalidated_root = STAGE2_ROOT / "runs" / INVALIDATED_RUN_ID
        invalidation = json.loads((invalidated_root / "reports" / "invalidation.json").read_text())
        if (
            invalidation.get("status") != "INVALIDATED"
            or (invalidated_root / "published" / "data").exists()
        ):
            raise ValueError("invalidated predecessor run state changed")
        self._assert_no_conflicting_run()
        self._assert_no_conflicting_process()
        required = (
            RUN_B_REQUIRED_FREE_BYTES if "full-b-" in self.run_id else RUN_A_REQUIRED_FREE_BYTES
        )
        free = shutil.disk_usage(STAGE2_ROOT).free
        if free < required:
            raise OSError(f"Stage 2 space gate failed: {free} < {required}")

    def _assert_quality_evidence(self, current_commit: str) -> None:
        evidence_hash = self.manifest.quality_gate_evidence_hash
        if evidence_hash is None:
            raise ValueError("quality evidence hash missing")
        path = (
            STAGE2_ROOT
            / "runs"
            / "stage2-g1-preregistration-v1.0"
            / "reports"
            / f"quality-gate-{evidence_hash}.json"
        )
        if not path.exists() or _sha256_file(path) != evidence_hash:
            raise ValueError("quality gate evidence missing or changed")
        evidence = json.loads(path.read_text())
        if evidence.get("status") != "PASS" or evidence.get("code_commit") != current_commit:
            raise ValueError("quality gate evidence does not bind current HEAD")
        if evidence.get("tool_versions") != self.manifest.tool_versions:
            raise ValueError("quality gate tool versions changed")

    def _assert_no_conflicting_run(self) -> None:
        runs = STAGE2_ROOT / "runs"
        for path in sorted(runs.glob("stage2-g1-full-*")):
            if path.name in {FAILED_RUN_ID, INVALIDATED_RUN_ID}:
                continue
            if path == self.root:
                continue
            checkpoint_path = path / "checkpoint.json"
            if not checkpoint_path.exists():
                continue
            status = json.loads(checkpoint_path.read_text()).get("status")
            invalidated = path / "reports" / "invalidation.json"
            effective_terminal = status in {"FAILED", "FAILED_UNPUBLISHED", "PUBLISHED"} or (
                invalidated.exists()
                and json.loads(invalidated.read_text()).get("status") == "INVALIDATED"
            )
            if not effective_terminal:
                raise ValueError(f"conflicting non-terminal Stage 2 run: {path.name}")

    def _assert_no_conflicting_process(self) -> None:
        ancestors = {os.getpid()}
        parent = os.getppid()
        while parent > 1:
            ancestors.add(parent)
            try:
                parent = int(
                    subprocess.check_output(
                        ["ps", "-o", "ppid=", "-p", str(parent)], text=True
                    ).strip()
                    or "1"
                )
            except subprocess.CalledProcessError:
                break
        output = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True)
        conflicts = []
        for line in output.splitlines():
            fields = line.strip().split(maxsplit=1)
            if len(fields) != 2:
                continue
            pid, command = int(fields[0]), fields[1]
            if (
                pid not in ancestors
                and "scripts/run_stage2_group1_candidates.py" in command
                and command.find("preflight") == -1
            ):
                conflicts.append({"pid": pid, "command": command})
        if conflicts:
            raise ValueError(f"conflicting Stage 2 processes: {conflicts}")

    def execute(self, instrument: Instrument, variant: Variant, *, resume: bool) -> None:
        checkpoint = self._checkpoint()
        if checkpoint["execution_manifest_hash"] != self.manifest.manifest_hash:
            raise ValueError("resume Manifest mismatch")
        if checkpoint["status"] in {"FAILED", "FAILED_UNPUBLISHED", "PUBLISHED"}:
            raise ValueError(f"terminal run cannot execute: {checkpoint['status']}")
        if variant == "V1_FLOW" and not self._variant_complete(instrument, "V1_PRICE", checkpoint):
            raise ValueError("V1_FLOW requires completed V1_PRICE windows")
        if resume:
            self._verify_completed_variant(instrument, variant, checkpoint)
        interruption_limit = int(os.environ.get("ERA_STAGE2_INTERRUPT_AFTER_PARTITIONS", "0"))
        completed_this_call = 0
        checkpoint["status"] = "IN_PROGRESS"
        atomic_json(self.root / "checkpoint.json", checkpoint)
        pending = [
            day for day in dates() if f"{instrument}:{variant}:{day}" not in checkpoint["completed"]
        ]
        if interruption_limit:
            for day in pending:
                try:
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
                except Exception as exc:
                    self._record_terminal_failure(checkpoint, f"{instrument}:{variant}:{day}", exc)
                    raise
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
                    self._record_terminal_failure(checkpoint, key, exc)
                    raise
            try:
                self._finish_execute(instrument, variant, checkpoint)
            except Exception as exc:
                self._record_terminal_failure(checkpoint, f"{instrument}:{variant}:FINALIZE", exc)
                raise
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
                    self._record_terminal_failure(checkpoint, key, exc)
                    for remaining in futures:
                        remaining.cancel()
                    raise
        try:
            self._finish_execute(instrument, variant, checkpoint)
        except Exception as exc:
            self._record_terminal_failure(checkpoint, f"{instrument}:{variant}:FINALIZE", exc)
            raise

    def _record_terminal_failure(
        self, checkpoint: dict[str, Any], failed_phase: str, exc: Exception
    ) -> None:
        failure = {"key": failed_phase, "error": repr(exc)}
        if failure not in checkpoint["failed"]:
            checkpoint["failed"].append(failure)
        checkpoint["status"] = "FAILED_UNPUBLISHED"
        atomic_json(self.root / "checkpoint.json", checkpoint)
        _write_once_json(
            self.root / "reports" / "failure.json",
            {
                "record_type": "STAGE2_GROUP1_RUN_FAILURE",
                "recorded_at": datetime.now(UTC).isoformat(),
                "run_id": self.run_id,
                "task_id": "S2-T10",
                "status": "FAILED_UNPUBLISHED",
                "failed_phase": failed_phase,
                "completed_items": len(checkpoint["completed"]),
                "planned_items": len(checkpoint["planned"]),
                "error": repr(exc),
                "publication": "NONE",
                "cleanup_authorized": False,
                "staging_retention": "REQUIRED_PENDING_AUDIT",
            },
        )

    def _verify_completed_variant(
        self, instrument: Instrument, variant: Variant, checkpoint: dict[str, Any]
    ) -> None:
        for day in dates():
            key = f"{instrument}:{variant}:{day}"
            if key not in checkpoint["completed"]:
                continue
            marker = self.root / "staging" / "status" / instrument / variant / f"{day}.json"
            if not marker.exists():
                raise ValueError(f"resume partition marker missing: {key}")
            _verify_completed_partition(self.root, marker)

    def verify(self) -> dict[str, Any]:
        published = self.root / "published" / "data"
        if not published.exists():
            raise ValueError("run is not published")
        catalog = catalog_tree(published)
        existing = json.loads((self.root / "manifests" / "catalog.json").read_text())
        if catalog != existing:
            raise ValueError("published Catalog/logical hash mismatch")
        analysis = analyze_release(
            published,
            expected_partition_count=len(dates()),
            checkpoint=self._checkpoint(),
            manifest_hash=self.manifest.manifest_hash,
        )
        stored_analysis = json.loads((self.root / "reports" / "release-analysis.json").read_text())
        if analysis != stored_analysis:
            raise ValueError("published semantic release analysis mismatch")
        if analysis["quality"]["status"] != "PASS":
            raise ValueError("published Quality Report is not PASS")
        return {**catalog, "release_analysis": analysis}

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
        daily = all(f"{instrument}:{variant}:{day}" in checkpoint["completed"] for day in dates())
        return daily and f"{instrument}:{variant}:FINALIZE" in checkpoint["completed"]

    def _finish_execute(
        self, instrument: Instrument, variant: Variant, checkpoint: dict[str, Any]
    ) -> None:
        if all(f"{instrument}:{variant}:{day}" in checkpoint["completed"] for day in dates()):
            final_key = f"{instrument}:{variant}:FINALIZE"
            if final_key not in checkpoint["completed"]:
                self._finalize_candidates(instrument, variant)
                checkpoint["completed"].append(final_key)
                atomic_json(self.root / "checkpoint.json", checkpoint)
        if self._all_complete(checkpoint):
            self._publish(checkpoint)
        else:
            checkpoint["status"] = "PARTIAL_COMPLETE"
            atomic_json(self.root / "checkpoint.json", checkpoint)

    def _finalize_candidates(self, instrument: Instrument, variant: Variant) -> None:
        summaries: list[dict[str, Any]] = []
        valid_days = dates()
        valid_set = set(valid_days)
        for owner_day in valid_days:
            attempts: list[dict[str, Any]] = []
            for source_day in (owner_day - timedelta(days=1), owner_day):
                source = (
                    self.root
                    / "staging"
                    / "work"
                    / f"instrument={instrument}"
                    / f"variant={variant}"
                    / "candidate_attempts"
                    / f"date={source_day}"
                    / "part-000.parquet"
                )
                if not source.exists():
                    continue
                frame = pl.read_parquet(source)
                if "empty_partition" in frame.columns:
                    continue
                attempts.extend(
                    row
                    for row in frame.to_dicts()
                    if owner_partition(int(row["available_at_ts"])) == owner_day.isoformat()
                )
            try:
                finalized = finalize_candidate_attempts(
                    attempts, include_flow_windows=variant == "V1_PRICE"
                )
            except CandidateIdentityConflict as exc:
                _write_once_json(
                    self.root
                    / "reports"
                    / "candidate_identity_conflicts"
                    / f"instrument={instrument}"
                    / f"variant={variant}"
                    / f"date={owner_day}.json",
                    {
                        "instrument": instrument,
                        "variant": variant,
                        "date": str(owner_day),
                        "conflicts": exc.conflicts,
                    },
                )
                raise
            output_records = {
                "market_episodes": finalized.market_episodes_by_date.get(str(owner_day), []),
                "candidate_inclusion": finalized.inclusion_by_date.get(str(owner_day), []),
            }
            if variant == "V1_PRICE":
                output_records["flow_windows"] = finalized.flow_windows_by_date.get(
                    str(owner_day), []
                )
            for dataset, records in output_records.items():
                path = (
                    self.root
                    / "staging"
                    / "data"
                    / f"instrument={instrument}"
                    / f"variant={variant}"
                    / dataset
                    / f"date={owner_day}"
                    / "part-000.parquet"
                )
                write_or_verify_partition(path, records, dataset)
            audit_path = (
                self.root
                / "reports"
                / "candidate_dedup_audit"
                / f"instrument={instrument}"
                / f"variant={variant}"
                / f"date={owner_day}"
                / "part-000.parquet"
            )
            write_or_verify_partition(audit_path, finalized.audit_records, "candidate_dedup_audit")
            summaries.append({"date": str(owner_day), **finalized.summary})
        terminal_attempts = self._attempts_for_source_day(instrument, variant, valid_days[-1])
        out_of_range = [
            row
            for row in terminal_attempts
            if date.fromisoformat(owner_partition(int(row["available_at_ts"]))) not in valid_set
        ]
        if out_of_range:
            atomic_json(
                self.root / "reports" / f"{instrument}-{variant}-out-of-period-candidates.json",
                {
                    "instrument": instrument,
                    "variant": variant,
                    "count": len(out_of_range),
                    "reason_code": "OUT_OF_PREREGISTERED_PERIOD",
                    "canonical_candidate_ids": sorted(
                        str(row["canonical_candidate_id"]) for row in out_of_range
                    ),
                },
            )
        aggregate = {
            "instrument": instrument,
            "variant": variant,
            "dates": len(valid_days),
            "attempt_count": sum(int(row["attempt_count"]) for row in summaries),
            "canonical_count": sum(int(row["canonical_count"]) for row in summaries),
            "exact_duplicate_excluded_count": sum(
                int(row["exact_duplicate_excluded_count"]) for row in summaries
            ),
            "identity_conflict_count": 0,
            "out_of_partition_context_count": sum(
                int(row["out_of_partition_context_count"]) for row in summaries
            ),
            "out_of_period_count": len(out_of_range),
            "daily_summary_logical_hash": audit_logical_hash(summaries),
        }
        summary_path = self.root / "reports" / f"{instrument}-{variant}-candidate-finalization.json"
        if summary_path.exists():
            if json.loads(summary_path.read_text()) != aggregate:
                raise ValueError("resume candidate finalization summary mismatch")
        else:
            atomic_json(summary_path, aggregate)

    def _attempts_for_source_day(
        self, instrument: Instrument, variant: Variant, source_day: date
    ) -> list[dict[str, Any]]:
        path = (
            self.root
            / "staging"
            / "work"
            / f"instrument={instrument}"
            / f"variant={variant}"
            / "candidate_attempts"
            / f"date={source_day}"
            / "part-000.parquet"
        )
        if not path.exists():
            return []
        frame = pl.read_parquet(path)
        return [] if "empty_partition" in frame.columns else frame.to_dicts()

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
        analysis = analyze_release(
            staging_data,
            expected_partition_count=len(dates()),
            checkpoint=checkpoint,
            manifest_hash=self.manifest.manifest_hash,
        )
        if analysis["quality"]["status"] != "PASS":
            _write_once_json(self.root / "reports" / "quality-report-failed.json", analysis)
            raise ValueError("Stage 2 Group 1 Quality Report failed")
        _write_once_json(self.root / "reports" / "release-analysis.json", analysis)
        _write_once_json(
            self.root / "reports" / "quality-report.json",
            {
                "schema_name": "stage2-group1-quality-report-v1",
                "status": "PASS",
                "manifest_hash": self.manifest.manifest_hash,
                "catalog_logical_hash": analysis["catalog_logical_hash"],
                "quality": analysis["quality"],
            },
        )
        _write_once_json(
            self.root / "reports" / "count-summary.json",
            {
                "schema_name": "stage2-group1-count-summary-v1",
                "manifest_hash": self.manifest.manifest_hash,
                "catalog_logical_hash": analysis["catalog_logical_hash"],
                "datasets": {
                    key: {
                        field: value
                        for field, value in stats.items()
                        if not field.startswith("partition_")
                    }
                    for key, stats in analysis["datasets"].items()
                },
                "distributions": analysis["distributions"],
                "finalization": analysis["finalization"],
            },
        )
        if (self.root / "manifests" / "catalog.json").exists():
            raise FileExistsError("published Catalog is append-only")
        atomic_json(self.root / "manifests" / "catalog.json", catalog)
        os.replace(staging_data, published_data)
        checkpoint["status"] = "PUBLISHED"
        checkpoint["published_logical_hash"] = catalog["logical_hash"]
        checkpoint["published_physical_hash"] = catalog["physical_hash"]
        atomic_json(self.root / "checkpoint.json", checkpoint)


def _write_once_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"append-only report exists: {path}")
    atomic_json(path, payload)


def _verify_completed_partition(run_root: Path, marker: Path) -> None:
    payload = json.loads(marker.read_text())
    if payload.get("status") != "COMPLETE" or not payload.get("outputs"):
        raise ValueError(f"incomplete or legacy partition marker: {marker}")
    for output in payload["outputs"]:
        path = run_root / output["relative_path"]
        if not path.exists() or _sha256_file(path) != output["byte_sha256"]:
            raise ValueError(f"resume partition checksum mismatch: {path}")


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
