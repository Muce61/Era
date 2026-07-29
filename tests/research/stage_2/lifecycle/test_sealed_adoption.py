from __future__ import annotations

from pathlib import Path

import pytest

from era100x.research.stage_2.lifecycle.sealed_adoption import (
    ADOPTED_TASKS,
    load_sealed_adoption_bundle,
)

ROOT = Path(__file__).resolve().parents[4]
SEALED_ROOT = Path("/Volumes/FuckingLife/era100x_stage2/formal")
MATCHING_HASH = "5f56fc680bc970596afff672da0f301bdad428ca37174a60324f9543c3c71477"
CLUSTER_HASH = "6be54d26a190bfc5894fa8957cb5fe7d65365db465f1f43332a607efc8dc8f5a"


@pytest.mark.skipif(not SEALED_ROOT.is_dir(), reason="formal sealed evidence volume is absent")
def test_real_t12_t18_sealed_adoption_closes_without_copying() -> None:
    bundle = load_sealed_adoption_bundle(
        ROOT,
        current_bindings={
            "matching_contract_hash": MATCHING_HASH,
            "cluster_contract_hash": CLUSTER_HASH,
        },
    )

    assert tuple(bundle.tasks) == ADOPTED_TASKS
    assert len(bundle.lock_payload()) == 7
    assert all(binding.source_path.is_file() for binding in bundle.tasks.values())


def test_sealed_adoption_rejects_matching_contract_drift_before_execution() -> None:
    with pytest.raises(
        ValueError,
        match="BLOCKED_SEALED_ADOPTION_INCOMPATIBLE: contract basis",
    ):
        load_sealed_adoption_bundle(
            ROOT,
            current_bindings={
                "matching_contract_hash": "0" * 64,
                "cluster_contract_hash": CLUSTER_HASH,
            },
        )
