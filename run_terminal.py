#!/usr/bin/env python3
"""
run_terminal.py — Entry point for Polymarket Bloomberg Terminal

Usage:
    python run_terminal.py                 # launch with 30s refresh
    python run_terminal.py --refresh 15   # set refresh interval to 15s
    python run_terminal.py --help
"""

import argparse
import sys
import traceback
import logging

LOG_FILE = "/tmp/pm_terminal_crash.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)


def main():
    parser = argparse.ArgumentParser(
        prog="pm-terminal",
        description="Polymarket Bloomberg Terminal — live prediction market TUI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Keyboard shortcuts:
  ENTER       Inspect market (show detail modal)
  A           Add focused market to watchlist
  S           Cycle sort order in market browser
  R           Manual refresh
  W           Focus watchlist panel
  B           Focus market browser panel
  ?           Show help
  Q / Ctrl+C  Quit

Panels:
  Top-left   : Top Movers — biggest % price changes
  Top-right  : Whale Activity — trades > $5K (live)
  Bottom-left: Market Browser — all active markets
  Bottom-right: Watchlist — your tracked markets
        """,
    )
    parser.add_argument(
        "--refresh",
        type=int,
        default=30,
        metavar="SECONDS",
        help="Data refresh interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="pm-terminal 1.0.0",
    )

    args = parser.parse_args()

    if args.refresh < 5:
        print("Error: refresh interval must be at least 5 seconds.", file=sys.stderr)
        sys.exit(1)

    try:
        from terminal import PolymarketTerminal
    except ImportError as e:
        print(f"Import error: {e}", file=sys.stderr)
        print("Run: pip install -r requirements.txt", file=sys.stderr)
        sys.exit(1)

    app = PolymarketTerminal(refresh_interval=args.refresh)

    print(f"Starting Polymarket Terminal (refresh: {args.refresh}s)…")
    logging.info(f"Starting Polymarket Terminal (refresh: {args.refresh}s)")
    try:
        app.run()
        logging.info("App exited cleanly.")
    except Exception as e:
        tb = traceback.format_exc()
        logging.error(f"App crashed: {e}\n{tb}")
        print(f"CRASH: {e}\n{tb}", file=sys.stderr)
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        tb = traceback.format_exc()
        logging.error(f"main() crashed: {e}\n{tb}")
        sys.exit(1)
