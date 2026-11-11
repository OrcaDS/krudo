"""Tests for the DOE file manifest."""

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ingestion.common import manifest
from ingestion.common.manifest import DISCOVERED, DOWNLOADED, Entry
from ingestion.common.storage import LocalStorage
from ingestion.doe.discover import Report

T0 = datetime(2026, 11, 11, 1, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 18, 1, 0, tzinfo=UTC)


def _report(name: str = "petro_ncr_2022_dec_09", text: str = "December 9") -> Report:
    return Report(
        source_url=f"https://prod-cms.doe.gov.ph/documents/d/oimb/{name}",
        file_name=f"{name}.pdf",
        link_text=text,
        listing_year=2022,
        revision_level=0,
    )


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "lake")


def test_load_empty_when_missing(storage: LocalStorage) -> None:
    assert manifest.load(storage) == []


def test_save_and_load_round_trip(storage: LocalStorage) -> None:
    entries = [
        replace(
            e,
            status=DOWNLOADED,
            sha256="ab",
            size_bytes=10,
            downloaded_at=T0,
            lake_path="x",
            era="B",
            report_date=date(2022, 12, 9),
            date_source="title",
        )
        for e in manifest.merge([], [_report()], T0)
    ]
    manifest.save(storage, entries)
    assert manifest.load(storage) == entries


def test_merge_keeps_state_and_marks_links_gone_from_the_page() -> None:
    entries = manifest.merge([], [_report()], T0)
    entries = [replace(entries[0], status=DOWNLOADED, sha256="ab", lake_path="x")]
    revised = _report("petro_ncr_2022_dec_09_0")
    merged = {e.file_name: e for e in manifest.merge(entries, [revised, _report(text="Dec 9")], T1)}
    old = merged["petro_ncr_2022_dec_09.pdf"]
    new = merged["petro_ncr_2022_dec_09_0.pdf"]
    assert (old.status, old.sha256, old.link_text, old.first_seen_at) == (
        DOWNLOADED,
        "ab",
        "Dec 9",
        T0,
    )
    assert (new.status, new.on_page, new.first_seen_at) == (DISCOVERED, True, T1)
    gone = manifest.merge(entries, [revised], T1)
    assert [e.on_page for e in gone if e.sha256] == [False]


def test_bronze_file_path_uses_the_listing_year() -> None:
    assert manifest.bronze_file_path(_report()) == (
        "bronze/files/doe/ncr/year=2022/petro_ncr_2022_dec_09.pdf"
    )


def test_unknown_status_rejected() -> None:
    entry = manifest.merge([], [_report()], T0)[0]
    with pytest.raises(ValueError, match="status"):
        Entry(**{**entry.__dict__, "status": "done"})
