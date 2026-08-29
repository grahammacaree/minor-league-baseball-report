from __future__ import annotations

import argparse
import sys

from .config_loader import load_settings, user_config_home


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mlb_report",
        description="Build the daily Mariners farm system digest.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the digest instead of emailing it",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()

    print(f"{settings['org']['team_name']} farm report")
    print(f"config home: {user_config_home()}")
    print(f"tracking top {settings['depth']['notable']} prospects")
    if args.dry_run:
        print("(dry run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
