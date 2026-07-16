from decimal import Decimal

from era100x.data.schema.models import ContractBar, ContractPrice1s
from era100x.research.stage_2.contracts.models import HoldEvent
from era100x.research.stage_2.gates.price import evaluate_price_trigger

S = 1_000_000_000
H = 3600 * S


def hold() -> HoldEvent:
    return HoldEvent(
        instrument="BTCUSDT",
        data_run_id="stage1",
        dataset_logical_hash="1" * 64,
        config_hash="2" * 64,
        code_version="abcdef0",
        parameter_set_id="G1-PRIMARY-V1",
        available_at_ts=25 * H,
        hold_id="3" * 64,
        reclaim_id="4" * 64,
        sweep_id="5" * 64,
        hold_start_ts=25 * H - 30 * S,
        hold_end_ts=25 * H,
        hold_result="PASS",
        failure_reason=None,
    )


def hours(up: bool = True) -> list[ContractBar]:
    return [
        ContractBar(
            instrument="BTCUSDT",
            source_type="CONTRACT",
            interval_seconds=3600,
            bucket_start_ns=i * H,
            open=Decimal(100 + i),
            high=Decimal(101 + i),
            low=Decimal(99 + i),
            close=Decimal(100 + i if up else 200 - i),
            volume=Decimal("1"),
        )
        for i in range(25)
    ]


def seconds(trigger: bool = True, new_low: bool = False) -> list[ContractPrice1s]:
    start = 25 * H - 5 * S
    rows = []
    for i in range(36):
        close = Decimal("100")
        if trigger and i == 6:
            close = Decimal("101")
        low = Decimal("90") if new_low and i == 5 else close
        rows.append(
            ContractPrice1s(
                instrument="BTCUSDT",
                ts_event_ns=start + i * S,
                open=close,
                high=close,
                low=low,
                close=close,
                volume=Decimal("1"),
                source_encoding="DECIMAL_TEXT",
            )
        )
    return rows


def test_g1_and_g3_pass_with_causal_detection() -> None:
    event = evaluate_price_trigger(hold(), hours(), seconds(), structural_low_price=Decimal("95"))
    assert event.status == "PASS"
    assert event.context_state == "UP"
    assert event.available_at_ts == 25 * H + 2 * S


def test_context_failure_and_future_hour_do_not_rescue() -> None:
    down = hours(False)
    future = down + [
        down[-1].model_copy(update={"bucket_start_ns": 25 * H, "close": Decimal("999")})
    ]
    assert evaluate_price_trigger(
        hold(), down, seconds(), structural_low_price=Decimal("95")
    ) == evaluate_price_trigger(hold(), future, seconds(), structural_low_price=Decimal("95"))


def test_new_structural_low_rejects_before_trigger() -> None:
    event = evaluate_price_trigger(
        hold(), hours(), seconds(new_low=True), structural_low_price=Decimal("95")
    )
    assert event.status == "REJECTED"
    assert event.reason_code == "G3_NEW_STRUCTURAL_LOW"
