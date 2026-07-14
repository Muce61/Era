"""Run the deterministic local quality gate used by Stage 0 and CI."""

from __future__ import annotations

import argparse
import subprocess
import sys


COMMANDS = (
    ("ruff", "format", "--check", "."),
    ("ruff", "check", "."),
    ("mypy", "src", "scripts"),
    (sys.executable, "scripts/check_traceability.py", "--strict"),
    (sys.executable, "-m", "pytest", "-q"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        if any(not command for command in COMMANDS):
            return 1
        print("quality gate commands registered:", len(COMMANDS))
        return 0
    for command in COMMANDS:
        print("+", " ".join(command), flush=True)
        completed = subprocess.run(command, check=False)
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
