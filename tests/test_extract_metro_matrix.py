"""Tests for the era A metro matrix extractor, on synthetic pages and real page fixtures."""

import json
from pathlib import Path

import pytest

from ingestion.doe.classify import Unsupported
from ingestion.doe.extract import metro_matrix
from ingestion.doe.extract.city_grid import Cell

FIXTURES = Path(__file__).parent / "fixtures"


def word(text: str, x0: float, top: float, width: float = 20, height: float = 8) -> dict:
    return {"text": text, "x0": x0, "x1": x0 + width, "top": top, "bottom": top + height}


def line(top: float, *words: tuple[str, float]) -> list[dict]:
    return [word(text, x0, top) for text, x0 in words]


AS_OF = line(20, ("As", 300), ("of", 322), ("May", 344), ("15,", 366), ("2019", 388))
EFFECTIVITY = line(200, ("Effectivity:", 40), ("May", 62), ("14,", 84), ("2019", 106))


def cells(found: list[Cell]) -> set[tuple]:
    return {(c.product, c.brand, c.kind, c.value) for c in found}


def test_wrapped_labels_and_names_and_an_empty_brand_pair() -> None:
    """``Flying`` over ``V`` and ``Common`` over ``Price`` are one label each; ``Gasoline``
    over ``(RON97)`` is one product; nobody priced Total, so its two columns are empty."""
    page = [
        *AS_OF,
        *line(40, ("Flying", 260), ("Common", 380)),
        *line(48, ("Petron", 105), ("Total", 185), ("Overall", 320), ("Range", 342)),
        *line(56, ("Product", 20), ("V", 266), ("Price", 382)),
        *line(70, ("Gasoline", 20)),
        *line(80, ("(RON97)", 20), ("50.00", 100), ("55.00", 140), ("51.00", 260)),
        *line(80, ("56.00", 300), ("50.00", 320), ("56.00", 340), ("53.00", 390)),
        *line(95, ("Diesel", 20), ("40.00", 100), ("44.00", 140), ("41.00", 260), ("NONE", 390)),
        *EFFECTIVITY,
    ]
    assert cells(metro_matrix.extract([page])) == {
        ("Gasoline (RON97)", "Petron", "brand_low", "50.00"),
        ("Gasoline (RON97)", "Petron", "brand_high", "55.00"),
        ("Gasoline (RON97)", "Flying V", "brand_low", "51.00"),
        ("Gasoline (RON97)", "Flying V", "brand_high", "56.00"),
        ("Gasoline (RON97)", None, "overall_low", "50.00"),
        ("Gasoline (RON97)", None, "overall_high", "56.00"),
        ("Gasoline (RON97)", None, "common", "53.00"),
        ("Diesel", "Petron", "brand_low", "40.00"),
        ("Diesel", "Petron", "brand_high", "44.00"),
        ("Diesel", "Flying V", "brand_low", "41.00"),
        ("Diesel", None, "common", "NONE"),
    }


def test_stacked_blocks_of_ranges_and_a_common_table_below() -> None:
    """Early 2017: each ``PRODUCT`` header starts a block of ``low-high`` cells (a lone price
    too is a ``brand_range``); the common prices sit in their own table after the grid."""
    page = [
        *AS_OF,
        *line(40, ("PRODUCT", 20), ("CALTEX", 100), ("PETRON", 200)),
        *line(50, ("DIESEL", 20), ("30.45-32.99", 95), ("35.65", 205)),
        *line(80, ("PRODUCT", 20), ("UNIOIL", 100)),
        *line(90, ("DIESEL", 20), ("29.70-32.50", 95)),
        *line(100, ("KEROSENE", 20)),
        *EFFECTIVITY,
        *line(220, ("Common", 300), ("Price", 322)),
        *line(230, ("Premium", 300), ("RON", 322), ("95", 344), ("47.58", 400)),
    ]
    assert cells(metro_matrix.extract([page])) == {
        ("DIESEL", "CALTEX", "brand_range", "30.45-32.99"),
        ("DIESEL", "PETRON", "brand_range", "35.65"),
        ("DIESEL", "UNIOIL", "brand_range", "29.70-32.50"),
        ("Premium RON 95", None, "common", "47.58"),
    }


