from __future__ import annotations

import random
from decimal import Decimal

import pytest
from pydantic import ValidationError

from era100x.data.schema.models import ContractPrice1s, NormalizedTrade
from era100x.research.stage_2.contracts.models import MarketEpisode
from era100x.research.stage_2.labels.first_passage import (
    REGISTERED_HORIZONS_SECONDS,
    REGISTERED_STOP_BPS,
    REGISTERED_TARGET_BPS,
    HistoricalFirstPassageLabel,
    classify_h1_first_passage,
    classify_h2_first_passage,
)
from era100x.research.stage_2.paths.extraction import PathSource, extract_historical_path

S = 1_000_000_000
START = 10 * S
T1_END = START + 60 * S
TARGET = Decimal("20")
STOP = Decimal("15")


def _episode(instrument: str = "BTCUSDT") -> MarketEpisode:
    return MarketEpisode.model_validate(
        {
            "instrument": instrument,
            "data_run_id": "stage1-baseline",
            "dataset_logical_hash": "a" * 64,
            "config_hash": "b" * 64,
            "code_version": "abcdef0",
            "parameter_set_id": "G1-PRIMARY-V1",
            "available_at_ts": START,
            "market_episode_id": "c" * 64,
            "canonical_candidate_id": "d" * 64,
            "candidate_version_id": "d" * 64,
            "canonical_payload_hash": "e" * 64,
            "venue": "BINANCE_USDM",
            "canonical_key_level_id": "level",
            "sweep_id": "sweep",
            "reclaim_id": "reclaim",
            "hold_id": "hold",
            "trigger_id": "trigger",
            "flow_feature_set_id": None,
            "variant": "V1_PRICE",
            "variant_id": "V1_PRICE",
            "time_combination_id": "T2",
            "research_role": "PRIMARY",
            "primary_eligible": True,
            "sweep_start_ns": S,
            "episode_status": "CANDIDATE",
        }
    )


def _source(level: str, instrument: str = "BTCUSDT") -> PathSource:
    return PathSource.model_validate(
        {
            "instrument": instrument,
            "evidence_level": level,
            "reference_price_type": "CONTRACT" if level == "H1" else "TRADE",
            "data_run_id": "stage1-baseline",
            "dataset_logical_hash": ("1" if level == "H1" else "2") * 64,
            "source_manifest_hash": "3" * 64,
        }
    )


def _bar(
    ts: int,
    *,
    high: str = "100",
    low: str = "100",
    instrument: str = "BTCUSDT",
) -> ContractPrice1s:
    high_price = Decimal(high)
    low_price = Decimal(low)
    middle = (high_price + low_price) / 2
    return ContractPrice1s.model_validate(
        {
            "instrument": instrument,
            "ts_event_ns": ts,
            "open": middle,
            "high": high_price,
            "low": low_price,
            "close": middle,
            "volume": Decimal("1"),
            "source_encoding": "DECIMAL_TEXT",
        }
    )


def _trade(
    venue_id: int,
    ts: int,
    price: str,
    *,
    canonical: str | None = None,
    instrument: str = "BTCUSDT",
) -> NormalizedTrade:
    return NormalizedTrade.model_validate(
        {
            "instrument": instrument,
            "venue_trade_id": venue_id,
            "canonical_trade_id": canonical or f"{venue_id:064x}",
            "identity_status": "UNIQUE_VENUE_ID",
            "venue_trade_id_conflict_group": None,
            "price": Decimal(price),
            "quantity": Decimal("1"),
            "quote_quantity": Decimal(price),
            "ts_event_ns": ts,
            "is_buyer_maker": False,
            "aggressor_side": "BUY",
            "source_sha256": "4" * 64,
        }
    )


