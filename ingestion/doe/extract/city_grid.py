"""Eras B and C: one block of product rows per city, brands across (project.md §6.3).

The header row reads ``[AREA] PRODUCT PETRON SHELL … INDEPENDENT OVERALL RANGE``, with
``COMMON`` / ``PRICE`` stacked over the last column. Each brand spans two sub-columns, low then
high; a brand that doesn't sell a product leaves both blank, so text lines can't be split by
count. Instead every word is placed by position:

- **Rows** start at a product word (``RON``, ``DIESEL``, ``KEROSENE``). Other words join the row
  whose middle is nearest theirs; a value between rows raises ``Unsupported``.
- **Columns** come from the header: band edges halfway between header label centres, a brand's
  low/high split at its label's centre. Labels are read from the header, so a new brand
  column is picked up by name.
- **City blocks** run until a product repeats, so a block can cross a page break (Mar 2026). The
  city label sits on any row of its block. A second label drawn under it (DOE's sheet repeats
  ``Caloocan City``, 1.4 pt off) is the city an earlier block already used and is dropped.
- **Strip pages** (two 2020 reports): pages 3-4 hold only the ``COMMON PRICE`` column of pages
  1-2, at the same heights, so their values join the rows of the matching grid page.

Text is kept exactly as read (``#N/A``, ``-``, ``55.15 - 68.39``); typing happens in silver.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import median

from pdfplumber.page import Page

from ingestion.doe.classify import Unsupported

Word = dict  # a pdfplumber word: text, x0, x1, top, bottom

ROW_STARTS = {"RON", "DIESEL", "KEROSENE"}
OVERALL = "OVERALL RANGE"
ROW_TOLERANCE = 0.4  # of the row pitch: how far a word's middle may sit from its row's middle
LABEL_LINE = 0.5  # pt: label words this close in height share a line (overlapping labels don't)
_MONITORING = re.compile(r"Date of Monitoring\s*:?\s*(.*?)\s*(?=Date of Effectivity|$)", re.I)
_EFFECTIVITY = re.compile(r"Date of Effectivity\s*:?\s*(.*?)\s*$", re.I)


@dataclass(frozen=True)
class Cell:
    page: int
    city: str
    product: str
    brand: str | None  # None for the overall range and common price
    kind: str  # brand_low | brand_high | overall_range | common
    value: str


@dataclass
class _Row:
    page: int
    middle: float
    product: str
    labels: list[Word] = field(default_factory=list)
    cells: list[tuple[int, str | None, str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class _Header:
    bottom: float
    value_left: float  # words whose middle lies right of this are values
    columns: list[tuple[str, float]]  # (label, centre), left to right; COMMON last if present


def page_words(page: Page) -> list[Word]:
    """Upright, on-page words of a page, with doubled bold text removed.

    A small y-tolerance keeps overlapping city labels (1.4 pt apart) as separate words.
    """
    page = page.dedupe_chars()
    return [
        w
        for w in page.extract_words(y_tolerance=LABEL_LINE)
        if w["upright"] and w["x0"] >= 0 and w["x1"] <= page.width
    ]


def _mid_x(w: Word) -> float:
    return (w["x0"] + w["x1"]) / 2


def _mid_y(w: Word) -> float:
    return (w["top"] + w["bottom"]) / 2


def _join(words: Sequence[Word]) -> str:
    return " ".join(w["text"] for w in sorted(words, key=lambda w: w["x0"]))


def _header(words: Sequence[Word]) -> _Header | None:
    """Column labels from the row holding ``PRODUCT``; None on a page without one."""
    product = next((w for w in words if w["text"] == "PRODUCT"), None)
    if product is None:
        return None
    line = sorted(
        (
            w
            for w in words
            if abs(_mid_y(w) - _mid_y(product)) < 3
            and w["x0"] > product["x1"]
            and w["text"] not in ("COMMON", "PRICE")
        ),
        key=lambda w: w["x0"],
    )
    labels: list[list[Word]] = []
    for w in line:  # words closer than their own height belong to one label ("FLYING V")
        if labels and w["x0"] - labels[-1][-1]["x1"] < w["bottom"] - w["top"]:
            labels[-1].append(w)
        else:
            labels.append([w])
    columns = [(_join(ws), (ws[0]["x0"] + ws[-1]["x1"]) / 2) for ws in labels]
    common = next((w for w in words if w["text"] == "COMMON"), None)
    if common is not None:
        columns.append(("COMMON", _mid_x(common)))
    if not columns or OVERALL not in [label for label, _ in columns]:
        raise Unsupported(f"header has no {OVERALL!r} column: {[c for c, _ in columns]}")
    bottom = max(w["bottom"] for w in [product, *line])
    return _Header(bottom, (product["x1"] + labels[0][0]["x0"]) / 2, columns)


def _wordy(w: Word) -> bool:
    return w["text"].isalpha()


def _phrases(words: Sequence[Word]) -> list[list[Word]]:
    """A row's words, left to right, with neighbouring letter-only words joined (``NO LFRO``).

    Prices are never joined: in 2019 neighbouring price columns sit closer than text height.
    """
    result: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w["x0"]):
        near = result and w["x0"] - result[-1][-1]["x1"] < w["bottom"] - w["top"]
        if near and _wordy(w) and _wordy(result[-1][-1]):
            result[-1].append(w)
        else:
            result.append([w])
    return result


def _cell(header: _Header, x0: float, x1: float) -> tuple[str | None, str]:
    """The (brand, cell kind) of the column a value spanning x0-x1 falls in.

    A value across a brand's centre fills both its sub-columns (``NO LFRO``): ``brand_range``.
    """
    x = (x0 + x1) / 2
    columns = header.columns
    edges = [(a + b) / 2 for (_, a), (_, b) in zip(columns, columns[1:], strict=False)]
    label, centre = columns[sum(x >= edge for edge in edges)]
    if label == OVERALL:
        return None, "overall_range"
    if label == "COMMON":
        return None, "common"
    if x0 < centre < x1:
        return label, "brand_range"
    return label, "brand_low" if x < centre else "brand_high"


def _pitch(middles: Sequence[float], fallback: float) -> float:
    gaps = [b - a for a, b in zip(middles, middles[1:], strict=False)]
    return median(gaps) if gaps else fallback


def _grid_rows(number: int, words: Sequence[Word], header: _Header) -> list[_Row]:
    """A grid page's product rows, each with its city label words and value cells."""
    below = [w for w in words if w["top"] >= header.bottom]
    starts = sorted(
        (w for w in below if w["text"] in ROW_STARTS and _mid_x(w) < header.value_left),
        key=_mid_y,
    )
    if not starts:
        return []
    middles = [_mid_y(w) for w in starts]
    tolerance = ROW_TOLERANCE * _pitch(middles, 2 * (starts[0]["bottom"] - starts[0]["top"]))
    product_words: list[list[Word]] = [[w] for w in starts]
    labels: list[list[Word]] = [[] for _ in starts]
    values: list[list[Word]] = [[] for _ in starts]
    for w in below:
        if w in starts:
            continue
        i = min(range(len(starts)), key=lambda i: abs(middles[i] - _mid_y(w)))
        if abs(middles[i] - _mid_y(w)) > tolerance:
            inside = middles[0] - tolerance < _mid_y(w) < middles[-1] + tolerance
            if inside and _mid_x(w) >= header.value_left:
                raise Unsupported(f"page {number}: value {w['text']!r} sits between rows")
            continue  # outside the grid: titles, notes, the NCR-wide summary table
        if _mid_x(w) >= header.value_left:
            values[i].append(w)
        elif w["x0"] > starts[i]["x0"]:
            product_words[i].append(w)
        else:
            labels[i].append(w)
    rows = []
    for i in range(len(starts)):
        row = _Row(number, middles[i], _join(product_words[i]), labels[i])
        cells: dict[tuple[str | None, str], list[Word]] = {}
        for ws in _phrases(values[i]):
            cells.setdefault(_cell(header, ws[0]["x0"], ws[-1]["x1"]), []).extend(ws)
        row.cells = [(number, brand, kind, _join(ws)) for (brand, kind), ws in cells.items()]
        rows.append(row)
    return rows


