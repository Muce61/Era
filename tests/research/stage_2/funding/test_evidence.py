from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from era100x.research.stage_2.funding import evidence
from era100x.research.stage_2.funding.evidence import (
    FundingEvidenceError,
    accept_local_history,
    build_funding_evidence,
    verify_funding_acceptance,
    verify_funding_evidence,
)


def _archive(instrument: str, rate: str) -> tuple[bytes, bytes]:
    csv_bytes = (
        "calc_time,funding_interval_hours,last_funding_rate\n"
        f"1577836800000,8,{rate}\n"
        "1577865600000,8,0.00010000\n"
    ).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(f"{instrument}-fundingRate-2020-01.csv", csv_bytes)
    archive = output.getvalue()
    checksum = (
        f"{hashlib.sha256(archive).hexdigest()}  {instrument}-fundingRate-2020-01.zip\n"
    ).encode()
    return archive, checksum


def _sources(root: Path, *, btc_rate: str = "0.00010000") -> None:
    root.mkdir()
    for instrument, rate in (("BTCUSDT", btc_rate), ("ETHUSDT", "0.00010000")):
        (root / f"{instrument}_fundingRate.csv").write_text(
            "calc_time,funding_interval_hours,last_funding_rate\n"
            f"1577836800000,8,{rate}\n"
            "1577865600000,8,0.00010000\n",
            encoding="utf-8",
        )


def _download_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    archives = {
        instrument: _archive(instrument, "0.00010000") for instrument in ("BTCUSDT", "ETHUSDT")
    }

    def download(url: str) -> bytes:
        instrument = "BTCUSDT" if "BTCUSDT" in url else "ETHUSDT"
        archive, checksum = archives[instrument]
        return checksum if url.endswith(".CHECKSUM") else archive

    monkeypatch.setattr(evidence, "_download", download)


def test_build_strict_readback_and_verify(tmp_path: Path, monkeypatch) -> None:
    _download_fixture(monkeypatch)
    local = tmp_path / "local"
    _sources(local)
    output = tmp_path / "evidence"
    output.mkdir()

    result = build_funding_evidence(
        output_root=output,
        evidence_id="funding-7d",
        local_root=local,
        start_date=date(2020, 1, 1),
        end_date_exclusive=date(2020, 1, 8),
        scope="SEVEN_DAY_REHEARSAL",
    )

    assert result["manifest"]["comparison_status"] == "MATCH"
    assert result["verify"]["status"] == "PASS"
    assert result["catalog"]["total_row_count"] == 4
    assert verify_funding_evidence(output / "funding-7d")["status"] == "PASS"
    assert result["manifest"]["lifecycle_run_created"] is False


def test_official_override_does_not_modify_legacy(tmp_path: Path, monkeypatch) -> None:
    _download_fixture(monkeypatch)
    local = tmp_path / "local"
    _sources(local, btc_rate="0.00020000")
    original = (local / "BTCUSDT_fundingRate.csv").read_bytes()
    output = tmp_path / "evidence"
    output.mkdir()

    result = build_funding_evidence(
        output_root=output,
        evidence_id="funding-override",
        local_root=local,
        start_date=date(2020, 1, 1),
        end_date_exclusive=date(2020, 1, 8),
        scope="SEVEN_DAY_REHEARSAL",
    )

    assert result["manifest"]["comparison_status"] == "OFFICIAL_OVERRIDE"
    assert result["catalog"]["instruments"]["BTCUSDT"]["difference_count"] == 1
    assert (local / "BTCUSDT_fundingRate.csv").read_bytes() == original
    accepted = (output / "funding-override/data/BTCUSDT.csv").read_text()
    assert "0.00010000" in accepted


def test_append_only_and_tamper_fail_closed(tmp_path: Path, monkeypatch) -> None:
    _download_fixture(monkeypatch)
    local = tmp_path / "local"
    _sources(local)
    output = tmp_path / "evidence"
    output.mkdir()
    kwargs = {
        "output_root": output,
        "evidence_id": "funding-7d",
        "local_root": local,
        "start_date": date(2020, 1, 1),
        "end_date_exclusive": date(2020, 1, 8),
        "scope": "SEVEN_DAY_REHEARSAL",
    }
    build_funding_evidence(**kwargs)
    with pytest.raises(FundingEvidenceError, match="already exists"):
        build_funding_evidence(**kwargs)

    accepted = output / "funding-7d/data/BTCUSDT.csv"
    accepted.write_text(accepted.read_text() + "BTCUSDT,1,8,0\n")
    assert verify_funding_evidence(output / "funding-7d")["status"] == "FAIL"


def test_official_checksum_mismatch_blocks_before_evidence(tmp_path: Path, monkeypatch) -> None:
    local = tmp_path / "local"
    _sources(local)
    output = tmp_path / "evidence"
    output.mkdir()
    monkeypatch.setattr(evidence, "_download", lambda url: b"bad")

    with pytest.raises(FundingEvidenceError, match="checksum mismatch"):
        build_funding_evidence(
            output_root=output,
            evidence_id="funding-bad",
            local_root=local,
            start_date=date(2020, 1, 1),
            end_date_exclusive=date(2020, 1, 8),
            scope="SEVEN_DAY_REHEARSAL",
        )
    assert not (output / "funding-bad").exists()


def test_human_acceptance_binds_structurally_complete_local_history(
    tmp_path: Path, monkeypatch
) -> None:
    _download_fixture(monkeypatch)
    local = tmp_path / "local"
    local.mkdir()
    for instrument in ("BTCUSDT", "ETHUSDT"):
        lines = ["calc_time,funding_interval_hours,last_funding_rate"]
        lines.extend(f"{1577836800000 + index * 28800000},8,0.0001" for index in range(7128))
        (local / f"{instrument}_fundingRate.csv").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
    output = tmp_path / "evidence"
    output.mkdir()
    build_funding_evidence(
        output_root=output,
        evidence_id="funding-accepted",
        local_root=local,
        start_date=date(2020, 1, 1),
        end_date_exclusive=date(2020, 1, 8),
        scope="SEVEN_DAY_REHEARSAL",
    )

    result = accept_local_history(output / "funding-accepted", accepted_by="Muce")

    assert result["verification"]["status"] == "PASS"
    assert result["acceptance"]["monthly_official_reconciliation_required"] is False
    assert verify_funding_acceptance(output / "funding-accepted")["historical_funding_bound"]
