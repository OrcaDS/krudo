# Parsing notes: DOE NCR pump price PDFs

Quirks found while building the extractors, with the reports that show them. Evidence for the
layout eras is in `recon.md`; the rules are in `project.md` §6.3.

## Titles and dates (classify)
- Era A: Jan 2017 → Sep 2019. Era B: Jun 2019 → Feb 2024 (overlaps A in Sep 2019). Era C: Mar 2024 →.
- Era B title variants: `as of`, `( As of: … )`, `as ofJuly 23` (no space).
- Era C: `For the week of …` or `For the period of …`; a `(cid:10)` glyph sometimes follows the letterhead.
- The title's date wins over the URL and link text: `petro_ncr_2020_july_28` is titled July 30.
  2020-02-18 and 2020-04-16 have no readable title date and use the link date.
- Not readable: `petro_mm_2019_may_28_updated` and `petro_ncr_2021_oct_21` are scanned images
  (no OCR, decided 2026-11-11); `priceadj_fuels_2024_feb_5_7` is a price-adjustment notice.

## City grid (eras B and C)
- **Header**: always `[AREA] PRODUCT PETRON SHELL CALTEX PHOENIX TOTAL FLYING V UNIOIL SEAOIL
  PTT INDEPENDENT OVERALL RANGE`, with `COMMON` / `PRICE` stacked over the last column (in
  some era C reports on the same text line). Era B has a `Cities | NATIONAL CAPITAL REGION`
  row under the header with no values.
- **Blank brand cells** shift text columns, so values are placed by x-position against the
  header labels, never by count. Each brand has a low and a high sub-column.
- **City label row**: the middle row of the block up to 2025 (`Caloocan City RON 91 …`); in 2026
  it can sit on the first row (`Parañaque City RON 100 …`). Blocks are found by product order
  (a new block starts when a product repeats), and the label is any label in the block.
- **Ghost labels**: from 2024 a second `Caloocan City` label is drawn 1.4 pt off the label of
  another block (`CMalaokoactai nC iCtyity`, `MCuanlotioncluapna C Citiyty` in plain text). Words
  are read with a 0.5 pt line tolerance so the two stay apart; the label already used by an
  earlier block is dropped.
- **Block across a page break**: `ncr_price_monitoring_03172026` starts Makati's block on page 1
  and ends it on page 2, which repeats `Makati City` above its header and puts the ghost
  `Caloocan City` on the KEROSENE row.
- **COMMON PRICE strip pages**: `petro_ncr_2020_may_14` and `petro_ncr_2020_aug_27` have 4
  pages; pages 3-4 hold only the COMMON PRICE column of pages 1-2, at the same heights.
- **Overall range** is kept as one raw cell: usually `55.15 - 68.39`, sometimes without the
  dash (`96.20 97.20`, `132.20 132.20`). Silver splits it.
- **Doubled bold text** (`NNAATTIIOONNAALL`): `dedupe_chars()` before reading words.
- **Rotated letterhead** under the 2026 grids (`R e p u b lic o f th e P h ilip`): not upright,
  so it is skipped.
- **NCR-wide summary table** (2026, page 2 under the grid): `Product | Overall Range | Common
  Price` for Gasoline (RON97/100), (RON95), (RON91), Diesel, Diesel Plus, Kerosene. Not
  extracted in v1 (decided 2026-11-12): it lies outside the grid and repeats what the
  city rows give.
- **`NO LFRO`** (from 2024) is one label centred across both of a brand's sub-columns. Letter-only
  words closer than their height are joined, and a value across the brand's centre becomes a
  `brand_range` cell. Prices are never joined: in 2019 neighbouring price columns sit closer
  than text height.
- **Missing and odd values** stay raw in bronze: `#N/A` (8,244 cells), `NONE` (3,193, common
  price), `NO LFRO` (904), `#VALUE!` (39), `-`, blank (no row), `0.00`, and one typo `68.3.9`.
  Silver turns the missing tokens into NULL and flags the rest.
- **DOE's own inconsistencies** (kept, flagged in silver): 26 rows whose common price lies outside
  the overall range, 5 brand pairs with high `0.00` (Valenzuela DIESEL PLUS, Jun-Jul 2026),
  7 rows with no overall range, 15 brands with only one of low/high (Taguig, Oct 2024).
- `Date of Monitoring` is in the title area in era B (2019: underlined, read as
  `__J_u_n_e_ _1_1_-1_3__`) and at the end of the last page in era C. Era C has no
  `Date of Effectivity`.
- City spellings kept raw: `Taguig Cty`, `Manila` / `Manila City`.

## How the extractor was checked (milestone 4)
A checker script read every era B/C page: all 373 reports extract (228,717 cells, none
failed). Two checks share no code with the extractor: for every report the values match the
`extract_text()` lines token for token (except the two strip-page reports, whose COMMON values
are on separate lines), and on every row the overall range equals the min and max of the brand
prices, which would fail if a value landed under the wrong brand. A third check clusters each
page's value x-positions into physical columns and confirms each maps to exactly one slot.

