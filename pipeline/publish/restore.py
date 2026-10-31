from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from pipeline.config import load_config
from pipeline.publish.store import current_version, list_versions, restore


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.publish.restore")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list", action="store_true", help="list approved versions")
    action.add_argument("--to", metavar="RUN_ID", help="make this approved version the current one")
    args = parser.parse_args(argv)

    approved_dir = load_config(args.config).paths.approved_dir
    if args.list:
        current = current_version(approved_dir)
        versions = list_versions(approved_dir)
        if not versions:
            print("no approved versions")
        for version in versions:
            print(f"{'*' if version == current else ' '} {version}")
        return 0

    try:
        restore(approved_dir, args.to)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"current version is now {args.to}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