HEADER = line(40, ("Product", 20), ("Petron", 105))


@pytest.mark.parametrize(
    ("page", "message"),
    [
        (
            [
                *AS_OF,
                *HEADER,
                *line(
                    60,
                    ("Diesel", 20),
                    *[(v, 100 + 40 * i) for i, v in enumerate(["1.0", "2.0", "3.0"])],
                ),
            ],
            "3 value columns for 2",
        ),
        ([*AS_OF, *line(60, ("Diesel", 20), ("40.00", 100))], "values before a header"),
        ([*line(10, ("Diesel", 20), ("40.00", 100))], "prices outside the table"),
        (
            [
                *AS_OF,
                *HEADER,
                *line(60, ("Diesel", 20), ("40.00", 100), ("44.00", 140)),
                *line(70, ("41.00", 100)),
            ],
            "no product name",
        ),
        (
            [
                *AS_OF,
                *HEADER,
                *line(60, ("Diesel", 20), ("40.00", 100), ("44.00", 140)),
                *line(70, ("Diesel", 20), ("41.00", 100)),
            ],
            "two values for one cell",
        ),
        ([*AS_OF], "no price rows"),
    ],
)
def test_layouts_it_cannot_read_raise_unsupported(page: list, message: str) -> None:
    with pytest.raises(Unsupported, match=message):
        metro_matrix.extract([page])


def test_report_dates_read_the_effectivity_line() -> None:
    lines = ["As of July 6, 2018", "Diesel 41.80 46.15", "Effectivity: July 4, 2018"]
    assert metro_matrix.report_dates(lines) == (None, "July 4, 2018")
    assert metro_matrix.report_dates(["As of September 27, 2017"]) == (None, None)


# Cells read by eye off the PDFs, so the fixtures don't only check the extractor against itself
BY_EYE = {
    "metro_matrix_2017_01_03": [
        ("GASOLINE (RON 91)", "CALTEX", "brand_range", "41.40-47.05"),
        ("KEROSENE", "SEAOIL", "brand_range", "35.65"),
        ("DIESEL", "TOTAL", "brand_range", "33.10-33.80"),
    ],
    "metro_matrix_2017_02_14": [
        ("GASOLINE (RON 95)", "SHELL", "brand_range", "42.45-48.799"),  # DOE's typo, kept
        ("Premium Plus RON 97", None, "common", "49.79"),
    ],
    "metro_matrix_2017_03_31": [  # names sit under their prices
        ("Gasoline (RON97)", "Seaoil", "brand_low", "42.20"),
        ("Kerosene", "Caltex", "brand_high", "40.93"),
        ("Kerosene", None, "common", "36.70"),
    ],
    "metro_matrix_2018_01_24": [  # Total and Seaoil columns empty in some rows
        ("Gasoline (RON95)", "Flying V", "brand_low", "48.92"),
        ("Gasoline (RON95)", "Unioil", "brand_high", "49.99"),
        ("Gasoline (RON95)", None, "overall_low", "45.80"),
        ("Gasoline (RON95)", None, "common", "51.97"),
    ],
    "metro_matrix_2019_05_15": [  # three-line header; Flying V's label sits over its low column
        ("Gasoline (RON95)", "Flying V", "brand_low", "45.75"),
        ("Gasoline (RON95)", "Flying V", "brand_high", "57.44"),
        ("Kerosene", None, "overall_high", "58.95"),
    ],
}


@pytest.mark.parametrize("name", sorted(p.stem for p in FIXTURES.glob("metro_matrix_*.json")))
def test_real_pages_match_their_expected_cells(name: str) -> None:
    """Word dumps of real DOE pages (``page_words`` trimmed to the keys used) and their cells."""
    fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    found = metro_matrix.extract(fixture["pages"])
    assert len(found) == fixture["cell_count"]
    for expected in fixture["expected"]:
        assert Cell(**expected) in found
    assert set(BY_EYE[name]) <= cells(found)
