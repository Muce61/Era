from __future__ import annotations

from pathlib import Path


def write_common_risk_gate_closed(output_dir: Path, reason: str) -> None:
    output_dir.joinpath("portfolio_risk_audit.csv").write_text(
        "status,reason\nnot_run," + reason.replace(",", ";") + "\n",
        encoding="utf-8",
    )

