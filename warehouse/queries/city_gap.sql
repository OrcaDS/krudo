-- Which cities pay more for diesel? Each city's common price minus the NCR average for
-- the same week. Cities DOE has covered for at least five years (260+ weeks) only.
WITH city_rows AS (
  SELECT week_start, city, common_price
  FROM fct_ncr_summary
  WHERE geo_level = 'city' AND product = 'Diesel' AND NOT is_out_of_bounds
),
ncr AS (
  SELECT week_start, AVG(common_price) AS ncr_avg
  FROM city_rows
  GROUP BY week_start
)
SELECT
  city,
  ROUND(AVG(common_price - ncr_avg), 2) AS avg_gap_pesos,
  COUNT(*) AS weeks
FROM city_rows
JOIN ncr USING (week_start)
GROUP BY city
HAVING COUNT(*) >= 260
ORDER BY avg_gap_pesos;
