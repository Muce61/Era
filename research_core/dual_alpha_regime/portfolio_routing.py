from __future__ import annotations

from pathlib import Path


def write_routing_gate_closed(output_dir: Path, reason: str) -> None:
    output_dir.joinpath("architecture_comparison.csv").write_text(
        "architecture,status,reason\nA_trend_only,documented,frozen_baseline_only\nB_mr_only,not_run,"
        + reason.replace(",", ";")
        + "\nC_no_routing,not_run,"
        + reason.replace(",", ";")
        + "\nD_regime_routing,not_run,"
        + reason.replace(",", ";")
        + "\n",
        encoding="utf-8",
    )
    output_dir.joinpath("portfolio_report.md").write_text(
        "# Portfolio Routing Report\n\n"
        f"Routing research not run. Reason: {reason}\n\n"
        "This is expected until independent MR validation passes R4/R5 and R6 is explicitly allowed.\n",
        encoding="utf-8",
    )

