"""Single entry point for the pipeline: `krudo <subcommand>` (also the Docker entrypoint).

Subcommands are wired up milestone by milestone; until then they exit with code 2 so a
scheduled run can never silently pass while doing nothing.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from config.settings import Settings, load_settings
from ingestion.common import manifest
from ingestion.common.storage import get_storage
from ingestion.doe import classify, discover, download, extract

logger = logging.getLogger("krudo")
TRANSFORM_DIR = Path("transform")  # the dbt project; commands run from the repo root (or /app)

# Stages not built yet, with the milestone that builds them (project.md §10)
PLANNED = {
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


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _ingest(args: argparse.Namespace, settings: Settings) -> int:
    """Discover DOE reports, download what is missing, and classify every new PDF."""
    storage = get_storage(settings)
    fetch = download.make_fetcher(settings)
    reports = discover.discover(download.fetch_listing(fetch, settings))
    entries = manifest.merge(manifest.load(storage), reports, datetime.now(UTC))
    manifest.save(storage, entries)
    entries = download.download_pending(
        storage, entries, fetch, limit=args.limit, refetch_missing=not args.new_only
    )
    classify.classify_pending(storage, entries)
    return 0


def _extract(args: argparse.Namespace, settings: Settings) -> int:
    """Extract classified reports into bronze rows."""
    storage = get_storage(settings)
    extract.extract_pending(storage, manifest.load(storage), redo=args.redo, limit=args.limit)
    return 0


def _transform(args: argparse.Namespace, settings: Settings) -> int:
    """Build silver and gold with dbt (models, seeds and tests) over the local bronze."""
    from dbt.cli.main import dbtRunner  # slow import; only this command needs it

    dbt_vars = {
        "lake_root": settings.lake_root.resolve().as_posix(),
        "duckdb_path": settings.duckdb_path.resolve().as_posix(),
    }
    result = dbtRunner().invoke(
        [
            "build",
            "--project-dir",
            str(TRANSFORM_DIR),
            "--profiles-dir",
            str(TRANSFORM_DIR),
            "--vars",
            json.dumps(dbt_vars),
        ]
    )
    return 0 if result.success else 1


def _not_built(args: argparse.Namespace, settings: Settings) -> int:
    logger.error("'%s' is not built yet (milestone %d)", args.command, PLANNED[args.command][1])
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="krudo", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show-config", help="Print the effective configuration").set_defaults(
        handler=_show_config
    )
    ingest = sub.add_parser("ingest", help="Discover and download DOE reports")
    ingest.add_argument("--limit", type=_positive, help="Download at most N files (newest first)")
    ingest.add_argument(
        "--new-only",
        action="store_true",
        help="Skip reports already downloaded, even if their PDF is not in this lake",
    )
    ingest.set_defaults(handler=_ingest)
    extract_cmd = sub.add_parser("extract", help="Extract classified reports into bronze rows")
    extract_cmd.add_argument("--limit", type=_positive, help="Extract at most N reports")
    extract_cmd.add_argument(
        "--redo", action="store_true", help="Also re-extract extracted and failed reports"
    )
    extract_cmd.set_defaults(handler=_extract)
    sub.add_parser("transform", help="dbt build: silver and gold").set_defaults(handler=_transform)
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
