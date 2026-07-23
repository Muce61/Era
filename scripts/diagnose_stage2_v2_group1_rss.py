#!/usr/bin/env python3
"""DIAGNOSTIC_ONLY: isolate Group-1 streaming RSS and Run-A parity.

This command is not imported by ``run_stage2_research.py`` and cannot create a
Stage 2 run, Execution Manifest, Catalog publication, or published directory.
Use ``prep`` in one process, then ``measure`` in a fresh process so source
aggregation memory is excluded from the measured high-water RSS.

Cleanup is intentionally manual.  ``paths`` prints the exact diagnostic-only
directories that may be removed after evidence review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import polars as pl
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.pipelines.candidates.io import records_logical_hash
from era100x.research.stage_2.runtime_v2.dataset_specs import (
    group1_dataset_binding,
)
from era100x.research.stage_2.runtime_v2.foundation_build import (
    aggregate_price_bars,
    aggregate_trade_seconds,
    normalize_contract_price_day,
    sha256_file,
)
from era100x.research.stage_2.runtime_v2.group1_feature_builder import Group1Lineage
from era100x.research.stage_2.runtime_v2.group1_pipeline import (
    GROUP1_BINDINGS,
    FoundationFeatureWindow,
    Group1PipelineConfig,
    _MonthlyBindingWriter,
    _stream_owner_day_to_writers,
)
from era100x.research.stage_2.runtime_v2.models import MAX_PROCESS_RSS_BYTES
from era100x.research.stage_2.runtime_v2.memory import ProcessMemoryBudget

Instrument = Literal["BTCUSDT", "ETHUSDT"]

DEFAULT_INPUT_ROOT = Path("/tmp/stage2-v2-rss-input")
DEFAULT_WORK_ROOT = Path("/tmp/stage2-v2-rss-output")
DEFAULT_CONTRACT_ROOT = Path("/Users/muce/1m_data/klines_data_usdm_1s_agg")
DEFAULT_STAGE1_CATALOG_ROOT = Path(
    "/Volumes/FuckingLife/era100x_stage1/catalog/runs/"
    "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
)
DEFAULT_STAGE1_PUBLISHED_ROOT = Path(
    "/Volumes/FuckingLife/era100x_stage1/published/stage1-trades-v2/"
    "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
)
DEFAULT_RUN_A_ROOT = Path(
    "/Volumes/FuckingLife/era100x_stage2/runs/"
    "stage2-g1-full-a-20260716T144233Z-366a541b7956/staging/data"
)
STAGE1_DATA_RUN_ID = "stage1-v1.0-20260714T090941Z-9676d50ae686-c70e5682"
CONFIG_HASH = "adb6295e210de66d1e69aa008e6161e8fef1e1fd72001ff812b68597f8c72e3f"
GENERATOR_COMMIT = "366a541b7956030d1a0ea2b5c67b4b30e2154c76"
INSTRUMENT_LOGICAL_HASHES: dict[Instrument, str] = {
    "BTCUSDT": "03d437ed9a6c19d92162e5c9dd115df4988e8accce3c8180b749f15cfdcc36a8",
    "ETHUSDT": "6db4d5e411edae3838b352944b83c38ba68915841a1f9c9de8f16ef44c3b8332",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="DIAGNOSTIC_ONLY two-process Group-1 streaming RSS harness"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("prep", "measure", "paths"):
        command = subparsers.add_parser(name)
        command.add_argument("--instrument", required=True, choices=("BTCUSDT", "ETHUSDT"))
        command.add_argument("--owner-date", required=True, type=date.fromisoformat)
        command.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
        command.add_argument("--work-root", type=Path, default=DEFAULT_WORK_ROOT)
        command.add_argument("--run-a-root", type=Path, default=DEFAULT_RUN_A_ROOT)
        if name in {"measure", "paths"}:
            command.add_argument("--label", default="attempt-1")
        if name == "prep":
            command.add_argument("--contract-root", type=Path, default=DEFAULT_CONTRACT_ROOT)
            command.add_argument(
                "--stage1-catalog-root", type=Path, default=DEFAULT_STAGE1_CATALOG_ROOT
            )
            command.add_argument(
                "--stage1-published-root", type=Path, default=DEFAULT_STAGE1_PUBLISHED_ROOT
            )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    instrument = cast(Instrument, args.instrument)
    if args.command == "prep":
        payload = _prep(args, instrument)
    elif args.command == "measure":
        payload = _measure(args, instrument)
    else:
        payload = _paths(args, instrument)
    print(json.dumps(payload, sort_keys=True, indent=2))
    return 0


def _prep(args: argparse.Namespace, instrument: Instrument) -> dict[str, Any]:
    target = _input_target(args.input_root, instrument, args.owner_date)
    if target.exists():
        raise FileExistsError(f"diagnostic input is append-only: {target}")
    target.mkdir(parents=True)

    price_tables: list[pa.Table] = []
    bar_tables: list[pa.Table] = []
    source_prices: list[dict[str, Any]] = []
    for offset in range(-2, 2):
        current = args.owner_date + timedelta(days=offset)
        source = (
            args.contract_root
            / f"{instrument}_1s_agg"
            / f"{instrument}_1s_{current.strftime('%Y%m%d')}.csv"
        )
        if not source.is_file():
            raise FileNotFoundError(source)
        prices = normalize_contract_price_day(path=source, instrument=instrument)
        price_tables.append(prices)
        if current <= args.owner_date:
            bar_tables.append(aggregate_price_bars(prices))
        source_prices.append(
            {
                "date": current.isoformat(),
                "path": str(source.resolve()),
                "sha256": sha256_file(source),
                "rows": prices.num_rows,
            }
        )

    catalog = json.loads((args.stage1_catalog_root / f"{instrument}.catalog.json").read_bytes())
    entries = {str(item["date"]): item for item in catalog["entries"]}
    trade_tables: list[pa.Table] = []
    source_trades: list[dict[str, Any]] = []
    for offset in (-1, 0):
        current = args.owner_date + timedelta(days=offset)
        entry = entries[current.isoformat()]
        source = (
            args.stage1_published_root
            / instrument
            / f"archive={current.strftime('%Y-%m')}"
            / f"date={current.isoformat()}"
            / "part-000.parquet"
        ).resolve()
        if not source.is_file() or sha256_file(source) != entry["byte_sha256"]:
            raise ValueError(f"frozen Stage 1 source mismatch: {source}")
        trade_tables.append(
            aggregate_trade_seconds(
                path=source,
                instrument=instrument,
                source_logical_hash=str(entry["logical_sha256"]),
                expected_source_rows=int(entry["rows"]),
            )
        )
        source_trades.append(
            {
                "date": current.isoformat(),
                "path": str(source),
                "sha256": entry["byte_sha256"],
                "logical_sha256": entry["logical_sha256"],
                "rows": entry["rows"],
            }
        )

    tables = {
        "contract_price_1s": pa.concat_tables(price_tables).combine_chunks(),
        "causal_price_bars": pa.concat_tables(bar_tables).combine_chunks(),
        "trade_second_primitives": pa.concat_tables(trade_tables).combine_chunks(),
    }
    outputs: dict[str, dict[str, Any]] = {}
    for name, table in tables.items():
        path = target / f"{name}.parquet"
        pq.write_table(table, path, compression="zstd", row_group_size=262_144)
        outputs[name] = {
            "path": path.name,
            "rows": table.num_rows,
            "arrow_bytes": table.nbytes,
            "sha256": sha256_file(path),
        }
    payload = {
        "schema_name": "stage2-v2-group1-rss-input-v1",
        "diagnostic_only": True,
        "instrument": instrument,
        "owner_date": args.owner_date.isoformat(),
        "stage1_data_run_id": STAGE1_DATA_RUN_ID,
        "instrument_logical_hash": INSTRUMENT_LOGICAL_HASHES[instrument],
        "config_hash": CONFIG_HASH,
        "generator_commit": GENERATOR_COMMIT,
        "source_contract_prices": source_prices,
        "source_stage1_trades": source_trades,
        "outputs": outputs,
    }
    payload["input_manifest_sha256"] = _semantic_hash(payload)
    (target / "input-manifest.json").write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def _measure(args: argparse.Namespace, instrument: Instrument) -> dict[str, Any]:
    input_target = _input_target(args.input_root, instrument, args.owner_date)
    manifest = json.loads((input_target / "input-manifest.json").read_bytes())
    claimed = manifest.pop("input_manifest_sha256")
    if claimed != _semantic_hash(manifest):
        raise ValueError("diagnostic input Manifest changed")
    if (
        manifest["instrument"] != instrument
        or manifest["owner_date"] != args.owner_date.isoformat()
    ):
        raise ValueError("diagnostic input scope mismatch")
    tables: dict[str, pa.Table] = {}
    for name, evidence in manifest["outputs"].items():
        path = input_target / evidence["path"]
        if sha256_file(path) != evidence["sha256"]:
            raise ValueError(f"diagnostic input changed: {name}")
        tables[name] = pq.read_table(path).combine_chunks()

    diagnostic_root = _work_target(args.work_root, instrument, args.owner_date, args.label)
    if diagnostic_root.exists():
        raise FileExistsError(f"diagnostic measurement is append-only: {diagnostic_root}")
    external = diagnostic_root / "external"
    run_root = external / "group1-measurement"
    foundation_root = run_root / "staging" / "snapshot"
    foundation_root.mkdir(parents=True)
    config = Group1PipelineConfig(
        run_root=run_root,
        foundation_catalog_root=foundation_root,
        approved_external_root=external,
    )
    window = FoundationFeatureWindow(
        instrument=instrument,
        owner_start=args.owner_date,
        owner_end_exclusive=args.owner_date + timedelta(days=1),
        contract_price_1s=tables["contract_price_1s"],
        causal_price_bars=tables["causal_price_bars"],
        trade_second_primitives=tables["trade_second_primitives"],
        trade_source_day_status={
            args.owner_date - timedelta(days=1): "COMPLETE",
            args.owner_date: "COMPLETE",
        },
        foundation_authority_members=tuple(
            sorted(str(item["sha256"]) for item in manifest["outputs"].values())
        ),
        max_inflight_bytes_observed=sum(table.nbytes for table in tables.values()),
    )
    lineage = Group1Lineage(
        data_run_id=STAGE1_DATA_RUN_ID,
        dataset_logical_hash=INSTRUMENT_LOGICAL_HASHES[instrument],
        config_hash=CONFIG_HASH,
        code_version=GENERATOR_COMMIT,
    )
    writers = {
        (variant, dataset): _MonthlyBindingWriter(
            config=config,
            snapshot_id=claimed,
            instrument=instrument,
            binding=group1_dataset_binding(variant, dataset),
            utc_month=args.owner_date.strftime("%Y-%m"),
            owner_start=args.owner_date,
            owner_end_exclusive=args.owner_date + timedelta(days=1),
        )
        for variant, dataset in GROUP1_BINDINGS
    }
    distributions: Counter[tuple[str, str]] = Counter()
    memory_budget = ProcessMemoryBudget()
    with ThreadPoolExecutor(max_workers=3) as pool:
        max_arrow, measured_inside = _stream_owner_day_to_writers(
            config=config,
            snapshot_id=claimed,
            instrument=instrument,
            owner_date=args.owner_date,
            window=window,
            lineage=lineage,
            writers=writers,
            distributions=distributions,
            compute_pool=pool,
            memory_budget=memory_budget,
        )
    seals = {key: writer.finalize() for key, writer in sorted(writers.items())}
    peak_rss = _peak_rss_bytes()
    parity = _run_a_parity(
        run_a_root=args.run_a_root,
        instrument=instrument,
        owner_date=args.owner_date,
        seals=seals,
    )
    payload = {
        "schema_name": "stage2-v2-group1-streaming-rss-evidence-v1",
        "diagnostic_only": True,
        "instrument": instrument,
        "owner_date": args.owner_date.isoformat(),
        "input_manifest_sha256": claimed,
        "stage1_data_run_id": STAGE1_DATA_RUN_ID,
        "instrument_logical_hash": INSTRUMENT_LOGICAL_HASHES[instrument],
        "config_hash": CONFIG_HASH,
        "generator_commit": GENERATOR_COMMIT,
        "diagnostic_code_hashes": _diagnostic_code_hashes(),
        "max_arrow_bytes_observed": max_arrow,
        "rss_inside_stream_bytes": measured_inside,
        "peak_process_rss_bytes": peak_rss,
        "rss_hard_limit_bytes": MAX_PROCESS_RSS_BYTES,
        "rss_gate_pass": peak_rss <= MAX_PROCESS_RSS_BYTES,
        "run_a_all_thirteen_pass": all(item["matches"] for item in parity),
        "parity": parity,
    }
    payload["evidence_sha256"] = _semantic_hash(payload)
    report = _report_path(args.work_root, instrument, args.owner_date, args.label)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    payload["resource_anomaly_status"] = (
        "NONE" if payload["rss_gate_pass"] else "RSS_THRESHOLD_EXCEEDED"
    )
    if not payload["run_a_all_thirteen_pass"]:
        raise RuntimeError(f"Group-1 streaming diagnostic failed; evidence={report}")
    return payload


def _run_a_parity(
    *,
    run_a_root: Path,
    instrument: Instrument,
    owner_date: date,
    seals: dict[tuple[str, str], Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for variant, dataset in GROUP1_BINDINGS:
        source = (
            run_a_root
            / f"instrument={instrument}"
            / f"variant={variant}"
            / dataset
            / f"date={owner_date.isoformat()}"
            / "part-000.parquet"
        )
        frame = pl.read_parquet(source)
        records = [] if "empty_partition" in frame.columns else frame.to_dicts()
        expected_hash = records_logical_hash(records, dataset)
        binding = group1_dataset_binding(variant, dataset)
        expected_ids = (
            None
            if binding.legacy_id_field is None or not records
            else hashlib.sha256(
                "\n".join(sorted({str(item[binding.legacy_id_field]) for item in records})).encode(
                    "utf-8"
                )
            ).hexdigest()
        )
        receipt = seals[(variant, dataset)].receipts[0]
        facts = {item.name: item.value for item in receipt.quality_facts}
        actual_ids = facts.get("legacy_id_set_sha256")
        matches = (
            receipt.row_count == len(records)
            and receipt.legacy_logical_sha256 == expected_hash
            and actual_ids == expected_ids
        )
        result.append(
            {
                "variant": variant,
                "dataset": dataset,
                "row_count": receipt.row_count,
                "legacy_logical_sha256": receipt.legacy_logical_sha256,
                "legacy_id_set_sha256": actual_ids,
                "matches": matches,
            }
        )
    return result


def _paths(args: argparse.Namespace, instrument: Instrument) -> dict[str, Any]:
    return {
        "diagnostic_only": True,
        "input": str(_input_target(args.input_root, instrument, args.owner_date)),
        "work": str(_work_target(args.work_root, instrument, args.owner_date, args.label)),
        "report": str(_report_path(args.work_root, instrument, args.owner_date, args.label)),
        "cleanup_policy": "manual deletion only after evidence review",
    }


def _input_target(root: Path, instrument: Instrument, owner_date: date) -> Path:
    return root / instrument / owner_date.isoformat()


def _work_target(root: Path, instrument: Instrument, owner_date: date, label: str) -> Path:
    if not label or "/" in label or label in {".", ".."}:
        raise ValueError("diagnostic label must be one safe path component")
    return root / instrument / owner_date.isoformat() / label / "streaming-child"


def _report_path(root: Path, instrument: Instrument, owner_date: date, label: str) -> Path:
    return _work_target(root, instrument, owner_date, label).parent / "rss-evidence.json"


def _semantic_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _diagnostic_code_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    paths = (
        Path(__file__).resolve(),
        root / "src/era100x/research/stage_2/runtime_v2/group1_pipeline.py",
        root / "src/era100x/research/stage_2/runtime_v2/group1_adapter.py",
        root / "src/era100x/research/stage_2/runtime_v2/group1_feature_builder.py",
        root / "src/era100x/research/stage_2/runtime_v2/models.py",
        root / "src/era100x/research/stage_2/pipelines/candidates/io.py",
    )
    return {path.relative_to(root).as_posix(): sha256_file(path) for path in paths}


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


if __name__ == "__main__":
    raise SystemExit(main())
