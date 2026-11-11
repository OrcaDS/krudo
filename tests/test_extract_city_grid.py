"""Tests for the era B/C city grid extractor, on synthetic pages and real page fixtures."""

import json
from pathlib import Path

import pytest

from ingestion.doe.classify import Unsupported
from ingestion.doe.extract import city_grid
from ingestion.doe.extract.city_grid import Cell

FIXTURES = Path(__file__).parent / "fixtures"
# Header label x-ranges: PRODUCT, two brands, OVERALL RANGE (two words), COMMON above
HEADER_Y = 50
COLUMNS = {"PETRON": (200, 240), "FLYING": (300, 330), "V": (333, 340)}


def word(text: str, x0: float, top: float, width: float = 20, height: float = 8) -> dict:
    return {"text": text, "x0": x0, "x1": x0 + width, "top": top, "bottom": top + height}


def header(top: float = HEADER_Y) -> list[dict]:
    return [
        word("COMMON", 470, top - 5, 30),
        word("PRODUCT", 100, top, 40),
        word("PETRON", 200, top, 40),
        word("FLYING", 300, top, 30),
        word("V", 333, top, 7),
        word("OVERALL", 380, top, 30),
        word("RANGE", 412, top, 25),
        word("PRICE", 475, top + 5, 20),
    ]


# Value x positions: PETRON low/high, FLYING V low/high, overall low/-/high, common
X = {"pl": 190, "ph": 235, "fl": 290, "fh": 330, "ol": 380, "dash": 404, "oh": 412, "c": 475}


def row(top: float, product: str, values: dict[str, str], label: str | None = None) -> list[dict]:
    words = [word(part, 100 + 25 * i, top) for i, part in enumerate(product.split())]
    if label:
        words += [word(part, 30 + 30 * i, top - 1) for i, part in enumerate(label.split())]
    return words + [word(text, X[key], top + 1) for key, text in values.items()]


FULL = {"pl": "60.00", "ph": "66.78", "fl": "58.40", "fh": "63.80"}
RANGE = {"ol": "58.40", "dash": "-", "oh": "66.78", "c": "#N/A"}


def cells(found: list[Cell]) -> set[tuple]:
    return {(c.city, c.product, c.brand, c.kind, c.value) for c in found}


def test_reads_brand_pairs_range_and_common_and_skips_blank_cells() -> None:
    page = [
        *header(),
        *row(70, "RON 95", {**FULL, **RANGE}),
        *row(85, "RON 91", {"pl": "59.00", "ph": "66.00", **RANGE}, label="Quezon City"),
        *row(100, "DIESEL PLUS", {"fh": "55.10"}),
    ]
    found = city_grid.extract([page])
    assert ("Quezon City", "RON 95", "FLYING V", "brand_high", "63.80") in cells(found)
    assert ("Quezon City", "RON 95", None, "overall_range", "58.40 - 66.78") in cells(found)
    assert ("Quezon City", "RON 95", None, "common", "#N/A") in cells(found)
    rows_91 = {c.brand for c in found if c.product == "RON 91" and c.brand}
    assert rows_91 == {"PETRON"}  # FLYING V is blank on this row: no cell, and nothing shifted
    assert [(c.brand, c.kind, c.value) for c in found if c.product == "DIESEL PLUS"] == [
        ("FLYING V", "brand_high", "55.10")
    ]
    assert {c.page for c in found} == {1}


def test_city_blocks_end_when_a_product_repeats() -> None:
    page = [
        *header(),
        *row(70, "RON 95", FULL, label="Caloocan City"),
        *row(85, "RON 91", FULL),
        *row(100, "RON 95", FULL),
        *row(115, "RON 91", FULL, label="Manila"),
    ]
    found = city_grid.extract([page])
    assert [c.city for c in found if c.kind == "brand_low"] == ["Caloocan City"] * 4 + [
        "Manila"
    ] * 4


def test_overlapping_ghost_label_is_dropped() -> None:
    ghost = [word("Caloocan", 31, 84.6), word("City", 61, 84.6)]  # 1.4 pt above "Makati City"
    page = [
        *header(),
        *row(55 + 15, "RON 95", FULL, label="Caloocan City"),
        *row(70 + 15, "RON 95", FULL, label="Makati City"),
        *ghost,
    ]
    found = city_grid.extract([page])
    assert {c.city for c in found} == {"Caloocan City", "Makati City"}


