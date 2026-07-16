from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from era100x.research.stage_2.contracts.models import (
    CanonicalKeyLevel,
    HoldEvent,
    PriceTriggerFact,
    RawKeyLevel,
    ReclaimEvent,
    SweepEpisode,
)
from era100x.research.stage_2.manifests.configuration import parameter_sets
from era100x.research.stage_2.pipelines.candidates import price_phase
from era100x.research.stage_2.pipelines.candidates.candidate_finalizer import (
    finalize_candidate_attempts,
)

SECOND_NS = 1_000_000_000
DAY = date(2020, 4, 27)
DAY_START = int(datetime(2020, 4, 27, tzinfo=UTC).timestamp()) * SECOND_NS
HASH_A = "a" * 64
HASH_B = "b" * 64


def _frame(*timestamps: int) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts_event_ns": list(timestamps),
            "open": [101] * len(timestamps),
            "high": [102] * len(timestamps),
            "low": [99] * len(timestamps),
            "close": [101] * len(timestamps),
            "volume": [1] * len(timestamps),
        }
    )


def _raw_level() -> RawKeyLevel:
    return RawKeyLevel(
        instrument="BTCUSDT",
        data_run_id="stage1",
        dataset_logical_hash=HASH_A,
        config_hash=HASH_B,
        code_version="abcdef0",
        parameter_set_id="KEYLEVEL-BASE-V1",
        available_at_ts=DAY_START + 60 * SECOND_NS,
        raw_key_level_id="1" * 64,
        source_type="rolling_low_1m",
        source_id="fixture-source",
        source_timeframe="1m",
        source_start_ts=DAY_START,
        source_end_ts=DAY_START + 60 * SECOND_NS,
        level_price=Decimal("100"),
        priority=6,
        quality_status="ACCEPTED",
    )


def _canonical(expires_at_ns: int) -> CanonicalKeyLevel:
    raw = _raw_level()
    return CanonicalKeyLevel(
        instrument=raw.instrument,
        data_run_id=raw.data_run_id,
        dataset_logical_hash=raw.dataset_logical_hash,
        config_hash=raw.config_hash,
        code_version=raw.code_version,
        parameter_set_id=raw.parameter_set_id,
        available_at_ts=raw.available_at_ts,
        key_level_id="2" * 64,
        source_type=raw.source_type,
        source_id=raw.source_id,
        source_timeframe=raw.source_timeframe,
        source_start_ts=raw.source_start_ts,
        source_end_ts=raw.source_end_ts,
        level_price=raw.level_price,
        priority=raw.priority,
        normalization_group="fixture-group",
        member_key_level_ids=(raw.raw_key_level_id,),
        formed_at_ns=raw.source_end_ts,
        expires_at_ns=expires_at_ns,
        status="ACTIVE",
        reason_code="ARBITRATION_PRIORITY_WINNER",
    )


def _sweep(level: CanonicalKeyLevel) -> SweepEpisode:
    return SweepEpisode(
        instrument=level.instrument,
        data_run_id=level.data_run_id,
        dataset_logical_hash=level.dataset_logical_hash,
        config_hash=level.config_hash,
        code_version=level.code_version,
        parameter_set_id=level.parameter_set_id,
        available_at_ts=DAY_START + 61 * SECOND_NS,
        sweep_id="3" * 64,
        key_level_id=level.key_level_id,
        sweep_start_ts=DAY_START + 60 * SECOND_NS,
        sweep_detection_ts=DAY_START + 61 * SECOND_NS,
        sweep_extreme_ts=DAY_START + 60 * SECOND_NS,
        sweep_extreme_price=Decimal("99.9"),
        sweep_depth=Decimal("10"),
        pre_sweep_reference=Decimal("101"),
        status="DETECTED",
        reason_code="SWEEP_CONFIRMED",
    )


def _reclaim(sweep: SweepEpisode) -> ReclaimEvent:
    return ReclaimEvent(
        instrument=sweep.instrument,
        data_run_id=sweep.data_run_id,
        dataset_logical_hash=sweep.dataset_logical_hash,
        config_hash=sweep.config_hash,
        code_version=sweep.code_version,
        parameter_set_id=sweep.parameter_set_id,
        available_at_ts=DAY_START + 62 * SECOND_NS,
        reclaim_id="4" * 64,
        sweep_id=sweep.sweep_id,
        reclaim_ts=DAY_START + 61 * SECOND_NS,
        reclaim_price=Decimal("100.1"),
        status="RECLAIMED",
        reason_code="RECLAIM_CONFIRMED",
    )


