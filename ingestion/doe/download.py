"""Download DOE report PDFs into bronze/files, politely and idempotently.

Requests go one at a time, at least ``REQUEST_DELAY_SECONDS`` apart, with the configured
User-Agent. Files already downloaded (and still in the lake) are skipped, so a run can be
interrupted and restarted at any point; the manifest is saved after every file.
"""

from __future__ import annotations

import hashlib
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from config.settings import Settings
from ingestion.common import manifest
from ingestion.common.manifest import DISCOVERED, DOWNLOADED, EXTRACTED, FAILED, Entry
from ingestion.common.storage import Storage

logger = logging.getLogger(__name__)
DUPLICATE = "same bytes as"  # status reason of a file identical to another report's

TIMEOUT_SECONDS = 60
Fetch = Callable[[str], bytes]


class PoliteFetcher:
    """HTTP GET that never sends two requests closer together than ``delay`` seconds."""

    def __init__(
        self,
        user_agent: str,
        delay: float,
        *,
        opener: Callable[[urllib.request.Request, float], bytes] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.user_agent = user_agent
        self.delay = delay
        self._open = opener or _urlopen
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def __call__(self, url: str) -> bytes:
        if self._last is not None:
            wait = self.delay - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            return self._open(request, TIMEOUT_SECONDS)
        finally:
            self._last = self._clock()  # failures count too: no fast retries


def _urlopen(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def make_fetcher(settings: Settings) -> PoliteFetcher:
    return PoliteFetcher(settings.http_user_agent, settings.request_delay_seconds)


def fetch_listing(fetch: Fetch, settings: Settings) -> str:
    """The NCR listing page HTML."""
    return fetch(settings.doe_listing_url).decode("utf-8", errors="replace")


def needs_download(entry: Entry, storage: Storage, *, refetch_missing: bool = True) -> bool:
    """New, failed before download, or (with ``refetch_missing``) recorded as downloaded
    but missing from the lake."""
    if entry.status == DISCOVERED:
        return True
    if entry.status == FAILED and entry.lake_path is None:
        return True
    if entry.status in (DOWNLOADED, EXTRACTED) and refetch_missing:
        return entry.lake_path is None or not storage.exists(entry.lake_path)
    return False


def _download_one(entry: Entry, storage: Storage, fetch: Fetch, known: dict[str, str]) -> Entry:
    try:
        data = fetch(entry.source_url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Download failed for %s: %s", entry.file_name, exc)
        return replace(entry, status=FAILED, status_reason=f"download: {exc}", lake_path=None)
    if not data.startswith(b"%PDF-"):
        logger.warning("Not a PDF (%d bytes): %s", len(data), entry.file_name)
        return replace(entry, status=FAILED, status_reason="download: not a PDF", lake_path=None)
    path = manifest.bronze_file_path(entry)
    storage.write_bytes(path, data)
    digest = hashlib.sha256(data).hexdigest()
    twin = known.get(digest)
    duplicate = twin is not None and twin != entry.file_name
    return replace(
        entry,
        lake_path=path,
        sha256=digest,
        size_bytes=len(data),
        downloaded_at=datetime.now(UTC),
        status=FAILED if duplicate else DOWNLOADED,
        status_reason=f"{DUPLICATE} {twin}" if duplicate else None,
    )


def download_pending(
    storage: Storage,
    entries: list[Entry],
    fetch: Fetch,
    *,
    limit: int | None = None,
    refetch_missing: bool = True,
) -> list[Entry]:
    """Download every entry that needs it (newest first), saving the manifest after each.

    ``refetch_missing=False`` (``--new-only``) is for a lake pulled without PDFs (the weekly
    run): it would otherwise fetch every report again.

    Returns the updated entries. Failures are recorded in the manifest and never stop the run.
    A file with the same bytes as another report is kept but marked failed, so it is never
    extracted twice.
    """
    current = {e.source_url: e for e in entries}
    pending = sorted(
        (e for e in entries if needs_download(e, storage, refetch_missing=refetch_missing)),
        key=lambda e: (e.listing_year, e.first_seen_at),
        reverse=True,
    )[:limit]
    logger.info("%d files to download", len(pending))
    known = {e.sha256: e.file_name for e in entries if e.sha256}
    failed = 0
    for number, entry in enumerate(pending, start=1):
        updated = _download_one(entry, storage, fetch, known)
        current[entry.source_url] = updated
        if updated.status == FAILED:
            failed += 1
        if updated.sha256:
            known.setdefault(updated.sha256, updated.file_name)
        manifest.save(storage, list(current.values()))
        if number % 50 == 0:
            logger.info("Downloaded %d of %d (%d failed)", number, len(pending), failed)
    logger.info("Download done: %d attempted, %d failed", len(pending), failed)
    return list(current.values())
