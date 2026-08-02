# Copyright 2026 the Radd authors
# SPDX-License-Identifier: Apache-2.0
"""radd-runner — poll a Radd tracker's event stream and dispatch to plugins."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .client import RaddClient
from .runner import Runner
from .types import DEFAULT_POLL_INTERVAL, EnvVar

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radd-runner",
        description="Poll a Radd tracker's /api/v1/events stream and dispatch "
        "each event to plugins (*.py files defining register(reg)).",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get(EnvVar.URL),
        help=f"Tracker base URL, e.g. http://tracker:8000 (env {EnvVar.URL})",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get(EnvVar.TOKEN),
        help=f"Personal access token, radd_pat_… (env {EnvVar.TOKEN})",
    )
    parser.add_argument(
        "--plugins",
        default=os.environ.get(EnvVar.PLUGINS),
        help=f"Directory of plugin .py files (env {EnvVar.PLUGINS})",
    )
    parser.add_argument(
        "--state",
        default=os.environ.get(EnvVar.STATE),
        help=f"Path of the JSON offset checkpoint file (env {EnvVar.STATE})",
    )
    parser.add_argument(
        "--from-start",
        action="store_true",
        help="With no existing checkpoint, start at offset 0 (full history) "
        "instead of the current head",
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=float(os.environ.get(EnvVar.POLL, DEFAULT_POLL_INTERVAL)),
        help=f"Seconds between empty polls (env {EnvVar.POLL}, "
        f"default {DEFAULT_POLL_INTERVAL})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    required = {"--url": args.url, "--token": args.token, "--plugins": args.plugins, "--state": args.state}
    missing = [flag for flag, value in required.items() if not value]
    if missing:
        print(f"radd-runner: missing required options: {', '.join(missing)}", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
    client = RaddClient(args.url, args.token)
    runner = Runner(
        client,
        plugins_dir=args.plugins,
        state_path=args.state,
        poll_interval=args.poll,
        from_start=args.from_start,
    )
    try:
        runner.run()
    except KeyboardInterrupt:
        logging.getLogger("radd_sdk.cli").info("interrupted; shutting down")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
