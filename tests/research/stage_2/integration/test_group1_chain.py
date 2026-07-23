from decimal import Decimal

from era100x.data.schema.models import ContractBar, ContractPrice1s, NormalizedTrade
from era100x.research.stage_2.episodes.hold import detect_hold
from era100x.research.stage_2.episodes.identity import build_market_episode
from era100x.research.stage_2.episodes.reclaim import detect_reclaim
from era100x.research.stage_2.episodes.sweep import detect_sweep
from era100x.research.stage_2.gates.flow import evaluate_flow_gate
from era100x.research.stage_2.gates.price import evaluate_price_trigger
from era100x.research.stage_2.key_levels.arbitration import arbitrate_key_levels
from era100x.research.stage_2.key_levels.sources.common import SourceLineage
from era100x.research.stage_2.key_levels.sources.range_low import generate_range_lows

S = 1_000_000_000
H = 3600 * S
LINEAGE = SourceLineage("stage1", "1" * 64, "2" * 64, "abcdef0", "G1-PRIMARY-V1")


def test_complete_fixture_chain_is_stable_and_causal() -> None:
    hours = [
        ContractBar(
            instrument="BTCUSDT",
            source_type="CONTRACT",
            interval_seconds=3600,
            bucket_start_ns=i * H,
            open=Decimal(100 + i),
            high=Decimal(101 + i),
            low=Decimal(99 + i),
            close=Decimal(100 + i),
            volume=Decimal("1"),
        )
        for i in range(20)
    ]
    raw = generate_range_lows(hours, "1H", LINEAGE)[-1]
    level = arbitrate_key_levels([raw], merge_tolerance_bps=Decimal("10"), expires_at_ns=21 * H)[0]
    sweep_start = 20 * H
    sweep = detect_sweep(
        level, [_price(sweep_start, "117.97", "117.98")], confirmation_bps=Decimal("2")
    )
    assert sweep is not None and sweep.status == "DETECTED"
    reclaim = detect_reclaim(
        sweep,
        level,
        [_price(sweep_start + S, "118.0118", "118.0118")],
        reclaim_buffer_bps=Decimal("1"),
        timeout_seconds=15,
    )
    hold_rows = [_price(sweep_start + (2 + i) * S, "118", "118") for i in range(15)]
    hold = detect_hold(
        reclaim, level, hold_rows, hold_window_seconds=15, failure_buffer_bps=Decimal("1")
    )
    trigger_start = hold.available_at_ts
    seconds = [_price(trigger_start + (i - 5) * S, "118", "118") for i in range(36)]
    seconds[6] = _price(trigger_start + S, "119", "119")
    trigger = evaluate_price_trigger(hold, hours, seconds, structural_low_price=Decimal("117.97"))
    trades = [
        _trade(1, trigger.available_at_ts - 4 * S, "SELL", "1"),
        _trade(2, trigger.available_at_ts - S, "BUY", "2"),
        _trade(3, trigger.available_at_ts - S + 1, "BUY", "2"),
    ]
    flow = evaluate_flow_gate(trigger, trades)
    episode = build_market_episode(
        level,
        sweep,
        reclaim,
        hold,
        trigger,
        flow,
        variant="V1_FLOW",
        event_parameter_set_id="G1-PRIMARY-V1",
        time_combination_id="T2",
    )
    assert episode.episode_status == "CANDIDATE"
    assert episode.available_at_ts == flow.available_at_ts
    assert episode == build_market_episode(
        level,
        sweep,
        reclaim,
        hold,
        trigger,
        flow,
        variant="V1_FLOW",
        event_parameter_set_id="G1-PRIMARY-V1",
        time_combination_id="T2",
    )


def _price(ts: int, low: str, close: str) -> ContractPrice1s:
    return ContractPrice1s(
        instrument="BTCUSDT",
        ts_event_ns=ts,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
        source_encoding="DECIMAL_TEXT",
    )


def _trade(identifier: int, ts: int, side: str, quantity: str) -> NormalizedTrade:
    return NormalizedTrade.model_validate(
        {
            "instrument": "BTCUSDT",
            "venue_trade_id": identifier,
            "canonical_trade_id": f"{identifier:064x}",
            "identity_status": "UNIQUE_VENUE_ID",
            "price": Decimal("118"),
            "quantity": Decimal(quantity),
            "quote_quantity": Decimal(quantity) * Decimal("118"),
            "ts_event_ns": ts,
            "is_buyer_maker": side == "SELL",
            "aggressor_side": side,
            "source_sha256": "a" * 64,
        }
    )
