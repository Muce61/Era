"""TRAIN-only feature preparation and append-only quintile freezing for T15."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from .features import NS, PERIOD_BLOCK_BOUNDARIES, ROLLING_FOLDS, freeze_tie_preserving_quintiles
from .production_core import prepare_daily_features
from .t10_access import FixedT10Reader, read_json_file
from .v14_contracts import (
    REGISTERED_PARAMETER_TIMING_PAIRS,
    S2T15ContractAuthority,
    canonical_hash,
)

DECIMAL_TYPE = pa.decimal128(38, 18)


def _safe_parameter_column(parameter_set_id: str) -> str:
    return f"distance_bps__{parameter_set_id}"


def _feature_schema(parameter_set_ids: tuple[str, ...]) -> pa.Schema:
    fields = [
        pa.field("instrument", pa.string(), nullable=False),
        pa.field("anchor_ns", pa.int64(), nullable=False),
        pa.field("reference_price", DECIMAL_TYPE, nullable=True),
        pa.field("volatility_rms_bps", DECIMAL_TYPE, nullable=True),
        pa.field("activity_count_60s", pa.int64(), nullable=True),
        pa.field("high_timeframe_trend_state", pa.string(), nullable=True),
        pa.field("market_exclusion_reason", pa.string(), nullable=True),
    ]
    fields.extend(
        pa.field(_safe_parameter_column(parameter), DECIMAL_TYPE, nullable=True)
        for parameter in parameter_set_ids
    )
    return pa.schema(fields)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    try:
        with path.open("xb") as handle:
            handle.write(encoded)
    except FileExistsError:
        if path.is_symlink() or path.read_bytes() != encoded:
            raise ValueError(f"append-only binning evidence conflict: {path}") from None


def _date_from_ns(value: int) -> date:
    return datetime.fromtimestamp(value / NS, UTC).date()


def _block_dates(period: str, block_index: int) -> tuple[date, ...]:
    boundaries = PERIOD_BLOCK_BOUNDARIES[cast(Any, period)]
    start = _date_from_ns(boundaries[block_index])
    end = _date_from_ns(boundaries[block_index + 1])
    return tuple(start + timedelta(days=index) for index in range((end - start).days))


def _block_path(root: Path, instrument: str, period: str, block_index: int) -> Path:
    return root / "prepared" / instrument / period / f"B{block_index}.parquet"


def _block_report_path(path: Path) -> Path:
    return path.with_suffix(".report.json")


def _validate_existing_block(path: Path, *, authority_hash: str) -> dict[str, Any] | None:
    report_path = _block_report_path(path)
    if not path.exists() and not report_path.exists():
        return None
    if path.is_symlink() or report_path.is_symlink() or not path.is_file():
        raise ValueError("unsafe or incomplete prepared TRAIN block")
    report = read_json_file(report_path)
    if report.get("authority_hash") != authority_hash:
        raise ValueError("prepared TRAIN block belongs to another Authority")
    if report.get("parquet_sha256") != _sha256_file(path):
        raise ValueError("prepared TRAIN block byte hash drift")
    if pq.ParquetFile(path).metadata.num_rows != int(report["grid_anchor_count"]):
        raise ValueError("prepared TRAIN block row count drift")
    return report


def _prepare_block(
    *,
    reader: FixedT10Reader,
    root: Path,
    authority_hash: str,
    instrument: str,
    period: str,
    block_index: int,
    parameter_set_ids: tuple[str, ...],
) -> dict[str, Any]:
    path = _block_path(root, instrument, period, block_index)
    existing = _validate_existing_block(path, authority_hash=authority_hash)
    if existing is not None:
        return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
    if temporary.exists():
        temporary.unlink()
    schema = _feature_schema(parameter_set_ids)
    writer = pq.ParquetWriter(temporary, schema, compression="zstd")
    exclusion_counts: Counter[str] = Counter()
    distance_unavailable: Counter[str] = Counter()
    grid_anchor_count = 0
    valid_market_anchor_count = 0
    try:
        for owner_date in _block_dates(period, block_index):
            prepared = prepare_daily_features(
                reader,
                instrument=instrument,
                owner_date=owner_date,
                parameter_set_ids=parameter_set_ids,
            )
            grid_anchor_count += prepared.grid_anchor_count
            exclusion_counts.update(prepared.exclusion_counts)
            by_anchor = {feature.anchor_ns: feature for feature in prepared.valid_rows}
            rows: list[dict[str, Any]] = []
            for anchor in sorted((*by_anchor, *prepared.exclusion_by_anchor)):
                feature = by_anchor.get(anchor)
                row: dict[str, Any] = {
                    "instrument": instrument,
                    "anchor_ns": anchor,
                    "reference_price": feature.reference_price if feature is not None else None,
                    "volatility_rms_bps": (
                        feature.volatility_rms_bps if feature is not None else None
                    ),
                    "activity_count_60s": (
                        feature.activity_count_60s if feature is not None else None
                    ),
                    "high_timeframe_trend_state": (
                        feature.high_timeframe_trend_state if feature is not None else None
                    ),
                    "market_exclusion_reason": prepared.exclusion_by_anchor.get(anchor),
                }
                for parameter in parameter_set_ids:
                    value = (
                        feature.distance_bps_by_parameter.get(parameter)
                        if feature is not None
                        else None
                    )
                    row[_safe_parameter_column(parameter)] = value
                    if feature is not None and value is None:
                        distance_unavailable[parameter] += 1
                rows.append(row)
            if rows:
                writer.write_table(pa.Table.from_pylist(rows, schema=schema))
                valid_market_anchor_count += len(prepared.valid_rows)
    finally:
        writer.close()
    os.replace(temporary, path)
    payload: dict[str, Any] = {
        "schema_name": "stage2-s2t15-train-feature-block",
        "schema_version": "1.0",
        "authority_hash": authority_hash,
        "instrument": instrument,
        "period": period,
        "block": f"B{block_index}",
        "grid_anchor_count": grid_anchor_count,
        "valid_market_anchor_count": valid_market_anchor_count,
        "market_exclusion_counts": dict(sorted(exclusion_counts.items())),
        "distance_unavailable_by_parameter": dict(sorted(distance_unavailable.items())),
        "parquet_sha256": _sha256_file(path),
        "outcome_fields_read": [],
        "historical_evidence_only": True,
    }
    payload["report_hash"] = canonical_hash(payload)
    _write_json_exclusive(_block_report_path(path), payload)
    return payload


def prepare_feature_block(
    *,
    reader: FixedT10Reader,
    root: Path,
    authority_hash: str,
    instrument: str,
    period: str,
    block_index: int,
    parameter_set_ids: tuple[str, ...],
) -> dict[str, Any]:
    """Public resumable wrapper used for B4 after the unique Run ID exists."""

    return _prepare_block(
        reader=reader,
        root=root,
        authority_hash=authority_hash,
        instrument=instrument,
        period=period,
        block_index=block_index,
        parameter_set_ids=parameter_set_ids,
    )


def _boundary_values(
    paths: tuple[Path, ...],
    *,
    column: str,
    train_start_ns: int,
    train_end_ns: int,
) -> tuple[tuple[Decimal, ...], int]:
    values: list[Decimal] = []
    source_anchor_count = 0
    for path in paths:
        table = pq.read_table(path, columns=["anchor_ns", column])
        for anchor, value in zip(
            table["anchor_ns"].to_pylist(), table[column].to_pylist(), strict=True
        ):
            if train_start_ns + 3600 * NS <= int(anchor) and int(anchor) + 600 * NS <= train_end_ns:
                source_anchor_count += 1
                if value is not None:
                    values.append(Decimal(value))
    return tuple(values), source_anchor_count


def freeze_binning_snapshots(
    *,
    authority_path: Path,
    bin_root: Path,
    t10_snapshot: Path,
    t10_snapshot_id: str,
    current_commit: str,
    repository_clean: bool,
) -> tuple[dict[str, Any], Path]:
    """Prepare TRAIN blocks and freeze all 504 registered boundary objects."""

    authority = S2T15ContractAuthority.model_validate_json(
        json.dumps(read_json_file(authority_path), ensure_ascii=False, sort_keys=True)
    )
    if authority.authority_hash != authority.computed_hash():
        raise ValueError("Authority changed before TRAIN binning")
    if authority.code_commit != current_commit or not repository_clean:
        raise ValueError("TRAIN binning requires the clean Authority commit")
    if authority.registered_parameter_timing_pairs != REGISTERED_PARAMETER_TIMING_PAIRS:
        raise ValueError("Authority parameter/timing universe drift")
    parameter_set_ids = tuple(pair[0] for pair in REGISTERED_PARAMETER_TIMING_PAIRS)
    root = bin_root / authority.authority_hash
    reader = FixedT10Reader(t10_snapshot, expected_snapshot_id=t10_snapshot_id)
    block_reports: list[dict[str, Any]] = []
    for instrument in ("BTCUSDT", "ETHUSDT"):
        for period in ("P1", "P2", "P3"):
            for block_index in range(4):
                block_reports.append(
                    _prepare_block(
                        reader=reader,
                        root=root,
                        authority_hash=authority.authority_hash,
                        instrument=instrument,
                        period=period,
                        block_index=block_index,
                        parameter_set_ids=parameter_set_ids,
                    )
                )
    split_contract_hash = canonical_hash(
        [contract.model_dump(mode="json") for contract in ROLLING_FOLDS]
    )
    boundary_refs: list[dict[str, Any]] = []
    combined: dict[str, str] = {}
    for contract in ROLLING_FOLDS:
        for instrument in ("BTCUSDT", "ETHUSDT"):
            source_paths = tuple(
                _block_path(root, instrument, contract.period, index)
                for index in range(int(contract.fold[1]) + 1)
            )
            hashes = tuple(_sha256_file(path) for path in source_paths)
            market_boundaries: dict[str, str] = {}
            for feature_kind, column in (
                ("VOLATILITY", "volatility_rms_bps"),
                ("TRADES_ACTIVITY", "activity_count_60s"),
            ):
                values, source_anchor_count = _boundary_values(
                    source_paths,
                    column=column,
                    train_start_ns=contract.train_start_ns,
                    train_end_ns=contract.train_end_ns,
                )
                source_hash = canonical_hash(
                    {"blocks": hashes, "column": column, "split": split_contract_hash}
                )
                boundary = freeze_tie_preserving_quintiles(
                    values,
                    instrument=instrument,
                    period=contract.period,
                    fold=contract.fold,
                    feature_kind=feature_kind,
                    feature_source_hash=source_hash,
                    split_contract_hash=split_contract_hash,
                    source_anchor_count=source_anchor_count,
                )
                relative = (
                    Path("boundaries")
                    / instrument
                    / contract.period
                    / contract.fold
                    / (f"{feature_kind}.json")
                )
                _write_json_exclusive(root / relative, boundary.model_dump(mode="json"))
                boundary_refs.append(
                    {"path": str(relative), "boundary_hash": boundary.boundary_hash}
                )
                market_boundaries[feature_kind] = boundary.boundary_hash
            for parameter in parameter_set_ids:
                column = _safe_parameter_column(parameter)
                values, source_anchor_count = _boundary_values(
                    source_paths,
                    column=column,
                    train_start_ns=contract.train_start_ns,
                    train_end_ns=contract.train_end_ns,
                )
                source_hash = canonical_hash(
                    {"blocks": hashes, "column": column, "split": split_contract_hash}
                )
                boundary = freeze_tie_preserving_quintiles(
                    values,
                    instrument=instrument,
                    period=contract.period,
                    fold=contract.fold,
                    feature_kind="KEY_LEVEL_DISTANCE",
                    feature_source_hash=source_hash,
                    split_contract_hash=split_contract_hash,
                    source_anchor_count=source_anchor_count,
                    parameter_set_id=parameter,
                )
                relative = (
                    Path("boundaries")
                    / instrument
                    / contract.period
                    / contract.fold
                    / f"KEY_LEVEL_DISTANCE__{parameter}.json"
                )
                _write_json_exclusive(root / relative, boundary.model_dump(mode="json"))
                boundary_refs.append(
                    {"path": str(relative), "boundary_hash": boundary.boundary_hash}
                )
                key = f"{instrument}|{contract.period}|{contract.fold}|{parameter}"
                combined[key] = canonical_hash(
                    {
                        "volatility_boundary_hash": market_boundaries["VOLATILITY"],
                        "activity_boundary_hash": market_boundaries["TRADES_ACTIVITY"],
                        "distance_boundary_hash": boundary.boundary_hash,
                        "split_contract_hash": split_contract_hash,
                    }
                )
    if len(boundary_refs) != 504 or len(combined) != 456:
        raise ValueError("registered binning snapshot universe is incomplete")
    payload: dict[str, Any] = {
        "schema_name": "stage2-s2t15-binning-snapshot-set",
        "schema_version": "1.0",
        "authority_hash": authority.authority_hash,
        "code_commit": authority.code_commit,
        "status": "PASS",
        "split_contract_hash": split_contract_hash,
        "prepared_block_reports": [report["report_hash"] for report in block_reports],
        "boundaries": sorted(boundary_refs, key=lambda item: item["path"]),
        "combined_binning_snapshot_hashes": dict(sorted(combined.items())),
        "boundary_count": len(boundary_refs),
        "combined_snapshot_count": len(combined),
        "outcome_fields_read": [],
        "historical_evidence_only": True,
    }
    payload["binning_set_hash"] = canonical_hash(payload)
    manifest_path = root / f"binning-set-{payload['binning_set_hash']}.json"
    _write_json_exclusive(manifest_path, payload)
    return payload, manifest_path


def read_binning_set(path: Path, *, authority_hash: str | None = None) -> dict[str, Any]:
    payload = read_json_file(path)
    claimed = payload.get("binning_set_hash")
    computed = canonical_hash(
        {key: value for key, value in payload.items() if key != "binning_set_hash"}
    )
    if claimed != computed:
        raise ValueError("binning snapshot set hash mismatch")
    if authority_hash is not None and payload.get("authority_hash") != authority_hash:
        raise ValueError("binning snapshot set belongs to another Authority")
    if payload.get("status") != "PASS" or payload.get("boundary_count") != 504:
        raise ValueError("binning snapshot set is incomplete")
    root = path.parent
    for item in payload.get("boundaries", []):
        relative = Path(str(item["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe binning boundary path")
        boundary = read_json_file(root / relative)
        if boundary.get("boundary_hash") != item.get("boundary_hash"):
            raise ValueError("binning boundary reference drift")
    return payload
