"""Append-only T20 smoke, producer, publication and independent verification."""

from __future__ import annotations

import fcntl
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.acceptance.canonical_json import (
    canonical_content_hash,
    canonical_json_bytes,
    read_canonical_json,
    sha256_file,
    verify_canonical_json_file,
    write_canonical_json_exclusive,
)
from era100x.research.stage_2.acceptance.evidence_gate.runner import (
    FREQUENCY_SCHEMA,
    GATE_SCHEMA,
)
from era100x.research.stage_2.statistics.bootstrap.runner import SUMMARY_SCHEMA

from .contracts import RESEARCH_DECISION, S2P17T20Authority
from .engine import (
    attach_event_evidence,
    evidence_index,
    final_decision,
    public_blind_selection,
    render_event_card_svg,
    render_explainer_svg,
    select_event_identities,
)
from .governance import (
    FinalAcceptancePolicy,
    SourceBindings,
    audit_sources,
    freeze_authority,
    repository_clean,
    repository_commit,
    validate_approval,
)

ProgressCallback = Callable[[dict[str, Any]], None]


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _atomic_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    sealed = {**payload, "checkpoint_hash": canonical_content_hash(payload)}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    data = canonical_json_bytes(sealed) + b"\n"
    temporary.write_bytes(data)
    verify_canonical_json_file(temporary)
    os.replace(temporary, path)


def _chrome_binary() -> Path:
    configured = os.environ.get("ERA_T20_CHROME_BIN")
    candidates = (
        Path(configured) if configured else None,
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path(shutil.which("google-chrome") or ""),
        Path(shutil.which("chromium") or ""),
    )
    for candidate in candidates:
        if candidate is not None and str(candidate) and candidate.is_file():
            return candidate
    raise ValueError("pinned Chromium-compatible renderer is unavailable")


def _render_png(svg_path: Path, png_path: Path) -> str:
    chrome = _chrome_binary()
    command = [
        str(chrome),
        "--headless",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--hide-scrollbars",
        "--allow-file-access-from-files",
        "--incognito",
        "--metrics-recording-only",
        "--mute-audio",
        "--no-first-run",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=1000",
        "--window-size=1200,675",
        f"--screenshot={png_path}",
        svg_path.resolve().as_uri(),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if completed.returncode != 0 or not png_path.is_file():
        raise ValueError(f"event-card PNG render failed: {completed.stderr.strip()}")
    version = subprocess.check_output([str(chrome), "--version"], text=True).strip()
    return version


def _write_svg(path: Path, payload: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)
    return sha256_file(path)


def _write_parquet_copy(source: Path, target: Path, *, expected_schema: Any) -> int:
    table = pq.read_table(source)
    if table.schema != expected_schema:
        raise ValueError(f"T20 source Parquet schema drift: {source.name}")
    pq.write_table(table, target)
    if pq.read_schema(target) != expected_schema:
        raise ValueError(f"T20 Parquet schema round-trip drift: {target.name}")
    return int(table.num_rows)


def _report(decision: dict[str, Any], cards: list[dict[str, Any]]) -> str:
    lines = [
        "# S2P17-T20 Final Evidence Acceptance",
        "",
        f"- Engineering: `{decision['engineering_status']}`",
        f"- H2 Primary: `{decision['h2_primary']}`",
        f"- ETH classification: `{decision['eth_classification']}`",
        f"- Research decision: `{decision['research_decision']}`",
        "- Stage 3: `LOCKED`",
        "",
        "## Lifecycle",
        "",
    ]
    for instrument, value in cast(dict[str, str], decision["h3_lifecycle"]).items():
        lines.append(f"- {instrument}: `{value}`")
    lines.extend(
        [
            "",
            "## Deterministic real evidence cards",
            "",
            "The six identities were selected before any outcome field was read.",
            "Cards show verified H2 identity and First Passage evidence, "
            "not PnL or live execution.",
            "",
        ]
    )
    for card in cards:
        lines.append(
            f"- {card['instrument']} / {card['pre_registered_period']}: "
            f"`{card.get('label', card.get('selection_status'))}`"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Engineering and evidence integrity can pass while the research result is NO-GO.",
            "No result in this package authorizes T21, Stage 3, testnet or real execution.",
            "",
        ]
    )
    return "\n".join(lines)


