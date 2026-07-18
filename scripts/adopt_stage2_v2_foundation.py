#!/usr/bin/env python3
"""Adopt CR-2026-013 verified BTC Foundation month objects into a fresh run."""

from __future__ import annotations

import argparse

from era100x.research.stage_2.manifests.models import canonical_json
from era100x.research.stage_2.runtime_v2.artifact_adoption import (
    adopt_btc_foundation_months,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination-run-id", required=True)
    parser.add_argument("--runtime-manifest", required=True, type=__import__("pathlib").Path)
    args = parser.parse_args()
    result = adopt_btc_foundation_months(
        destination_run_id=args.destination_run_id,
        destination_manifest_path=args.runtime_manifest,
    )
    print(canonical_json(result.model_dump(mode="json")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
