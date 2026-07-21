from __future__ import annotations

from pathlib import Path

import pytest

from era100x.research.stage_2.paths.extraction import (
    PathExtractionReceipt,
    publish_path_extraction_receipt,
    read_path_extraction_receipts,
)


def receipt(
    *,
    sequence: int = 0,
    previous: str | None = None,
    status: str = "IN_PROGRESS",
) -> PathExtractionReceipt:
    passed = status == "PASS"
    return PathExtractionReceipt.seal(
        {
            "code_commit": "abcdef0",
            "sequence": sequence,
            "previous_receipt_hash": previous,
            "status": status,
            "reason_code": f"S2_T11_{status}",
            "btc_episodes_done": 2 if passed else 1,
            "btc_episodes_total": 2,
            "eth_episodes_done": 3 if passed else 0,
            "eth_episodes_total": 3,
            "input_hashes": {"BTCUSDT": "1" * 64, "ETHUSDT": "2" * 64},
            "output_hashes": {"BTCUSDT": "3" * 64, "ETHUSDT": "4" * 64} if passed else {},
            "acceptance_checks": {"utc_boundary": True, "shuffle_determinism": True},
            "full_output_complete": passed,
            "validation_status": "PASS" if passed else "NOT_RUN",
            "validation_path": "docs/development/validations/stage_2/S2-T11.md",
            "validation_hash": "5" * 64 if passed else None,
            "created_at": "2026-07-21T00:00:00Z",
        }
    )


def test_receipts_are_append_only_and_hash_chained(tmp_path: Path) -> None:
    directory = tmp_path / "S2-T11"
    first = receipt()
    publish_path_extraction_receipt(directory, first)
    final = receipt(sequence=1, previous=first.receipt_hash, status="PASS")
    publish_path_extraction_receipt(directory, final)

    assert read_path_extraction_receipts(directory) == (first, final)
    assert len(tuple(directory.iterdir())) == 2


def test_receipt_chain_rejects_symlinks_and_wrong_predecessor(tmp_path: Path) -> None:
    directory = tmp_path / "S2-T11"
    first = receipt()
    publish_path_extraction_receipt(directory, first)
    with pytest.raises(ValueError, match="predecessor"):
        publish_path_extraction_receipt(
            directory,
            receipt(sequence=1, previous="9" * 64, status="PASS"),
        )

    unsafe = tmp_path / "unsafe"
    unsafe.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ValueError, match="safe directory"):
        read_path_extraction_receipts(unsafe)


def test_pass_receipt_fails_closed_without_full_evidence() -> None:
    with pytest.raises(ValueError, match="complete full output"):
        PathExtractionReceipt.seal(
            {
                **receipt().model_dump(mode="python", exclude={"receipt_hash"}),
                "status": "PASS",
            }
        )
