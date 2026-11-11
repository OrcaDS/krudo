-- Fuel products: family (gasoline, diesel, kerosene) and octane (RON) for gasoline.
select distinct product, family, octane from {{ ref('products') }}
