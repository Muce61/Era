#!/usr/bin/env python3
"""Basis event study stub.

Per data audit: delivery futures historical data unavailable.
No expiry contracts, settlement rules, or historical basis-to-convergence series discovered in 1m_data or standard locations.
Marking explicitly unavailable; no BSC1 evaluation possible.
"""

from pathlib import Path
import pandas as pd

def run_basis_event_study(data_dir: Path, symbols: list, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    note = pd.DataFrame([{
        "status": "data_unavailable",
        "reason": "No historical delivery/expiry klines + rules/roll dates found. Focus remains on perp funding carry only.",
        "symbols_checked": ",".join(symbols)
    }])
    note.to_csv(output_dir / "basis_event_summary.csv", index=False)
    print("Basis event study: data_unavailable (see data_quality_report.md).")
    return note

if __name__ == "__main__":
    run_basis_event_study(Path("/Users/muce/1m_data"), ["BTCUSDT","ETHUSDT"], Path("research_core/carry_research"))
