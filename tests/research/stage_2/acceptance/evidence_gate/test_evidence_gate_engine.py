from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from era100x.research.stage_2.acceptance.evidence_gate.contracts import GateResult
from era100x.research.stage_2.acceptance.evidence_gate.engine import (
    classify_eth,
    overall_recommendation,
    project_lifecycle,
)
from era100x.research.stage_2.acceptance.evidence_gate.formatting import canonical_json
from era100x.research.stage_2.acceptance.evidence_gate.governance import (
    canonical_json_file_hash,
)

SOURCE_HASH = "1" * 64


def _episode(instrument: str, timestamp: int, censor_reason: str) -> dict[str, object]:
    return {
        "instrument": instrument,
        "entry_ts_ns": timestamp,
        "source_coverage": "DECLARED_GAP",
        "funding_tracks": [
            {
                "funding_track": "PRIMARY_HISTORICAL_ACTUAL",
                "eligible_at_primary_landmark": False,
                "continue_holding": {
                    "terminal_state": "RIGHT_CENSORED",
                    "censor_reason": censor_reason,
                    "reserve_breached": False,
                    "exit_reason": None,
                },
            }
        ],
    }


def test_lifecycle_projection_keeps_gap_censoring_separate(tmp_path: Path) -> None:
    path = tmp_path / "output.json"
    path.write_text(
        json.dumps(
            {
                "lifecycle": [
                    _episode("BTCUSDT", 1_609_459_200_000_000_000, "SOURCE_GAP_CENSORED"),
                    _episode("ETHUSDT", 1_609_545_600_000_000_000, "DATA_END_CENSORED"),
                ]
            }
        ),
        encoding="utf-8",
    )

    gates, frequency, cards = project_lifecycle(
        path,
        source_hash=SOURCE_HASH,
        expected_episode_count=2,
    )

    assert len(gates) == 16
    assert len(frequency) == 2
    assert cards["BTCUSDT"]["source_gap_censored"] == 1
    assert cards["BTCUSDT"]["data_end_censored"] == 0
    assert cards["ETHUSDT"]["data_end_censored"] == 1
    assert cards["BTCUSDT"]["decision"] == "INCONCLUSIVE_SOURCE_GAP_CENSORING"


@pytest.mark.parametrize(
    ("btc_failed", "estimate", "lower", "expected"),
    [
        (True, "1", "1", "PRIMARY_FAILED"),
        (False, "1", "0.01", "REPLICATED"),
        (False, "0.01", "0", "BTC_ONLY"),
        (False, "0", "-0.01", "NOT_REPLICATED"),
    ],
)
def test_eth_classification(btc_failed: bool, estimate: str, lower: str, expected: str) -> None:
    assert (
        classify_eth(
            btc_primary_failed=btc_failed,
            eth_estimate=Decimal(estimate),
            eth_ci_lower=Decimal(lower),
        )
        == expected
    )


@pytest.mark.parametrize(
    ("h2_failed", "h3_inconclusive", "expected"),
    [
        (True, True, "NO_GO_CURRENT_EVIDENCE"),
        (True, False, "NO_GO_CURRENT_EVIDENCE"),
        (False, True, "INCONCLUSIVE_CURRENT_EVIDENCE"),
        (False, False, "READY_FOR_STAGE2_FINAL_ACCEPTANCE"),
    ],
)
def test_overall_priority(h2_failed: bool, h3_inconclusive: bool, expected: str) -> None:
    assert (
        overall_recommendation(
            h2_primary_failed=h2_failed,
            lifecycle_inconclusive=h3_inconclusive,
        )
        == expected
    )


def test_gate_hash_tamper_fails() -> None:
    gate = GateResult.seal(
        {
            "gate_id": "F1",
            "instrument": "BTCUSDT",
            "evidence_family": "H2_PRIMARY",
            "status": "FAIL",
            "observed_value": "0",
            "threshold": ">0",
            "reason_code": "OVERALL_CI_LOWER",
            "source_hash": SOURCE_HASH,
        }
    )
    payload = gate.model_dump(mode="python")
    payload["status"] = "PASS"
    with pytest.raises(ValueError, match="Hash mismatch"):
        GateResult.model_validate(payload)


def test_canonical_json_rejects_binary_float() -> None:
    with pytest.raises(ValueError, match="float"):
        canonical_json({"value": 0.1})


def test_canonical_json_file_hash_excludes_exactly_one_terminal_lf(
    tmp_path: Path,
) -> None:
    payload = canonical_json({"rows": [1, 2, 3]})
    path = tmp_path / "output.json"
    path.write_text(payload + "\n", encoding="utf-8")

    assert canonical_json_file_hash(path) == hashlib.sha256(payload.encode("utf-8")).hexdigest()

    path.write_text(payload + "\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="terminal"):
        canonical_json_file_hash(path)
