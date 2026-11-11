-- One row per week x city x product: DOE's overall low-high range across brands and its
-- common (most frequent) price. Era A gives these metro-wide (geo_level 'metro', city NULL).
with summary as (
    select
        week_start,
        report_date,
        geo_level,
        city,
        product,
        max(price_low) filter (where measure = 'overall') as overall_low,
        max(price_high) filter (where measure = 'overall') as overall_high,
        max(price_low) filter (where measure = 'common') as common_price,
        source_file
    from {{ ref('stg_doe_prices') }}
    where measure in ('overall', 'common')
    group by all
)

select
    *,
    coalesce(overall_low > overall_high, false) as is_low_above_high,
    {{ out_of_bounds('overall_low') }}
        or {{ out_of_bounds('overall_high') }}
        or {{ out_of_bounds('common_price') }} as is_out_of_bounds
from summary
