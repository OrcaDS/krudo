-- Brands with a price column in DOE's reports ("Independent" = unbranded stations).
select distinct brand from {{ ref('brands') }}
