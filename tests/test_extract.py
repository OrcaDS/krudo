"""Tests for the extract stage: which reports it reads, and how results land in the lake."""

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ingestion.common import manifest
from ingestion.common.manifest import DOWNLOADED, EXTRACTED, FAILED, Entry
from ingestion.common.storage import LocalStorage
from ingestion.doe import extract
from ingestion.doe.classify import Unsupported
from ingestion.doe.discover import Report
from ingestion.doe.extract.city_grid import Cell

NOW = datetime(2026, 11, 11, tzinfo=UTC)


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "lake")


def _entry(storage: LocalStorage, name: str = "a.pdf", era: str = "B") -> Entry:
    report = Report(f"https://x/{name}", name, "link", 2021, 0)
    entry = manifest.merge([], [report], NOW)[0]
    storage.write_bytes(f"bronze/{name}", b"%PDF-")
    return replace(
        entry,
        status=DOWNLOADED,
        lake_path=f"bronze/{name}",
        era=era,
        title_raw="NCR Prevailing Retail Pump Price as of November 11, 2021",
        report_date=date(2021, 11, 11),
    )


def _fake_pdf(monkeypatch: pytest.MonkeyPatch, cells: list[Cell] | Exception) -> None:
    """Skip pdfplumber: the extractor sees no pages and returns ``cells`` (or raises)."""

    class FakePdf:
        pages: list = []

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def fake_extract(_pages):
        if isinstance(cells, Exception):
            raise cells
        return cells

    monkeypatch.setattr(extract.pdfplumber, "open", lambda _: FakePdf())
    monkeypatch.setitem(extract.EXTRACTORS, "B", extract.Extractor("city_grid", "1", fake_extract))


def test_extracted_rows_land_in_one_file_per_pdf(
    storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_pdf(monkeypatch, [Cell(1, "Manila", "RON 91", "PETRON", "brand_low", "#N/A")])
    [entry] = extract.extract_pending(storage, [_entry(storage)])
    assert entry.status == EXTRACTED
    path = "bronze/tables/doe_prices/year=2021/part-2021-11-11-a.parquet"
    assert extract.table_path(entry) == path
    [row] = storage.read_parquet(path).to_pylist()
    assert row["value_raw"] == "#N/A"  # raw text, never typed or zeroed
    assert row["extractor_version"] == "city_grid/1"
    assert (row["city_raw"], row["source_file"], row["page"]) == ("Manila", "a.pdf", 1)
    assert manifest.load(storage) == [entry]


def test_unreadable_reports_fail_with_a_reason_and_redo_retries_them(
    storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_pdf(monkeypatch, Unsupported("header has no 'OVERALL RANGE' column"))
    [entry] = extract.extract_pending(storage, [_entry(storage)])
    assert entry.status == FAILED
    assert entry.status_reason == "extract: header has no 'OVERALL RANGE' column"
    assert extract.extract_pending(storage, [entry]) == [entry]  # not retried without --redo
    _fake_pdf(monkeypatch, [])
    [entry] = extract.extract_pending(storage, [entry], redo=True)
    assert entry.status == EXTRACTED


def test_what_waits(storage: LocalStorage) -> None:
    era_a = _entry(storage, "a.pdf", era="A")  # no extractor until milestone 5
    no_pdf = replace(_entry(storage, "b.pdf"), lake_path="bronze/missing.pdf")
    duplicate = replace(_entry(storage, "c.pdf"), status=FAILED, status_reason="same bytes")
    for entry in (era_a, no_pdf, duplicate):
        assert not extract.needs_extract(entry, storage, redo=True)
    assert not extract.needs_extract(replace(era_a, era="B", status=EXTRACTED), storage, redo=False)
