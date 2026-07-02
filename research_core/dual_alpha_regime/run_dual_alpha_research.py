from __future__ import annotations

import argparse
from pathlib import Path

from research_core.dual_alpha_regime.config import RegimeResearchConfig
from research_core.dual_alpha_regime.common_risk_layer import write_common_risk_gate_closed
from research_core.dual_alpha_regime.market_regime_event_table import build_market_regime_events, write_outputs
from research_core.dual_alpha_regime.mean_reversion_backtest import run_minimal_mean_reversion_backtest, write_gate_closed_summary
from research_core.dual_alpha_regime.mean_reversion_event_study import run_mean_reversion_event_study
from research_core.dual_alpha_regime.phase_gates import PhaseGateError
from research_core.dual_alpha_regime.portfolio_routing import write_routing_gate_closed
from research_core.dual_alpha_regime.random_baseline import run_random_baseline
from research_core.dual_alpha_regime.regime_classifiers import classify_regimes
from research_core.dual_alpha_regime.regime_factor_research import run_factor_research
from research_core.dual_alpha_regime.trend_baseline_adapter import write_trend_baseline_freeze


def run_r1_to_r3(config: RegimeResearchConfig) -> None:
    events, audit, missing = build_market_regime_events(config)
    write_outputs(events, audit, missing, config)
    run_factor_research(config.output_dir)
    classify_regimes(config.output_dir, config)


def run_r4_to_r5(config: RegimeResearchConfig) -> None:
    run_mean_reversion_event_study(config.output_dir, config)
    run_random_baseline(config.output_dir)


def run_gated_later_phases(config: RegimeResearchConfig) -> None:
    write_trend_baseline_freeze(config.output_dir)
    try:
        run_minimal_mean_reversion_backtest(config.output_dir)
    except PhaseGateError as exc:
        reason = str(exc)
        write_gate_closed_summary(config.output_dir, reason)
        write_routing_gate_closed(config.output_dir, reason)
        write_common_risk_gate_closed(config.output_dir, reason)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run staged dual-alpha regime research.")
    parser.add_argument("--data-dir", default=str(RegimeResearchConfig().data_dir))
    parser.add_argument("--output-dir", default=str(RegimeResearchConfig().output_dir))
    parser.add_argument("--symbols", nargs="*", default=RegimeResearchConfig().symbols)
    parser.add_argument("--through-phase", choices=["R3", "R5", "R14"], default="R3")
    args = parser.parse_args()
    config = RegimeResearchConfig(data_dir=Path(args.data_dir), output_dir=Path(args.output_dir), symbols=args.symbols)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    run_r1_to_r3(config)
    if args.through_phase in {"R5", "R14"}:
        run_r4_to_r5(config)
    if args.through_phase == "R14":
        run_gated_later_phases(config)
    print(f"Dual-alpha research run complete through {args.through_phase}: {config.output_dir}")


if __name__ == "__main__":
    main()

