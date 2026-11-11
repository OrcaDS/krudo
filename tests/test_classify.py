"""Tests for reading era and report date from a DOE PDF's title lines."""

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ingestion.common import manifest
from ingestion.common.manifest import DOWNLOADED, FAILED
from ingestion.common.storage import LocalStorage
from ingestion.doe import classify
from ingestion.doe.classify import Title, Unsupported, parse_date, read_title
from ingestion.doe.discover import Report

ERA_A = [
    "PREVAILING RETAIL PRICES OF PETROLEUM PRODUCTS IN METRO MANILA",
    "As of January 10, 2017",
    "PRODUCT CALTEX PETRON SHELL",
]
ERA_B = [
    "NCR Prevailing Retail Pump Price as of March 12, 2020",
    "Date of Monitoring: March 10-11, 2020 Date of Effectivity : March 10, 2020",
]
ERA_C = [
    "Republic of the Philippines",
    "Department of Energy",
    "Oil Industry Management Bureau",
    "Price Monitoring of Liquid Fuels",
    "NCR",
    "(For the week of December 29 - January 4, 2027)",
    "AREA PRODUCT PETRON SHELL",
]


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (
            ERA_A,
            Title("A", " | ".join(ERA_A[:2]), date(2017, 1, 10)),
        ),
        (ERA_B, Title("B", ERA_B[0], date(2020, 3, 12))),
        (ERA_C, Title("C", " | ".join(ERA_C[3:6]), date(2026, 12, 29))),
    ],
)
def test_read_title(lines: list[str], expected: Title) -> None:
    assert read_title(lines) == expected


@pytest.mark.parametrize(
    "line",
    [
        "NCR Prevailing Retail Pump Price as ofJuly 23, 2020",
        "NCR Prevailing Retail Pump Price ( As of: July 23, 2020 )",
    ],
)
def test_era_b_title_variants(line: str) -> None:
    assert read_title([line]) == Title("B", line, date(2020, 7, 23))


def test_era_c_for_the_period_of() -> None:
    lines = [*ERA_C[:5], "(For the period of March 5-11, 2024)"]
    assert read_title(lines).report_date == date(2024, 3, 5)


def test_title_without_a_date_line() -> None:
    assert read_title(ERA_C[:5]) == Title("C", ERA_C[3], None)


def test_unknown_title_raises() -> None:
    with pytest.raises(Unsupported, match="Price Adjustment"):
        read_title(["Price Adjustment of Petroleum Products", "Effective February 6, 2024"])
    with pytest.raises(Unsupported, match="scanned image"):
        read_title(["", "  "])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("January 10, 2017", date(2017, 1, 10)),
        ("Sept. 2,2021", date(2021, 9, 2)),
        ("August 25-31, 2026", date(2026, 8, 25)),
        ("September 29 - October 5, 2026", date(2026, 9, 29)),
        ("December 29 - January 4, 2027", date(2026, 12, 29)),
        ("December 30, 2025 - January 5, 2026", date(2025, 12, 30)),
        ("(For the period of March 5-11, 2024)", date(2024, 3, 5)),
        ("February 30, 2021", None),
        ("March 10", None),  # no year
    ],
)
def test_parse_date(text: str, expected: date | None) -> None:
    assert parse_date(text) == expected


def _entry(storage: LocalStorage, link_text: str = "December 9"):
    report = Report("https://x/a", "a.pdf", link_text, 2022, 0)
    entry = manifest.merge([], [report], datetime(2026, 11, 11, tzinfo=UTC))[0]
    storage.write_bytes("bronze/a.pdf", b"%PDF-")
    return replace(entry, status=DOWNLOADED, lake_path="bronze/a.pdf")


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "lake")


def test_classify_pending_falls_back_to_the_link_date(
    storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(classify, "title_of", lambda _: Title("B", "NCR ... as of", None))
    [entry] = classify.classify_pending(storage, [_entry(storage)])
    assert (entry.era, entry.report_date, entry.date_source, entry.status) == (
        "B",
        date(2022, 12, 9),
        "link_text",
        DOWNLOADED,
    )
    assert manifest.load(storage) == [entry]


def test_classify_failures_are_recorded_and_retried(
    storage: LocalStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unsupported(_: bytes) -> Title:
        raise Unsupported("no known title")

    monkeypatch.setattr(classify, "title_of", unsupported)
    [entry] = classify.classify_pending(storage, [_entry(storage)])
    assert (entry.status, entry.status_reason) == (FAILED, "classify: no known title")

    monkeypatch.setattr(classify, "title_of", lambda _: Title("A", "t", date(2017, 1, 10)))
    [entry] = classify.classify_pending(storage, [entry])
    assert (entry.status, entry.status_reason, entry.date_source) == (DOWNLOADED, None, "title")


def test_no_date_anywhere_fails(storage: LocalStorage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(classify, "title_of", lambda _: Title("C", "t", None))
    [entry] = classify.classify_pending(storage, [_entry(storage, link_text="Latest")])
    assert entry.status == FAILED and entry.era == "C"