def _hold(reclaim: ReclaimEvent) -> HoldEvent:
    return HoldEvent(
        instrument=reclaim.instrument,
        data_run_id=reclaim.data_run_id,
        dataset_logical_hash=reclaim.dataset_logical_hash,
        config_hash=reclaim.config_hash,
        code_version=reclaim.code_version,
        parameter_set_id=reclaim.parameter_set_id,
        available_at_ts=DAY_START + 63 * SECOND_NS,
        hold_id="5" * 64,
        reclaim_id=reclaim.reclaim_id,
        sweep_id=reclaim.sweep_id,
        hold_start_ts=DAY_START + 62 * SECOND_NS,
        hold_end_ts=DAY_START + 63 * SECOND_NS,
        hold_result="PASS",
        failure_reason=None,
    )


def _trigger(hold: HoldEvent) -> PriceTriggerFact:
    return PriceTriggerFact(
        instrument=hold.instrument,
        data_run_id=hold.data_run_id,
        dataset_logical_hash=hold.dataset_logical_hash,
        config_hash=hold.config_hash,
        code_version=hold.code_version,
        parameter_set_id=hold.parameter_set_id,
        available_at_ts=DAY_START + 64 * SECOND_NS,
        trigger_id="6" * 64,
        hold_id=hold.hold_id,
        sweep_id=hold.sweep_id,
        trigger_version="G1_G3_V1",
        detection_ts=DAY_START + 64 * SECOND_NS,
        reference_price=Decimal("101"),
        context_state="UP",
        status="PASS",
        reason_code="G3_PRICE_START_CONFIRMED",
    )


def test_adjacent_seed_context_emits_one_event_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = next(item for item in parameter_sets() if item.parameter_set_id == "G1-PRIMARY-V1")
    monkeypatch.setattr(price_phase, "parameter_sets", lambda: (primary,))
    monkeypatch.setattr(price_phase, "_path", lambda _root, _instrument, day: Path(day.isoformat()))

    def read(path: Path) -> pl.DataFrame:
        observed = date.fromisoformat(path.name)
        if observed < DAY:
            return _frame(DAY_START - 60 * SECOND_NS)
        if observed == DAY:
            return _frame(DAY_START, DAY_START + 60 * SECOND_NS)
        return _frame(DAY_START + 120 * SECOND_NS)

    monkeypatch.setattr(price_phase, "_read", read)
    monkeypatch.setattr(price_phase, "_raw_levels", lambda *_args: [_raw_level()])
    monkeypatch.setattr(
        price_phase,
        "arbitrate_key_levels",
        lambda _items, *, merge_tolerance_bps, expires_at_ns: [_canonical(expires_at_ns)],
    )
    monkeypatch.setattr(
        price_phase,
        "detect_sweep",
        lambda level, _window, *, confirmation_bps: _sweep(level),
    )
    monkeypatch.setattr(
        price_phase,
        "detect_reclaim",
        lambda sweep, _level, _window, **_kwargs: _reclaim(sweep),
    )
    monkeypatch.setattr(
        price_phase,
        "detect_hold",
        lambda reclaim, _level, _window, **_kwargs: _hold(reclaim),
    )
    monkeypatch.setattr(
        price_phase,
        "evaluate_price_trigger",
        lambda hold, _hourly, _window, **_kwargs: _trigger(hold),
    )

    output = price_phase.build_price_day(
        contract_root=Path("/unused"),
        instrument="BTCUSDT",
        day=DAY,
        data_run_id="stage1",
        dataset_logical_hash=HASH_A,
        config_hash=HASH_B,
        code_version="abcdef0",
    )

    attempts = output["candidate_attempts"]
    assert len(attempts) == 1
    result = finalize_candidate_attempts(attempts)
    assert result.summary["identity_conflict_count"] == 0
    assert result.summary["canonical_count"] == 1


@pytest.mark.parametrize(
    ("minute_start", "sweep_start", "expected"),
    [
        (0, 0, True),
        (0, 60 * SECOND_NS - 1, True),
        (0, 60 * SECOND_NS, False),
        (86_340 * SECOND_NS, 86_400 * SECOND_NS - 1, True),
        (86_340 * SECOND_NS, 86_400 * SECOND_NS, False),
    ],
)
def test_sweep_seed_ownership_is_left_closed_right_open(
    minute_start: int, sweep_start: int, expected: bool
) -> None:
    assert price_phase.owns_sweep_start(minute_start, sweep_start) is expected
