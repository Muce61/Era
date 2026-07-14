from pathlib import Path

import pytest
import yaml

from era100x.spike.ports.execution import (
    CapabilityStatus,
    OfflineExecutionMock,
    SpikeManifest,
    deny_network_access,
)


ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "scenario", ["IOC", "ALGO_CREATE", "ALGO_UPDATE", "UNKNOWN", "RESTART", "EXIT_RACE"]
)
def test_offline_scenarios_are_expressible(scenario: str) -> None:
    observation = OfflineExecutionMock().observe(scenario)
    assert observation.status is CapabilityStatus.OBSERVED_OFFLINE
    assert observation.evidence == "deterministic_mock"


def test_unknown_scenario_fails_closed() -> None:
    with pytest.raises(ValueError):
        OfflineExecutionMock().observe("SEND_REAL_ORDER")


def test_network_is_hard_denied() -> None:
    with pytest.raises(PermissionError, match="network access is disabled"):
        deny_network_access("https://example.invalid")


def test_manifest_rejects_network_or_credentials() -> None:
    with pytest.raises(ValueError):
        SpikeManifest(network_disabled=False, credential_fields_present=False, observations=())
    with pytest.raises(ValueError):
        SpikeManifest(network_disabled=True, credential_fields_present=True, observations=())


def test_example_config_is_offline_and_contains_no_credential_keys() -> None:
    config = yaml.safe_load((ROOT / "configs/spike/example.yaml").read_text())
    assert config == {"network_disabled": True, "mode": "offline_mock"}
