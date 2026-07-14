"""Catalog verification CLI; full build orchestration is gated by S1-T13."""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("catalog", type=Path)
    a = p.parse_args()
    data = json.loads(a.catalog.read_text())
    file = a.catalog.parent / data["relative_path"]
    if hashlib.sha256(file.read_bytes()).hexdigest() != data["byte_sha256"]:
        raise ValueError("partition checksum mismatch")
    print("catalog checksum PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
