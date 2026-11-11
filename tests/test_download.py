"""Tests for polite, idempotent DOE downloads (no network: fetches are faked)."""

import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ingestion.common import manifest
from ingestion.common.manifest import DOWNLOADED, FAILED, Entry
from ingestion.common.storage import LocalStorage
from ingestion.doe.discover import Report
from ingestion.doe.download import PoliteFetcher, download_pending

T0 = datetime(2026, 11, 11, tzinfo=UTC)


def _entries(*days: int) -> list[Entry]:
    """Entries in page order (newest first), as discover returns them."""
    reports = [
        Report(
            source_url=f"https://prod-cms.doe.gov.ph/documents/d/oimb/petro_ncr_2022_dec_{d:02}",
            file_name=f"petro_ncr_2022_dec_{d:02}.pdf",
            link_text=f"December {d}",
            listing_year=2022,
            revision_level=0,
        )
        for d in sorted(days, reverse=True)
    ]
    return manifest.merge([], reports, T0)


def _by_day(entries: list[Entry]) -> dict[int, Entry]:
    return {int(e.file_name[-6:-4]): e for e in entries}


class FakeFetch:
    def __init__(self, responses: dict[str, bytes | Exception] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        response = self.responses.get(url, b"%PDF-1.7 " + url.encode())
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "lake")


def test_downloads_in_page_order_and_records_hashes(storage: LocalStorage) -> None:
    fetch = FakeFetch()
    result = _by_day(download_pending(storage, _entries(1, 2), fetch))
    assert [url[-2:] for url in fetch.calls] == ["02", "01"]
    entry = result[2]
    assert entry.status == DOWNLOADED and len(entry.sha256 or "") == 64
    assert entry.lake_path == "bronze/files/doe/ncr/year=2022/petro_ncr_2022_dec_02.pdf"
    assert storage.read_bytes(entry.lake_path).startswith(b"%PDF-")
    assert _by_day(manifest.load(storage)) == result


def test_rerun_skips_downloaded_files(storage: LocalStorage) -> None:
    entries = download_pending(storage, _entries(1, 2), FakeFetch())
    fetch = FakeFetch()
    download_pending(storage, entries, fetch)
    assert fetch.calls == []


def test_missing_file_is_downloaded_again_unless_new_only(
    storage: LocalStorage, tmp_path: Path
) -> None:
    entries = download_pending(storage, _entries(1), FakeFetch())
    (tmp_path / "lake" / (entries[0].lake_path or "")).unlink()
    fetch = FakeFetch()
    download_pending(storage, entries, fetch, refetch_missing=False)
    assert fetch.calls == []
    download_pending(storage, entries, fetch)
    assert len(fetch.calls) == 1


def test_failures_are_recorded_and_retried(storage: LocalStorage) -> None:
    entries = _entries(1, 2, 3)
    url = {d: e.source_url for d, e in _by_day(entries).items()}
    fetch = FakeFetch({url[3]: urllib.error.URLError("timed out"), url[2]: b"<html>404</html>"})
    result = _by_day(download_pending(storage, entries, fetch))
    assert (result[3].status, result[3].status_reason) == (
        FAILED,
        "download: <urlopen error timed out>",
    )
    assert (result[2].status, result[2].status_reason) == (FAILED, "download: not a PDF")
    assert result[1].status == DOWNLOADED
    retry = FakeFetch()
    download_pending(storage, list(result.values()), retry)
    assert sorted(retry.calls) == sorted([url[2], url[3]])


def test_limit(storage: LocalStorage) -> None:
    fetch = FakeFetch()
    download_pending(storage, _entries(1, 2, 3, 4), fetch, limit=2)
    assert [url[-2:] for url in fetch.calls] == ["04", "03"]


def test_identical_bytes_fail_as_a_duplicate_and_are_not_refetched(storage: LocalStorage) -> None:
    entries = _entries(1, 2)
    fetch = FakeFetch({e.source_url: b"%PDF-same" for e in entries})
    result = _by_day(download_pending(storage, entries, fetch))
    assert (result[2].status, result[2].status_reason) == (DOWNLOADED, None)
    assert (result[1].status, result[1].status_reason) == (
        FAILED,
        "same bytes as petro_ncr_2022_dec_02.pdf",
    )
    assert result[1].lake_path is not None  # kept in bronze
    again = FakeFetch()
    download_pending(storage, list(result.values()), again)
    assert again.calls == []


def test_polite_fetcher_spaces_requests_and_sets_user_agent() -> None:
    now = [100.0]
    sleeps: list[float] = []
    requests: list[urllib.request.Request] = []

    def opener(request: urllib.request.Request, timeout: float) -> bytes:
        requests.append(request)
        now[0] += 1.0  # each request takes 1 s
        return b"ok"

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    fetch = PoliteFetcher("TestAgent/1", 5, opener=opener, clock=lambda: now[0], sleep=sleep)
    fetch("https://doe.gov.ph/a")
    fetch("https://doe.gov.ph/b")
    assert sleeps == [5.0]  # no wait before the first request, full delay before the second
    assert requests[0].get_header("User-agent") == "TestAgent/1"


def test_polite_fetcher_waits_after_a_failure_too() -> None:
    now = [0.0]
    sleeps: list[float] = []

    def failing(request: urllib.request.Request, timeout: float) -> bytes:
        raise urllib.error.URLError("down")

    fetch = PoliteFetcher(
        "T", 5, opener=failing, clock=lambda: now[0], sleep=lambda s: sleeps.append(s)
    )
    for _ in range(2):
        with pytest.raises(urllib.error.URLError):
            fetch("https://doe.gov.ph/a")
    assert sleeps == [5.0]
