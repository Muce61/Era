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


def _execution_observability(run_root: Path) -> dict[str, Any]:
    """Project append-only execution evidence into compact UI counters."""

    adoption: dict[str, Any] = {}
    resource_anomalies: dict[str, int] = {}
    adoption_paths = sorted((run_root / "manifests").glob("group1-monthly-adoption-*.json"))
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
    return {
        "successor_created": True,
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
        "publication_record_present": (run_root / "reports/v2-publication-record.json").is_file(),
        "comparison_report_present": (run_root / "reports/v2-run-a-comparison.json").is_file(),
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
                payload["execution_observability"] = _execution_observability(self.server.run_root)
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
