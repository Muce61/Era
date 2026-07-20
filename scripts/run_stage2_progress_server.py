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

_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Era Stage 2 进度</title>
<style>
:root{color-scheme:dark;--bg:#09101c;--panel:#111c2e;--line:#24354f;--fg:#e9f0fa;--muted:#95a7bf;--ok:#55d69e;--warn:#f5c451;--bad:#ff6b75}
*{box-sizing:border-box}body{margin:0;background:linear-gradient(140deg,#08101e,#101a2c);color:var(--fg);font:14px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}.wrap{max-width:1280px;margin:auto;padding:18px}.head,.grid{display:grid;gap:12px}.head{grid-template-columns:1fr auto;align-items:center}.grid{grid-template-columns:repeat(auto-fit,minmax(260px,1fr));margin-top:12px}.card{background:rgba(17,28,46,.96);border:1px solid var(--line);border-radius:12px;padding:14px;box-shadow:0 12px 30px #0005}.muted{color:var(--muted)}.big{font-size:22px;font-weight:700}.bar{height:14px;background:#07101e;border:1px solid var(--line);border-radius:10px;overflow:hidden;margin:7px 0 11px}.fill{height:100%;width:0;background:linear-gradient(90deg,#318bff,#55d69e);transition:width .4s}.kv{display:grid;grid-template-columns:1fr auto;gap:6px;border-bottom:1px solid #1c2b42;padding:5px 0}.workers,.events,.pipeline{max-height:330px;overflow:auto}.subflow{padding:9px 0;border-bottom:1px solid #1c2b42}.subhead{display:flex;justify-content:space-between;gap:10px}.tiny{height:8px;margin:5px 0}.PASS{color:var(--ok)}.FAILED,.BLOCKED{color:var(--bad)}.RUNNING{color:var(--warn)}.health{padding:5px 9px;border-radius:999px;background:#24354f}.health.HEALTHY,.health.COMPLETE{background:#164936;color:#7df2bd}.health.STALLED,.health.PAUSED,.health.RUNNING_WITH_ANOMALIES{background:#5d4617;color:#ffd670}.health.FAILED_INTEGRITY{background:#61202a;color:#ff9da5}@media(max-width:620px){.wrap{padding:9px}.head{grid-template-columns:1fr}.big{font-size:17px}}
</style></head><body><main class="wrap"><div class="head"><div><div class="muted">ERA / Stage 2 Runtime V2</div><div class="big" id="run">加载中…</div></div><span id="health" class="health">LOADING</span></div>
<section class="grid">
<div class="card"><b>总进度</b><div class="bar"><div id="overall" class="fill"></div></div><span id="overallText"></span><div class="kv"><span>阶段</span><span id="phase"></span></div><div class="kv"><span>任务</span><span id="task"></span></div><div class="kv"><span>ETA</span><span id="eta"></span></div></div>
<div class="card"><b>Foundation</b><div class="bar"><div id="foundation" class="fill"></div></div><span id="foundationText"></span><b>Group 1</b><div class="bar"><div id="group1" class="fill"></div></div><span id="group1Text"></span></div>
<div class="card"><b>BTC / ETH</b><div class="bar"><div id="btc" class="fill"></div></div><span id="btcText"></span><div class="bar"><div id="eth" class="fill"></div></div><span id="ethText"></span><b>PRICE / FLOW</b><div class="bar"><div id="price" class="fill"></div></div><span id="priceText"></span><div class="bar"><div id="flow" class="fill"></div></div><span id="flowText"></span></div>
<div class="card"><b>当前细粒度</b><div class="kv"><span>标的 / 变体</span><span id="iv"></span></div><div class="kv"><span>UTC 月 / owner day</span><span id="md"></span></div><div class="bar"><div id="minute" class="fill"></div></div><span id="minuteText"></span><div class="kv"><span>30分钟增量</span><span id="delta"></span></div></div>
<div class="card"><b>资源</b><div class="kv"><span>CPU</span><span id="cpu"></span></div><div class="kv"><span>RSS</span><span id="rss"></span></div><div class="kv"><span>Arrow</span><span id="arrow"></span></div><div class="kv"><span>外盘剩余</span><span id="disk"></span></div><div class="kv"><span>异常 / 失败</span><span id="af"></span></div></div>
<div class="card"><b>三个 Worker</b><div id="workers" class="workers"></div></div><div class="card"><b>最近事件</b><div id="events" class="events"></div></div>
<div class="card" style="grid-column:1/-1"><b>恢复、发布与验收小流程</b><div id="pipeline" class="pipeline"></div></div>
<div class="card" style="grid-column:1/-1"><b>小流程实时日志</b><div id="pipelineLogs" class="events"></div></div>
</section><p class="muted">只读页面，每5秒刷新；checkpoint 终态优先。无恢复、停止、发布或清理按钮。</p></main>
<script>
const fmt=n=>{if(n==null)return'-';for(const u of ['B','KiB','MiB','GiB','TiB']){if(Math.abs(n)<1024||u==='TiB')return n.toFixed(n<10&&u!=='B'?2:0)+' '+u;n/=1024}};
const pct=(id,v)=>{document.getElementById(id).style.width=Math.max(0,Math.min(100,v||0))+'%'};
const set=(id,v)=>document.getElementById(id).textContent=v??'-';
async function refresh(){try{const r=await fetch('/api/status',{cache:'no-store'});const s=await r.json();set('run',s.run_id);const h=document.getElementById('health');h.textContent=s.health;h.className='health '+s.health;set('phase',s.phase);set('task',s.active_task);pct('overall',s.overall_percentage);set('overallText',`${s.overall_logical_partitions_done.toLocaleString()} / ${s.overall_logical_partitions_total.toLocaleString()} (${s.overall_percentage.toFixed(2)}%)`);pct('foundation',100*s.foundation_logical_partitions_done/s.foundation_logical_partitions_total);set('foundationText',`${s.foundation_logical_partitions_done.toLocaleString()} / ${s.foundation_logical_partitions_total.toLocaleString()}`);pct('group1',s.group1_percentage);set('group1Text',`${s.group1_logical_partitions_sealed.toLocaleString()} / ${s.group1_logical_partitions_total.toLocaleString()} (${s.group1_percentage.toFixed(2)}%)`);pct('btc',100*s.btc_group1_partitions_done/30888);set('btcText',`BTC ${s.btc_group1_partitions_done.toLocaleString()} / 30,888`);pct('eth',100*s.eth_group1_partitions_done/30888);set('ethText',`ETH ${s.eth_group1_partitions_done.toLocaleString()} / 30,888`);pct('price',100*s.price_partitions_done/47520);set('priceText',`PRICE ${s.price_partitions_done.toLocaleString()} / 47,520`);pct('flow',100*s.flow_partitions_done/14256);set('flowText',`FLOW ${s.flow_partitions_done.toLocaleString()} / 14,256`);pct('minute',100*s.processing_minutes_done/1440);set('minuteText',`${s.processing_minutes_done} / 1440 分钟`);set('iv',`${s.instrument||'-'} / ${s.variant||'-'}`);set('md',`${s.current_month||'-'} / ${s.current_owner_date||'-'}`);set('eta',s.eta_seconds==null?'-':Math.round(s.eta_seconds/60)+' min');set('delta',s.recent_30m_delta??'-');set('cpu',(s.cpu_percent||0).toFixed(1)+'%');set('rss',fmt(s.current_rss_bytes));set('arrow',fmt(s.arrow_inflight_bytes));set('disk',fmt(s.external_disk_free_bytes));set('af',`${s.anomaly_count} / ${s.failure_count}`);document.getElementById('workers').innerHTML=(s.worker_states||[]).map(w=>`<div class="kv"><span>${w.worker_id}</span><span>${w.status} ${w.current_month||''} ${w.current_processing_minute??''}</span></div>`).join('')||'<span class="muted">暂无 worker 快照</span>';document.getElementById('events').innerHTML=(s.recent_events||[]).slice().reverse().map(e=>`<div class="kv"><span>${e.timestamp}</span><span>${e.message}</span></div>`).join('')||'<span class="muted">暂无事件</span>';document.getElementById('pipeline').innerHTML=(s.pipeline_subflows||[]).map(x=>{const p=x.total?100*x.done/x.total:(x.status==='PASS'?100:0);return `<div class="subflow"><div class="subhead"><b>${x.name}</b><span class="${x.status}">${x.status}</span></div><div class="bar tiny"><div class="fill" style="width:${Math.min(100,p)}%"></div></div><div class="muted">${x.done.toLocaleString()} / ${x.total.toLocaleString()} · ${Math.round(x.elapsed_seconds)}s · ${x.current_item||'-'} · ${x.message||''}</div></div>`}).join('')||'<span class="muted">尚未启动恢复小流程</span>';document.getElementById('pipelineLogs').innerHTML=(s.pipeline_recent_logs||[]).slice().reverse().map(e=>`<div class="kv"><span>${e.timestamp} · ${e.phase}</span><span>${e.message}</span></div>`).join('')||'<span class="muted">暂无小流程日志</span>';}catch(e){const h=document.getElementById('health');h.textContent='UNAVAILABLE';h.className='health FAILED_INTEGRITY';}}
refresh();setInterval(refresh,5000);
</script></body></html>"""


class ProgressHandler(BaseHTTPRequestHandler):
    server: ProgressHTTPServer

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path == "/":
            self._reply(HTTPStatus.OK, "text/html; charset=utf-8", _PAGE.encode("utf-8"))
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
