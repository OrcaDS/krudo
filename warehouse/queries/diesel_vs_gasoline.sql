-- Diesel vs gasoline: yearly average common price of Diesel and RON 91, and the gap
-- (positive = diesel dearer). Era A metro-wide rows and city rows alike.
WITH yearly AS (
  SELECT
    YEAR(week_start) AS year,
    AVG(CASE WHEN product = 'Diesel' THEN common_price END) AS diesel,
    AVG(CASE WHEN product = 'RON 91' THEN common_price END) AS ron91
  FROM fct_ncr_summary
  WHERE product IN ('Diesel', 'RON 91') AND NOT is_out_of_bounds
  GROUP BY YEAR(week_start)
)
SELECT
  year,
  ROUND(diesel, 2) AS diesel,
  ROUND(ron91, 2) AS ron91,
  ROUND(diesel - ron91, 2) AS diesel_minus_ron91
FROM yearly
ORDER BY year;