## Metro matrix (era A)
- **No cities**: one Metro Manila table per report, product rows × brand columns; `city_raw` is
  NULL. 7 brands: Petron, Shell, Caltex, Total, Flying V, Unioil, Seaoil.
- **Jan-Mar 2017** (`petro_mm_2017_january_03`): uppercase `PRODUCT CALTEX PETRON SHELL SEAOIL
  FLYING V`, then a second block `PRODUCT UNIOIL TOTAL` with the same product rows. One cell per
  brand, `41.40-47.05` or a lone price (`35.65`): `brand_range`. Empty rows in block 2 are
  skipped. One typo kept raw: `42.45-48.799` (Feb 14).
- **Apr 2017 on**: one block, low and high sub-columns per brand. `Overall Range` (two cells,
  `overall_low` / `overall_high`) and `Common Price` columns from Aug 2017.
- **Separate common-price tables**: Feb-Mar 2017 a small `Common Price` table right of the
  grid, below `Effectivity` (product names like `Premium Plus RON 97`); Apr-Jul 2017 a
  `COMMON PRICES OF PETROLEUM PRODUCTS IN METRO MANILA` table under the grid (on page 2 in
  `petro_mm_2017_may31`). `Aug 2, 2017` has neither.
- **Header labels wrap** over up to three lines and `Product` sits on any of them
  (`petro_mm_2019_may_15`: `Flying` / `Common` above, `V` / `Overall Range` / `Price` below).
  Words that overlap across lines, or sit on one line closer than their height, are one label.
  `Coommon Price` (Jan 31, 2019) is a common label.
- **Label positions vary label by label**: centred over a brand's two sub-columns (2017), over
  the low one (Jul 2018), or a few points left of it (Jul 2017 `Flying V`), and a brand's
  empty columns may be drawn narrower (Jan 2018 `Total`). So no rule from label positions held;
  columns come from the prices, and the header only gives their order and count. The white
  rectangles behind the text are not cell borders.
- **A brand missing from the header**: `petro_mm_2018_january_12` / `_17` have no `Total` label
  and no Total prices; the count still matches.
- **Product names**: `Gasoline` on the line above `(RON97)` (2017-2018), on one line (2019), or
  on their own line *under* each row of prices (`petro_mm_2017_mar31`, grid and common table).
  `extract_text()` reads that report's prices as `39. 85`; `extract_words()` reads `39.85`.
- **Effectivity**: `Effectivity: July 4, 2018` under the grid; `petro_mm_2017_september_27`
  has none. There is no monitoring date (the title's `As of` date is the report date).
- **DOE's own inconsistencies** (kept, flagged in silver): Unioil low above high on three
  products in `petro_mm_2017_may18`, `_may31`, `_august_09` (values sit under Unioil's columns);
  Total Diesel Plus low above high (`42.49` / `40.04`) on Feb 7, 2019, whose overall low (`40.45`)
  skips Total's `40.04`;
  overall range off the brand prices on Aug 2 and Aug 16, 2018 and Jan 31, 2019; Kerosene
  common price `NONE` on Sep 6, 2018; `3700` (Seaoil Kerosene low, Aug 2, 2017; Seaoil has no high that row).

## Found in silver/gold (milestone 6)
- **Overlapping city labels, same spot**: on page 2 of `ncr_price_monitoring_01062026` and
  `_01132026`, "Makati City" is typed exactly over "Caloocan City" (same x and y), so the label
  reads `CMalaokoactai nC iCtyity`. It is Makati: Caloocan has its own block on page 1, and
  Makati sits in this block in the reports before and after. Bronze keeps the text; the
  `cities` seed maps it to Makati.
- **Title date of the wrong week**: `petro_ncr_2021_dec_21` says "as of December 14, 2021"; its
  file name, link and monitoring period say December 21.
- **Stale effectivity date**: `petro_ncr_2019_november_19` says effectivity "November 12, 2019"
  (last week's); its monitoring period is November 19-21. So `week_start` reads the monitoring
  period first. Holidays push the monitoring start to Wednesday or Thursday in 6 other
  reports; `week_start` is that week's Tuesday either way.
- **Era B typos** (kept, flagged `is_out_of_bounds` in gold): Petron RON 91 low `2.68` in
  Caloocan (Dec 21, 2021, also the overall low); Petron Diesel Plus high `850.31` in Manila
  (Nov 17, 2022, also the overall high).
- **0 / 0.00 prices**: 69 brand cells and 45 overall ranges print `0.00` where other weeks have
  a blank; silver reads 0 as NULL.

## How era A was checked (milestone 5)
A checker script read all 109 era A reports: all extract, none fail. Checks that share no code
with the extractor: every price token of each page's `extract_text()` (minus title, date and
`RON` numbers) is emitted exactly once; where an overall range exists it equals the min and max
of the brand prices; each brand's low is at most its high; the common price lies in the brand
range. The only misses are DOE's own inconsistencies listed above, each checked by hand
against word positions.