def _add_strip(number: int, words: Sequence[Word], rows: Sequence[_Row]) -> None:
    """Join a ``COMMON PRICE``-only strip page's values to its grid page's rows by height."""
    price = next((w for w in words if w["text"] == "PRICE"), None)
    if price is None or not rows:
        raise Unsupported(f"page {number}: a page without a PRODUCT header")
    tolerance = ROW_TOLERANCE * _pitch([r.middle for r in rows], 10.0)
    for w in words:
        if w["top"] <= price["bottom"]:
            continue  # the header (the NATIONAL CAPITAL REGION label is off the page)
        row = min(rows, key=lambda r: abs(r.middle - _mid_y(w)))
        if abs(row.middle - _mid_y(w)) > tolerance:
            raise Unsupported(f"page {number}: strip value {w['text']!r} matches no row")
        row.cells.append((number, None, "common", w["text"]))


def _label_texts(words: Sequence[Word]) -> list[str]:
    """Label words as separate labels: overlapping labels differ in height by over 1 pt."""
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w["top"]):
        if lines and w["top"] - lines[-1][0]["top"] < LABEL_LINE:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [_join(line) for line in lines]


def _cities(rows: Sequence[_Row]) -> list[tuple[str, list[_Row]]]:
    """Rows grouped into city blocks (a block ends when a product repeats), with their city."""
    blocks: list[list[_Row]] = []
    for row in rows:
        if not blocks or row.product in {r.product for r in blocks[-1]}:
            blocks.append([])
        blocks[-1].append(row)
    used: set[str] = set()
    result = []
    for block in blocks:
        labels = {text for row in block for text in _label_texts(row.labels)}
        new = labels - used
        if len(new) != 1:
            raise Unsupported(
                f"page {block[0].page}: city block starting {block[0].product!r} "
                f"has labels {sorted(labels)}, {len(new)} not used before"
            )
        city = new.pop()
        used.add(city)
        result.append((city, block))
    return result


