"""Read only H2 windows authorized by completed outcome-blind T15 matching."""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left
from collections import OrderedDict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from era100x.research.stage_2.paths.extraction.full_run import (
    STAGE1_CATALOG_ROOT,
    STAGE1_PUBLISHED_ROOT,
    H2RowGroup,
    _h2_row_groups,
    _safe_relative,
    _stage1_quality,
    select_h2_row_groups,
)
from era100x.research.stage_2.metrics.path.full_run import CONFIG_PATH as RECOVERY_CONFIG_PATH
from era100x.research.stage_2.runtime_v2.catalog import CatalogReaderV2

from era100x.research.stage_2.paths.extraction.models import PathGap

from .outcomes import H2_COVERAGE_CONTRACT_ID, H2Trade, detect_h2_window_gaps
from .v14_contracts import canonical_hash


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_date(timestamp_ns: int) -> date:
    return datetime.fromtimestamp(timestamp_ns / 1_000_000_000, UTC).date()


def _days(start_ns: int, end_ns: int) -> tuple[date, ...]:
    current = _utc_date(start_ns)
    last = _utc_date(end_ns - 1)
    values: list[date] = []
    while current <= last:
        values.append(current)
        current += timedelta(days=1)
    return tuple(values)


class H2ControlReader:
    """Fail-closed Stage1 reader that never substitutes another control."""

    def __init__(self, *, t10_snapshot: Path, t10_snapshot_id: str) -> None:
        catalog = CatalogReaderV2.open(t10_snapshot, expected_snapshot_id=t10_snapshot_id)
        self._groups = _h2_row_groups(catalog)
        self._quality = _stage1_quality(STAGE1_CATALOG_ROOT)
        config = cast(dict[str, Any], json.loads(RECOVERY_CONFIG_PATH.read_bytes()))
        self._overlays = {
            str(item["source_relative_path"]): cast(dict[str, Any], item)
            for item in config.get("read_only_recovery_overlays", [])
        }
        self._verified: set[str] = set()
        self._cache: OrderedDict[tuple[str, int], list[dict[str, Any]]] = OrderedDict()

    def _group_rows(self, group: H2RowGroup) -> list[dict[str, Any]]:
        key = (group.source_relative_path, group.ordinal)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        overlay = self._overlays.get(group.source_relative_path)
        path = (
            _safe_relative(STAGE1_PUBLISHED_ROOT, group.source_relative_path)
            if overlay is None
            else Path(str(overlay["overlay_path"]))
        )
        expected_hash = (
            group.source_byte_sha256 if overlay is None else str(overlay["overlay_sha256"])
        )
        if path.is_symlink() or not path.is_file():
            raise ValueError("unsafe or missing H2 control source")
        identity = f"{path}|{expected_hash}"
        if identity not in self._verified:
            if _sha256_file(path) != expected_hash:
                raise ValueError("H2 control source byte hash drift")
            self._verified.add(identity)
        table = pq.ParquetFile(path).read_row_group(
            group.ordinal,
            columns=["ts_event_ns", "venue_trade_id", "canonical_trade_id", "price"],
        )
        expected = table.sort_by(
            [
                ("ts_event_ns", "ascending"),
                ("venue_trade_id", "ascending"),
                ("canonical_trade_id", "ascending"),
            ]
        )
        if not table.equals(expected):
            raise ValueError("H2 control row group violates frozen stable order")
        rows = cast(list[dict[str, Any]], table.to_pylist())
        self._cache[key] = rows
        while len(self._cache) > 8:
            self._cache.popitem(last=False)
        return rows

    def read_window(
        self, *, instrument: str, start_ns: int, end_ns: int
    ) -> tuple[tuple[H2Trade, ...], tuple[PathGap, ...], str]:
        if end_ns <= start_ns:
            raise ValueError("H2 control window must be non-empty")
        selected: list[H2RowGroup] = []
        for owner_date in _days(start_ns, end_ns):
            quality = self._quality.get((cast(Any, instrument), owner_date))
            if quality is None:
                raise ValueError("UPSTREAM_SOURCE_PARTITION_UNBOUND")
            day_groups = self._groups.get((cast(Any, instrument), owner_date), ())
            selected.extend(select_h2_row_groups(day_groups, start_ns, end_ns))
        facts: list[H2Trade] = []
        bindings: list[dict[str, Any]] = []
        for group in selected:
            rows = self._group_rows(group)
            timestamps = [int(row["ts_event_ns"]) for row in rows]
            first = bisect_left(timestamps, start_ns)
            last = bisect_left(timestamps, end_ns)
            facts.extend(
                H2Trade(
                    ts_event_ns=int(row["ts_event_ns"]),
                    venue_trade_id=int(row["venue_trade_id"]),
                    canonical_trade_id=str(row["canonical_trade_id"]),
                    price=row["price"],
                )
                for row in rows[first:last]
            )
            bindings.append(
                {
                    "relative_path": group.source_relative_path,
                    "source_byte_sha256": group.source_byte_sha256,
                    "source_logical_sha256": group.source_logical_sha256,
                    "row_group_ordinal": group.ordinal,
                }
            )
        ordered = sorted(
            facts,
            key=lambda row: (row.ts_event_ns, row.venue_trade_id, row.canonical_trade_id),
        )
        if facts != ordered:
            raise ValueError("cross-row-group H2 control order drift")
        gaps = detect_h2_window_gaps(ordered)
        source_path_hash = canonical_hash(
            {
                "instrument": instrument,
                "start_ns": start_ns,
                "end_ns": end_ns,
                "bindings": bindings,
                "coverage_contract_id": H2_COVERAGE_CONTRACT_ID,
                "gaps": [gap.model_dump(mode="json") for gap in gaps],
            }
        )
        return tuple(facts), gaps, source_path_hash
