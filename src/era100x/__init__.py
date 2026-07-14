"""Top-level package for the V1.3.4 governed engineering workspace.

Stage 0 Task S0-T01 intentionally exposes version metadata only. Business,
research, data, risk, state, and execution modules are introduced only by
their separately approved tasks.
"""

from typing import Final

__version__: Final[str] = "0.0.0"
SPECIFICATION_VERSION: Final[str] = "V1.3.4"

__all__ = ["SPECIFICATION_VERSION", "__version__"]