def _project_and_write(
    sources: SourceBindings,
    output: Path,
    *,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    if progress:
        progress({"phase": "HASH_CHAIN", "processed_units": 1, "total_units": 9})
    index = evidence_index(sources)
    write_canonical_json_exclusive(output / "evidence-index.json", index)

    if progress:
        progress({"phase": "BLIND_EVENT_SELECTION", "processed_units": 2, "total_units": 9})
    selected = select_event_identities(sources)
    blind = public_blind_selection(selected)
    write_canonical_json_exclusive(output / "blind-event-selection.json", blind)
    verify_canonical_json_file(
        output / "blind-event-selection.json",
        expected_hash=canonical_content_hash(blind),
    )

    if progress:
        progress({"phase": "EVIDENCE_CARDS", "processed_units": 3, "total_units": 9})
    cards = attach_event_evidence(sources, selected)
    cards_payload: dict[str, Any] = {
        "schema_name": "s2p17-t20-event-cards",
        "schema_version": "1.0",
        "selection_hash": blind["selection_hash"],
        "outcomes_read_after_selection_sealed": True,
        "items": cards,
    }
    cards_payload["event_cards_hash"] = canonical_content_hash(cards_payload)
    write_canonical_json_exclusive(output / "event-cards.json", cards_payload)

    visual_root = output / "visuals"
    explainer_svg = visual_root / "event-explainer.svg"
    _write_svg(explainer_svg, render_explainer_svg())
    renderer_versions = {_render_png(explainer_svg, visual_root / "event-explainer.png")}
    for card in cards:
        stem = f"{str(card['instrument']).lower()}-{str(card['pre_registered_period']).lower()}"
        svg = visual_root / f"{stem}.svg"
        _write_svg(svg, render_event_card_svg(card))
        renderer_versions.add(_render_png(svg, visual_root / f"{stem}.png"))
    if len(renderer_versions) != 1:
        raise ValueError("event-card renderer version drift")

    if progress:
        progress({"phase": "GATE_LEDGER", "processed_units": 4, "total_units": 9})
    gate_rows = _write_parquet_copy(
        sources.t19.gate_path, output / "gate-ledger.parquet", expected_schema=GATE_SCHEMA
    )
    landscape_rows = _write_parquet_copy(
        sources.t19.landscape_path,
        output / "parameter-landscape.parquet",
        expected_schema=SUMMARY_SCHEMA,
    )
    frequency_rows = _write_parquet_copy(
        sources.t19.frequency_path,
        output / "frequency-waiting.parquet",
        expected_schema=FREQUENCY_SCHEMA,
    )
    if (gate_rows, landscape_rows, frequency_rows) != (28, 3420, 14):
        raise ValueError("T20 source projection count drift")

    if progress:
        progress({"phase": "FINAL_REPORT", "processed_units": 6, "total_units": 9})
    decision = final_decision(sources)
    decision["event_selection_hash"] = blind["selection_hash"]
    decision["event_cards_hash"] = cards_payload["event_cards_hash"]
    decision["renderer_version"] = next(iter(renderer_versions))
    decision["decision_hash"] = canonical_content_hash(
        {key: value for key, value in decision.items() if key != "decision_hash"}
    )
    write_canonical_json_exclusive(output / "stage2-final-decision.json", decision)
    (output / "stage2-final-report.md").write_text(
        _report(decision, cards), encoding="utf-8", newline="\n"
    )
    reconciliation: dict[str, Any] = {
        "schema_name": "s2p17-t20-reconciliation",
        "schema_version": "1.0",
        "gate_rows": gate_rows,
        "parameter_landscape_rows": landscape_rows,
        "frequency_waiting_rows": frequency_rows,
        "event_card_slots": len(cards),
        "event_card_selected": sum("market_episode_id" in card for card in cards),
        "illustrative_explainer_count": 1,
        "research_decision": RESEARCH_DECISION,
        "status": "PASS",
    }
    reconciliation["reconciliation_hash"] = canonical_content_hash(reconciliation)
    write_canonical_json_exclusive(output / "reconciliation.json", reconciliation)
    if progress:
        progress({"phase": "PUBLISH", "processed_units": 8, "total_units": 9})
    return {
        "gate_rows": gate_rows,
        "parameter_landscape_rows": landscape_rows,
        "frequency_waiting_rows": frequency_rows,
        "event_card_count": len(cards),
        "renderer_version": next(iter(renderer_versions)),
        "decision_hash": decision["decision_hash"],
        "reconciliation_hash": reconciliation["reconciliation_hash"],
    }


def _catalog(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(
        item
        for item in root.rglob("*")
        if item.is_file()
        and not item.is_symlink()
        and not item.name.startswith("._")
        and item.name not in {"catalog.json", "manifest.json"}
        and not any(part.startswith("._") for part in item.relative_to(root).parts)
    ):
        relative = path.relative_to(root).as_posix()
        item: dict[str, Any] = {
            "relative_path": relative,
            "byte_size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        if path.suffix == ".json":
            item["content_hash"] = verify_canonical_json_file(path)
        elif path.suffix == ".svg":
            raw = path.read_bytes()
            if not raw.endswith(b"\n") or raw.endswith(b"\n\n") or raw.endswith(b"\r\n"):
                raise ValueError("canonical SVG must end with exactly one LF")
            item["svg_content_hash"] = __import__("hashlib").sha256(raw[:-1]).hexdigest()
        elif path.suffix == ".parquet":
            item["row_count"] = pq.read_metadata(path).num_rows
        files.append(item)
    payload: dict[str, Any] = {
        "schema_name": "s2p17-t20-catalog",
        "schema_version": "1.0",
        "files": files,
    }
    payload["catalog_hash"] = canonical_content_hash(payload)
    return payload


def format_smoke(
    *,
    policy: FinalAcceptancePolicy,
    sources: SourceBindings,
    repository_root: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="era-s2p17-t20-smoke-") as raw:
        root = Path(raw)
        projection = _project_and_write(sources, root)
        catalog = _catalog(root)
        write_canonical_json_exclusive(root / "catalog.json", catalog)
        verify_canonical_json_file(
            root / "catalog.json", expected_hash=canonical_content_hash(catalog)
        )
    elapsed = max(time.monotonic() - started, 0.000001)
    payload: dict[str, Any] = {
        "schema_name": "s2p17-t20-format-smoke",
        "schema_version": "1.0",
        "status": "PASS",
        "task_id": "S2P17-T20",
        "code_commit": repository_commit(repository_root),
        "policy_hash": policy.policy_hash,
        "source_t19_verify_hash": sources.t19.verify_hash,
        "canonical_json_schema": "CANONICAL_JSON_CONTENT_V1",
        "gate_rows": projection["gate_rows"],
        "parameter_landscape_rows": projection["parameter_landscape_rows"],
        "frequency_waiting_rows": projection["frequency_waiting_rows"],
        "event_card_count": projection["event_card_count"],
        "renderer_version": projection["renderer_version"],
        "elapsed_seconds": f"{elapsed:.6f}",
        "rss_bytes": _rss_bytes(),
        "formal_objects_created": False,
    }
    payload["format_smoke_hash"] = canonical_content_hash(payload)
    path = policy.operations_root / "format-smokes" / f"{payload['format_smoke_hash']}.json"
    write_canonical_json_exclusive(path, payload)
    return payload


def verify_run(run_root: Path) -> dict[str, Any]:
    contract = read_canonical_json(run_root / "run-contract.json")
    published = run_root / "published"
    catalog = read_canonical_json(published / "catalog.json")
    manifest = read_canonical_json(published / "manifest.json")
    if (
        not canonical_content_hash(
            {key: value for key, value in contract.items() if key != "run_contract_hash"}
        )
        == contract.get("run_contract_hash")
        or not canonical_content_hash(
            {key: value for key, value in catalog.items() if key != "catalog_hash"}
        )
        == catalog.get("catalog_hash")
        or not canonical_content_hash(
            {key: value for key, value in manifest.items() if key != "manifest_hash"}
        )
        == manifest.get("manifest_hash")
        or manifest.get("catalog_hash") != catalog.get("catalog_hash")
    ):
        raise ValueError("T20 run contract/Manifest/Catalog drift")
    for entry in cast(list[dict[str, Any]], catalog["files"]):
        path = published / str(entry["relative_path"])
        if sha256_file(path) != entry["sha256"] or path.stat().st_size != entry["byte_size"]:
            raise ValueError("T20 Catalog file drift")
        if path.suffix == ".json" and verify_canonical_json_file(path) != entry["content_hash"]:
            raise ValueError("T20 canonical JSON content Hash drift")
        if path.suffix == ".parquet" and pq.read_metadata(path).num_rows != entry["row_count"]:
            raise ValueError("T20 Parquet row-count drift")
    decision = read_canonical_json(published / "stage2-final-decision.json")
    reconciliation = read_canonical_json(published / "reconciliation.json")
    cards = read_canonical_json(published / "event-cards.json")
    if (
        decision.get("research_decision") != RESEARCH_DECISION
        or decision.get("stage3_locked") is not True
        or reconciliation.get("status") != "PASS"
        or reconciliation.get("gate_rows") != 28
        or reconciliation.get("parameter_landscape_rows") != 3420
        or reconciliation.get("frequency_waiting_rows") != 14
        or len(cast(list[object], cards.get("items"))) != 6
    ):
        raise ValueError("T20 decision/reconciliation drift")
    verify: dict[str, Any] = {
        "schema_name": "s2p17-t20-verify-record",
        "schema_version": "1.0",
        "status": "PASS",
        "run_id": contract["run_id"],
        "authority_hash": contract["authority_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "reconciliation_hash": reconciliation["reconciliation_hash"],
        "decision_hash": decision["decision_hash"],
        "gate_rows": 28,
        "parameter_landscape_rows": 3420,
        "frequency_waiting_rows": 14,
        "event_card_count": 6,
        "research_decision": RESEARCH_DECISION,
        "stage3_locked": True,
    }
    verify["verify_hash"] = canonical_content_hash(verify)
    verify_path = run_root / "verify" / f"{verify['verify_hash']}.json"
    if verify_path.exists():
        existing = read_canonical_json(verify_path)
        if existing != verify:
            raise ValueError("T20 Verify append-only conflict")
    else:
        write_canonical_json_exclusive(verify_path, verify)
    return verify


def run_formal(
    *,
    policy: FinalAcceptancePolicy,
    approval_path: Path,
    repository_root: Path,
    resume_run_root: Path | None = None,
) -> dict[str, Any]:
    if not repository_clean(repository_root):
        raise ValueError("formal T20 run requires a clean repository")
    lock_path = policy.operations_root / "run.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        approval = validate_approval(approval_path, policy=policy, repository_root=repository_root)
        sources = audit_sources(policy, repository_root=repository_root, full_hash_scan=True)
        runs_root = policy.evidence_root / "runs"
        runs_root.mkdir(parents=True, exist_ok=True)
        runs = tuple(
            sorted(
                path
                for path in runs_root.glob("stage2-s2p17-t20-*")
                if path.is_dir() and not path.is_symlink()
            )
        )
        if resume_run_root is None:
            if runs:
                raise ValueError("T20 permits exactly one formal Run")
            authority = freeze_authority(
                policy=policy,
                approval=approval,
                sources=sources,
                repository_root=repository_root,
            )
            run_id = (
                f"stage2-s2p17-t20-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
                f"{authority.authority_hash[:12]}"
            )
            run_root = runs_root / run_id
            run_root.mkdir(parents=True, exist_ok=False)
            contract: dict[str, Any] = {
                "schema_name": "s2p17-t20-run-contract",
                "schema_version": "1.0",
                "run_id": run_id,
                "authority_hash": authority.authority_hash,
                "code_commit": repository_commit(repository_root),
                "policy_hash": policy.policy_hash,
                "status": "UNPUBLISHED",
            }
            contract["run_contract_hash"] = canonical_content_hash(contract)
            write_canonical_json_exclusive(run_root / "run-contract.json", contract)
        else:
            run_root = resume_run_root
            if len(runs) != 1 or runs[0].resolve() != run_root.resolve():
                raise ValueError("T20 resume Run identity drift")
            contract = read_canonical_json(run_root / "run-contract.json")
            run_id = str(contract["run_id"])
            authority_path = (
                policy.evidence_root
                / "authorities"
                / f"authority-{contract['authority_hash']}.json"
            )
            authority = S2P17T20Authority.model_validate_json(
                authority_path.read_bytes(), strict=True
            )
            if authority.approval_hash != approval["approval_hash"]:
                raise ValueError("T20 resume Authority drift")
            if (run_root / "published").is_dir():
                return verify_run(run_root)

        checkpoint = run_root / "checkpoint.json"
        started = time.monotonic()

        def progress(value: dict[str, Any]) -> None:
            processed = int(value.get("processed_units", 0))
            total = max(int(value.get("total_units", 1)), 1)
            elapsed = max(time.monotonic() - started, 0.000001)
            rate = processed / elapsed
            _atomic_checkpoint(
                checkpoint,
                {
                    "schema_name": "s2p17-t20-checkpoint",
                    "schema_version": "1.0",
                    "run_id": run_id,
                    "status": "IN_PROGRESS",
                    **value,
                    "percent": f"{processed * 100 / total:.6f}",
                    "elapsed_seconds": f"{elapsed:.6f}",
                    "rows_per_second": f"{rate:.6f}",
                    "rss_bytes": _rss_bytes(),
                    "eta_seconds": None if rate == 0 else f"{(total - processed) / rate:.6f}",
                    "heartbeat_at": datetime.now(UTC).isoformat(),
                },
            )

        work = run_root / "work"
        if work.exists():
            shutil.rmtree(work)
        projection = _project_and_write(sources, work, progress=progress)
        catalog = _catalog(work)
        write_canonical_json_exclusive(work / "catalog.json", catalog)
        manifest: dict[str, Any] = {
            "schema_name": "s2p17-t20-manifest",
            "schema_version": "1.0",
            "run_id": run_id,
            "authority_hash": authority.authority_hash,
            "catalog_hash": catalog["catalog_hash"],
            "reconciliation_hash": projection["reconciliation_hash"],
            "decision_hash": projection["decision_hash"],
            "source_t19_verify_hash": sources.t19.verify_hash,
            "research_decision": RESEARCH_DECISION,
            "historical_evidence_only": True,
            "stage3_locked": True,
        }
        manifest["manifest_hash"] = canonical_content_hash(manifest)
        write_canonical_json_exclusive(work / "manifest.json", manifest)
        os.replace(work, run_root / "published")
        progress({"phase": "VERIFY", "processed_units": 9, "total_units": 9})
        verify = verify_run(run_root)
        _atomic_checkpoint(
            checkpoint,
            {
                "schema_name": "s2p17-t20-checkpoint",
                "schema_version": "1.0",
                "run_id": run_id,
                "status": "PASS",
                "phase": "VERIFY",
                "processed_units": 9,
                "total_units": 9,
                "percent": "100.000000",
                "elapsed_seconds": f"{time.monotonic() - started:.6f}",
                "heartbeat_at": datetime.now(UTC).isoformat(),
                "verify_hash": verify["verify_hash"],
            },
        )
        return verify


def resume_formal(
    *,
    policy: FinalAcceptancePolicy,
    approval_path: Path,
    repository_root: Path,
) -> dict[str, Any]:
    runs = tuple(
        sorted(
            path
            for path in (policy.evidence_root / "runs").glob("stage2-s2p17-t20-*")
            if path.is_dir() and not path.is_symlink()
        )
    )
    if len(runs) != 1:
        raise ValueError("T20 resume requires exactly one formal Run")
    return run_formal(
        policy=policy,
        approval_path=approval_path,
        repository_root=repository_root,
        resume_run_root=runs[0],
    )
