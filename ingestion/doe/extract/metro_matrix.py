"""Era A (Jan 2017 → Sep 2019): one Metro Manila table, product rows × brand columns.

Shapes (project.md §6.3, docs/parsing_notes.md):

- **Jan-Mar 2017**: brands in two stacked blocks (``PRODUCT CALTEX … FLYING V``, then
  ``PRODUCT UNIOIL TOTAL``), one cell per brand, ``41.40-47.05`` or a single price:
  ``brand_range``.
- **Apr 2017 on**: one block; each brand has a low and a high sub-column (``brand_low`` /
  ``brand_high``). From Aug 2017 also ``Overall Range`` (``overall_low`` / ``overall_high``)
  and ``Common Price`` (``common``).
- **Separate common-price tables** under the grid or on page 2 (Feb-Jul 2017): one product name
  and one price per row.
- Header labels wrap over up to three lines (``Flying`` over ``V``, ``Common`` over ``Price``)
  and ``Product`` sits on any of them. Product names wrap (``Gasoline`` over ``(RON97)``), and
  in Mar 2017 sit on their own line under each row of prices.

Labels sit centred over their columns, over the low one, or a little left of it, label by label,
so columns come from the prices instead: price x-positions are grouped into columns, a column
nobody priced that week is filled in from the regular spacing, and the count must match the
header's slots (two per brand and for the overall range, one for the common price) or the
report fails.

Text is kept exactly as read (``3700``); typing happens in silver. ``city`` is None throughout.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from itertools import pairwise
from statistics import median

from ingestion.doe.classify import Unsupported
from ingestion.doe.extract.city_grid import Cell, Word, _join, _mid_x

PRICE = re.compile(r"[\d.,-]*\d[\d.,-]*")  # fullmatch: a price, a range, or a DOE typo of one
DOTTED = re.compile(r".*\d\.\d.*")  # a common-table price (its product names hold numbers: RON 97)
RANGED = re.compile(r"\d-\d")
COMMON = re.compile(r"co+mmon", re.I)  # one header spells it "Coommon"
LINE = 3  # pt: words whose tops are this close share a line
COLUMN = 10  # pt: prices whose centres are this close share a column
_EFFECTIVITY = re.compile(r"^\s*Effectivity\s*:?\s*(.*?)\s*$", re.I)

Row = tuple[list[Word], list[Word], list[Word]]  # names on the line, names line above, values


def _is_price(w: Word) -> bool:
    return PRICE.fullmatch(w["text"]) is not None


def _text(words: Sequence[Word]) -> str:
    return " ".join(w["text"] for w in words)


def _lines(words: Sequence[Word]) -> list[list[Word]]:
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w["top"]):
        if lines and w["top"] - lines[-1][0]["top"] < LINE:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _sections(lines: Sequence[list[Word]]) -> tuple[list[list[Word]], list[list[Word]]]:
    """A page's (grid, common-price table) lines: the grid runs from ``As of`` to
    ``Effectivity``; a table from its ``Common Price…`` title (after the grid) to the end."""
    grid: list[list[Word]] = []
    common: list[list[Word]] = []
    part: list[list[Word]] | None = None
    for line in lines:
        text = _join(line).lower()
        if text.startswith("as of"):
            part = part if part is not None else grid
        elif text.startswith("effectivity"):
            part = None
        elif part is None and text.startswith("common"):
            part = common
        elif part is not None:
            part.append(line)
        elif any(_is_price(w) for w in line):
            raise Unsupported(f"prices outside the table: {_join(line)!r}")
    return grid, common


def _products(rows: Sequence[Row], loose: Sequence[list[Word]]) -> list[str]:
    """Each row's product name. When no price line carries a name (Mar 2017), the name-only
    lines are the names, in order. Otherwise a name starting with ``(`` continues the line
    above (``Gasoline`` / ``(RON97)``)."""
    if all(not names for names, _, _ in rows):
        if len(loose) != len(rows):
            raise Unsupported(f"{len(loose)} product names for {len(rows)} price rows")
        return [_text(names) for names in loose]
    result = []
    for names, above, values in rows:
        if names and names[0]["text"].startswith("("):
            names = above + names
        if not names:
            raise Unsupported(f"no product name: {_text(values)!r}")
        result.append(_text(names))
    return result


def _labels(words: Sequence[Word]) -> list[str]:
    """Header labels left to right. Words join one label when they share a line less than
    their height apart (``Overall Range``) or overlap across lines (``Flying`` over ``V``)."""
    groups: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w["x0"]):
        group = next(
            (
                g
                for g in groups
                for v in g
                if w["x0"] < v["x1"]
                or (abs(w["top"] - v["top"]) < LINE and w["x0"] - v["x1"] < w["bottom"] - w["top"])
            ),
            None,
        )
        if group is None:
            groups.append([w])
        else:
            group.append(w)
    return [" ".join(_join(line) for line in _lines(g)) for g in groups]


def _slots(labels: Sequence[str], ranged: bool) -> Iterator[tuple[str | None, str]]:
    """(brand, cell kind) of each value column the header implies, left to right."""
    for label in labels:
        if COMMON.search(label):
            yield None, "common"
        elif "overall" in label.lower():
            yield from [(None, "overall_low"), (None, "overall_high")]
        elif ranged:
            yield label, "brand_range"
        else:
            yield from [(label, "brand_low"), (label, "brand_high")]


def _columns(values: Sequence[Word], slots: Sequence[tuple[str | None, str]]) -> dict[int, tuple]:
    """Map each value (by ``id``) to its slot. Columns come from the values' x-centres. The
    header says how many columns there are, so the ones nobody priced that week go into the
    gaps that best fit the usual column pitch (empty columns may be drawn narrower, Jan 2018).
    The common price sits apart (wider gap), so it is the last column, outside the pitch."""
    columns: list[list[Word]] = []
    for v in sorted(values, key=_mid_x):
        if columns and _mid_x(v) - _mid_x(columns[-1][-1]) < COLUMN:
            columns[-1].append(v)
        else:
            columns.append([v])
    has_common = slots[-1][1] == "common"
    body = columns[:-1] if has_common else columns
    missing = len(slots) - has_common - len(body)
    gaps = [b - a for a, b in pairwise(median(_mid_x(v) for v in c) for c in body)]
    if missing < 0 or (missing and not gaps):
        raise Unsupported(f"{len(columns)} value columns for {len(slots)} header slots: {slots}")
    pitch = median(gaps) if gaps else 0.0
    empty = [0] * len(gaps)
    for _ in range(missing):  # each to the gap where it costs least: |gap - columns * pitch|
        i = min(
            range(len(gaps)),
            key=lambda i: (
                abs(gaps[i] - (empty[i] + 2) * pitch) - abs(gaps[i] - (empty[i] + 1) * pitch)
            ),
        )
        empty[i] += 1
    placed: list[list[Word] | None] = body[:1]
    for n, column in zip(empty, body[1:], strict=True):
        placed += [None] * n + [column]
    if has_common:
        placed.append(columns[-1])
    return {id(v): slot for column, slot in zip(placed, slots, strict=True) for v in column or []}


def _grid(number: int, lines: Sequence[list[Word]]) -> list[Cell]:
    """Cells of the product × brand grid. Lines without prices hold header labels (right of
    the first price column) or product names (left of it). Each header starts a block."""
    prices = [w for line in lines for w in line if _is_price(w)]
    if not prices:
        return []
    left = min(w["x0"] for w in prices)
    ranged = any(RANGED.search(w["text"]) for w in prices)
    blocks: list[tuple[list[str], list[Row]]] = []
    header: list[Word] = []
    loose: list[list[Word]] = []
    above: list[Word] = []
    for line in lines:
        names = [w for w in line if w["x1"] < left and w["text"].lower() != "product"]
        values = [w for w in line if w["x1"] >= left]
        if not any(_is_price(w) for w in values):
            if any(re.search(r"\d", w["text"]) for w in values):
                raise Unsupported(f"digits in a header line: {_join(line)!r}")
            header += values
            if names:
                loose.append(names)
                above = names
            continue
        if header:
            blocks.append((_labels(header), []))
            header = []
        if not blocks:
            raise Unsupported(f"values before a header: {_join(line)!r}")
        blocks[-1][1].append((names, above, values))
        above = []
    cells = []
    products = _products([row for _, rows in blocks for row in rows], loose)
    for labels, rows in blocks:
        values = [v for _, _, vs in rows for v in vs]
        slots = _columns(values, list(_slots(labels, ranged)))
        for (_, _, vs), product in zip(rows, products, strict=False):
            cells += [Cell(number, None, product, *slots[id(v)], v["text"]) for v in vs]
        products = products[len(rows) :]
    return cells


def _common(number: int, lines: Sequence[list[Word]]) -> list[Cell]:
    """Cells of a separate common-price table: a product name and its price per row."""
    rows: list[Row] = []
    loose = []
    for line in lines:
        if DOTTED.fullmatch(line[-1]["text"]):
            rows.append((line[:-1], [], [line[-1]]))
        elif _join(line).lower() != "product":
            loose.append(line)
    if not rows:
        return []
    products = _products(rows, loose)
    return [
        Cell(number, None, product, None, "common", values[0]["text"])
        for (_, _, values), product in zip(rows, products, strict=True)
    ]


def extract(pages: Sequence[Sequence[Word]]) -> list[Cell]:
    """Every price cell of a report, from its pages' words (in page order)."""
    cells: list[Cell] = []
    for number, words in enumerate(pages, start=1):
        grid, common = _sections(_lines(words))
        cells += _grid(number, grid) + _common(number, common)
    if not cells:
        raise Unsupported("no price rows under a header")
    seen: set[tuple[str, str | None, str]] = set()
    for c in cells:
        key = (c.product, c.brand, c.kind)
        if key in seen:
            raise Unsupported(f"two values for one cell {key}: columns misread")
        seen.add(key)
    return cells


def report_dates(lines: Sequence[str]) -> tuple[str | None, str | None]:
    """Era A has no monitoring period (the title date is it); effectivity is its own line."""
    effectivity = next((m[1] for line in lines if (m := _EFFECTIVITY.match(line))), None)
    return None, effectivity or None
