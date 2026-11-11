"""The DOE file manifest: one row per report PDF ever seen, with its download and classify state.

It lives in the lake at ``MANIFEST_PATH`` as a small Parquet file that is rewritten whole on
each save (~500 rows). Rows are never deleted: a report that disappears from DOE's page (for
example, replaced by a revised file) keeps its row, so silver can still pick the newest version.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime

import pyarrow as pa

from ingestion.common.storage import Storage
from ingestion.doe.discover import Report

logger = logging.getLogger(__name__)

MANIFEST_PATH = "bronze/manifest.parquet"

# Status values
DISCOVERED = "discovered"  # known from the page, not downloaded yet
DOWNLOADED = "downloaded"  # PDF stored in bronze/files (classified once era is set)
FAILED = "failed"  # download, duplicate, classify or extract failed; see status_reason
EXTRACTED = "extracted"  # rows written to bronze/tables
STATUSES = (DISCOVERED, DOWNLOADED, FAILED, EXTRACTED)

# Fixed offset, not "UTC": a named zone needs a tz database, which Windows lacks
_TS = pa.timestamp("us", tz="+00:00")
SCHEMA = pa.schema(
    [
        pa.field("source_url", pa.string(), nullable=False),
        pa.field("file_name", pa.string(), nullable=False),
        pa.field("link_text", pa.string(), nullable=False),
        pa.field("listing_year", pa.int16(), nullable=False),
        pa.field("revision_level", pa.int16(), nullable=False),
        pa.field("on_page", pa.bool_(), nullable=False),
        pa.field("first_seen_at", _TS, nullable=False),
        pa.field("lake_path", pa.string()),
        pa.field("sha256", pa.string()),
        pa.field("size_bytes", pa.int64()),
        pa.field("downloaded_at", _TS),
        pa.field("title_raw", pa.string()),
        pa.field("era", pa.string()),
        pa.field("report_date", pa.date32()),
        pa.field("date_source", pa.string()),  # title | link_text
        pa.field("status", pa.string(), nullable=False),
        pa.field("status_reason", pa.string()),
    ]
)


@dataclass(frozen=True)
class Entry:
    """One manifest row."""

    source_url: str
    file_name: str
    link_text: str
    listing_year: int
    revision_level: int
    on_page: bool  # still linked from DOE's page at the last discovery
    first_seen_at: datetime
    lake_path: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    downloaded_at: datetime | None = None
    title_raw: str | None = None
    era: str | None = None
    report_date: date | None = None
    date_source: str | None = None
    status: str = DISCOVERED
    status_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"Unknown manifest status {self.status!r}")


def bronze_file_path(entry: Report | Entry) -> str:
    """Where a report's PDF lives in the lake.

    Partitioned by the year row on DOE's page, which is known before download (the report
    date is only known after reading the PDF) and only differs from it at a year's edge.
    """
    return f"bronze/files/doe/ncr/year={entry.listing_year}/{entry.file_name}"


def load(storage: Storage) -> list[Entry]:
    """Read the manifest, or an empty one on the first run."""
    if not storage.exists(MANIFEST_PATH):
        return []
    return [Entry(**row) for row in storage.read_parquet(MANIFEST_PATH).to_pylist()]


def save(storage: Storage, entries: list[Entry]) -> None:
    """Rewrite the manifest, sorted for stable diffs."""
    ordered = sorted(entries, key=lambda e: (e.listing_year, e.file_name))
    table = pa.Table.from_pylist([asdict(e) for e in ordered], schema=SCHEMA)
    storage.write_parquet(MANIFEST_PATH, table, SCHEMA)
    logger.debug("Saved manifest with %d entries", len(entries))


def merge(entries: list[Entry], reports: list[Report], now: datetime) -> list[Entry]:
    """Fold a fresh discovery into the manifest.

    New reports are added as ``discovered``. Known ones keep their state but take the page's
    current link text. Reports no longer on the page stay, with ``on_page=False``.
    """
    on_page = {r.source_url for r in reports}
    merged = {e.source_url: replace(e, on_page=e.source_url in on_page) for e in entries}
    added = 0
    for report in reports:
        if report.source_url in merged:
            merged[report.source_url] = replace(
                merged[report.source_url], link_text=report.link_text
            )
        else:
            merged[report.source_url] = Entry(**asdict(report), on_page=True, first_seen_at=now)
            added += 1
    result = list(merged.values())
    logger.info(
        "Manifest: %d entries (%d new, %d no longer on the page)",
        len(result),
        added,
        sum(not e.on_page for e in result),
    )
    return result
