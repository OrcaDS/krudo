-- DOE price cells from bronze: prices parsed to numbers (missing -> NULL, never 0), ranges
-- split into low and high, names mapped to canonical ones through the seeds, and only the
-- newest download of each report.
with cells as (
    select
        b.*,
        case
            when b.cell_kind like 'brand%' then 'brand'
            when b.cell_kind like 'overall%' then 'overall'
            else 'common'
        end as measure,
        case b.cell_kind
            when 'brand_high' then null
            when 'overall_high' then null
            when 'brand_range' then {{ range_part('b.value_raw', 1) }}
            when 'overall_range' then {{ range_part('b.value_raw', 1) }}
            else {{ parse_price('b.value_raw') }}
        end as price_low,
        case b.cell_kind
            when 'brand_low' then null
            when 'overall_low' then null
            when 'brand_range' then {{ range_part('b.value_raw', 2) }}
            when 'overall_range' then {{ range_part('b.value_raw', 2) }}
            else {{ parse_price('b.value_raw') }}
        end as price_high
    from {{ source('bronze', 'doe_prices') }} as b
    left join {{ source('bronze', 'manifest') }} as m on m.file_name = b.source_file
    -- A revised file replaces the original for the same report (project.md §6.1).
    qualify b.source_file = first_value(b.source_file) over (
        partition by b.era, b.report_date
        order by m.revision_level desc nulls last, m.downloaded_at desc nulls last
    )
)

select
    -- Tuesday (DOE's price adjustment day) of the week the report covers. The week comes from
    -- the monitoring period's start, else the effectivity date (once copied stale from the
    -- week before, so it comes second), else the report date. Holidays move the monitoring
    -- start to Monday-Thursday, which all map to that week's Tuesday.
    cast(date_trunc('week', coalesce(
        {{ first_date('monitoring_period_raw') }},
        {{ first_date('effectivity_raw') }},
        report_date
    )) + interval 1 day as date) as week_start,
    report_date,
    era,
    case when era = 'A' then 'metro' else 'city' end as geo_level,
    ci.city,
    br.brand,
    pr.product,
    measure,
    cell_kind,
    -- the common price is one number: kept in both columns so every measure reads alike
    price_low,
    price_high,
    c.city_raw,
    c.brand_raw,
    c.product_raw,
    value_raw,
    effectivity_raw,
    monitoring_period_raw,
    source_file,
    page,
    extractor_version,
    ingested_at
from cells as c
left join {{ ref('cities') }} as ci on ci.city_raw = {{ normalize_name('c.city_raw') }}
left join {{ ref('brands') }} as br on br.brand_raw = {{ normalize_name('c.brand_raw') }}
left join {{ ref('products') }} as pr on pr.product_raw = {{ normalize_name('c.product_raw') }}
