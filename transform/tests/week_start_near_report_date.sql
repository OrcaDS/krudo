-- The week a report covers starts near its title date: at most 10 days before, or 7 after
-- (DOE's title date is sometimes the wrong week: "as of December 14, 2021" on the Dec 21
-- report). Catches a misread date text, e.g. a range across New Year read with the wrong year.
select distinct report_date, week_start, effectivity_raw, monitoring_period_raw
from {{ ref('stg_doe_prices') }}
where week_start not between report_date - 10 and report_date + 7
