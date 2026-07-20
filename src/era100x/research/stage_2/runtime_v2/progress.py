"""Read-only Runtime V2 progress evidence and deterministic status projection."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from .checkpoint import CheckpointStore, RuntimeV2Checkpoint, SAFE_RUN_ID
from .models import FrozenModel, SHA256_PATTERN, ZERO_SHA256

ProgressHealth = Literal[
    "HEALTHY",
    "RUNNING_WITH_ANOMALIES",
    "STALLED",
    "PAUSED",
    "INTERRUPTED_RECOVERABLE",
    "FAILED_INTEGRITY",
    "COMPLETE",
]

FOUNDATION_LOGICAL_PARTITIONS = 19_008
GROUP1_LOGICAL_PARTITIONS = 61_776
OVERALL_LOGICAL_PARTITIONS = 80_784

PIPELINE_SUBFLOW_ORDER = (
    "FAILED_RUN_PROTECTION",
    "DUPLICATE_ARTIFACT_AUDIT",
    "MONTHLY_RESULT_ADOPTION",
    "FINAL_PACKING",
    "RELEASE",
    "VERIFY",
    "RUN_A_RUN_B_COMPARE",
)


class WorkerProgressV2(FrozenModel):
    worker_id: str
    pid: int | None = Field(default=None, ge=1)
    status: Literal["PENDING", "RUNNING", "SEALED", "STOPPED", "FAILED"]
    instrument: Literal["BTCUSDT", "ETHUSDT"] | None = None
    variant: Literal["V1_PRICE", "V1_FLOW"] | None = None
    current_month: str | None = Field(default=None, pattern=r"^[0-9]{4}-[0-9]{2}$")
    current_owner_date: str | None = None
    current_processing_minute: int | None = Field(default=None, ge=0, le=1440)
    foundation_fragment_reads: int = Field(default=0, ge=0)
    foundation_cache_hits: int = Field(default=0, ge=0)
    processing_day_executions: int = Field(default=0, ge=0)
    legacy_runs_generated: int = Field(default=0, ge=0)
    bytes_written: int = Field(default=0, ge=0)
    message: str | None = None
    updated_at: str


class ProgressEventV2(FrozenModel):
    event_id: str = Field(pattern=SHA256_PATTERN)
    timestamp: str
    level: Literal["INFO", "ANOMALY", "ERROR"]
    phase: str
    message: str


class PipelineSubflowV1(FrozenModel):
    """One observable recovery subflow; it never changes research semantics."""

    name: str
    status: Literal["PENDING", "RUNNING", "PASS", "FAILED", "BLOCKED", "SKIPPED"]
    done: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    current_item: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    elapsed_seconds: float = Field(default=0.0, ge=0.0)
    message: str | None = None


class PipelineProgressV1(FrozenModel):
    schema_name: Literal["stage2-v2-recovery-pipeline-progress"] = (
        "stage2-v2-recovery-pipeline-progress"
    )
    progress_version: Literal["1.0"] = "1.0"
    run_id: str
    subflows: tuple[PipelineSubflowV1, ...]
    recent_logs: tuple[ProgressEventV2, ...] = Field(default=(), max_length=50)
    updated_at: str
    progress_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        return hashlib.sha256(
            _progress_json(self.model_dump(mode="json", exclude={"progress_hash"})).encode()
        ).hexdigest()

    @model_validator(mode="after")
    def valid_pipeline(self) -> Self:
        if SAFE_RUN_ID.fullmatch(self.run_id) is None:
            raise ValueError("pipeline progress run_id is invalid")
        names = tuple(item.name for item in self.subflows)
        expected = tuple(name for name in PIPELINE_SUBFLOW_ORDER if name in names)
        if names != expected or len(names) != len(set(names)):
            raise ValueError("pipeline subflows must be unique and canonically ordered")
        if self.progress_hash != ZERO_SHA256 and self.progress_hash != self.computed_hash():
            raise ValueError("pipeline progress hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "progress_hash": ZERO_SHA256})
        return provisional.model_copy(update={"progress_hash": provisional.computed_hash()})


class ProgressV2(FrozenModel):
    schema_name: Literal["stage2-v2-runtime-progress"] = "stage2-v2-runtime-progress"
    progress_version: Literal["2.0"] = "2.0"
    run_id: str
    status: str
    health: ProgressHealth
    phase: str
    active_task: str | None = None
    instrument: Literal["BTCUSDT", "ETHUSDT"] | None = None
    variant: Literal["V1_PRICE", "V1_FLOW"] | None = None
    current_month: str | None = None
    current_owner_date: str | None = None
    current_processing_minute: int = Field(default=0, ge=0, le=1440)
    processing_minutes_done: int = Field(default=0, ge=0, le=1440)
    processing_minutes_total: Literal[1440] = 1440
    owner_days_done: int = Field(default=0, ge=0)
    owner_days_total: int = Field(default=4752, ge=0)
    instrument_months_done: int = Field(default=0, ge=0)
    instrument_months_total: int = Field(default=156, ge=0)
    foundation_logical_partitions_done: int = Field(default=0, ge=0)
    foundation_logical_partitions_total: Literal[19008] = 19_008
    group1_logical_partitions_sealed: int = Field(default=0, ge=0)
    group1_logical_partitions_total: Literal[61776] = 61_776
    overall_logical_partitions_done: int = Field(default=0, ge=0)
    overall_logical_partitions_total: Literal[80784] = 80_784
    btc_group1_partitions_done: int = Field(default=0, ge=0)
    eth_group1_partitions_done: int = Field(default=0, ge=0)
    price_partitions_done: int = Field(default=0, ge=0)
    flow_partitions_done: int = Field(default=0, ge=0)
    current_month_percentage: float = Field(default=0.0, ge=0.0, le=100.0)
    current_instrument_percentage: float = Field(default=0.0, ge=0.0, le=100.0)
    group1_percentage: float = Field(default=0.0, ge=0.0, le=100.0)
    overall_percentage: float = Field(default=0.0, ge=0.0, le=100.0)
    rows_generated_by_dataset: dict[str, int] = Field(default_factory=dict)
    bytes_written: int = Field(default=0, ge=0)
    legacy_runs_generated: int = Field(default=0, ge=0)
    cache_hits: int = Field(default=0, ge=0)
    cache_misses: int = Field(default=0, ge=0)
    worker_count: int = Field(default=3, ge=0)
    worker_states: tuple[WorkerProgressV2, ...] = ()
    cpu_percent: float = Field(default=0.0, ge=0.0)
    current_rss_bytes: int = Field(default=0, ge=0)
    arrow_inflight_bytes: int = Field(default=0, ge=0)
    external_disk_free_bytes: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0.0, ge=0.0)
    rolling_throughput: float = Field(default=0.0, ge=0.0)
    recent_30m_delta: int = Field(default=0, ge=0)
    eta_seconds: float | None = Field(default=None, ge=0.0)
    anomaly_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    recent_events: tuple[ProgressEventV2, ...] = Field(default=(), max_length=20)
    started_at: str
    updated_at: str
    progress_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude={"progress_hash"})
        return hashlib.sha256(_progress_json(payload).encode()).hexdigest()

    @model_validator(mode="after")
    def valid_progress(self) -> Self:
        if SAFE_RUN_ID.fullmatch(self.run_id) is None:
            raise ValueError("progress run_id is outside the approved Run-B namespace")
        if self.progress_hash != ZERO_SHA256 and self.progress_hash != self.computed_hash():
            raise ValueError("progress hash mismatch")
        if self.overall_logical_partitions_done != (
            self.foundation_logical_partitions_done + self.group1_logical_partitions_sealed
        ):
            raise ValueError("overall progress does not equal Foundation plus Group-1")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "progress_hash": ZERO_SHA256})
        return provisional.model_copy(update={"progress_hash": provisional.computed_hash()})


class UserStopReportV1(FrozenModel):
    schema_name: Literal["stage2-v2-user-stop-report"] = "stage2-v2-user-stop-report"
    report_version: Literal["1.0"] = "1.0"
    run_id: str
    task_id: str
    instrument: str | None = None
    variant: str | None = None
    current_month: str | None = None
    current_owner_date: str | None = None
    completed_months: tuple[str, ...] = ()
    partial_files: tuple[str, ...] = ()
    checkpoint_before_hash: str = Field(pattern=SHA256_PATTERN)
    checkpoint_after_hash: str = Field(pattern=SHA256_PATTERN)
    code_commit: str = Field(min_length=7)
    authority_bundle_id: str
    stopped_at: str
    status: Literal["INTERRUPTED_RECOVERABLE"] = "INTERRUPTED_RECOVERABLE"


class ProgressStore:
    """Single-parent atomic progress writer; workers write isolated snapshots."""

    def __init__(self, run_root: Path) -> None:
        self.run_root = run_root
        self.path = run_root / "logs" / "progress-v2.json"

    def read(self) -> ProgressV2:
        return ProgressV2.model_validate_json(self.path.read_bytes())

    def replace(self, progress: ProgressV2) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        payload = (_progress_json(progress.model_dump(mode="json")) + "\n").encode()
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            _fsync_directory(self.path.parent)
        finally:
            temporary.unlink(missing_ok=True)


class PipelineProgressStore:
    """Atomic, execution-only progress for adoption through comparison."""

    def __init__(self, run_root: Path) -> None:
        self.run_root = run_root
        self.path = run_root / "logs" / "pipeline-progress-v1.json"

    def read(self) -> PipelineProgressV1:
        return PipelineProgressV1.model_validate_json(self.path.read_bytes())

    def replace(self, progress: PipelineProgressV1) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        payload = (_progress_json(progress.model_dump(mode="json")) + "\n").encode()
        try:
            with temporary.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            _fsync_directory(self.path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def update(
        self,
        *,
        name: str,
        status: Literal["PENDING", "RUNNING", "PASS", "FAILED", "BLOCKED", "SKIPPED"],
        done: int | None = None,
        total: int | None = None,
        current_item: str | None = None,
        message: str | None = None,
        level: Literal["INFO", "ANOMALY", "ERROR"] = "INFO",
    ) -> PipelineProgressV1:
        if name not in PIPELINE_SUBFLOW_ORDER:
            raise ValueError(f"unknown pipeline subflow: {name}")
        now = utc_now_text()
        previous = self.read() if self.path.is_file() else None
        existing = {item.name: item for item in (previous.subflows if previous else ())}
        old = existing.get(name)
        started_at = old.started_at if old is not None else None
        if status == "RUNNING" and started_at is None:
            started_at = now
        ended_at = now if status in {"PASS", "FAILED", "BLOCKED", "SKIPPED"} else None
        elapsed = 0.0
        if started_at is not None:
            elapsed = max(
                0.0,
                (
                    datetime.fromisoformat((ended_at or now).replace("Z", "+00:00"))
                    - datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                ).total_seconds(),
            )
        existing[name] = PipelineSubflowV1(
            name=name,
            status=status,
            done=(old.done if done is None and old is not None else done or 0),
            total=(old.total if total is None and old is not None else total or 0),
            current_item=current_item,
            started_at=started_at,
            ended_at=ended_at,
            elapsed_seconds=elapsed,
            message=message,
        )
        logs = list(previous.recent_logs if previous else ())
        if message:
            logs.append(progress_event(timestamp=now, level=level, phase=name, message=message))
        progress = PipelineProgressV1.seal(
            {
                "run_id": self.run_root.name,
                "subflows": tuple(
                    existing[item] for item in PIPELINE_SUBFLOW_ORDER if item in existing
                ),
                "recent_logs": tuple(logs[-50:]),
                "updated_at": now,
            }
        )
        self.replace(progress)
        return progress


class ProgressHeartbeat:
    """Parent-owned ten-second projection while a backend task is active."""

    def __init__(self, run_root: Path, interval_seconds: float = 10.0) -> None:
        self.run_root = run_root
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="stage2-v2-progress-heartbeat",
            daemon=True,
        )

    def __enter__(self) -> ProgressHeartbeat:
        self._write()
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self._stop.set()
        self._thread.join(timeout=max(2.0, self.interval_seconds + 1.0))
        self._write()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self._write()

    def _write(self) -> None:
        try:
            store = ProgressStore(self.run_root)
            previous = store.read() if store.path.is_file() else None
            store.replace(progress_from_checkpoint(run_root=self.run_root, previous=previous))
        except (OSError, ValueError, subprocess.SubprocessError):
            # Progress is observational and may never turn a valid research
            # calculation into an integrity failure.
            return


def progress_event(
    *,
    timestamp: str,
    level: Literal["INFO", "ANOMALY", "ERROR"],
    phase: str,
    message: str,
) -> ProgressEventV2:
    payload = f"{timestamp}|{level}|{phase}|{message}".encode()
    return ProgressEventV2(
        event_id=hashlib.sha256(payload).hexdigest(),
        timestamp=timestamp,
        level=level,
        phase=phase,
        message=message,
    )


def progress_from_checkpoint(
    *,
    run_root: Path,
    previous: ProgressV2 | None = None,
    now: datetime | None = None,
) -> ProgressV2:
    """Project checkpoint-first health without mutating any run evidence."""

    clock = now or datetime.now(UTC)
    checkpoint = CheckpointStore(run_root).read()
    updated = clock.isoformat().replace("+00:00", "Z")
    started = previous.started_at if previous is not None else updated
    completed = {item.task_id for item in checkpoint.completed_tasks}
    foundation_done = (
        FOUNDATION_LOGICAL_PARTITIONS
        * len(completed & {"FOUNDATION:BTCUSDT", "FOUNDATION:ETHUSDT"})
        // 2
    )
    group_tasks_done = len(
        completed
        & {
            "GROUP1:BTCUSDT:V1_PRICE",
            "GROUP1:BTCUSDT:V1_FLOW",
            "GROUP1:ETHUSDT:V1_PRICE",
            "GROUP1:ETHUSDT:V1_FLOW",
        }
    )
    sealed_months, sealed_owner_days, month_group_done, owner_days_by_instrument = (
        _sealed_month_progress(run_root)
    )
    group_done = max(GROUP1_LOGICAL_PARTITIONS * group_tasks_done // 4, month_group_done)
    worker_states = _read_worker_snapshots(run_root)
    active_worker = max(worker_states, key=lambda item: item.updated_at, default=None)
    health = checkpoint_health(
        checkpoint, progress_updated_at=(previous.updated_at if previous else None), now=clock
    )
    cpu_percent, current_rss_bytes = _process_metrics(
        (os.getpid(), *(item.pid for item in worker_states if item.pid is not None))
    )
    payload = {
        **(previous.model_dump(mode="python", exclude={"progress_hash"}) if previous else {}),
        "run_id": checkpoint.run_id,
        "status": checkpoint.status,
        "health": health,
        "phase": checkpoint.phase,
        "active_task": checkpoint.active_task,
        "instrument": (None if active_worker is None else active_worker.instrument),
        "variant": (None if active_worker is None else active_worker.variant),
        "current_month": (None if active_worker is None else active_worker.current_month),
        "current_owner_date": (None if active_worker is None else active_worker.current_owner_date),
        "current_processing_minute": (
            0 if active_worker is None else active_worker.current_processing_minute or 0
        ),
        "processing_minutes_done": (
            0 if active_worker is None else active_worker.current_processing_minute or 0
        ),
        "owner_days_done": sealed_owner_days,
        "instrument_months_done": sealed_months,
        "foundation_logical_partitions_done": foundation_done,
        "group1_logical_partitions_sealed": group_done,
        "overall_logical_partitions_done": foundation_done + group_done,
        "btc_group1_partitions_done": owner_days_by_instrument["BTCUSDT"] * 13,
        "eth_group1_partitions_done": owner_days_by_instrument["ETHUSDT"] * 13,
        "price_partitions_done": sealed_owner_days * 10,
        "flow_partitions_done": sealed_owner_days * 3,
        "group1_percentage": group_done / GROUP1_LOGICAL_PARTITIONS * 100,
        "overall_percentage": (foundation_done + group_done) / OVERALL_LOGICAL_PARTITIONS * 100,
        "current_month_percentage": (
            0.0
            if active_worker is None
            else (active_worker.current_processing_minute or 0) / 1440 * 100
        ),
        "worker_states": worker_states,
        "cpu_percent": cpu_percent,
        "current_rss_bytes": current_rss_bytes,
        "external_disk_free_bytes": shutil.disk_usage(run_root).free,
        "started_at": started,
        "updated_at": updated,
    }
    return ProgressV2.seal(payload)


def checkpoint_health(
    checkpoint: RuntimeV2Checkpoint,
    *,
    progress_updated_at: str | None,
    now: datetime | None = None,
) -> ProgressHealth:
    if checkpoint.status == "FAILED_INTEGRITY" or checkpoint.status == "FAILED_UNPUBLISHED":
        return "FAILED_INTEGRITY"
    if checkpoint.status == "INTERRUPTED_RECOVERABLE":
        return "INTERRUPTED_RECOVERABLE"
    if checkpoint.status in {"PAUSED_RESOURCE_PRESSURE", "PAUSED_STORAGE_UNAVAILABLE"}:
        return "PAUSED"
    if checkpoint.status == "GROUP1_COMPLETE" and len(checkpoint.completed_tasks) == 6:
        return "COMPLETE"
    if progress_updated_at is not None:
        updated = datetime.fromisoformat(progress_updated_at.replace("Z", "+00:00"))
        if ((now or datetime.now(UTC)) - updated).total_seconds() > 60:
            return "STALLED"
    if checkpoint.status == "RUNNING_WITH_ANOMALIES" or any(
        item.resource_anomaly_count for item in checkpoint.completed_tasks
    ):
        return "RUNNING_WITH_ANOMALIES"
    return "HEALTHY"


def read_progress_status(run_root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Read progress if valid and always overlay checkpoint-terminal truth."""

    progress_path = run_root / "logs" / "progress-v2.json"
    progress: ProgressV2 | None = None
    if progress_path.is_file() and not progress_path.is_symlink():
        try:
            progress = ProgressV2.model_validate_json(progress_path.read_bytes())
        except (OSError, ValueError):
            progress = None
    projected = progress_from_checkpoint(run_root=run_root, previous=progress, now=now)
    result = projected.model_dump(mode="json")
    result["progress_file_present"] = progress is not None
    result["superseded"] = any(
        path.name.startswith("superseded")
        for path in (run_root / "reports").glob("*.json")
        if not path.name.startswith("._")
    )
    pipeline_path = run_root / "logs" / "pipeline-progress-v1.json"
    try:
        pipeline = PipelineProgressV1.model_validate_json(pipeline_path.read_bytes())
        result["pipeline_subflows"] = [item.model_dump(mode="json") for item in pipeline.subflows]
        result["pipeline_recent_logs"] = [
            item.model_dump(mode="json") for item in pipeline.recent_logs
        ]
        result["pipeline_progress_present"] = True
    except (OSError, ValueError):
        result["pipeline_subflows"] = []
        result["pipeline_recent_logs"] = []
        result["pipeline_progress_present"] = False
    return result