def test_text_across_both_sub_columns_is_one_brand_range_cell() -> None:
    no_lfro = [word("NO", 205, 71, 10), word("LFRO", 217, 71, 18)]  # spans PETRON's centre 220
    page = [*header(), *row(70, "RON 91", {"fl": "58.40"}, label="Manila"), *no_lfro]
    found = city_grid.extract([page])
    assert ("Manila", "RON 91", "PETRON", "brand_range", "NO LFRO") in cells(found)
    assert ("Manila", "RON 91", "FLYING V", "brand_low", "58.40") in cells(found)


def test_block_continues_across_a_page_break() -> None:
    page1 = [*header(), *row(70, "RON 95", FULL, label="Pasig City")]
    page2 = [*header(), *row(70, "RON 91", FULL), *row(85, "DIESEL", FULL)]
    found = city_grid.extract([page1, page2])
    assert {(c.page, c.product, c.city) for c in found} == {
        (1, "RON 95", "Pasig City"),
        (2, "RON 91", "Pasig City"),
        (2, "DIESEL", "Pasig City"),
    }


def test_common_price_strip_page_joins_its_grid_page_by_height() -> None:
    grid = [w for w in header() if w["text"] not in ("COMMON", "PRICE")]
    grid += row(70, "RON 95", FULL, label="Manila") + row(85, "RON 91", FULL)
    strip = [
        word("COMMON", 40, 30),
        word("PRICE", 45, 40),
        word("61.00", 45, 71),
        word("#N/A", 45, 86),
    ]
    found = city_grid.extract([grid, strip])
    assert {(c.page, c.product, c.value) for c in found if c.kind == "common"} == {
        (2, "RON 95", "61.00"),
        (2, "RON 91", "#N/A"),
    }


@pytest.mark.parametrize(
    ("pages", "message"),
    [
        ([[*header(), *row(70, "RON 95", FULL)]], "has labels \\[\\], 0 not used"),
        ([[w for w in header() if w["text"] != "OVERALL"]], "no 'OVERALL RANGE' column"),
        ([[*header(), word("Notes", 30, 300)]], "no product rows"),
        (
            [
                [
                    *header(),
                    *row(70, "RON 95", FULL, "Manila"),
                    *row(100, "RON 91", FULL),
                    word("61.00", X["c"], 85),
                ]
            ],
            "'61.00' sits between rows",
        ),
        (
            [[*header(), *row(70, "RON 95", FULL, "Manila")], [word("COMMON", 40, 30)]],
            "without a PRODUCT header",
        ),
    ],
)
def test_layouts_it_cannot_read_raise_unsupported(pages: list, message: str) -> None:
    with pytest.raises(Unsupported, match=message):
        city_grid.extract(pages)


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (
            ["Date of Monitoring: November 9-10, 2021 Date of Effectivity : November 9, 2021"],
            ("November 9-10, 2021", "November 9, 2021"),
        ),
        (
            [
                "Date of Monitoring: __J_u_n_e_ _1_1_-1_3__, _2_0_1_9______ "
                "Date of Effectivity: June 11, 2019"
            ],
            ("__J_u_n_e_ _1_1_-1_3__, _2_0_1_9______", "June 11, 2019"),
        ),
        (["KEROSENE 1.00", "Date of Monitoring: March 5-7,2024"], ("March 5-7,2024", None)),
        (["(For the week of November 3-9, 2026)"], (None, None)),
    ],
)
def test_report_dates_keep_raw_text(lines: list[str], expected: tuple) -> None:
    assert city_grid.report_dates(lines) == expected


@pytest.mark.parametrize("name", sorted(p.stem for p in FIXTURES.glob("city_grid_*.json")))
def test_real_pages_match_their_expected_cells(name: str) -> None:
    """Word dumps of real DOE pages (``page_words`` trimmed to the keys used) and their cells."""
    fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    found = city_grid.extract(fixture["pages"])
    assert len(found) == fixture["cell_count"]
    for expected in fixture["expected"]:
        assert Cell(**expected) in found
