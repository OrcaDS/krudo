"""Find every NCR report PDF on DOE's listing page.

The page is one HTML table: a row per year, whose first cell is the year in bold and whose
second cell lists links grouped by month. Link text is a loose label ("November 3 to 9",
"December 20" for a December 19 report), never with a year, so the report date comes from
the PDF title after download (``classify.py``); the link only gives a fallback date.
"""

from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

logger = logging.getLogger(__name__)

_MONTHS = {name[:3].lower(): number for number, name in enumerate(calendar.month_name) if name}
_LINK_DATE = re.compile(r"([A-Za-z]{3,})\.? (\d{1,2})\b")
_REVISED = re.compile(r"updated|revised|edited")
# CMS suffix on a re-upload (petro_ncr_2020_march_17_0); not the end of a range (apr_1_7)
_REUPLOAD = re.compile(r"\d_[01]$")


@dataclass(frozen=True)
class Report:
    """One report link, with everything known before downloading it."""

    source_url: str  # always https
    file_name: str  # lake file name: unique, lowercase, safe on every OS
    link_text: str
    listing_year: int  # the year row the link sits in on DOE's page
    revision_level: int  # 0 original, 1 marked as updated/revised/edited or re-uploaded


def _is_report(url: str) -> bool:
    parts = urlsplit(url)
    return (parts.netloc == "prod-cms.doe.gov.ph" and parts.path.startswith("/documents/")) or (
        parts.netloc.endswith(".cloudfront.net") and parts.path.startswith("/api/media/file/")
    )


class _ListingParser(HTMLParser):
    """Collect (year, href, link text) for every report link, in page order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[int | None, str, str]] = []
        self._year: int | None = None
        self._in_strong = False
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        href = dict(attrs).get("href") or ""
        if tag == "strong":
            self._in_strong = True
        elif tag == "a" and _is_report(href):
            self._href, self._text = href, []

    def handle_endtag(self, tag: str) -> None:
        if tag == "strong":
            self._in_strong = False
        elif tag == "a" and self._href is not None:
            self.links.append((self._year, self._href, " ".join("".join(self._text).split())))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._in_strong and re.fullmatch(r"\s*(19|20)\d\d\s*", data):
            self._year = int(data)
        if self._href is not None:
            self._text.append(data)


def https_url(url: str) -> str:
    """Older links on DOE's page use http://; always fetch over https."""
    return "https://" + url.removeprefix("http://") if url.startswith("http://") else url


def safe_name(url: str) -> str:
    """Lake file name from the URL's last path segment: 'petro_ncr_2022_dec_29.pdf'."""
    stem = unquote(urlsplit(url).path.rsplit("/", 1)[-1]).lower()
    stem = re.sub(r"[-_. ]pdf$", "", stem)
    return re.sub(r"[^a-z0-9]+", "_", stem).strip("_") + ".pdf"


def revision_level(file_name: str) -> int:
    stem = file_name.removesuffix(".pdf")
    return int(bool(_REVISED.search(stem) or _REUPLOAD.search(stem)))


def date_from_link(text: str, year: int) -> date | None:
    """The first 'Month D' in the link text, in the listing year; None if there is none."""
    match = _LINK_DATE.search(text)
    month = _MONTHS.get(match[1][:3].lower()) if match else None
    if match is None or month is None:
        return None
    try:
        return date(year, month, int(match[2]))
    except ValueError:
        return None


def discover(html: str) -> list[Report]:
    """Every report link on the page, once per URL, in page order (newest first)."""
    reports: list[Report] = []
    seen_urls: set[str] = set()
    seen_names: set[str] = set()
    for year, href, text in _parse(html):
        url = https_url(href)
        if url in seen_urls:
            logger.info("Link listed twice, kept once: %s", url)
            continue
        if year is None:
            logger.warning("Link outside any year row, skipped: %s", url)
            continue
        seen_urls.add(url)
        name = safe_name(url)
        while name in seen_names:  # two URLs, one name: keep both files apart
            name = name.removesuffix(".pdf") + "_dup.pdf"
        seen_names.add(name)
        reports.append(Report(url, name, text, year, revision_level(name)))
    logger.info("Found %d report links", len(reports))
    return reports


def _parse(html: str) -> list[tuple[int | None, str, str]]:
    parser = _ListingParser()
    parser.feed(html)
    parser.close()
    return parser.links
