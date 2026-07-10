import argparse
import json
import platform
import sys
from pathlib import Path

from era100x import __version__
from era100x.domain.models import load_app_config


def main() -> None:
    parser = argparse.ArgumentParser(prog="era100x")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor")
    show = subparsers.add_parser("show-config")
    show.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.command == "doctor":
        supported = (3, 12) <= sys.version_info[:2] < (3, 15)
        print(json.dumps({"era100x_version": __version__, "python": sys.version.split()[0], "platform": platform.platform(), "python_supported": supported}, ensure_ascii=False, indent=2))
        raise SystemExit(0 if supported else 1)
    config = load_app_config(args.path)
    print(config.model_dump_json(indent=2))
