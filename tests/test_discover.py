"""Tests for DOE report discovery from the listing page."""

from datetime import date
from pathlib import Path

import pytest

from ingestion.doe.discover import date_from_link, discover, revision_level, safe_name

LISTING = (Path(__file__).parent / "fixtures" / "doe_listing.html").read_text(encoding="utf-8")


def test_discover_finds_report_links_once_with_their_year_row() -> None:
    reports = discover(LISTING)
    assert [(r.file_name, r.listing_year) for r in reports] == [
        ("ncr_price_monitoring_for_3_to_9_november_2026.pdf", 2026),
        ("ncr_price_monitoring_10062026.pdf", 2026),
        ("petro_ncr_2020_march_17_0.pdf", 2020),
        ("petro_ncr_2020_january_03.pdf", 2020),  # listed twice on the page, kept once
        ("petro_mm_2017_feb_7_updated.pdf", 2017),
        ("petro_ncr_2025_apr_1_7.pdf", 2017),  # the year row wins over the slug
    ]
    assert reports[1].link_text == "October 6 to 12"
    assert all(r.source_url.startswith("https://") for r in reports)
    assert [r.revision_level for r in reports] == [0, 0, 1, 0, 1, 0]


def test_a_name_shared_by_two_urls_gets_a_suffix() -> None:
    html = "<strong>2020</strong>" + "".join(
        f'<a href="https://prod-cms.doe.gov.ph/documents/d/{folder}/petro_ncr_x">x</a>'
        for folder in ("oimb", "guest")
    )
    assert [r.file_name for r in discover(html)] == ["petro_ncr_x.pdf", "petro_ncr_x_dup.pdf"]


def test_links_outside_a_year_row_are_skipped() -> None:
    html = '<a href="https://prod-cms.doe.gov.ph/documents/d/oimb/petro_ncr_x">x</a>'
    assert discover(html) == []


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://prod-cms.doe.gov.ph/documents/d/oimb/petro_ncr_2023-apr-09-pdf",
            "petro_ncr_2023_apr_09.pdf",
        ),
        (
            "https://x.cloudfront.net/api/media/file/NCR%20Price%20Monitoring%2010062026.pdf?p=d",
            "ncr_price_monitoring_10062026.pdf",
        ),
    ],
)  # fmt: skip
def test_safe_name(url: str, expected: str) -> None:
    assert safe_name(url) == expected


@pytest.mark.parametrize(
    ("name", "level"),
    [
        ("petro_mm_2018_february_15_edited.pdf", 1),
        ("petro_ncr_2022_jul_14_1.pdf", 1),
        ("petro_ncr_2024_jul_16_22_0.pdf", 1),
        ("petro_ncr_2024_dec_3_9.pdf", 0),  # a date range, not a re-upload
        ("petro_mm_2017_feb_7.pdf", 0),
    ],
)
def test_revision_level(name: str, level: int) -> None:
    assert revision_level(name) == level


def test_date_from_link() -> None:
    assert date_from_link("October 27 to November 2", 2026) == date(2026, 10, 27)
    assert date_from_link("Sept. 2", 2021) == date(2021, 9, 2)
    assert date_from_link("February 30", 2021) is None
    assert date_from_link("Latest", 2021) is None
