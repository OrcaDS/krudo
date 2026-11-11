"""Read each downloaded PDF's title: its layout era and report date (project.md §6.3).

| Era | Title |
|---|---|
| A | ``PREVAILING RETAIL PRICES OF PETROLEUM PRODUCTS IN METRO MANILA`` / ``As of <date>`` |
| B | ``NCR Prevailing Retail Pump Price as of <date>`` |
| C | ``Price Monitoring of Liquid Fuels`` / ``NCR`` / ``(For the week of <range>)`` |

The report date is the title's date (era C: the first day of the week). Only when the title
has no readable date does the link text give it (``date_source = "link_text"``). A PDF with
none of these titles is marked failed, never guessed.
"""

from __future__ import annotations

import calendar
import io
import logging
import re
from dataclasses import dataclass, replace
from datetime import date

import pdfplumber

from ingestion.common import manifest
from ingestion.common.manifest import DOWNLOADED, FAILED, Entry
from ingestion.common.storage import Storage
from ingestion.doe.discover import date_from_link

logger = logging.getLogger(__name__)

TITLE_LINES = 12  # titles sit under at most a 4-line letterhead
DATE_LINES = 4  # the date line is the title line or one of the next three
_MONTHS = {name[:3].lower(): number for number, name in enumerate(calendar.month_name) if name}
_MONTH_DAY = re.compile(r"\b([A-Za-z]{3,})\.? ?(\d{1,2})\b")
_YEAR = re.compile(r"\b(20\d\d)\b")

# (era, title pattern, pattern of the line holding the date), searched in order
_AS_OF = r"\bas of"  # no \b after: DOE writes "as ofJuly 23, 2020"
_ERAS = tuple(
    (era, re.compile(title, re.I), re.compile(date_line, re.I))
    for era, title, date_line in (
        ("A", r"prevailing retail prices of petroleum products", _AS_OF),
        ("B", r"ncr prevailing retail pump price", _AS_OF),
        ("C", r"price monitoring of liquid fuels", r"for the (week|period) of"),
    )
)
CLASSIFY = "classify:"  # status reason prefix; such entries are retried on the next run


class Unsupported(ValueError):
    """The PDF has no title this pipeline knows."""


@dataclass(frozen=True)
class Title:
    era: str
    title_raw: str  # title lines through the date line, joined with " | "
    report_date: date | None


def parse_date(text: str) -> date | None:
    """First 'Month D' in the text, in the first year after it.

    A range across New Year ('December 29 - January 4, 2027') starts the year before.
    """
    found = [m for m in _MONTH_DAY.finditer(text) if m[1][:3].lower() in _MONTHS]
    year = _YEAR.search(text, found[0].end()) if found else None
    if year is None:
        return None
    month, day = _MONTHS[found[0][1][:3].lower()], int(found[0][2])
    # only months before the year count: 'December 30, 2025 - January 5, 2026' names its year
    across_new_year = any(
        _MONTHS[m[1][:3].lower()] < month for m in found[1:] if m.start() < year.start()
    )
    start_year = int(year[1]) - across_new_year
    try:
        return date(start_year, month, day)
    except ValueError:
        return None


def read_title(lines: list[str]) -> Title:
    """Era, raw title and title date from a page's first text lines."""
    lines = [" ".join(line.split()) for line in lines if line.strip()][:TITLE_LINES]
    for era, title, date_line in _ERAS:
        start = next((i for i, line in enumerate(lines) if title.search(line)), None)
        if start is None:
            continue
        for end in range(start, min(start + DATE_LINES, len(lines))):
            if match := date_line.search(lines[end]):
                found = parse_date(lines[end][match.end() :])
                return Title(era, " | ".join(lines[start : end + 1]), found)
        return Title(era, lines[start], None)
    if not lines:
        raise Unsupported("no text on page 1 (a scanned image; would need OCR)")
    raise Unsupported("no known title in the first lines: " + " | ".join(lines[:3]))


def title_of(pdf_bytes: bytes) -> Title:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = pdf.pages[0].dedupe_chars().extract_text() or ""
    return read_title(text.splitlines())


def _classify_one(entry: Entry, storage: Storage) -> Entry:
    try:
        title = title_of(storage.read_bytes(entry.lake_path or ""))
    except Exception as exc:  # any unreadable PDF is recorded, never stops the run
        return replace(entry, status=FAILED, status_reason=f"{CLASSIFY} {exc}")
    found, source = title.report_date, "title"
    if found is None:
        found, source = date_from_link(entry.link_text, entry.listing_year), "link_text"
    if found is None:
        return replace(
            entry,
            era=title.era,
            title_raw=title.title_raw,
            status=FAILED,
            status_reason=f"{CLASSIFY} no report date in title or link text",
        )
    return replace(
        entry,
        era=title.era,
        title_raw=title.title_raw,
        report_date=found,
        date_source=source,
        status=DOWNLOADED,
        status_reason=None,
    )


def needs_classify(entry: Entry, storage: Storage) -> bool:
    if entry.lake_path is None or not storage.exists(entry.lake_path):
        return False
    if entry.status == DOWNLOADED:
        return entry.era is None
    return entry.status == FAILED and (entry.status_reason or "").startswith(CLASSIFY)


def classify_pending(storage: Storage, entries: list[Entry]) -> list[Entry]:
    """Classify every downloaded, unclassified PDF (no network); save the manifest once."""
    result = [_classify_one(e, storage) if needs_classify(e, storage) else e for e in entries]
    manifest.save(storage, result)
    failed = [e for e in result if (e.status_reason or "").startswith(CLASSIFY)]
    for e in failed:
        logger.warning("Classify failed for %s: %s", e.file_name, e.status_reason)
    logger.info(
        "Classified: %d files, %d failed", sum(e.era is not None for e in result), len(failed)
    )
    return result
