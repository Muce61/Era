"""Append-only, hash-chained observability receipts for S2-T11."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from era100x.research.stage_2.contracts.models import StrictEventModel

from .models import SHA256_PATTERN, _canonical_json


class PathExtractionReceipt(StrictEventModel):
    schema_name: Literal["stage2-path-extraction-receipt"] = "stage2-path-extraction-receipt"
    schema_version: Literal["1.0"] = "1.0"
    task_id: Literal["S2-T11"] = "S2-T11"
    task_version: Literal["1.2"] = "1.2"
    code_commit: str = Field(min_length=7, max_length=40)
    sequence: int = Field(ge=0)
    previous_receipt_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    status: Literal["IN_PROGRESS", "FAILED", "BLOCKED", "PASS"]
    reason_code: str = Field(min_length=1)
    btc_episodes_done: int = Field(ge=0)
    btc_episodes_total: int = Field(ge=0)
    eth_episodes_done: int = Field(ge=0)
    eth_episodes_total: int = Field(ge=0)
    input_hashes: dict[Literal["BTCUSDT", "ETHUSDT"], str]
    output_hashes: dict[Literal["BTCUSDT", "ETHUSDT"], str]
    acceptance_checks: dict[str, bool]
    full_output_complete: bool
    validation_status: Literal["NOT_RUN", "PASS", "FAILED", "BLOCKED"]
    validation_path: str = Field(min_length=1)
    validation_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    created_at: str = Field(min_length=1)
    receipt_hash: str = Field(pattern=SHA256_PATTERN)

    def computed_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"receipt_hash"})
        return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()

    @model_validator(mode="after")
    def valid_receipt(self) -> Self:
        if self.sequence == 0 and self.previous_receipt_hash is not None:
            raise ValueError("first receipt cannot reference a predecessor")
        if self.sequence > 0 and self.previous_receipt_hash is None:
            raise ValueError("later receipt must reference its predecessor")
        if self.btc_episodes_done > self.btc_episodes_total:
            raise ValueError("BTC completed count exceeds total")
        if self.eth_episodes_done > self.eth_episodes_total:
            raise ValueError("ETH completed count exceeds total")
        for value in (*self.input_hashes.values(), *self.output_hashes.values()):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError("input/output hash must be lowercase SHA-256")
        if self.status == "PASS":
            if not self.full_output_complete or self.validation_status != "PASS":
                raise ValueError("PASS requires complete full output and PASS validation")
            if self.validation_hash is None:
                raise ValueError("PASS requires validation hash")
            if set(self.input_hashes) != {"BTCUSDT", "ETHUSDT"}:
                raise ValueError("PASS requires separate BTC and ETH input hashes")
            if set(self.output_hashes) != {"BTCUSDT", "ETHUSDT"}:
                raise ValueError("PASS requires separate BTC and ETH output hashes")
            if not self.acceptance_checks or not all(self.acceptance_checks.values()):
                raise ValueError("PASS requires every registered acceptance check")
            if self.btc_episodes_done != self.btc_episodes_total or self.btc_episodes_total == 0:
                raise ValueError("PASS requires all BTC episodes")
            if self.eth_episodes_done != self.eth_episodes_total or self.eth_episodes_total == 0:
                raise ValueError("PASS requires all ETH episodes")
        if self.receipt_hash != "0" * 64 and self.receipt_hash != self.computed_hash():
            raise ValueError("receipt hash mismatch")
        return self

    @classmethod
    def seal(cls, payload: dict[str, Any]) -> Self:
        provisional = cls.model_validate({**payload, "receipt_hash": "0" * 64})
        return provisional.model_copy(update={"receipt_hash": provisional.computed_hash()})


def read_path_extraction_receipts(directory: Path) -> tuple[PathExtractionReceipt, ...]:
    """Read and verify one canonical append-only S2-T11 receipt chain."""

    if not directory.exists():
        return ()
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("S2-T11 receipt directory is not a safe directory")
    entries = tuple(path for path in directory.iterdir() if not path.name.startswith("._"))
    if any(path.suffix != ".json" for path in entries):
        raise ValueError("S2-T11 receipt chain contains an unexpected entry")
    paths = sorted(entries)
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError("S2-T11 receipt chain contains an unsafe entry")
    receipts = tuple(PathExtractionReceipt.model_validate_json(path.read_bytes()) for path in paths)
    if tuple(receipt.sequence for receipt in receipts) != tuple(range(len(receipts))):
        raise ValueError("S2-T11 receipt sequence is non-append-only or conflicting")
    for previous, current in zip(receipts, receipts[1:], strict=False):
        if current.previous_receipt_hash != previous.receipt_hash:
            raise ValueError("S2-T11 receipt hash chain is broken")
    expected_names = tuple(
        f"{receipt.sequence:06d}-{receipt.receipt_hash}.json" for receipt in receipts
    )
    if tuple(path.name for path in paths) != expected_names:
        raise ValueError("S2-T11 receipt filenames do not match their immutable content")
    return receipts


def publish_path_extraction_receipt(directory: Path, receipt: PathExtractionReceipt) -> Path:
    """Publish exactly one immutable next receipt; never replace prior evidence."""

    existing = read_path_extraction_receipts(directory)
    if receipt.sequence != len(existing):
        raise ValueError("receipt is not the next append-only sequence")
    expected_previous = existing[-1].receipt_hash if existing else None
    if receipt.previous_receipt_hash != expected_previous:
        raise ValueError("receipt predecessor does not match the current chain")
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("S2-T11 receipt directory cannot be a symlink")
    path = directory / f"{receipt.sequence:06d}-{receipt.receipt_hash}.json"
    payload = json.dumps(receipt.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    with path.open("x", encoding="utf-8") as stream:
        stream.write(payload + "\n")
    return path
