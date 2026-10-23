"""``oeds-post`` command line: run a post-run command in-process."""

from __future__ import annotations

import argparse
import sys
from importlib import import_module
from typing import Sequence

# "<group> <action>" -> (module with main(), arguments put before the given ones)
COMMANDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "gapfill entsoe-fms": ("scripts.gapfill_timeseries", ("--job", "entsoe_fms")),
    "refresh entsoe-availability-map": ("scripts.refresh_entsoe_availability_map", ()),
    "forecast day-ahead-price": ("scripts.run_price_forecast", ()),
    "backfill entsoe-unavailability": ("scripts.backfill_entsoe_unavailability", ()),
}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="oeds-post",
        description="Run an OEDS post-run command.",
        epilog="commands:\n  " + "\n  ".join(COMMANDS),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("group")
    parser.add_argument("action")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="arguments passed on to the command")
    args = parser.parse_args(argv)

    command = f"{args.group} {args.action}"
    if command not in COMMANDS:
        parser.error(f"unknown command: {command}")
    module_name, default_args = COMMANDS[command]
    main_func = import_module(module_name).main
    # Not every command's main() takes argv, so the arguments go through sys.argv.
    sys.argv = [f"oeds-post {command}", *default_args, *args.args]
    raise SystemExit(main_func())


if __name__ == "__main__":
    main()
