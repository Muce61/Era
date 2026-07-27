"""Append-only T19 smoke, producer, publication and independent verification."""

from __future__ import annotations

import fcntl
import os
import resource
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.statistics.bootstrap.runner import SUMMARY_SCHEMA

from .contracts import GateResult, S2P16T19Authority
from .engine import synthesize_evidence
from .formatting import canonical_hash, canonical_json, read_json, sha256_file, write_exclusive
from .governance import (
    EvidenceGatePolicy,
    SourceBindings,
    audit_sources,
    freeze_authority,
    repository_clean,
    repository_commit,
    validate_approval,
)

ProgressCallback = Callable[[dict[str, Any]], None]

GATE_SCHEMA = pa.schema(
    [
        pa.field("gate_id", pa.string(), nullable=False),
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("evidence_family", pa.string(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("observed_value", pa.string()),
        pa.field("threshold", pa.string()),
        pa.field("reason_code", pa.string(), nullable=False),
        pa.field("source_hash", pa.string(), nullable=False),
        pa.field("result_hash", pa.string(), nullable=False),
        pa.field("result_json", pa.string(), nullable=False),
    ]
)

FREQUENCY_SCHEMA = pa.schema(
    [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("utc_year", pa.int32(), nullable=False),
        pa.field("event_count", pa.int64(), nullable=False),
        pa.field("independent_week_cluster_count", pa.int64(), nullable=False),
        pa.field("median_wait_seconds", pa.string()),
        pa.field("p95_wait_seconds", pa.string()),
    ]
)


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _atomic_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    sealed = {**payload, "checkpoint_hash": canonical_hash(payload)}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(canonical_json(sealed) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _gate_rows(items: list[GateResult]) -> list[dict[str, Any]]:
    return [
        {
            **item.model_dump(mode="python"),
            "result_json": canonical_json(item.model_dump(mode="python")),
        }
        for item in items
    ]


def _write_parquet(path: Path, rows: list[dict[str, Any]], schema: pa.Schema) -> None:
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    if pq.read_schema(path) != schema:
        raise ValueError(f"T19 Parquet schema round-trip drift: {path.name}")


def _strict_gate_read(path: Path) -> tuple[GateResult, ...]:
    if pq.read_schema(path) != GATE_SCHEMA:
        raise ValueError("T19 gate-results schema drift")
    values = pq.read_table(path, columns=["result_json"]).column(0).to_pylist()
    result = tuple(GateResult.model_validate_json(str(value), strict=True) for value in values)
    if [canonical_json(item.model_dump(mode="python")) for item in result] != [
        str(value) for value in values
    ]:
        raise ValueError("T19 gate-results strict JSON drift")
    return result


def _markdown(cards: dict[str, Any]) -> str:
    lifecycle = cast(dict[str, dict[str, Any]], cards["lifecycle"])
    lines = [
        "# S2P16-T19 Evidence Gate",
        "",
        f"- Engineering: `{cards['engineering_status']}`",
        f"- BTC Primary: `{cards['btc_primary']}`",
        f"- ETH classification: `{cards['eth_classification']}`",
        f"- Overall: `{cards['overall_recommendation']}`",
        f"- Research status: `{cards['research_status']}`",
        "- Stage 3: `LOCKED`",
        "",
        "## Lifecycle evidence",
        "",
    ]
    for instrument in ("BTCUSDT", "ETHUSDT"):
        item = lifecycle[instrument]
        lines.extend(
            [
                f"### {instrument}",
                "",
                f"- Episodes: {item['episodes']}",
                f"- Eligible: {item['eligible']}",
                f"- Source-gap censored: {item['source_gap_censored']}",
                f"- Decision: `{item['decision']}`",
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
        progress({"phase": "SOURCE_PROJECTION", "processed_units": 0, "total_units": 4})
    result = synthesize_evidence(sources)
    if progress:
        progress({"phase": "H2_F1_F10", "processed_units": 2, "total_units": 4})
    gate_path = output / "gate-results.parquet"
    landscape_path = output / "parameter-landscape.parquet"
    frequency_path = output / "frequency-waiting.parquet"
    cards_path = output / "evidence-cards.json"
    report_path = output / "evidence-report.md"
    reconciliation_path = output / "reconciliation.json"

    gates = cast(list[GateResult], result["gates"])
    landscape = cast(list[dict[str, Any]], result["parameter_landscape"])
    frequency = cast(list[dict[str, Any]], result["frequency_waiting"])
    _write_parquet(gate_path, _gate_rows(gates), GATE_SCHEMA)
    _write_parquet(landscape_path, landscape, SUMMARY_SCHEMA)
    _write_parquet(frequency_path, frequency, FREQUENCY_SCHEMA)
    _strict_gate_read(gate_path)
    write_exclusive(cards_path, cast(dict[str, Any], result["evidence_cards"]))
    with report_path.open("x", encoding="utf-8") as handle:
        handle.write(_markdown(cast(dict[str, Any], result["evidence_cards"])))
    reconciliation = cast(dict[str, Any], result["reconciliation"])
    reconciliation["reconciliation_hash"] = canonical_hash(reconciliation)
    write_exclusive(reconciliation_path, reconciliation)
    if progress:
        progress({"phase": "EVIDENCE_CARDS", "processed_units": 4, "total_units": 4})
    return {
        "gate_rows": len(gates),
        "parameter_landscape_rows": len(landscape),
        "frequency_waiting_rows": len(frequency),
        "evidence_cards": result["evidence_cards"],
        "reconciliation_hash": reconciliation["reconciliation_hash"],
    }


def format_smoke(
    *,
    policy: EvidenceGatePolicy,
    sources: SourceBindings,
    repository_root: Path,
) -> dict[str, Any]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="era-s2p16-t19-smoke-") as raw:
        root = Path(raw)
        projection = _project_and_write(sources, root)
        output_hashes = {
            path.name: sha256_file(path)
            for path in sorted(root.iterdir())
            if path.is_file() and not path.name.startswith("._")
        }
    elapsed = max(time.monotonic() - started, 0.000001)
    payload: dict[str, Any] = {
        "schema_name": "s2p16-t19-format-smoke",
        "schema_version": "1.0",
        "status": "PASS",
        "task_id": "S2P16-T19",
        "code_commit": repository_commit(repository_root),
        "policy_hash": policy.policy_hash,
        "source_t11_receipt_hash": sources.t11.receipt_hash,
        "source_t16_verify_hash": sources.upstreams.t16.verify_hash,
        "source_t17_verify_hash": sources.upstreams.t17.verify_hash,
        "source_t18_verify_hash": sources.t18.verify_hash,
        "projection": projection,
        "output_hashes": output_hashes,
        "elapsed_seconds": f"{elapsed:.6f}",
        "bytes_read": sources.t11.output_path.stat().st_size,
        "rows_per_second": f"{21_942 / elapsed:.6f}",
        "rss_bytes": _rss_bytes(),
        "cache_hits": 0,
        "cache_misses": 1,
        "formal_objects_created": False,
    }
    payload["format_smoke_hash"] = canonical_hash(payload)
    receipt = policy.operations_root / "format-smokes" / f"{payload['format_smoke_hash']}.json"
    if receipt.exists():
        if read_json(receipt) != payload:
            raise ValueError("T19 format-smoke receipt collision")
    else:
        write_exclusive(receipt, payload)
    return payload


def _catalog(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(root.iterdir()):
        if (
            not path.is_file()
            or path.name.startswith("._")
            or path.name in {"catalog.json", "manifest.json"}
        ):
            continue
        entry: dict[str, Any] = {
            "relative_path": path.name,
            "byte_size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        if path.suffix == ".parquet":
            entry["row_count"] = pq.ParquetFile(path).metadata.num_rows
        files.append(entry)
    payload: dict[str, Any] = {
        "schema_name": "s2p16-t19-catalog",
        "schema_version": "1.0",
        "files": files,
    }
    payload["catalog_hash"] = canonical_hash(payload)
    return payload


def verify_run(run_root: Path) -> dict[str, Any]:
    contract = read_json(run_root / "run-contract.json")
    published = run_root / "published"
    catalog = read_json(published / "catalog.json")
    manifest = read_json(published / "manifest.json")
    if catalog.get("catalog_hash") != canonical_hash(
        {key: value for key, value in catalog.items() if key != "catalog_hash"}
    ) or manifest.get("manifest_hash") != canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    ):
        raise ValueError("T19 published self Hash drift")
    for entry in cast(list[dict[str, Any]], catalog["files"]):
        path = published / str(entry["relative_path"])
        if sha256_file(path) != entry["sha256"] or path.stat().st_size != entry["byte_size"]:
            raise ValueError("T19 Catalog file drift")
        if (
            path.suffix == ".parquet"
            and pq.ParquetFile(path).metadata.num_rows != entry["row_count"]
        ):
            raise ValueError("T19 Catalog row-count drift")
    gates = _strict_gate_read(published / "gate-results.parquet")
    landscape_rows = pq.ParquetFile(published / "parameter-landscape.parquet").metadata.num_rows
    frequency_rows = pq.ParquetFile(published / "frequency-waiting.parquet").metadata.num_rows
    reconciliation = read_json(published / "reconciliation.json")
    if (
        len(gates) != 28
        or landscape_rows != 3_420
        or reconciliation.get("status") != "PASS"
        or reconciliation.get("gate_rows") != len(gates)
        or reconciliation.get("parameter_landscape_rows") != landscape_rows
        or reconciliation.get("frequency_waiting_rows") != frequency_rows
        or reconciliation.get("reconciliation_hash")
        != canonical_hash(
            {key: value for key, value in reconciliation.items() if key != "reconciliation_hash"}
        )
    ):
        raise ValueError("T19 reconciliation drift")
    payload: dict[str, Any] = {
        "schema_name": "s2p16-t19-verify-record",
        "schema_version": "1.0",
        "status": "PASS",
        "run_id": contract["run_id"],
        "authority_hash": contract["authority_hash"],
        "catalog_hash": catalog["catalog_hash"],
        "manifest_hash": manifest["manifest_hash"],
        "gate_rows": len(gates),
        "parameter_landscape_rows": landscape_rows,
        "frequency_waiting_rows": frequency_rows,
        "research_status": "EVIDENCE_SYNTHESIS_COMPLETE_FINAL_HUMAN_GATE_PENDING",
        "stage3_locked": True,
    }
    payload["verify_hash"] = canonical_hash(payload)
    verify_path = run_root / "verify" / f"{payload['verify_hash']}.json"
    if not verify_path.exists():
        write_exclusive(verify_path, payload)
    return payload


def run_formal(
    *,
    policy: EvidenceGatePolicy,
    approval_path: Path,
    repository_root: Path,
    resume_run_root: Path | None = None,
) -> dict[str, Any]:
    if not repository_clean(repository_root):
        raise ValueError("formal T19 Run requires a clean repository")
    sources = audit_sources(policy, repository_root=repository_root, full_hash_scan=True)
    approval = validate_approval(approval_path, policy=policy, repository_root=repository_root)
    smoke = read_json(
        policy.operations_root / "format-smokes" / f"{approval['format_smoke_hash']}.json"
    )
    if (
        smoke.get("status") != "PASS"
        or smoke.get("code_commit") != repository_commit(repository_root)
        or smoke.get("policy_hash") != policy.policy_hash
    ):
        raise ValueError("formal T19 Run requires current passing format smoke")
    lock_path = policy.operations_root / "run.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("another T19 Run holds the unique lock") from error
        runs = tuple(
            sorted(
                path
                for path in (policy.evidence_root / "runs").glob("stage2-s2p16-t19-*")
                if path.is_dir() and not path.is_symlink()
            )
        )
        if resume_run_root is None:
            if runs:
                raise ValueError("T19 formal Run already exists; successor approval required")
            authority = freeze_authority(
                policy=policy,
                approval=approval,
                sources=sources,
                repository_root=repository_root,
            )
            run_id = (
                f"stage2-s2p16-t19-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
                f"{authority.authority_hash[:12]}"
            )
            run_root = policy.evidence_root / "runs" / run_id
            run_root.mkdir(parents=True, exist_ok=False)
            contract: dict[str, Any] = {
                "schema_name": "s2p16-t19-run-contract",
                "schema_version": "1.0",
                "run_id": run_id,
                "authority_hash": authority.authority_hash,
                "code_commit": repository_commit(repository_root),
                "policy_hash": policy.policy_hash,
                "status": "UNPUBLISHED",
            }
            contract["run_contract_hash"] = canonical_hash(contract)
            write_exclusive(run_root / "run-contract.json", contract)
        else:
            run_root = resume_run_root
            if len(runs) != 1 or runs[0].resolve() != run_root.resolve():
                raise ValueError("T19 resume Run identity drift")
            contract = read_json(run_root / "run-contract.json")
            run_id = str(contract["run_id"])
            authority_path = (
                policy.evidence_root
                / "authorities"
                / f"authority-{contract['authority_hash']}.json"
            )
            authority = S2P16T19Authority.model_validate_json(
                authority_path.read_bytes(), strict=True
            )
            if authority.approval_hash != approval[
                "approval_hash"
            ] or authority.code_commit != repository_commit(repository_root):
                raise ValueError("T19 resume Authority drift")
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
                    "schema_name": "s2p16-t19-checkpoint",
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
        progress({"phase": "PUBLISH", "processed_units": 1, "total_units": 2})
        catalog = _catalog(work)
        write_exclusive(work / "catalog.json", catalog)
        manifest: dict[str, Any] = {
            "schema_name": "s2p16-t19-manifest",
            "schema_version": "1.0",
            "run_id": run_id,
            "authority_hash": authority.authority_hash,
            "catalog_hash": catalog["catalog_hash"],
            "reconciliation_hash": projection["reconciliation_hash"],
            "source_t11_receipt_hash": sources.t11.receipt_hash,
            "source_t16_verify_hash": sources.upstreams.t16.verify_hash,
            "source_t17_verify_hash": sources.upstreams.t17.verify_hash,
            "source_t18_verify_hash": sources.t18.verify_hash,
            "research_status": "EVIDENCE_SYNTHESIS_COMPLETE_FINAL_HUMAN_GATE_PENDING",
            "stage3_locked": True,
        }
        manifest["manifest_hash"] = canonical_hash(manifest)
        write_exclusive(work / "manifest.json", manifest)
        published = run_root / "published"
        os.replace(work, published)
        progress({"phase": "VERIFY", "processed_units": 2, "total_units": 2})
        verify = verify_run(run_root)
        _atomic_checkpoint(
            checkpoint,
            {
                "schema_name": "s2p16-t19-checkpoint",
                "schema_version": "1.0",
                "run_id": run_id,
                "status": "PASS",
                "phase": "VERIFY",
                "processed_units": 2,
                "total_units": 2,
                "percent": "100.000000",
                "elapsed_seconds": f"{time.monotonic() - started:.6f}",
                "heartbeat_at": datetime.now(UTC).isoformat(),
                "verify_hash": verify["verify_hash"],
            },
        )
        return verify


def resume_formal(
    *,
    policy: EvidenceGatePolicy,
    approval_path: Path,
    repository_root: Path,
) -> dict[str, Any]:
    runs = tuple(
        sorted(
            path
            for path in (policy.evidence_root / "runs").glob("stage2-s2p16-t19-*")
            if path.is_dir() and not path.is_symlink()
        )
    )
    if len(runs) != 1:
        raise ValueError("T19 resume requires exactly one formal Run")
    return run_formal(
        policy=policy,
        approval_path=approval_path,
        repository_root=repository_root,
        resume_run_root=runs[0],
    )