def _flat_bars(
    *,
    end_ns: int = T1_END,
    overrides: dict[int, tuple[str, str]] | None = None,
    instrument: str = "BTCUSDT",
) -> list[ContractPrice1s]:
    overrides = overrides or {}
    return [
        _bar(
            ts,
            high=overrides.get(ts, ("100", "100"))[0],
            low=overrides.get(ts, ("100", "100"))[1],
            instrument=instrument,
        )
        for ts in range(START, end_ns, S)
    ]


def _path(
    *,
    h1: list[ContractPrice1s] | None = None,
    h2: list[NormalizedTrade] | None = None,
    window_end_ns: int = T1_END,
    instrument: str = "BTCUSDT",
):
    return extract_historical_path(
        episode=_episode(instrument),
        h1_rows=h1 or [],
        h2_rows=h2 or [],
        h1_source=_source("H1", instrument),
        h2_source=_source("H2", instrument),
        window_start_ns=START,
        window_end_ns=window_end_ns,
    )


def _h1(path):
    return classify_h1_first_passage(
        path,
        reference_price=Decimal("100"),
        target_bps=TARGET,
        stop_bps=STOP,
        timing_id="T1",
    )


def _h2(path):
    return classify_h2_first_passage(
        path,
        reference_price=Decimal("100"),
        target_bps=TARGET,
        stop_bps=STOP,
        timing_id="T1",
    )


def test_registered_contract_matches_frozen_stage2_preregistration() -> None:
    assert REGISTERED_TARGET_BPS == tuple(map(Decimal, ("20", "30", "40", "50", "70", "100")))
    assert REGISTERED_STOP_BPS == tuple(map(Decimal, ("15", "20", "25", "30", "35")))
    assert REGISTERED_HORIZONS_SECONDS == {"T1": 60, "T2": 180, "T3": 300, "T4": 600}


def test_h1_target_and_stop_first_use_inclusive_decimal_boundaries() -> None:
    target_path = _path(h1=_flat_bars(overrides={20 * S: ("100.20", "100")}))
    target = _h1(target_path)
    assert target.label == "TARGET_FIRST"
    assert target.target_touch_ts_event_ns == 20 * S
    assert target.time_to_decision_ns == 10 * S
    assert target.strict_target_first is True

    stop_path = _path(h1=_flat_bars(overrides={20 * S: ("100", "99.85")}))
    stop = _h1(stop_path)
    assert stop.label == "STOP_FIRST"
    assert stop.stop_touch_ts_event_ns == 20 * S
    assert stop.strict_target_first is False


def test_h1_same_event_both_is_ambiguous_with_adverse_first_primary_handling() -> None:
    path = _path(h1=_flat_bars(overrides={20 * S: ("100.20", "99.85")}))

    result = _h1(path)

    assert result.label == "AMBIGUOUS"
    assert result.label_reason == "H1_SAME_EVENT_TARGET_AND_STOP"
    assert result.target_touch_ts_event_ns == result.stop_touch_ts_event_ns == 20 * S
    assert result.conservative_main_label == "STOP_FIRST"
    assert result.strict_target_first is False
    assert "AMBIGUOUS_BOUNDS" in result.prohibited_interpretations


def test_h2_same_timestamp_uses_v2_stable_trade_order() -> None:
    rows = [
        _trade(2, 20 * S, "99.85"),
        _trade(1, 20 * S, "100.20"),
    ]
    random.Random(20260721).shuffle(rows)
    path = _path(h2=rows)

    result = _h2(path)

    assert result.label == "TARGET_FIRST"
    assert result.stable_order == ("ts_event_ns", "venue_trade_id", "canonical_trade_id")
    assert path.h2_points[0].venue_trade_id == 1


def test_complete_observed_horizon_without_touch_expires() -> None:
    result = _h1(_path(h1=_flat_bars()))

    assert result.label == "EXPIRED"
    assert result.label_reason == "HORIZON_EXPIRED_WITHOUT_TOUCH"
    assert result.window_complete is True
    assert result.decision_ts_event_ns is None
    assert result.conservative_main_label == "EXPIRED"


