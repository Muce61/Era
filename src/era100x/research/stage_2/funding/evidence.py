"""CR-2026-038 read-only funding acceptance and append-only evidence."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from era100x.foundation.governance import require_operation_allowed

INSTRUMENTS = ("BTCUSDT", "ETHUSDT")
SCHEMA_VERSION = "1.0"
OFFICIAL_BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"


class FundingEvidenceError(RuntimeError):
    """Fail-closed funding evidence error."""


@dataclass(frozen=True, order=True)
class FundingRow:
    instrument: str
    settlement_ts_ms: int
    funding_interval_hours: int
    funding_rate: Decimal


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_hash(value: dict[str, Any], field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_root(path: Path) -> None:
    if path.is_symlink():
        raise FundingEvidenceError(f"symlink path is forbidden: {path}")
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise FundingEvidenceError(f"unsafe evidence parent: {parent}")
    if path.exists():
        raise FundingEvidenceError(f"append-only evidence already exists: {path}")


def _parse_decimal(raw: str) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise FundingEvidenceError(f"invalid funding rate: {raw}") from exc
    if not value.is_finite():
        raise FundingEvidenceError(f"non-finite funding rate: {raw}")
    return value


def _parse_local(path: Path, instrument: str) -> list[FundingRow]:
    if not path.is_file() or path.is_symlink():
        raise FundingEvidenceError(f"local funding source missing or unsafe: {path}")
    rows: list[FundingRow] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if "funding_interval_hours" not in fields or not (
            {"last_funding_rate", "funding_rate"} & fields
        ):
            raise FundingEvidenceError(f"local funding schema invalid: {path}")
        for raw in reader:
            if "settlement_ts_ms" in raw:
                timestamp_ms = int(raw["settlement_ts_ms"])
            elif "calc_time" in raw:
                timestamp_ms = int(raw["calc_time"])
            else:
                parsed = datetime.strptime(raw["timestamp"], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=UTC
                )
                timestamp_ms = int(parsed.timestamp() * 1000)
            rows.append(
                FundingRow(
                    instrument=instrument,
                    settlement_ts_ms=timestamp_ms,
                    funding_interval_hours=int(raw["funding_interval_hours"]),
                    funding_rate=_parse_decimal(
                        raw.get("last_funding_rate") or raw["funding_rate"]
                    ),
                )
            )
    if len({row.settlement_ts_ms for row in rows}) != len(rows):
        raise FundingEvidenceError(f"duplicate local funding timestamp: {instrument}")
    return sorted(rows)


def _month_starts(start: date, end_exclusive: date) -> list[date]:
    current = start.replace(day=1)
    values: list[date] = []
    while current < end_exclusive:
        values.append(current)
        current = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )
    return values


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "era100x-cr-2026-038/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return cast(bytes, response.read())
    except OSError as exc:
        raise FundingEvidenceError(f"official archive download failed: {url}: {exc}") from exc


def _official_month(instrument: str, month: date) -> tuple[list[FundingRow], dict[str, Any]]:
    stem = f"{instrument}-fundingRate-{month:%Y-%m}.zip"
    url = f"{OFFICIAL_BASE}/{instrument}/{stem}"
    archive = _download(url)
    checksum_bytes = _download(f"{url}.CHECKSUM")
    checksum_text = checksum_bytes.decode("utf-8").strip()
    expected = checksum_text.split()[0] if checksum_text else ""
    actual = hashlib.sha256(archive).hexdigest()
    if expected != actual:
        raise FundingEvidenceError(f"official checksum mismatch: {stem}")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            members = [name for name in bundle.namelist() if name.endswith(".csv")]
            if len(members) != 1:
                raise FundingEvidenceError(f"official archive member count invalid: {stem}")
            text = bundle.read(members[0]).decode("utf-8")
    except (OSError, UnicodeError, zipfile.BadZipFile) as exc:
        raise FundingEvidenceError(f"official archive invalid: {stem}") from exc
    rows: list[FundingRow] = []
    for raw in csv.DictReader(io.StringIO(text)):
        rows.append(
            FundingRow(
                instrument=instrument,
                settlement_ts_ms=int(raw["calc_time"]),
                funding_interval_hours=int(raw["funding_interval_hours"]),
                funding_rate=_parse_decimal(raw["last_funding_rate"]),
            )
        )
    return rows, {
        "url": url,
        "checksum_url": f"{url}.CHECKSUM",
        "sha256": actual,
        "checksum_sha256": hashlib.sha256(checksum_bytes).hexdigest(),
        "row_count": len(rows),
    }


def _write_rows(path: Path, rows: list[FundingRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            ("instrument", "settlement_ts_ms", "funding_interval_hours", "funding_rate")
        )
        for row in rows:
            writer.writerow(
                (
                    row.instrument,
                    row.settlement_ts_ms,
                    row.funding_interval_hours,
                    format(row.funding_rate, "f"),
                )
            )


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json(value) + b"\n")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FundingEvidenceError(f"evidence file missing or unsafe: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise FundingEvidenceError(f"evidence object invalid: {path}")
    return value


def verify_funding_evidence(root: Path) -> dict[str, Any]:
    """Strictly read back and verify one append-only funding evidence directory."""

    if not root.is_dir() or root.is_symlink():
        raise FundingEvidenceError(f"evidence root missing or unsafe: {root}")
    manifest = _read_json(root / "manifest.json")
    catalog = _read_json(root / "catalog.json")
    checks: dict[str, bool] = {
        "manifest_self_hash": manifest.get("manifest_hash")
        == _json_hash(manifest, "manifest_hash"),
        "catalog_self_hash": catalog.get("catalog_hash") == _json_hash(catalog, "catalog_hash"),
        "catalog_bound": manifest.get("catalog_hash") == catalog.get("catalog_hash"),
        "stage3_locked": manifest.get("stage3_locked") is True,
        "no_lifecycle_run": manifest.get("lifecycle_run_created") is False,
    }
    total_rows = 0
    instruments = catalog.get("instruments")
    if not isinstance(instruments, dict):
        raise FundingEvidenceError("catalog instruments invalid")
    for instrument in INSTRUMENTS:
        entry = instruments.get(instrument)
        if not isinstance(entry, dict):
            raise FundingEvidenceError(f"catalog entry missing: {instrument}")
        relative = Path(str(entry.get("path")))
        path = root / relative
        safe_relative = (
            not relative.is_absolute()
            and ".." not in relative.parts
            and path.is_file()
            and not path.is_symlink()
        )
        checks[f"{instrument.lower()}_safe_path"] = safe_relative
        if not safe_relative:
            continue
        row_count = sum(1 for _ in path.open(encoding="utf-8")) - 1
        checks[f"{instrument.lower()}_sha256"] = _file_hash(path) == entry.get("sha256")
        checks[f"{instrument.lower()}_row_count"] = row_count == entry.get("row_count")
        checks[f"{instrument.lower()}_official_source"] = (
            entry.get("accepted_source") == "BINANCE_OFFICIAL_MONTHLY_ARCHIVE"
        )
        total_rows += row_count
    checks["total_rows"] = total_rows == catalog.get("total_row_count")
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "schema_name": "s2p13-funding-verify",
        "schema_version": SCHEMA_VERSION,
        "evidence_id": manifest.get("evidence_id"),
        "status": status,
        "checks": checks,
        "total_row_count": total_rows,
        "manifest_hash": manifest.get("manifest_hash"),
        "catalog_hash": catalog.get("catalog_hash"),
        "stage3_locked": True,
        "lifecycle_run_created": False,
    }


def _local_history_summary(path: Path, instrument: str) -> dict[str, Any]:
    rows = _parse_local(path, instrument)
    timestamps = [row.settlement_ts_ms for row in rows]
    gaps = sorted({right - left for left, right in zip(timestamps, timestamps[1:], strict=False)})
    return {
        "path": str(path),
        "sha256": _file_hash(path),
        "row_count": len(rows),
        "unique_timestamp_count": len(set(timestamps)),
        "start_ts_ms": timestamps[0] if timestamps else None,
        "end_ts_ms": timestamps[-1] if timestamps else None,
        "gap_ms_values": gaps,
        "funding_interval_hours": sorted({row.funding_interval_hours for row in rows}),
    }


def verify_funding_acceptance(root: Path) -> dict[str, Any]:
    """Verify the human decision accepting local history without monthly reconciliation."""

    evidence_verify = verify_funding_evidence(root)
    acceptance = _read_json(root / "acceptance.json")
    checks = {
        "evidence_verify_pass": evidence_verify.get("status") == "PASS",
        "acceptance_self_hash": acceptance.get("acceptance_hash")
        == _json_hash(acceptance, "acceptance_hash"),
        "human_accepted": acceptance.get("human_accepted") is True
        and acceptance.get("accepted_by") == "Muce",
        "monthly_reconciliation_waived": acceptance.get("monthly_official_reconciliation_required")
        is False,
        "historical_funding_bound": acceptance.get("historical_funding_bound") is True,
        "no_lifecycle_run": acceptance.get("lifecycle_run_created") is False,
        "stage3_locked": acceptance.get("stage3_locked") is True,
    }
    summaries = acceptance.get("local_history")
    if not isinstance(summaries, dict):
        raise FundingEvidenceError("funding acceptance local history invalid")
    for instrument in INSTRUMENTS:
        expected = summaries.get(instrument)
        if not isinstance(expected, dict):
            raise FundingEvidenceError(f"funding acceptance instrument missing: {instrument}")
        current = _local_history_summary(Path(str(expected.get("path"))), instrument)
        checks[f"{instrument.lower()}_source_hash"] = current["sha256"] == expected.get("sha256")
        checks[f"{instrument.lower()}_structure"] = (
            current["row_count"] == expected.get("row_count") == 7128
            and current["unique_timestamp_count"] == 7128
            and current["start_ts_ms"] == 1577836800000
            and current["end_ts_ms"] == 1783094400000
            and current["gap_ms_values"] == [28800000]
            and current["funding_interval_hours"] == [8]
        )
    status = "PASS" if all(checks.values()) else "FAIL"
    return {
        "schema_name": "s2p13-funding-acceptance-verify",
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "checks": checks,
        "acceptance_hash": acceptance.get("acceptance_hash"),
        "historical_funding_bound": status == "PASS",
        "monthly_official_reconciliation_required": False,
        "lifecycle_run_created": False,
        "stage3_locked": True,
    }


def accept_local_history(root: Path, *, accepted_by: str) -> dict[str, Any]:
    """Append the explicit human acceptance of the structurally audited local history."""

    if accepted_by != "Muce":
        raise FundingEvidenceError("only Muce may accept the funding history")
    evidence_verify = verify_funding_evidence(root)
    if evidence_verify.get("status") != "PASS":
        raise FundingEvidenceError("seven-day evidence must Verify before acceptance")
    catalog = _read_json(root / "catalog.json")
    entries = catalog.get("instruments")
    if not isinstance(entries, dict):
        raise FundingEvidenceError("funding catalog instruments invalid")
    local_history: dict[str, Any] = {}
    for instrument in INSTRUMENTS:
        entry = entries.get(instrument)
        if not isinstance(entry, dict):
            raise FundingEvidenceError(f"funding catalog entry missing: {instrument}")
        summary = _local_history_summary(Path(str(entry["local_source_path"])), instrument)
        if summary["sha256"] != entry.get("local_source_sha256"):
            raise FundingEvidenceError(f"legacy source drift: {instrument}")
        local_history[instrument] = summary
    acceptance: dict[str, Any] = {
        "schema_name": "s2p13-funding-local-history-acceptance",
        "schema_version": SCHEMA_VERSION,
        "change_request": "CR-2026-038",
        "accepted_by": accepted_by,
        "accepted_at": "2026-07-23",
        "human_accepted": True,
        "basis": [
            "COMPLETE_LOCAL_STRUCTURE_AND_HASH",
            "SEVEN_DAY_BINANCE_OFFICIAL_ARCHIVE_SAMPLE",
            "KNOWN_LEGACY_MILLISECOND_ROUNDING",
        ],
        "local_history": local_history,
        "monthly_official_reconciliation_required": False,
        "limitation": (
            "No claim that every historical month was reconciled row-by-row to "
            "the Binance monthly archive."
        ),
        "historical_funding_bound": True,
        "legacy_sources_modified": False,
        "lifecycle_run_created": False,
        "stage3_locked": True,
        "acceptance_hash": "",
    }
    acceptance["acceptance_hash"] = _json_hash(acceptance, "acceptance_hash")
    path = root / "acceptance.json"
    if path.exists() or path.is_symlink():
        raise FundingEvidenceError("append-only funding acceptance already exists")
    _write_json(path, acceptance)
    verification = verify_funding_acceptance(root)
    if verification["status"] != "PASS":
        raise FundingEvidenceError("funding acceptance Verify failed")
    return {"acceptance": acceptance, "verification": verification}


def build_funding_evidence(
    *,
    output_root: Path,
    evidence_id: str,
    local_root: Path,
    start_date: date,
    end_date_exclusive: date,
    scope: str,
) -> dict[str, Any]:
    """Compare local rows to official monthly archives and publish isolated evidence."""

    require_operation_allowed("BUILD_FUNDING_AUDIT_SUPPLEMENT")
    if start_date >= end_date_exclusive:
        raise FundingEvidenceError("empty funding audit range")
    target = output_root / evidence_id
    _safe_root(target)
    start_ms = int(datetime.combine(start_date, datetime.min.time(), UTC).timestamp() * 1000)
    end_ms = int(datetime.combine(end_date_exclusive, datetime.min.time(), UTC).timestamp() * 1000)
    temp = Path(tempfile.mkdtemp(prefix=f".{evidence_id}.", dir=output_root))
    try:
        instrument_catalog: dict[str, Any] = {}
        official_archives: dict[str, list[dict[str, Any]]] = {}
        total_rows = 0
        for instrument in INSTRUMENTS:
            local_path = local_root / f"{instrument}_fundingRate.csv"
            local_all = _parse_local(local_path, instrument)
            local = {
                row.settlement_ts_ms: row
                for row in local_all
                if start_ms <= row.settlement_ts_ms < end_ms
            }
            official_rows: list[FundingRow] = []
            archive_records: list[dict[str, Any]] = []
            for month in _month_starts(start_date, end_date_exclusive):
                month_rows, archive = _official_month(instrument, month)
                official_rows.extend(month_rows)
                archive_records.append(archive)
            official = {
                row.settlement_ts_ms: row
                for row in official_rows
                if start_ms <= row.settlement_ts_ms < end_ms
            }
            if len(official) != len(
                [row for row in official_rows if start_ms <= row.settlement_ts_ms < end_ms]
            ):
                raise FundingEvidenceError(f"duplicate official funding timestamp: {instrument}")
            differences = 0
            for timestamp in set(local) | set(official):
                if local.get(timestamp) != official.get(timestamp):
                    differences += 1
            accepted = sorted(official.values())
            relative = Path("data") / f"{instrument}.csv"
            output = temp / relative
            _write_rows(output, accepted)
            strict_rows = _parse_local(output, instrument)
            if strict_rows != accepted:
                raise FundingEvidenceError(f"strict consumer read-back failed: {instrument}")
            instrument_catalog[instrument] = {
                "path": relative.as_posix(),
                "row_count": len(accepted),
                "sha256": _file_hash(output),
                "local_source_path": str(local_path),
                "local_source_sha256": _file_hash(local_path),
                "local_row_count": len(local),
                "official_row_count": len(official),
                "difference_count": differences,
                "accepted_source": "BINANCE_OFFICIAL_MONTHLY_ARCHIVE",
                "legacy_source_modified": False,
            }
            official_archives[instrument] = archive_records
            total_rows += len(accepted)
        catalog: dict[str, Any] = {
            "schema_name": "s2p13-funding-catalog",
            "schema_version": SCHEMA_VERSION,
            "evidence_id": evidence_id,
            "instruments": instrument_catalog,
            "total_row_count": total_rows,
            "catalog_hash": "",
        }
        catalog["catalog_hash"] = _json_hash(catalog, "catalog_hash")
        _write_json(temp / "catalog.json", catalog)
        manifest: dict[str, Any] = {
            "schema_name": "s2p13-funding-manifest",
            "schema_version": SCHEMA_VERSION,
            "evidence_id": evidence_id,
            "change_request": "CR-2026-038",
            "scope": scope,
            "start_date": start_date.isoformat(),
            "end_date_exclusive": end_date_exclusive.isoformat(),
            "instruments": list(INSTRUMENTS),
            "official_archives": official_archives,
            "catalog_hash": catalog["catalog_hash"],
            "comparison_status": (
                "MATCH"
                if all(entry["difference_count"] == 0 for entry in instrument_catalog.values())
                else "OFFICIAL_OVERRIDE"
            ),
            "append_only": True,
            "legacy_sources_modified": False,
            "historical_evidence_only": True,
            "lifecycle_run_created": False,
            "stage3_locked": True,
            "manifest_hash": "",
        }
        manifest["manifest_hash"] = _json_hash(manifest, "manifest_hash")
        _write_json(temp / "manifest.json", manifest)
        verify = verify_funding_evidence(temp)
        verify["verify_hash"] = _json_hash(verify, "verify_hash")
        _write_json(temp / "verify.json", verify)
        if verify["status"] != "PASS":
            raise FundingEvidenceError("funding evidence Verify failed")
        os.rename(temp, target)
        return {
            "evidence_root": str(target),
            "manifest": manifest,
            "catalog": catalog,
            "verify": verify,
        }
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
