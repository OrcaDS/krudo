"""Publish gold as open data: a GitHub Release marked "Latest", only when gold changed.

Assets: each gold table as Parquet, every table as CSV in one zip, and the data dictionary.
Asset names never change, so ``releases/latest/download/<name>`` URLs stay stable. The
Parquet files are written in a stable row order (``export_gold``), so their sha256 tells
whether anything changed since the latest release.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

GOLD_DIR = Path("transform/models/gold")  # one table per model file
DICTIONARY = Path("docs/data_dictionary.md")
CSV_ZIP = "krudo_gold_csv.zip"
NOTES = """\
Metro Manila (NCR) weekly retail pump prices, cleaned and standardized. Each gold table comes \
as Parquet (`<table>.parquet`) and as CSV (all tables in `{csv_zip}`). Columns, units and \
grain: `data_dictionary.md`.

**Source:** Department of Energy – Oil Industry Management Bureau, NCR price monitoring. \
Public domain. Cleaned and standardized by krudo; not an official DOE product.

**Disclaimer:** provided as is. DOE's own typos are kept and flagged (`is_low_above_high`, \
`is_out_of_bounds`), and parsing may contain errors.

**Licenses:** the data is Philippine government data (no copyright under RA 8293 §176). \
The code is MIT.

Tables: {tables}
"""


@dataclass(frozen=True)
class Export:
    table: str
    path: Path
    sha256: str
    rows: int


def gold_tables(gold_dir: Path = GOLD_DIR) -> list[str]:
    return sorted(p.stem for p in gold_dir.glob("*.sql"))


def export_gold(duckdb_path: Path, out_dir: Path, tables: list[str]) -> list[Export]:
    """Write each gold table to Parquet in a stable row order, so equal data hashes equal."""
    out_dir.mkdir(parents=True, exist_ok=True)
    exports = []
    # Not read_only: in run-all, dbt still holds a read-write connection in this process,
    # and DuckDB refuses a second one to the same file with a different configuration
    with duckdb.connect(str(duckdb_path)) as con:
        for table in tables:
            path = out_dir / f"{table}.parquet"
            con.execute(
                f"COPY (SELECT * FROM {table} ORDER BY ALL) TO '{path.as_posix()}' (FORMAT parquet)"
            )
            rows = con.execute(f"SELECT count(*) FROM {table}").fetchall()[0][0]
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            exports.append(Export(table, path, sha, rows))
    return exports


def changed(exports: list[Export], published: dict[str, str]) -> bool:
    """True if any gold table differs from the latest release (or it has none of them)."""
    return any(published.get(f"{e.table}.parquet") != e.sha256 for e in exports)


def csv_zip(exports: list[Export], out: Path) -> Path:
    """Write every table as CSV into one zip."""
    with duckdb.connect() as con, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for e in exports:
            csv = out.parent / f"{e.table}.csv"
            con.execute(
                f"COPY (FROM read_parquet('{e.path.as_posix()}')) TO '{csv.as_posix()}' (HEADER)"
            )
            zf.write(csv, csv.name)
            csv.unlink()
    return out


def _gh(*args: str) -> str:
    try:
        return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError as exc:
        exc.add_note(f"gh stderr: {exc.stderr.strip()}")
        raise


def latest_release() -> tuple[str | None, dict[str, str]]:
    """Tag and asset sha256s of the "Latest" release (never a prerelease such as ``lake``)."""
    try:
        release = json.loads(_gh("api", "repos/{owner}/{repo}/releases/latest"))
    except subprocess.CalledProcessError as exc:
        if "404" in exc.stderr:
            return None, {}
        raise
    digests = {
        a["name"]: (a.get("digest") or "").removeprefix("sha256:") for a in release["assets"]
    }
    return release["tag_name"], digests


def publish(exports: list[Export], work_dir: Path, today: date) -> bool:
    """Release gold if it changed since the latest release. Returns True if it published."""
    tag, published = latest_release()
    if not changed(exports, published):
        logger.info("Gold unchanged since release %s; not publishing", tag)
        return False
    files = [str(e.path) for e in exports]
    files += [str(csv_zip(exports, work_dir / CSV_ZIP)), str(DICTIONARY)]
    new_tag = f"data-{today:%Y-%m-%d}"
    if tag == new_tag:  # a second run on the same day replaces that day's files
        _gh("release", "upload", new_tag, *files, "--clobber")
    else:
        notes = NOTES.format(
            csv_zip=CSV_ZIP, tables=", ".join(f"{e.table} ({e.rows:,} rows)" for e in exports)
        )
        _gh(
            "release", "create", new_tag, *files, "--latest",
            "--title", f"Open data {today:%Y-%m-%d}", "--notes", notes,
        )  # fmt: skip
    logger.info("Published gold as release %s", new_tag)
    return True
