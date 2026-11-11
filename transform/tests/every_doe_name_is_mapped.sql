-- Every city, brand and product name in bronze must have a row in its seed. Fails the run
-- and logs each missing name, so it can be added to transform/seeds/.
{% set unmapped %}
select distinct 'cities' as seed, {{ normalize_name('city_raw') }} as name_raw
from {{ source('bronze', 'doe_prices') }}
where city_raw is not null
    and {{ normalize_name('city_raw') }} not in (select city_raw from {{ ref('cities') }})
union all
select distinct 'brands', {{ normalize_name('brand_raw') }}
from {{ source('bronze', 'doe_prices') }}
where brand_raw is not null
    and {{ normalize_name('brand_raw') }} not in (select brand_raw from {{ ref('brands') }})
union all
select distinct 'products', {{ normalize_name('product_raw') }}
from {{ source('bronze', 'doe_prices') }}
where {{ normalize_name('product_raw') }} not in (select product_raw from {{ ref('products') }})
{% endset %}

{{ log_rows(unmapped, 'Unmapped DOE name (seed | name)') }}
{{ unmapped }}
