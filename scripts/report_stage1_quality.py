from __future__ import annotations
import json
from era100x.data.reporting.quality import REQUIRED, sample_quality_report


def main() -> int:
    print(json.dumps(sample_quality_report({k: True for k in REQUIRED}), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
