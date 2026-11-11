-- Warns about prices outside the plausible range (DOE typos such as 3700 or 2.68). They
-- stay in gold with is_out_of_bounds = true; this lists them in the run log.
{{ config(severity='warn') }}

select 'fct_pump_prices' as model, week_start, city, brand, product, price_low, price_high
from {{ ref('fct_pump_prices') }} where is_out_of_bounds
union all
select 'fct_ncr_summary', week_start, city, null, product, overall_low, overall_high
from {{ ref('fct_ncr_summary') }} where is_out_of_bounds
