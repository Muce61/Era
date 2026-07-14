import pytest

from era100x.foundation.config import resolve_effective_config


BASE = {"venue": "BINANCE_USDM", "direction": "LONG_ONLY", "max_leverage": 100}


def test_same_input_produces_same_hash() -> None:
    kwargs = dict(
        mode="research", exchange_constraints=BASE, approved_risk={}, strategy_defaults={}
    )
    first = resolve_effective_config(**kwargs).config_hash
    second = resolve_effective_config(**kwargs).config_hash
    assert first == second


def test_frozen_override_fails() -> None:
    with pytest.raises(ValueError, match="FROZEN"):
        resolve_effective_config(
            mode="research",
            exchange_constraints=BASE,
            approved_risk={},
            strategy_defaults={"max_leverage": 101},
        )


@pytest.mark.parametrize("mode", ["live", "compound"])
def test_cli_override_forbidden_for_live_modes(mode: str) -> None:
    with pytest.raises(ValueError, match="CLI"):
        resolve_effective_config(
            mode=mode,
            exchange_constraints=BASE,
            approved_risk={},
            strategy_defaults={},
            cli_overrides={"anything": True},
        )


def test_research_override_not_applied_to_shadow() -> None:
    result = resolve_effective_config(
        mode="shadow",
        exchange_constraints=BASE,
        approved_risk={},
        strategy_defaults={},
        research_overrides={"threshold": "research-only"},
    )
    assert "threshold" not in result.values
