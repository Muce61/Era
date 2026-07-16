"""Create the immutable S2-T19 preregistration manifest after real preflight."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from era100x.research.stage_2.manifests.preflight import create_preregistration


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--governance-commit", required=True)
    parser.add_argument("--stage1-run-root", type=Path, required=True)
    parser.add_argument("--contract-price-root", type=Path, required=True)
    parser.add_argument("--stage2-root", type=Path, required=True)
    args = parser.parse_args()
    manifest, path = create_preregistration(
        governance_commit=args.governance_commit,
        stage1_run_root=args.stage1_run_root,
        contract_price_root=args.contract_price_root,
        stage2_root=args.stage2_root,
    )
    print(json.dumps({"manifest_hash": manifest.manifest_hash, "path": str(path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
