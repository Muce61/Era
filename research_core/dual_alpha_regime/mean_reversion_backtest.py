from __future__ import annotations

from pathlib import Path

import pandas as pd

from research_core.dual_alpha_regime.phase_gates import R6_GATE, PhaseGateError


def run_minimal_mean_reversion_backtest(output_dir: Path) -> pd.DataFrame:
    """R6 placeholder with a hard gate.

    The executable MR strategy is intentionally blocked until R4/R5 artifacts
    exist. This prevents event-study outputs from being misreported as a
    deployable trading strategy.
    """

    R6_GATE.assert_open(output_dir)
    baseline = pd.read_csv(output_dir / "mean_reversion_random_baseline.csv")
    mr = baseline[baseline["baseline"] == "mean_reversion_events"]
    same_range = baseline[baseline["baseline"] == "same_range_random"]
    if mr.empty or same_range.empty or float(mr["mean_fwd_ret_120m"].iloc[0]) <= float(same_range["mean_fwd_ret_120m"].iloc[0]):
        raise PhaseGateError("R6 gate closed: MR events do not beat same-range matched random baseline.")
    raise PhaseGateError("R6 implementation intentionally requires explicit approval after R4/R5 report review.")


def write_gate_closed_summary(output_dir: Path, reason: str) -> None:
    output_dir.joinpath("mean_reversion_strategy_summary.csv").write_text(
        "status,reason\nnot_run," + reason.replace(",", ";") + "\n",
        encoding="utf-8",
    )

