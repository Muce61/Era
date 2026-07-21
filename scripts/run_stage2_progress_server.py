#!/usr/bin/env python3
# ruff: noqa: E501
"""Serve the local, read-only Stage 2 Runtime V2 progress dashboard."""

from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from era100x.research.stage_2.runtime_v2.checkpoint import SAFE_RUN_ID
from era100x.research.stage_2.runtime_v2.progress import read_progress_status

DEFAULT_ROOT = Path("/Volumes/FuckingLife/era100x_stage2")

_PAGE_PATH = Path(__file__).with_name("stage2_progress_ui.html")
RUNTIME_TASK_RECEIPTS = {
    "foundation_btc": "staging/receipts/foundation/BTCUSDT.json",
    "foundation_eth": "staging/receipts/foundation/ETHUSDT.json",
    "group1_btc_price": "staging/receipts/group1/BTCUSDT/V1_PRICE.json",
    "group1_btc_flow": "staging/receipts/group1/BTCUSDT/V1_FLOW.json",
    "group1_eth_price": "staging/receipts/group1/ETHUSDT/V1_PRICE.json",
    "group1_eth_flow": "staging/receipts/group1/ETHUSDT/V1_FLOW.json",
}
RUNTIME_GROUP1_COMPONENTS = {
    "group1_btc_price": "staging/evidence/group1-components/group1-btcusdt-v1_price.json",
    "group1_btc_flow": "staging/evidence/group1-components/group1-btcusdt-v1_flow.json",
    "group1_eth_price": "staging/evidence/group1-components/group1-ethusdt-v1_price.json",
    "group1_eth_flow": "staging/evidence/group1-components/group1-ethusdt-v1_flow.json",
}


def _safe_file_count(root: Path, pattern: str = "*") -> int:
    if not root.is_dir() or root.is_symlink():
        return 0
    return sum(
        1
        for path in root.rglob(pattern)
        if path.is_file() and not path.is_symlink() and not path.name.startswith("._")
    )


def _safe_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _execution_observability(run_root: Path) -> dict[str, Any]:
    """Project append-only execution evidence into compact UI counters."""

    amendment = _safe_json_object(run_root / "reports/release-only-authority-cr-2026-018.json")
    adoption: dict[str, Any] = {}
    resource_anomalies: dict[str, int] = {}
    adoption_paths = (
        [] if amendment else sorted((run_root / "manifests").glob("group1-monthly-adoption-*.json"))
    )
    if (
        len(adoption_paths) == 1
        and adoption_paths[0].is_file()
        and not adoption_paths[0].is_symlink()
    ):
        raw = json.loads(adoption_paths[0].read_bytes())
        if isinstance(raw, dict):
            adoption = {
                key: raw.get(key)
                for key in (
                    "adopted_file_count",
                    "adopted_byte_count",
                    "foundation_checkpoint_count",
                    "group1_month_count",
                    "group1_dataset_count",
                )
            }
    receipts = {
        name: (run_root / relative_path).is_file() and not (run_root / relative_path).is_symlink()
        for name, relative_path in RUNTIME_TASK_RECEIPTS.items()
    }
    components = {
        name: (run_root / relative_path).is_file() and not (run_root / relative_path).is_symlink()
        for name, relative_path in RUNTIME_GROUP1_COMPONENTS.items()
    }
    checkpoint_path = run_root / "checkpoint-v2.json"
    if checkpoint_path.is_file() and not checkpoint_path.is_symlink():
        checkpoint = json.loads(checkpoint_path.read_bytes())
        if isinstance(checkpoint, dict):
            for task in checkpoint.get("completed_tasks", []):
                if not isinstance(task, dict):
                    continue
                task_id = task.get("task_id")
                count = task.get("resource_anomaly_count", 0)
                if isinstance(task_id, str) and isinstance(count, int) and count >= 0:
                    resource_anomalies[task_id] = count
    preflight = _safe_json_object(run_root / "reports/release-only-preflight-cr-2026-018.json")
    publication = _safe_json_object(run_root / "reports/v2-publication-record.json")
    quality = _safe_json_object(run_root / "reports/v2-quality-report.json")
    compare_authority = _safe_json_object(
        run_root / "reports/compare-only-authority-cr-2026-019.json"
    )
    comparison = _safe_json_object(run_root / "reports/v2-run-a-comparison.json")
    comparison_report = comparison.get("report")
    if not isinstance(comparison_report, dict):
        comparison_report = {}
    differences = comparison_report.get("differences")
    missing = comparison_report.get("missing_in_v2")
    extra = comparison_report.get("extra_in_v2")
    return {
        "successor_created": not bool(amendment),
        "release_only": bool(amendment),
        "release_only_status": amendment.get("status"),
        "release_only_preflight_status": preflight.get("status"),
        "release_only_allowed_commands": amendment.get("allowed_commands", []),
        "sealed_object_count": amendment.get("object_count"),
        "sealed_seal_count": amendment.get("seal_count"),
        "sealed_partition_count": amendment.get("partition_count"),
        "superseded_run_id": amendment.get("superseded_run_id"),
        "adoption": adoption,
        "packed_seal_count": _safe_file_count(run_root / "staging/group1/packed-seals", "*.json"),
        "partial_file_count": _safe_file_count(run_root / "staging/group1/partials"),
        "group1_component_count": _safe_file_count(
            run_root / "staging/evidence/group1-components", "*.json"
        ),
        "group1_component_total": 4,
        "group1_components": components,
        "task_receipts": receipts,
        "resource_anomalies": resource_anomalies,
        "resource_anomaly_count": sum(resource_anomalies.values()),
        "publication_record_present": bool(publication),
        "publication_state": publication.get("publication_state"),
        "quality_report_present": bool(quality),
        "quality_status": quality.get("quality_status"),
        "compare_only_status": compare_authority.get("status"),
        "compare_only_allowed_commands": compare_authority.get("allowed_commands", []),
        "comparison_report_present": bool(comparison),
        "comparison_status": comparison_report.get("status"),
        "matched_partition_count": comparison_report.get("matched_partition_count"),
        "daily_row_hash_match_count": comparison_report.get("daily_row_hash_match_count"),
        "difference_count": len(differences) if isinstance(differences, list) else None,
        "missing_partition_count": len(missing) if isinstance(missing, list) else None,
        "extra_partition_count": len(extra) if isinstance(extra, list) else None,
        "global_distributions_equal": comparison_report.get("global_distributions_equal"),
    }


