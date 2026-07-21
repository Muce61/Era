from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from era100x.research.stage_2.runtime_v2.checkpoint import (
    FULL_TASK_MATRIX,
    CheckpointStore,
    RuntimeV2Checkpoint,
)
from era100x.research.stage_2.runtime_v2.progress import (
    PipelineProgressStore,
    ProgressStore,
    WorkerProgressV2,
    checkpoint_health,
    read_progress_status,
)

H = "a" * 64
RUN_ID = "stage2-g1-v2-b-progress-test"


def _checkpoint(run_root: Path, status: str = "INTERRUPTED_RECOVERABLE") -> RuntimeV2Checkpoint:
    run_root.mkdir(parents=True)
    checkpoint = RuntimeV2Checkpoint.seal(
        {
            "run_id": RUN_ID,
            "snapshot_id": H,
            "manifest_hash": H,
            "manifest_source_sha256": H,
            "run_a_protection_manifest_hash": H,
            "run_a_protection_source_sha256": H,
            "migration_manifest_hash": H,
            "migration_manifest_source_sha256": H,
            "code_tree_sha256": H,
            "stage1_data_run_id": "stage1-test",
            "preregistration_manifest_sha256": H,
            "config_sha256": H,
            "planned_tasks": FULL_TASK_MATRIX,
            "completed_tasks": (),
            "phase": "FOUNDATION",
            "status": status,
            "active_task": FULL_TASK_MATRIX[0],
            "failure": None,
            "resource_pause": None,
            "revision": 0,
        }
    )
    CheckpointStore(run_root).create(checkpoint)
    return checkpoint


def test_checkpoint_terminal_status_overrides_stale_or_missing_progress(tmp_path: Path) -> None:
    run_root = tmp_path / "runs" / RUN_ID
    checkpoint = _checkpoint(run_root)
    (run_root / "logs").mkdir()
    (run_root / "logs" / "._progress-v2.json").write_text("junk", encoding="utf-8")

    status = read_progress_status(run_root)

    assert status["health"] == "INTERRUPTED_RECOVERABLE"
    assert status["progress_file_present"] is False
    assert checkpoint_health(checkpoint, progress_updated_at=None) == "INTERRUPTED_RECOVERABLE"


def test_worker_snapshot_and_sealed_month_drive_fine_progress(tmp_path: Path) -> None:
    run_root = tmp_path / "runs" / RUN_ID
    _checkpoint(run_root)
    worker = WorkerProgressV2(
        worker_id="BTCUSDT-2020-07",
        pid=123,
        status="RUNNING",
        instrument="BTCUSDT",
        variant="V1_PRICE",
        current_month="2020-07",
        current_owner_date="2020-07-15",
        current_processing_minute=720,
        updated_at="2026-07-19T00:00:00Z",
    )
    worker_path = run_root / "logs" / "worker-progress" / "BTCUSDT-2020-07.json"
    worker_path.parent.mkdir(parents=True)
    worker_path.write_text(json.dumps(worker.model_dump(mode="json")), encoding="utf-8")
    checkpoint_path = (
        run_root
        / "staging"
        / "group1"
        / "monthly-checkpoints"
        / "instrument=BTCUSDT"
        / "2020-06.json"
    )
    checkpoint_path.parent.mkdir(parents=True)
    checkpoint_path.write_text(
        json.dumps({"owner_start": "2020-06-01", "owner_end_exclusive": "2020-07-01"}),
        encoding="utf-8",
    )

    status = read_progress_status(run_root)

    assert status["current_processing_minute"] == 720
    assert status["instrument_months_done"] == 1
    assert status["owner_days_done"] == 30
    assert status["btc_group1_partitions_done"] == 390
    assert status["price_partitions_done"] == 300
    assert status["flow_partitions_done"] == 90