def test_right_window_boundary_is_excluded() -> None:
    bars = _flat_bars(end_ns=T1_END + S, overrides={T1_END: ("100.20", "100")})
    result = _h1(_path(h1=bars, window_end_ns=T1_END + S))

    assert result.label == "EXPIRED"
    assert result.observation_count == 60


def test_truncated_window_without_decision_is_ambiguous_not_expired() -> None:
    truncated_end = START + 40 * S
    result = _h1(_path(h1=_flat_bars(end_ns=truncated_end), window_end_ns=truncated_end))

    assert result.label == "AMBIGUOUS"
    assert result.label_reason == "WINDOW_TRUNCATED_BEFORE_DECISION"
    assert result.window_complete is False
    assert result.conservative_main_label is None


def test_source_gap_before_observed_touch_invalidates_first_passage_order() -> None:
    bars = _flat_bars(overrides={20 * S: ("100.20", "100")})
    bars = [bar for bar in bars if bar.ts_event_ns != 15 * S]
    result = _h1(_path(h1=bars))

    assert result.label == "AMBIGUOUS"
    assert result.label_reason == "SOURCE_GAP_BEFORE_DECISION"
    assert result.target_touch_ts_event_ns == 20 * S
    assert result.decision_ts_event_ns is None


def test_source_gap_after_decision_does_not_rewrite_earlier_fact() -> None:
    bars = _flat_bars(overrides={12 * S: ("100.20", "100")})
    bars = [bar for bar in bars if bar.ts_event_ns != 20 * S]
    result = _h1(_path(h1=bars))

    assert result.label == "TARGET_FIRST"
    assert result.decision_ts_event_ns == 12 * S
    assert result.source_gap_codes == ("H1_MISSING_SECONDS",)


def test_no_observations_is_ambiguous_not_zero_or_expired() -> None:
    result = _h2(_path())

    assert result.label == "AMBIGUOUS"
    assert result.label_reason == "NO_OBSERVATIONS"
    assert result.observation_count == 0


@pytest.mark.parametrize(
    ("target", "stop"),
    ((Decimal("21"), STOP), (TARGET, Decimal("16"))),
)
def test_unregistered_thresholds_fail_closed(target: Decimal, stop: Decimal) -> None:
    with pytest.raises(ValueError, match="outside the frozen Stage 2 preregistration"):
        classify_h1_first_passage(
            _path(h1=_flat_bars()),
            reference_price=Decimal("100"),
            target_bps=target,
            stop_bps=stop,
            timing_id="T1",
        )


def test_lineage_btc_eth_isolation_and_historical_boundary_are_preserved() -> None:
    eth_path = _path(
        h1=_flat_bars(instrument="ETHUSDT", overrides={20 * S: ("100.20", "100")}),
        instrument="ETHUSDT",
    )
    result = _h1(eth_path)

    assert result.instrument == "ETHUSDT"
    assert result.market_episode_id == eth_path.market_episode_id
    assert result.source_path_hash == eth_path.output_hash
    assert result.historical_evidence_only is True
    assert {"PNL", "RETURN", "ROUND_SUCCESS", "LIVE_EXECUTION"}.issubset(
        result.prohibited_interpretations
    )
    assert "round_success" not in HistoricalFirstPassageLabel.model_fields


def test_output_hash_and_source_hash_tampering_fail_closed() -> None:
    path = _path(h1=_flat_bars(overrides={20 * S: ("100.20", "100")}))
    result = _h1(path)
    payload = result.model_dump(mode="python")
    payload["source_gap_codes"] = ("TAMPERED",)
    with pytest.raises(ValidationError, match="output_hash mismatch"):
        HistoricalFirstPassageLabel.model_validate(payload)

    tampered_path = path.model_copy(update={"market_episode_id": "f" * 64})
    with pytest.raises(ValueError, match="source path hash is not valid"):
        _h1(tampered_path)
