"""Single entry point for the pipeline: `krudo <subcommand>` (also the Docker entrypoint).

Subcommands are wired up milestone by milestone; until then they exit with code 2 so a
scheduled run can never silently pass while doing nothing.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
from collections.abc import Sequence

from config.settings import Settings, load_settings

logger = logging.getLogger("krudo")

# Stages not built yet, with the milestone that builds them (project.md §10)
PLANNED = {
    "ingest": ("Discover and download DOE reports", 3),
    "extract": ("Extract downloaded reports into bronze rows", 4),
    "transform": ("dbt build: silver and gold", 6),
    "lake-push": ("Upload changed lake files to the release", 7),
    "lake-pull": ("Restore the lake from the release", 7),
    "publish-data": ("Release gold as open data if it changed", 7),
    "run-all": ("Run every stage in order (the weekly run)", 7),
}


def _show_config(args: argparse.Namespace, settings: Settings) -> int:
    """Log the effective configuration (no secrets are held in Settings)."""
    for field in dataclasses.fields(settings):
        logger.info("%s = %s", field.name, getattr(settings, field.name))
    return 0


def _not_built(args: argparse.Namespace, settings: Settings) -> int:
    logger.error("'%s' is not built yet (milestone %d)", args.command, PLANNED[args.command][1])
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="krudo", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show-config", help="Print the effective configuration").set_defaults(
        handler=_show_config
    )
    for name, (help_text, milestone) in PLANNED.items():
        sub.add_parser(name, help=f"{help_text} (milestone {milestone})").set_defaults(
            handler=_not_built
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings()
    except ValueError as exc:  # bad env var: report it plainly, not as a traceback
        logging.basicConfig(format="%(levelname)s krudo: %(message)s")
        logger.error("Configuration error: %s", exc)
        return 2
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.handler(args, settings)


if __name__ == "__main__":
    sys.exit(main())
