-- Warns when the newest DOE report is more than 10 days old: the downloader may have
-- stopped, or DOE stopped publishing. Always warns on the CI sample, whose rows are old.
{{ config(severity='warn') }}

select max(report_date) as latest_report, current_date - max(report_date) as days_old
from {{ ref('stg_doe_prices') }}
having current_date - max(report_date) > 10
