"""Shared filesystem discovery rules for published research evidence."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path


def is_appledouble_relative_path(path: Path) -> bool:
    """Return whether any relative path component is a macOS AppleDouble sidecar."""

    return any(part.startswith("._") for part in path.parts)


def iter_evidence_files(root: Path) -> Iterator[Path]:
    """Yield regular evidence files while excluding AppleDouble metadata."""

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if is_appledouble_relative_path(path.relative_to(root)):
            continue
        yield path