def _acceptance_projection(status: dict[str, Any], observability: dict[str, Any]) -> dict[str, Any]:
    """Derive S2-T10 acceptance from live append-only evidence, never UI constants."""

    subflows = {
        item.get("name"): item.get("status")
        for item in status.get("pipeline_subflows", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    checks = {
        "all_partitions_complete": status.get("overall_logical_partitions_done") == 80_784,
        "all_task_receipts_present": all(observability.get("task_receipts", {}).values()),
        "publication_pass": observability.get("publication_state")
        in {"PUBLISHED", "PUBLISHED_WITH_RESOURCE_ANOMALIES"},
        "quality_pass": observability.get("quality_status") == "PASS",
        "release_subflow_pass": subflows.get("RELEASE") == "PASS",
        "verify_subflow_pass": subflows.get("VERIFY") == "PASS",
        "compare_subflow_pass": subflows.get("RUN_A_RUN_B_COMPARE") == "PASS",
        "exact_partition_match": observability.get("matched_partition_count") == 61_776,
        "all_daily_hashes_match": observability.get("daily_row_hash_match_count") == 61_776,
        "no_missing_partitions": observability.get("missing_partition_count") == 0,
        "no_extra_partitions": observability.get("extra_partition_count") == 0,
        "no_differences": observability.get("difference_count") == 0,
        "global_distributions_equal": observability.get("global_distributions_equal") is True,
    }
    comparison_checks = (
        "exact_partition_match",
        "all_daily_hashes_match",
        "no_missing_partitions",
        "no_extra_partitions",
        "no_differences",
        "global_distributions_equal",
    )
    failed = any(
        subflows.get(name) == "FAILED" for name in ("RELEASE", "VERIFY", "RUN_A_RUN_B_COMPARE")
    ) or (
        observability.get("comparison_report_present") is True
        and not all(checks[name] for name in comparison_checks)
    )
    task_status = "PASS" if all(checks.values()) else "FAILED" if failed else "IN_PROGRESS"
    return {
        "s2_t10_status": task_status,
        "group1_status": task_status,
        "stage3_status": "LOCKED",
        "checks": checks,
    }


class ProgressHandler(BaseHTTPRequestHandler):
    server: ProgressHTTPServer

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path == "/":
            self._reply(HTTPStatus.OK, "text/html; charset=utf-8", _PAGE_PATH.read_bytes())
        elif path == "/api/status":
            try:
                payload = read_progress_status(self.server.run_root)
                observability = _execution_observability(self.server.run_root)
                observability["acceptance"] = _acceptance_projection(payload, observability)
                payload["execution_observability"] = observability
                self._reply_json(HTTPStatus.OK, payload)
            except (OSError, ValueError) as exc:
                self._reply_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        elif path == "/healthz":
            try:
                payload = read_progress_status(self.server.run_root)
                self._reply_json(HTTPStatus.OK, {"status": "ok", "health": payload["health"]})
            except (OSError, ValueError) as exc:
                self._reply_json(
                    HTTPStatus.SERVICE_UNAVAILABLE, {"status": "unavailable", "error": str(exc)}
                )
        else:
            self._reply_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._reply_json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "read-only server"})

    def log_message(self, format: str, *args: Any) -> None:
        del format, args

    def _reply_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        self._reply(
            status,
            "application/json; charset=utf-8",
            (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        )

    def _reply(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


class ProgressHTTPServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], run_root: Path) -> None:
        super().__init__(address, ProgressHandler)
        self.run_root = run_root


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Read-only Stage 2 Runtime V2 progress")
    root.add_argument("--run-id", required=True)
    root.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    root.add_argument("--bind", default="127.0.0.1")
    root.add_argument("--port", type=int, default=8765)
    root.add_argument("--open-browser", action="store_true")
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if SAFE_RUN_ID.fullmatch(args.run_id) is None:
        raise SystemExit("invalid Runtime V2 run id")
    run_root = (args.root / "runs" / args.run_id).resolve()
    approved = args.root.resolve()
    if not run_root.is_relative_to(approved) or not run_root.is_dir():
        raise SystemExit(f"run directory is unavailable: {run_root}")
    server = ProgressHTTPServer((args.bind, args.port), run_root)
    url = f"http://{args.bind}:{args.port}"
    if args.open_browser:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    print(url, flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