def extract(pages: Sequence[Sequence[Word]]) -> list[Cell]:
    """Every price cell of a report, from its pages' words (in page order)."""
    rows: list[_Row] = []
    grid_rows: list[list[_Row]] = []
    strips: list[tuple[int, Sequence[Word]]] = []
    for number, words in enumerate(pages, start=1):
        header = _header(words)
        if header is not None:
            grid_rows.append(_grid_rows(number, words, header))
            rows += grid_rows[-1]
        elif any(w["text"] == "COMMON" for w in words):
            strips.append((number, words))
    if strips and len(strips) != len(grid_rows):
        raise Unsupported(f"{len(strips)} COMMON PRICE strip pages for {len(grid_rows)} grids")
    for (number, words), page_rows in zip(strips, grid_rows, strict=False):
        _add_strip(number, words, page_rows)
    if not rows:
        raise Unsupported("no product rows under a PRODUCT header")
    return [
        Cell(page, city, row.product, brand, kind, value)
        for city, block in _cities(rows)
        for row in block
        for page, brand, kind, value in row.cells
    ]


def report_dates(lines: Sequence[str]) -> tuple[str | None, str | None]:
    """The raw 'Date of Monitoring' and 'Date of Effectivity' texts, if the report has them."""
    monitoring = effectivity = None
    for line in lines:
        if monitoring is None and (match := _MONITORING.search(line)):
            monitoring = match[1]
        if effectivity is None and (match := _EFFECTIVITY.search(line)):
            effectivity = match[1]
    return monitoring or None, effectivity or None
