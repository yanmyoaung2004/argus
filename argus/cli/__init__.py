from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] != "onboard":
        print("Usage:  python -m argus onboard")
        print("        python -m argus            # start server")
        sys.exit(1)

    from argus.cli.onboard import run_onboard

    run_onboard()