def monotonic_seconds() -> float:
    return time.monotonic()


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _process_metrics(pids: tuple[int, ...]) -> tuple[float, int]:
    """Read parent plus worker CPU/RSS without introducing a new dependency."""

    result = subprocess.run(
        ("ps", "-o", "%cpu=,rss=", "-p", ",".join(str(item) for item in sorted(set(pids)))),
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    if result.returncode or any(len(row) != 2 for row in rows):
        return 0.0, 0
    return (
        sum(float(row[0]) for row in rows),
        sum(int(row[1]) * 1024 for row in rows),
    )


def _read_worker_snapshots(run_root: Path) -> tuple[WorkerProgressV2, ...]:
    root = run_root / "logs" / "worker-progress"
    workers: list[WorkerProgressV2] = []
    if root.is_dir():
        for path in sorted(root.glob("*.json")):
            if path.name.startswith("._") or path.is_symlink():
                continue
            try:
                workers.append(WorkerProgressV2.model_validate_json(path.read_bytes()))
            except (OSError, ValueError):
                continue
    selected = sorted(
        workers,
        key=lambda item: (item.status == "RUNNING", item.updated_at),
        reverse=True,
    )[:3]
    return tuple(sorted(selected, key=lambda item: item.worker_id))


def _sealed_month_progress(
    run_root: Path,
) -> tuple[int, int, int, dict[str, int]]:
    root = run_root / "staging" / "group1" / "monthly-checkpoints"
    months = 0
    owner_days = 0
    by_instrument = {"BTCUSDT": 0, "ETHUSDT": 0}
    if not root.is_dir():
        return 0, 0, 0, by_instrument
    for path in sorted(root.glob("instrument=*/*.json")):
        if path.name.startswith("._") or path.is_symlink():
            continue
        try:
            start = date.fromisoformat(f"{path.stem}-01")
            next_month = (
                date(start.year + 1, 1, 1)
                if start.month == 12
                else date(start.year, start.month + 1, 1)
            )
            start = max(start, date(2020, 1, 1))
            end = min(next_month, date(2026, 7, 4))
        except ValueError:
            continue
        if end <= start:
            continue
        months += 1
        days = (end - start).days
        owner_days += days
        instrument = path.parent.name.removeprefix("instrument=")
        if instrument in by_instrument:
            by_instrument[instrument] += days
    return months, owner_days, owner_days * 13, by_instrument


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _progress_json(value: Any) -> str:
    """Canonical execution-metric JSON; floats are audit values, not semantics."""

    return json.JSONEncoder(
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode(value)
