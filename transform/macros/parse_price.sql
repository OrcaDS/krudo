{#
  Raw DOE price text -> DOUBLE, or NULL when the cell holds no price.

  Only plain numbers ("53.38", "100.00", "54.3", "3700") are prices. Everything else is
  NULL: the missing tokens (-, #N/A, #VALUE!, NONE, NO LFRO, blank) and garbled text
  ("68.3.9"). 0 / 0.00 is NULL too: DOE prints it for "no price", never as a price.
  Typos that are plain numbers (3700) stay and are flagged in gold, never fixed.
#}
{% macro parse_price(col) -%}
nullif(
    case when regexp_full_match(trim({{ col }}), '[0-9]+(\.[0-9]+)?') then cast(trim({{ col }}) as double) end,
    0
)
{%- endmacro %}

{#
  Low or high end (part 1 or 2) of a range cell: "47.30-52.35", "23.00 - 29.67",
  "51.07 77.21". A lone price ("35.05") is both ends. Anything else is NULL.
#}
{% macro range_part(col, part) -%}
{%- set pattern = '^\s*([0-9.]+)(?:\s*-\s*|\s+)([0-9.]+)\s*$' -%}
case
    when regexp_matches({{ col }}, '{{ pattern }}')
        then {{ parse_price("regexp_extract(" ~ col ~ ", '" ~ pattern ~ "', " ~ part ~ ")") }}
    else {{ parse_price(col) }}
end
{%- endmacro %}

{#
  First date in a DOE date text: "June 11, 2019", "March 24,2020", "Januray 7, 2025",
  "March 5-7,2024" (-> Mar 5), "December 30, 2024 - January 2, 2025" (-> Dec 30, 2024),
  "__J_u_n_e_ _1_1_-1_3__, _2_0_1_9__" (underscores dropped). The year is the first
  4-digit number, so a range across New Year keeps the start year. NULL if unreadable.
#}
{% macro first_date(col) -%}
{%- set s = "replace(" ~ col ~ ", '_', '')" -%}
try_strptime(
    concat_ws(' ',
        regexp_extract({{ s }}, '([A-Za-z]{3})[A-Za-z]*\s*([0-9]{1,2})', 1),
        regexp_extract({{ s }}, '([A-Za-z]{3})[A-Za-z]*\s*([0-9]{1,2})', 2),
        regexp_extract({{ s }}, '[0-9]{4}')
    ),
    '%b %d %Y'
)::date
{%- endmacro %}