def test_sealed_month_progress_uses_atomic_checkpoint_path_without_loading_payload(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "runs" / RUN_ID
    _checkpoint(run_root)
    checkpoint_path = (
        run_root
        / "staging"
        / "group1"
        / "monthly-checkpoints"
        / "instrument=ETHUSDT"
        / "2026-07.json"
    )
    checkpoint_path.parent.mkdir(parents=True)
    checkpoint_path.write_text("not loaded by the read-only dashboard", encoding="utf-8")

    status = read_progress_status(run_root)

    assert status["instrument_months_done"] == 1
    assert status["owner_days_done"] == 3
    assert status["eth_group1_partitions_done"] == 39


def test_progress_store_atomic_round_trip(tmp_path: Path) -> None:
    run_root = tmp_path / "runs" / RUN_ID
    _checkpoint(run_root)
    status = read_progress_status(run_root)
    store = ProgressStore(run_root)
    from era100x.research.stage_2.runtime_v2.progress import ProgressV2

    progress = ProgressV2.model_validate_json(
        json.dumps({key: value for key, value in status.items() if key in ProgressV2.model_fields})
    )
    store.replace(progress)
    assert store.read() == progress


def test_pipeline_subflows_and_logs_are_projected_to_web_status(tmp_path: Path) -> None:
    run_root = tmp_path / "runs" / RUN_ID
    _checkpoint(run_root)
    pipeline = PipelineProgressStore(run_root)
    pipeline.update(
        name="DUPLICATE_ARTIFACT_AUDIT",
        status="RUNNING",
        done=9,
        total=19,
        current_item="object-09",
        message="verified object 9",
    )
    pipeline.update(
        name="DUPLICATE_ARTIFACT_AUDIT",
        status="PASS",
        done=19,
        total=19,
        message="all physical hashes are unique",
    )

    status = read_progress_status(run_root)

    assert status["pipeline_progress_present"] is True
    assert status["pipeline_subflows"][0]["name"] == "DUPLICATE_ARTIFACT_AUDIT"
    assert status["pipeline_subflows"][0]["status"] == "PASS"
    assert status["pipeline_subflows"][0]["done"] == 19
    assert status["pipeline_recent_logs"][-1]["message"] == "all physical hashes are unique"


def test_read_only_web_endpoints(tmp_path: Path) -> None:
    root = tmp_path / "external"
    run_root = root / "runs" / RUN_ID
    _checkpoint(run_root)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        (
            sys.executable,
            "scripts/run_stage2_progress_server.py",
            "--run-id",
            RUN_ID,
            "--root",
            str(root),
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz") as response:
                    assert response.status == 200
                    break
            except urllib.error.URLError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as response:
            page = response.read().decode("utf-8")
            assert "Stage 2 · Event Research" in page
            assert "S2-T01" in page
            assert "S2-T10" in page
            assert "S2-T11" in page
            assert "S2-T12" in page
            assert "Full Generation" in page
            assert "Path Extraction" in page
            assert "Path Metrics" in page
            assert "10 / 14 PASSED" in page
            assert "S2-T13<b>CHECKING</b>" in page
            assert "S2-T13<b>PASSED</b>" not in page
            assert "S2-T11 v1.2" not in page
            assert "证据轨道" in page
            assert "Stage 3 LOCKED" in page
            assert "Group 1 CHECKING" in page
            assert "固定旧 Run · 自动识别流水线" in page
            assert "HTML 不预置最终 PASS" in page
            assert "查看执行说明" in page
            assert "只读" in page
            assert "恢复运行" not in page
            assert "停止任务" not in page
            assert "发布数据" not in page
            assert "清理产物" not in page
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as response:
            status = json.load(response)
            assert status["health"] == "INTERRUPTED_RECOVERABLE"
            assert (
                status["execution_observability"]["stage2_tasks"]["S2-T12"]["status"]
                == "NOT_STARTED"
            )
        request = urllib.request.Request(f"http://127.0.0.1:{port}/", method="POST")
        try:
            urllib.request.urlopen(request)
        except urllib.error.HTTPError as exc:
            assert exc.code == 405
        else:  # pragma: no cover - server must always reject controls.
            raise AssertionError("read-only progress server accepted POST")
    finally:
        process.terminate()
        process.wait(timeout=5)
