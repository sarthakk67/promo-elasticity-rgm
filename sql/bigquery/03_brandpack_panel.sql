-- GENERATED from sql/03_brandpack_panel.sql by src/port_to_bigquery.py -- do not edit.
-- Regenerate after changing the DuckDB source.

/* Brand-pack x week panel: the grain a category manager actually prices at. */
/* WHY NOT product x store x week: 71.4% of those cells contain exactly one unit, */
/* so log(units) is zero for most of the panel and the outcome barely varies. The */
/* elasticity there is attenuated and unstable. 2,500 households simply do not */
/* generate enough volume to support SKU x store x week. */
/* PRICE INDEX: not sales/units. That ratio moves when the MIX moves -- sell more */
/* 2L and fewer 12-packs and the "price" falls with no pricing action. Instead we */
/* build a fixed-base-weight geometric index: each SKU's log price is weighted by */
/* its share of the brand-pack's units across the WHOLE period, with weights */
/* renormalised over the SKUs actually present each week. Mix is held constant by */
/* construction, so the index moves only when prices move. */
CREATE OR REPLACE TABLE `promo-rgm`.promo_rgm.brandpack AS
WITH sku_week AS (
  SELECT
    manufacturer,
    sub_commodity_desc,
    brand,
    product_id,
    week_no,
    SUM(units) AS units,
    SUM(sales_value) AS sales_value,
    SUM(retail_disc) AS retail_disc,
    SUM(coupon_match_disc) AS coupon_match_disc,
    SUM(sales_value) / SUM(units) AS paid_price,
    (
      SUM(sales_value) + SUM(retail_disc) + SUM(coupon_match_disc)
    ) / SUM(units) AS shelf_price,
    SUM(units * on_display) /* promo exposure, unit-weighted so a promoted SKU counts by its size */ / SUM(units) AS display_share,
    SUM(units * on_mailer) / SUM(units) AS mailer_share
  FROM `promo-rgm`.promo_rgm.panel_all
  WHERE
    commodity_desc = 'SOFT DRINKS'
  GROUP BY
    1,
    2,
    3,
    4,
    5
), base_w AS (
  SELECT
    product_id,
    manufacturer,
    sub_commodity_desc,
    SUM(units) AS sku_units,
    SUM(units) / SUM(SUM(units)) OVER (PARTITION BY manufacturer, sub_commodity_desc) AS w
  FROM sku_week
  GROUP BY
    1,
    2,
    3
)
SELECT
  s.manufacturer,
  s.sub_commodity_desc,
  ANY_VALUE(s.brand) AS brand,
  s.week_no,
  COUNT(DISTINCT s.product_id) AS skus_present,
  SUM(s.units) AS units,
  SUM(s.sales_value) AS sales_value,
  SUM(s.retail_disc) AS retail_disc,
  EXP(SUM(b.w * LN(s.paid_price)) / SUM(b.w)) AS price_index, /* fixed-weight geometric price index (weights renormalised over SKUs present) */
  EXP(SUM(b.w * LN(s.shelf_price)) / SUM(b.w)) AS shelf_index,
  SUM(s.sales_value) /* naive unit value, kept ONLY so the mix-bias gap can be quantified */ / SUM(s.units) AS unit_value,
  SUM(s.units * s.display_share) / SUM(s.units) AS display_share,
  SUM(s.units * s.mailer_share) / SUM(s.units) AS mailer_share
FROM sku_week AS s
JOIN base_w AS b
  USING (product_id)
WHERE
  s.paid_price > 0 AND s.shelf_price > 0
GROUP BY
  s.manufacturer,
  s.sub_commodity_desc,
  s.week_no
HAVING
  SUM(s.units) > 0;
