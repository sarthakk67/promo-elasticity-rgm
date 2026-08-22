-- GENERATED from sql/02_category_screen.sql by src/port_to_bigquery.py -- do not edit.
-- Regenerate after changing the DuckDB source.

/* Screen every commodity for the four things this project needs. */
/* The column that actually decides the project is within_sw_variation: the share */
/* of store-weeks in which SOME SKUs in the category were promoted and others were */
/* not. Store x week fixed effects absorb anything that moves in lockstep across a */
/* store-week, so if this number is near zero the FE eat the treatment and the */
/* identification strategy collapses. Want it comfortably above ~0.30. */
WITH cat AS (
  SELECT
    commodity_desc,
    store_id,
    week_no,
    COUNT(*) AS skus_in_sw,
    SUM(CASE WHEN on_display = 1 OR on_mailer = 1 THEN 1 ELSE 0 END) AS promoted_in_sw
  FROM `promo-rgm`.promo_rgm.panel_all
  GROUP BY
    1,
    2,
    3
), variation AS (
  SELECT
    commodity_desc,
    AVG(
      CASE WHEN promoted_in_sw > 0 AND promoted_in_sw < skus_in_sw THEN 1.0 ELSE 0.0 END
    ) AS within_sw_variation
  FROM cat
  WHERE
    skus_in_sw >= 2
  GROUP BY
    1
), mfr AS (
  SELECT
    commodity_desc,
    SUM(share) AS top2_mfr_share
  FROM (
    SELECT
      commodity_desc,
      manufacturer,
      SUM(units) * 1.0 / SUM(SUM(units)) OVER (PARTITION BY commodity_desc) AS share,
      ROW_NUMBER() OVER (PARTITION BY commodity_desc ORDER BY SUM(units) DESC) AS rk
    FROM `promo-rgm`.promo_rgm.panel_all
    GROUP BY
      1,
      2
  )
  WHERE
    rk <= 2
  GROUP BY
    1
)
SELECT
  b.commodity_desc,
  COUNT(DISTINCT b.product_id) AS skus,
  COUNT(DISTINCT b.manufacturer) AS manufacturers,
  COUNT(*) AS panel_rows,
  SUM(b.units) AS units,
  ROUND(SUM(b.sales_value), 0) AS sales,
  ROUND(AVG(CASE WHEN b.on_display = 1 OR b.on_mailer = 1 THEN 1.0 ELSE 0 END), 3) AS promo_share,
  ROUND(m.top2_mfr_share, 3) AS top2_mfr_share,
  ROUND(v.within_sw_variation, 3) AS within_sw_variation
FROM `promo-rgm`.promo_rgm.panel_all AS b
JOIN variation AS v
  USING (commodity_desc)
JOIN mfr AS m
  USING (commodity_desc)
GROUP BY
  b.commodity_desc,
  m.top2_mfr_share,
  v.within_sw_variation
HAVING
  COUNT(*) > 20000 /* enough panel rows to estimate on */ AND SUM(b.units) > 50000
ORDER BY
  within_sw_variation DESC,
  units DESC;
