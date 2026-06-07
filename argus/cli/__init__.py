from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="argus",
        description="Argus — Autonomous Research Agent",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # onboard
    onboard_parser = subparsers.add_parser("onboard", help="Interactive provider setup wizard")
    onboard_parser.set_defaults(func=_run_onboard)

    # research
    from argus.cli.research import add_subparser as add_research_subparser
    add_research_subparser(subparsers)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    args.func(args)


def _run_onboard(_args: argparse.Namespace | None = None) -> None:
    from argus.cli.onboard import run_onboard
    run_onboard()
