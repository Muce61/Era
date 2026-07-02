from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PhaseGateError(RuntimeError):
    """Raised when a later phase is invoked before prior evidence is present."""


@dataclass(frozen=True)
class PhaseGate:
    phase: str
    required_files: tuple[str, ...]
    message: str

    def assert_open(self, output_dir: Path) -> None:
        missing = [name for name in self.required_files if not (output_dir / name).exists()]
        if missing:
            raise PhaseGateError(f"{self.phase} gate closed: missing {missing}. {self.message}")


R4_GATE = PhaseGate(
    phase="R4",
    required_files=(
        "market_regime_events.parquet",
        "regime_factor_registry.csv",
        "regime_factor_stability.csv",
        "regime_transition_matrix.csv",
        "regime_coverage_summary.csv",
        "regime_report.md",
    ),
    message="Finish R1-R3 and explicitly select/freeze a regime prototype before MR event study.",
)

R6_GATE = PhaseGate(
    phase="R6",
    required_files=(
        "mean_reversion_events.parquet",
        "mean_reversion_group_summary.csv",
        "mean_reversion_random_baseline.csv",
        "mean_reversion_walk_forward.csv",
        "mean_reversion_report.md",
    ),
    message="R4/R5 event and random-baseline evidence must exist before executable MR backtest.",
)

