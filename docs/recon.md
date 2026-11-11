# Recon: DOE NCR retail pump prices

Checked 2026-11-11. Evidence for the krudo spec: where the data is, what it looks like, and what will be hard.

## 1. Source

- **Listing page:** <https://doe.gov.ph/data-and-prices/liquid-fuels/retail-pump-prices/ncr-pump-prices>.
  One server-rendered HTML page links **every** NCR report (no pagination, no JavaScript needed). Plain `GET` + parse `<a href>`.
- **The legacy site is gone.** `legacy.doe.gov.ph` no longer resolves, and `doe.gov.ph/retail-pump-prices-metro-manila` returns a 404. Older guides and scrapers that point there are dead.
- **Two file hosts:**
  - `prod-cms.doe.gov.ph/documents/d/{oimb|guest}/<slug>`: 477 links, Jan 2017 to Aug 2026. Some are `http://`; fetch as `https://`.
  - `d24qbtp4vooyzi.cloudfront.net/api/media/file/<name>.pdf`: 11 links, Aug 2026 to the latest (3–9 Nov 2026). This is the new CMS.
- **Cadence:** weekly. Prices take effect on Tuesday, and the report covers Tuesday to the following Monday. 2017–19 reports came out roughly weekly, with some weeks having two.
- **Licence:** the site footer says *"All content is in the public domain unless otherwise stated."* Republishing is fine; credit DOE-OIMB anyway.
- **robots.txt:** none (the URL returns the 404 HTML page). Be polite anyway: sequential requests, ≥5 s apart, descriptive User-Agent.
- Sibling pages with the same structure, for later scope: `north-luzon-pump-prices`, `south-luzon-…`, `visayas-pump-prices`, `mindanao-pump-prices`, `price-adjustments`, plus `/data-and-prices/lpg-monitor`.
- Checked: PSA OpenSTAT has no NCR fuel price table that turned up in search. CEIC sells a monthly series. PhilRice mirrors DOE data only to 2021. **This weekly brand × city data is not available anywhere as open data**, which is the case for building krudo.

## 2. Report count by year (NCR)

| 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| 39 | 47 | 49 | 55 | 49 | 54 | 52 | 51 | 49 | 32 + 11 |

About 488 PDFs. 2020 has a duplicate `january_03` link.

## 3. Dates: never take them from the URL

Slugs change style every year or two: `petro_mm_2017_january_10`, `petro_ncr_2020_march_17_0`, `petro_ncr_2023-apr-09-pdf`, `petro_ncr_2025_mar-18-24-pdf`, `ncr-price-monitoring-04152025-pdf`, `NCR Price Monitoring 10062026.pdf`, `…for 3 to 9 November 2026.pdf`. Suffixes include `_updated`, `_revised`, `_edited`, `_0`.
Link text is also unreliable ("February 25 to 3", "December 20" for a `december_19` slug).
**Take the date from the PDF title line**, and use link text as a fallback (same rule as tawad/DA).

## 4. PDF layout eras (6 samples, all with a text layer, no OCR needed)

| Era | Seen | Title line | Shape |
|---|---|---|---|
| **A** | Jan 2017 to ~Nov 2019 (`petro_mm_*`) | `PREVAILING RETAIL PRICES OF PETROLEUM PRODUCTS IN METRO MANILA` / `As of January 10, 2017` | 1 page, landscape. Rows = product (RON 91/95/97/100, DIESEL, DIESEL PLUS, KEROSENE); columns = brand (CALTEX, PETRON, SHELL, SEAOIL, FLYING V, then UNIOIL, TOTAL in a second block). Cells are `low-high` ranges (`41.40-47.05`) or a single value. **Metro Manila as a whole; no cities, no common price.** |
| **B** | Dec 2019 to ~2024 (`petro_ncr_*`) | `NCR Prevailing Retail Pump Price as of March 12, 2020` + `Date of Monitoring: … Date of Effectivity : …` | 2 pages. Rows = city × product; columns = 10 brands (PETRON SHELL CALTEX PHOENIX TOTAL FLYING V UNIOIL SEAOIL PTT INDEPENDENT), each a **low high pair**, then `OVERALL RANGE` (`43.67 - 51.70`) and `COMMON PRICE`. |
| **C** | 2025 onwards | DOE letterhead, then `Price Monitoring of Liquid Fuels` / `NCR` / `(For the week of March 18-24, 2025)` | Same grid as B, first column header `AREA` instead of `Cities`. Has 2 images (logos) but a full text layer. |

Cities sampled: 5 in 2019–20 (Caloocan, Makati, Muntinlupa, Pasig, Quezon); about 10 or more by 2026 (adds Manila, Marikina, Navotas, Pasay, Taguig, Valenzuela, Parañaque, …). Coverage grows over time, so gold needs a `city` dimension and nulls where a city was not monitored.

## 5. Hard parts (to put in the spec)

1. **Empty brand cells shift columns.** A brand that doesn't sell a product is blank, so `extract_text()` lines can't be split by position count. `extract_tables()` finds the ruled grid but returns `None` for every brand cell (only RANGE and COMMON are read). → Assign words to brand columns by **x-position from the header row**, the same way tawad's DA matrix extractor does.
2. **City label spans rows.** The city name sits on the middle product row (`Caloocan City RON 91 …`); the rows above and below belong to the same city. Group by vertical position.
3. **Doubled / overlapping text.** `NNAATTIIOONNAALL CCAAPPIITTAALL` (bold drawn twice) and `CMalaokoactai nC iCtyity` (two city labels overlapping). Dedupe chars (`pdfplumber` `dedupe_chars`) and split overlapping labels by position.
4. **Missing-value tokens:** `-`, `#N/A`, `NONE`, `NO LFRO` (meaning not yet confirmed; ask DOE or treat as missing), blank. All → NULL in silver, never 0. Bronze keeps them raw.
5. **Encoding:** `Para�aque` (ñ lost in some PDFs). Normalise city names through a seed.
6. **Era A is a different table** (metro-wide, ranges in one cell). Its own small extractor, and gold marks `city = NULL` / `geo_level = 'metro'`.
7. **Products:** RON 100, RON 97, RON 95, RON 91, DIESEL, DIESEL PLUS, KEROSENE. Brand set changes over time (PTT, Phoenix appear; TOTAL becomes Cleanfuel?); keep brands as raw text + seed.

## 6. What carries over from tawad

Polite fetcher, manifest + `--new-only`, bronze-raw / silver-typed rule, `parse_price`-style macro, seed-mapped names, dbt-duckdb, `lake` + "Latest" GitHub Releases, daily Actions run in a Docker image. The new code is only the listing parser and two extractors (era A, eras B/C).
