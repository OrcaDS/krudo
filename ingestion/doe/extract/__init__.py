"""Extract classified DOE reports into bronze rows: one Parquet file per report PDF.

Each era has its extractor (project.md §6.3); an era without one yet (A until milestone 5)
waits. Rows keep cell text exactly as read; typing and cleaning happen in silver. A report
that can't be read is marked ``failed`` in the manifest with the reason, never dropped, and
``--redo`` retries it.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import PurePosixPath

import pdfplumber
import pyarrow as pa

from ingestion.common import manifest
from ingestion.common.manifest import DOWNLOADED, EXTRACTED, FAILED, Entry
from ingestion.common.storage import Storage
from ingestion.doe.extract import city_grid

logger = logging.getLogger(__name__)

EXTRACT = "extract:"  # status reason prefix of reports --redo retries
_TS = pa.timestamp("us", tz="+00:00")
SCHEMA = pa.schema(
    [
        pa.field("report_date", pa.date32(), nullable=False),
        pa.field("era", pa.string(), nullable=False),
        pa.field("title_raw", pa.string()),
        pa.field("monitoring_period_raw", pa.string()),
        pa.field("effectivity_raw", pa.string()),
        pa.field("city_raw", pa.string()),  # NULL in era A
        pa.field("product_raw", pa.string(), nullable=False),
        pa.field("brand_raw", pa.string()),  # NULL for the overall range and common price
        pa.field("cell_kind", pa.string(), nullable=False),
        pa.field("value_raw", pa.string(), nullable=False),
        pa.field("source_file", pa.string(), nullable=False),
        pa.field("page", pa.int16(), nullable=False),
        pa.field("extractor_version", pa.string(), nullable=False),
        pa.field("ingested_at", _TS, nullable=False),
    ]
)


@dataclass(frozen=True)
class Extractor:
    name: str
    version: str  # bump when the output for the same PDF changes
    extract: Callable[[Sequence[Sequence[dict]]], list[city_grid.Cell]]


_CITY_GRID = Extractor("city_grid", "1", city_grid.extract)
EXTRACTORS = {"B": _CITY_GRID, "C": _CITY_GRID}


def table_path(entry: Entry) -> str:
    """One file per PDF: a revised report keeps its own file; silver picks the newest."""
    d = entry.report_date
    return (
        f"bronze/tables/doe_prices/year={d:%Y}/"
        f"part-{d.isoformat()}-{PurePosixPath(entry.file_name).stem}.parquet"
    )


def extract_rows(pdf_bytes: bytes, entry: Entry, now: datetime) -> list[dict]:
    """Bronze rows (as dicts in ``SCHEMA`` order) for one report; raises ``Unsupported``."""
    extractor = EXTRACTORS[entry.era]
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = [city_grid.page_words(p) for p in pdf.pages]
        text = [p.dedupe_chars().extract_text() or "" for p in pdf.pages]
        lines = [line for page_text in text for line in page_text.splitlines()]
    cells = extractor.extract(pages)
    monitoring, effectivity = city_grid.report_dates(lines)
    return [
        {
            "report_date": entry.report_date,
            "era": entry.era,
            "title_raw": entry.title_raw,
            "monitoring_period_raw": monitoring,
            "effectivity_raw": effectivity,
            "city_raw": c.city,
            "product_raw": c.product,
            "brand_raw": c.brand,
            "cell_kind": c.kind,
            "value_raw": c.value,
            "source_file": entry.file_name,
            "page": c.page,
            "extractor_version": f"{extractor.name}/{extractor.version}",
            "ingested_at": now,
        }
        for c in cells
    ]


def extract_one(entry: Entry, storage: Storage, now: datetime) -> Entry:
    try:
        rows = extract_rows(storage.read_bytes(entry.lake_path or ""), entry, now)
    except Exception as exc:  # any unreadable report is recorded, never stops the run
        logger.warning("Extract failed for %s: %s", entry.file_name, exc)
        return replace(entry, status=FAILED, status_reason=f"{EXTRACT} {exc}")
    storage.write_parquet(table_path(entry), pa.Table.from_pylist(rows, schema=SCHEMA), SCHEMA)
    return replace(entry, status=EXTRACTED, status_reason=None)


def needs_extract(entry: Entry, storage: Storage, *, redo: bool) -> bool:
    if entry.era not in EXTRACTORS or entry.report_date is None:
        return False
    if entry.lake_path is None or not storage.exists(entry.lake_path):
        return False  # a lake pulled without PDFs (the weekly run) lacks older files
    if entry.status == DOWNLOADED:
        return True
    retry = entry.status == EXTRACTED or (entry.status_reason or "").startswith(EXTRACT)
    return redo and retry


def extract_pending(
    storage: Storage, entries: list[Entry], *, redo: bool = False, limit: int | None = None
) -> list[Entry]:
    """Extract classified reports (with ``redo``, also extracted and extract-failed ones).

    The manifest is saved after each report. Returns the updated entries.
    """
    current = {e.source_url: e for e in entries}
    pending = [e for e in entries if needs_extract(e, storage, redo=redo)][:limit]
    waiting = sum(e.status == DOWNLOADED and e.era not in EXTRACTORS for e in entries)
    logger.info("%d reports to extract (%d wait for their era's extractor)", len(pending), waiting)
    for number, entry in enumerate(pending, start=1):
        current[entry.source_url] = extract_one(entry, storage, datetime.now(UTC))
        manifest.save(storage, list(current.values()))
        if number % 50 == 0:
            logger.info("Extracted %d of %d", number, len(pending))
    result = list(current.values())
    done = [current[e.source_url] for e in pending]
    logger.info(
        "Extract done: %d extracted, %d failed",
        sum(e.status == EXTRACTED for e in done),
        sum(e.status == FAILED for e in done),
    )
    return result
