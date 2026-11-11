# Project: krudo, NCR Pump Price Tracker

> Brief for Claude. Read this fully before writing code. When something here conflicts with what you find in the actual data or services, trust what you find, tell me, and propose an update to this file.
>
> v1 (2026-11-11), written after recon. Evidence for every claim is in `docs/recon.md`.

## 1. What this is

A batch pipeline in a **medallion architecture** (bronze → silver → gold) that turns the Department of Energy's weekly **NCR retail pump price** PDFs into one clean, open dataset: price by **week × city × brand × product**, from January 2017 to now.

DOE publishes these only as PDFs, in three layouts, with no API. Nobody else publishes them as open data (PSA doesn't carry them, CEIC sells them, and PhilRice's mirror stops in 2021). krudo's output is a free, versioned **CSV + Parquet release on GitHub** with a data dictionary, so a developer can `curl` one file and start working.

It is the sister project of **tawad** (DA food prices) and reuses its architecture and code. It is also a portfolio piece: it shows that tawad's design carries over to a new source with little new code.

## 2. Questions the gold layer must answer

- How have NCR pump prices for each product (RON 91/95/97/100, diesel, diesel plus, kerosene) moved week by week since 2017?
- How far apart are brands for the same product and week (e.g. Petron vs Unioil vs independents)?
- Which cities are cheapest or most expensive, and is the gap stable?
- What was the "common price" (DOE's most frequent price) each week, and how wide was the low–high spread?
- (Later) Do weekly changes match the price adjustments DOE announces each Monday?

## 3. Architecture

```
 DOE listing page (HTML) ──▶ PDFs (prod-cms + cloudfront)
        │
        ▼
 Ingestion (Python, Docker): discover → download → extract
        │
        ▼
 BRONZE  bronze/files/doe/…  original PDFs (immutable) + manifest
         bronze/tables/doe_prices/…  rows as raw text + lineage (Parquet)
        │
        ▼
 dbt + DuckDB
 SILVER  typed, missing tokens → NULL, canonical city/brand/product
 GOLD    fct_pump_prices, fct_ncr_summary, dims
        │
        ▼
 GitHub Release "Latest": CSV + Parquet + data dictionary
```

DuckDB is the only compute engine and is rebuilt from bronze every run (the data is tiny: ~500 PDFs, ~150k rows).

## 4. Tech stack

Same as tawad, minus BigQuery:

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11+, `uv` | |
| HTTP | stdlib `urllib` | Copied from tawad's polite fetcher; no extra dependency (decided 2026-11-11) |
| PDF extraction | `pdfplumber` | 483 of 485 PDFs have a text layer; the 2 scanned ones are marked failed (no OCR) |
| Bronze format | Parquet via `pyarrow`, explicit schemas, snappy | |
| Lake storage | Local lake, copied to and from a `lake` GitHub **prerelease** (`krudo lake-push` / `lake-pull`) | Same as tawad; free, no card |
| Transform | dbt Core + `dbt-duckdb` | |
| Publishing | GitHub Release "Latest" (CSV + Parquet + dictionary), only when gold changed | Like tawad's `publish-data` |
| Orchestration | GitHub Actions cron, **weekly** (Wednesday 02:00 UTC) | DOE posts reports for the week that starts on Tuesday |
| Containers | Docker image on GHCR | |
| CI | GitHub Actions on every PR: ruff, pytest, dbt build on fixtures, image build | |
| Lint / tests | `ruff`, `pytest`, dbt tests | |

**No BigQuery** in v1: the goal is files developers can download. Add it only if I ask. No other infrastructure without asking.

## 5. Repository layout

```
krudo/
├── config/settings.py            # every setting, from env vars (.env.example lists them)
├── ingestion/
│   ├── common/                   # copied from tawad: storage.py, manifest, fetcher, lake_release.py
│   └── doe/
│       ├── discover.py           # listing page → links (url, link_text)
│       ├── download.py           # polite fetcher, manifest, --new-only
│       ├── classify.py           # title line → era (A, B, C) + report date
│       └── extract/
│           ├── metro_matrix.py   # era A
│           └── city_grid.py      # eras B and C
├── pipeline/cli.py               # `krudo …` commands
├── transform/                    # dbt project (models/silver, models/gold, seeds, macros)
├── warehouse/publish.py          # gold → CSV/Parquet → release (from tawad)
├── tests/ (+ tests/fixtures/)    # small sample PDFs' rows as CSV, never the lake
├── docs/recon.md, docs/parsing_notes.md, docs/data_dictionary.md
├── Dockerfile, .github/workflows/{ci,publish_image,weekly_pipeline}.yml
└── project.md, README.md
```

**Reuse policy:** copy tawad's generic modules (storage, manifest, polite fetcher, lake release, publish, CLI skeleton, CI/Docker files) rather than import them across repos. Copy them once and trim anything DA-specific. Don't build a shared library.

## 6. Pipeline stages

### 6.1 Discover and download → bronze/files
- One `GET` of `https://doe.gov.ph/data-and-prices/liquid-fuels/retail-pump-prices/ncr-pump-prices` lists every NCR report (~488 links, no pagination, server-rendered). Parse `<a href>` pointing at `prod-cms.doe.gov.ph/documents/` or `*.cloudfront.net/api/media/file/`. Upgrade `http://` to `https://`.
- Save each file untouched to `bronze/files/doe/ncr/year=YYYY/<safe_name>.pdf`, where YYYY is the year row the link sits in on DOE's page (known before download; the report date is only known after reading the PDF). Manifest row: url, link text, download time, sha256, report date (after classify), era, status, status_reason.
- **Report date comes from the PDF title, never the URL**; link text is a fallback only (see recon §3). Unparseable → `failed`, reason recorded.
- Duplicate links (e.g. two `2020 january_03`) and files with the same bytes as another report → `failed (same bytes as …)`, never extracted.
- Revised files (`_updated`, `_revised`, `_edited`, `_0`) replace the original for the same report date: keep both in bronze, and silver keeps the newest download.
- Polite: sequential, ≥5 s apart, User-Agent `krudo/<version> (+<repo url>)`, no personal email.
- `--new-only` skips URLs already in the manifest (the weekly run pulls the lake without PDFs).

### 6.2 Bronze layout
```
bronze/files/doe/ncr/year=2026/<name>.pdf
bronze/tables/doe_prices/year=2026/part-<report_date>-<pdf name>.parquet
bronze/manifest.parquet
```
Bronze row (**all text, exactly as extracted**): `report_date`, `era`, `title_raw`, `monitoring_period_raw`, `effectivity_raw`, `city_raw` (NULL in era A), `product_raw`, `brand_raw` (NULL for the summary columns), `cell_kind` ∈ {`brand_low`, `brand_high`, `brand_range`, `overall_range` (B/C, one cell), `overall_low`, `overall_high` (A, two cells), `common`}, `value_raw`, `source_file`, `page`, `extractor_version`, `ingested_at`.
One file per PDF, so a revised report never overwrites the original (silver keeps the newest); re-extracting a PDF overwrites its own file.

### 6.3 Extract
`classify.py` picks the era from the title line:

| Era | Title starts with | Extractor | Output |
|---|---|---|---|
| A (Jan 2017 → Sep 2019) | `PREVAILING RETAIL PRICES OF PETROLEUM PRODUCTS IN METRO MANILA` | `metro_matrix` | product × brand. Jan–Mar 2017: brands in two stacked blocks, cell `low-high` or single → `brand_range`. Apr 2017 on: low/high sub-columns → `brand_low`/`brand_high`, plus (Aug 2017 on) overall range → `overall_low`/`overall_high` and common price; Feb–Jul 2017 print common prices in a separate table |
| B (Jun 2019 → Feb 2024; overlaps A in Sep 2019) | `NCR Prevailing Retail Pump Price as of` (also `( As of: …)`, `as ofJuly …`) | `city_grid` | city × product × brand low/high + overall range + common |
| C (Mar 2024 →) | letterhead, then `Price Monitoring of Liquid Fuels` / `NCR` / `(For the week of …)` or `(For the period of …)` | `city_grid` | same as B |

`city_grid` rules (recon §5):
- Build column bands from the **header row's word x-positions** (each brand has a low and a high sub-column). Assign every price word to a band by its x-centre. Never split lines by position count: blank cells shift them.
- City label sits on the middle row of its block; group rows into cities by y-position between labels.
- Use `dedupe_chars()` for doubled bold text; split overlapping city labels by x-position.
- Map columns by header text, not position, so a new brand column is picked up.
- A label across both of a brand's sub-columns (`NO LFRO`) is one `brand_range` cell.

`metro_matrix` rules: era A labels sit centred, over the low sub-column, or off both, label by label, so columns come from the **prices' x-positions**. Empty columns are filled in from the header's slot count (two per brand and for the overall range, one for common) at the gaps that best fit the column pitch; any other count raises `Unsupported`.

A layout the extractor can't read raises `Unsupported`: the report is marked `failed` with the reason, and the run continues. Every new quirk goes into `docs/parsing_notes.md`.

### 6.4 Transform (dbt + DuckDB)
- **silver** `stg_doe_prices`:
  - Missing tokens `-`, `#N/A`, `NONE`, `NO LFRO`, blank → NULL, never 0, via a `parse_price` macro with a unit test listing every raw shape.
  - Split `low-high` / `low - high` ranges.
  - Canonical names come from seeds: `cities.csv` (fixes `Para�aque` etc.), `brands.csv`, `products.csv`. An unmapped name fails the run and logs the name.
  - Keep the newest download per report date.
  - `week_start` = effectivity date when stated, else the start of the "For the week of" range, else report date (era A). Keep `report_date` as well.
- **gold:**
  - `fct_pump_prices`: week_start × geo_level (`metro` | `city`) × city × brand × product, with `price_low`, `price_high`, `source_file`. Era A rows have `geo_level = 'metro'`, `city = NULL`.
  - `fct_ncr_summary`: week_start × city × product, with `overall_low`, `overall_high`, `common_price` (eras B/C).
  - `dim_city`, `dim_brand`, `dim_product` (product family: gasoline / diesel / kerosene; octane).
- `docs/data_dictionary.md`: every gold column, plus attribution: "Source: Department of Energy – Oil Industry Management Bureau, NCR price monitoring. Public domain."

### 6.5 Publish
`krudo publish-data` exports gold to CSV + Parquet, zips the CSVs, and updates the "Latest" release only when the gold hash changed (tawad's logic). Asset names are stable (`fct_pump_prices.parquet`, …) so download URLs never change.

### 6.6 Data quality
- dbt `not_null` / `unique` on keys, relationships between facts and dims, accepted values for product and geo_level.
- `price_low <= price_high` (warn, don't drop: DOE typos stay visible).
- Plausible bounds per product (e.g. ₱20–₱200/L): flag outliers in a column, never drop or "fix" them.
- Freshness: warn if no new report in more than 10 days.
- Every downloaded report is either extracted or `failed` with a reason. None are skipped silently.

## 7. Containerization
Copy tawad's Dockerfile. The lake is at `/app/lake`; no secrets in the image (`GH_TOKEN` comes from Actions at run time).

## 8. CI/CD
- `ci.yml` (every PR): `uv sync --locked`, ruff check + format check, pytest, build the fixture lake, `dbt build` on it, `docker build`.
- `publish_image.yml` (push to `main`): image → GHCR.
- `weekly_pipeline.yml` (Wed 02:00 UTC + manual): `krudo run-all` = lake-pull → discover/download `--new-only` → extract → transform → lake-push → publish-data. If DOE times out, skip the download and still publish.

## 9. Conventions
Same as tawad: `logging` not `print` (ruff T20), config only from `config/settings.py`, lake paths are POSIX strings, LF line endings, no data committed (except small `tests/fixtures/`), feature branches + PRs, never commit to `main`.

## 10. Milestones (stop after each for my review)

1. ✅ **Recon**: `docs/recon.md`.
2. **Scaffold**: repo, uv project, settings, copied common modules, CLI skeleton, CI green on an empty pipeline.
3. **Discover + download**: manifest, all ~488 PDFs into the local lake, classify every one by era; report era counts and failures.
4. **Extract eras B/C** (`city_grid`) with tests on fixtures; check against an independent reading of every page (like tawad's extractor-checker).
5. **Extract era A** (`metro_matrix`).
6. **dbt silver + gold** with seeds, macros, tests, and data dictionary.
7. **Lake release + publish + Docker + weekly Action**; first public "Latest" release.
8. **README** for developers: what the data is, a 3-line quickstart (`curl` + pandas/duckdb), schema, attribution, limitations.

## 11. Ask me rather than assume
- Other regions (North/South Luzon, Visayas, Mindanao), LPG, or the price-adjustments page: later, only when I say so. v1 is NCR only (decided 2026-11-11).
- Era A (2017–19, metro-wide, no cities) is included (decided 2026-11-11).
- `NO LFRO` is treated as missing (NULL), since its meaning can't be confirmed (decided 2026-11-11).
- Creating the GitHub repo, pushing, publishing a release, or adding BigQuery: always ask.
