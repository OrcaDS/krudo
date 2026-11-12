-- Which brands charge more? Each brand's mid price (halfway between its low and high)
-- minus the average mid price of all brands in the same city, week and product.
-- City-level reports only (June 2019 on), flagged typos excluded.
WITH priced AS (
  SELECT *, (price_low + price_high) / 2 AS mid
  FROM fct_pump_prices
  WHERE geo_level = 'city'
    AND product IN ('Diesel', 'RON 91')
    AND price_low IS NOT NULL AND price_high IS NOT NULL
    AND NOT is_out_of_bounds AND NOT is_low_above_high
),
peers AS (
  SELECT week_start, city, product, AVG(mid) AS peer_mid
  FROM priced
  GROUP BY week_start, city, product
)
SELECT
  brand,
  product,
  ROUND(AVG(mid - peer_mid), 2) AS avg_gap_pesos,
  COUNT(*) AS readings
FROM priced
JOIN peers USING (week_start, city, product)
GROUP BY brand, product
ORDER BY product, avg_gap_pesos;
