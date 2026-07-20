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


class ProgressHandler(BaseHTTPRequestHandler):
    server: ProgressHTTPServer

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path == "/":
            self._reply(HTTPStatus.OK, "text/html; charset=utf-8", _PAGE_PATH.read_bytes())
        elif path == "/api/status":
            try:
                payload = read_progress_status(self.server.run_root)
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
