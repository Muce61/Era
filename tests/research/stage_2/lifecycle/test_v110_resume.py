from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from era100x.research.stage_2.lifecycle.models import (
    CensorReason,
    FundingTrack,
    LifecyclePolicyResult,
)
from era100x.research.stage_2.rerun import seven_day_rehearsal
from era100x.research.stage_2.rerun.strict_json import strict_json_bytes


@dataclass(frozen=True)
class _FakePair:
    market_episode_id: str
    funding_track: FundingTrack
    immediate_exit: LifecyclePolicyResult
    continue_holding: LifecyclePolicyResult


def _policy(policy_id: str) -> LifecyclePolicyResult:
    return LifecyclePolicyResult(
        policy_id=policy_id,
        terminal_state="RIGHT_CENSORED",
        exit_reason=None,
        censor_reason=CensorReason.MAX_HORIZON_CENSORED,
        decision_ts_ns=None,
        scenario_net_pnl=None,
        terminal_ticket_equity=None,
        ticket_doubled=None,
        reserve_breached=None,
        remaining_proxy_quantity=Decimal("1"),
    )


def _rows() -> dict[str, list[dict[str, Any]]]:
    start = date(2020, 1, 1)
    btc = []
    for offset in range(70):
        owner = start + timedelta(days=offset)
        entry_ns = int(datetime.combine(owner, datetime.min.time(), UTC).timestamp() * 1e9)
        btc.append(
            {
                "market_episode_id": f"episode-{offset:03d}",
                "window_start_ns": entry_ns,
            }
        )
    return {"BTCUSDT": btc, "ETHUSDT": []}


def _install_fakes(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    monkeypatch.setattr(
        seven_day_rehearsal,
        "_selected_t10_rows",
        lambda **_kwargs: _rows(),
    )
    monkeypatch.setattr(
        seven_day_rehearsal,
        "FixedT10Reader",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(seven_day_rehearsal, "_read_json", lambda _path: {})
    monkeypatch.setattr(
        seven_day_rehearsal._FundingIndex,
        "from_acceptance",
        lambda _acceptance: object(),
    )

    def probe(**kwargs: Any) -> tuple[dict[str, Any], tuple[_FakePair, ...]]:
        row = kwargs["row"]
        episode_id = str(row["market_episode_id"])
        calls.append(episode_id)
        pair = _FakePair(
            market_episode_id=episode_id,
            funding_track=FundingTrack.PRIMARY_HISTORICAL_ACTUAL,
            immediate_exit=_policy("IMMEDIATE_EXIT"),
            continue_holding=_policy("CONTINUE_HOLDING"),
        )
        return {"market_episode_id": episode_id}, (pair,)

    monkeypatch.setattr(seven_day_rehearsal, "_lifecycle_probe_v18", probe)


def test_t11_resume_only_computes_remaining_batch_and_matches_clean_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _install_fakes(monkeypatch, calls)
    audit = SimpleNamespace(status="PASS", audit_hash="a" * 64)
    first_checkpoint: dict[str, Any] = {}

    def interrupt(update: dict[str, Any]) -> None:
        first_checkpoint.update(update)
        raise RuntimeError("fixture interruption")

    with pytest.raises(RuntimeError, match="fixture interruption"):
        seven_day_rehearsal.produce_scoped_lifecycle_v110(
            start_date=date(2020, 1, 1),
            end_date_exclusive=date(2020, 3, 11),
            source_audit_hash="a" * 64,
            source_audit=audit,
            resume_root=tmp_path / "resume",
            progress_callback=interrupt,
        )
    assert len(calls) == 64

    calls.clear()
    resumed = seven_day_rehearsal.produce_scoped_lifecycle_v110(
        start_date=date(2020, 1, 1),
        end_date_exclusive=date(2020, 3, 11),
        source_audit_hash="a" * 64,
        source_audit=audit,
        resume_root=tmp_path / "resume",
        resume_state=first_checkpoint,
    )
    assert len(calls) == 6

    calls.clear()
    clean = seven_day_rehearsal.produce_scoped_lifecycle_v110(
        start_date=date(2020, 1, 1),
        end_date_exclusive=date(2020, 3, 11),
        source_audit_hash="a" * 64,
        source_audit=audit,
        resume_root=tmp_path / "clean",
    )
    assert len(calls) == 70
    assert strict_json_bytes(resumed) == strict_json_bytes(clean)
