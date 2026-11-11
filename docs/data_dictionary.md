# Data dictionary

Weekly retail pump prices in Metro Manila (NCR), January 2017 to now, read from the
Department of Energy's weekly price monitoring PDFs.

**Source:** Department of Energy – Oil Industry Management Bureau, NCR price monitoring.
Public domain.

Prices are Philippine pesos per litre. An empty (NULL) price means DOE printed no price for
that cell (blank, `-`, `#N/A`, `NONE`, `NO LFRO`, `0.00`). It never means zero.

## Coverage

| Period | `geo_level` | What DOE reports |
|---|---|---|
| Jan 2017 – Sep 2019 | `metro` | One table for all of Metro Manila: each brand's low and high price; from Aug 2017 also the overall range and the common price. `city` is empty. |
| Jun 2019 – now | `city` | One block per city: each brand's low and high price, the overall range and the common price. |

The two overlap from June to September 2019, so those weeks have both levels.
Cities monitored vary over time: 8 cities since June 2019, Pasay since June 2021, and
Marikina, Navotas and Valenzuela since March 2026. Some weeks are missing: DOE skipped them
(mostly holidays), or the report is a scanned image with no readable text (May 28, 2019 and
Oct 21, 2021).

## `fct_pump_prices`

One row per week × city × brand × product.

| Column | Type | Description |
|---|---|---|
| `week_start` | date | Tuesday of the week the prices apply to. DOE adjusts pump prices on Tuesdays. |
| `report_date` | date | Date in the report's title. |
| `geo_level` | text | `metro` (2017–2019, all of Metro Manila) or `city`. |
| `city` | text | City (see `dim_city`); empty when `geo_level` is `metro`. |
| `brand` | text | Brand (see `dim_brand`). `Independent` = unbranded stations. |
| `product` | text | Product (see `dim_product`). |
| `price_low` | double | Lowest price DOE saw for this brand in this city and week. |
| `price_high` | double | Highest price. Early 2017 reports give one price per cell for some brands; then low = high. |
| `source_file` | text | DOE PDF the row came from. |
| `is_low_above_high` | boolean | `price_low` > `price_high`: a DOE typo or swapped columns, kept as printed. |
| `is_out_of_bounds` | boolean | A price outside ₱20–₱200: a DOE typo (e.g. `3700`, `2.68`), kept as printed. |

## `fct_ncr_summary`

DOE's own summary per week × city × product.

| Column | Type | Description |
|---|---|---|
| `week_start`, `report_date`, `geo_level`, `city`, `product`, `source_file` | | As in `fct_pump_prices`. |
| `overall_low` | double | Lowest price across all brands (DOE's "overall range"). Not in reports before Aug 2017. |
| `overall_high` | double | Highest price across all brands. |
| `common_price` | double | DOE's "common price": the price most stations charged. |
| `is_low_above_high` | boolean | `overall_low` > `overall_high`. |
| `is_out_of_bounds` | boolean | Any of the three prices outside ₱20–₱200. |

## Dimensions

| Table | Columns | Description |
|---|---|---|
| `dim_city` | `city` | NCR cities DOE reports on. |
| `dim_brand` | `brand` | Petron, Shell, Caltex, Phoenix, Seaoil, Total, Unioil, Flying V, PTT, Independent. |
| `dim_product` | `product`, `family`, `octane` | `RON 91`, `RON 95`, `RON 97`, `RON 100` (family `gasoline`, octane = RON), `Diesel`, `Diesel Plus` (`diesel`), `Kerosene` (`kerosene`). |

## Known limits

- DOE's typos are kept, not corrected; the `is_*` flags mark the ones that can be detected.
  The full list is in `docs/parsing_notes.md`.
- DOE's overall range and common price are copied as printed. They don't always match the
  brand prices in the same report.
- Where DOE released a revised report, only the newest version is used.
