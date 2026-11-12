-- The 2026 diesel spike: DOE's weekly common price (the price most stations charged),
-- averaged over the NCR cities, February to June 2026.
SELECT
  week_start,
  ROUND(AVG(common_price), 2) AS diesel_common_price,
  COUNT(*) AS cities
FROM fct_ncr_summary
WHERE product = 'Diesel'
  AND week_start BETWEEN DATE '2026-02-01' AND DATE '2026-06-30'
  AND NOT is_out_of_bounds
GROUP BY week_start
ORDER BY week_start;
