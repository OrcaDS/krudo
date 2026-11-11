-- One row per week x city x brand x product: the brand's low and high pump price.
-- Era A (2017-2019) is metro-wide: geo_level 'metro', city NULL. NULL price = DOE gave none.
-- DOE typos stay in and are flagged, never dropped or fixed.
with prices as (
    select
        week_start,
        report_date,
        geo_level,
        city,
        brand,
        product,
        max(price_low) as price_low,
        max(price_high) as price_high,
        source_file
    from {{ ref('stg_doe_prices') }}
    where measure = 'brand'
    group by all
)

select
    *,
    coalesce(price_low > price_high, false) as is_low_above_high,
    {{ out_of_bounds('price_low') }} or {{ out_of_bounds('price_high') }} as is_out_of_bounds
from prices
