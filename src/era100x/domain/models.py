from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProtectionStep(BaseModel):
    model_config = ConfigDict(frozen=True)
    mfe_net_roe_pct: Decimal
    lock_net_roe_pct: Decimal


class RiskConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    isolated_margin_only: bool = True
    ticket_equity_usdt: Decimal = Decimal("10")
    max_margin_usdt: Decimal = Decimal("8")
    fee_and_slippage_reserve_usdt: Decimal = Decimal("2")
    leverage: int = Field(default=100, ge=1, le=125)
    max_concurrent_positions: int = Field(default=1, ge=1)
    max_daily_stops: int = Field(default=2, ge=1)
    stop_cooldown_seconds: int = Field(default=900, ge=0)
    min_initial_stop_bps: Decimal = Decimal("15")
    max_initial_stop_bps: Decimal = Decimal("35")
    activation_net_roe_pct: Decimal = Decimal("20")
    target_equity_multiple: Decimal = Decimal("2")
    protection_ladder: tuple[ProtectionStep, ...]

    @model_validator(mode="after")
    def validate_invariants(self) -> "RiskConfig":
        if not self.isolated_margin_only:
            raise ValueError("V1 requires isolated margin")
        if self.max_concurrent_positions != 1:
            raise ValueError("V1 permits exactly one concurrent position")
        if self.max_margin_usdt + self.fee_and_slippage_reserve_usdt > self.ticket_equity_usdt:
            raise ValueError("margin plus reserve cannot exceed ticket equity")
        if self.min_initial_stop_bps >= self.max_initial_stop_bps:
            raise ValueError("minimum stop distance must be below maximum")
        previous_mfe = Decimal("-Infinity")
        previous_lock = Decimal("-Infinity")
        for step in self.protection_ladder:
            if step.mfe_net_roe_pct <= previous_mfe:
                raise ValueError("protection MFE thresholds must strictly increase")
            if step.lock_net_roe_pct < previous_lock:
                raise ValueError("protection locks must be monotonic")
            if step.lock_net_roe_pct >= step.mfe_net_roe_pct:
                raise ValueError("locked ROE must stay below its MFE threshold")
            previous_mfe = step.mfe_net_roe_pct
            previous_lock = step.lock_net_roe_pct
        return self


class ExecutionAssumptions(BaseModel):
    model_config = ConfigDict(frozen=True)
    entry_fee_rate: Decimal = Field(ge=0)
    exit_fee_rate: Decimal = Field(ge=0)
    entry_slippage_bps: Decimal = Field(ge=0)
    exit_slippage_bps: Decimal = Field(ge=0)
    use_reduce_only_exits: bool = True
    require_exchange_native_stop: bool = True


class ResearchConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    path_horizon_seconds: int = Field(gt=0)
    activation_barrier_net_roe_pct: Decimal
    target_barrier_net_roe_pct: Decimal
    adverse_barriers_net_roe_pct: tuple[Decimal, ...]
    report_horizons_seconds: tuple[int, ...]
    purge_seconds: int = Field(ge=0)
    embargo_seconds: int = Field(ge=0)


class AppConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str
    mode: Literal["research", "backtest", "demo", "live"]
    venue: str = "OKX"
    instruments: tuple[str, ...] = ()
    direction: str = "long_only"
    risk: RiskConfig
    execution_assumptions: ExecutionAssumptions
    research: ResearchConfig


def load_app_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"configuration root must be a mapping: {config_path}")
    return AppConfig.model_validate(raw)
