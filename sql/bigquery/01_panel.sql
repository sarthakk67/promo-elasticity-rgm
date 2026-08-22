-- GENERATED from sql/01_panel.sql by src/port_to_bigquery.py -- do not edit.
-- Regenerate after changing the DuckDB source.

/* Build the product x store x week panel for the whole store. */
/* One row = one SKU in one store in one week. */
/* Price reconstruction (verify the sign convention on your copy first -- */
/* retail_disc and coupon_match_disc are stored NEGATIVE in the raw dunnhumby files): */
/*   paid_price  = what the customer actually handed over */
/*   NOTE: discounts are stored NEGATIVE. 36 rows carry a small POSITIVE retail_disc */
/*   (a surcharge, $8.53 in total); GREATEST(-x, 0) floors those at zero rather than */
/*   letting ABS() flip them into phantom discounts that inflate shelf price. */
/*   shelf_price = paid price grossed back up by the loyalty discount and the */
/*                 retailer's coupon match, i.e. the pre-promo regular price */
CREATE OR REPLACE TABLE `promo-rgm`.promo_rgm.panel_all AS
WITH tx AS (
  SELECT
    product_id,
    store_id,
    week_no,
    SUM(quantity) AS units,
    SUM(sales_value) AS sales_value,
    SUM(GREATEST(-retail_disc, 0)) AS retail_disc,
    SUM(GREATEST(-coupon_match_disc, 0)) AS coupon_match_disc,
    SUM(GREATEST(-coupon_disc, 0)) AS coupon_disc,
    COUNT(DISTINCT basket_id) AS baskets
  FROM `promo-rgm`.promo_rgm.transactions
  /* data-quality guards: drop giveaways, returns, and weight-priced outliers */
  WHERE
    quantity BETWEEN 1 AND 50 AND sales_value > 0
  GROUP BY
    1,
    2,
    3
)
SELECT
  tx.product_id,
  tx.store_id,
  tx.week_no,
  p.commodity_desc,
  p.sub_commodity_desc,
  p.manufacturer,
  p.brand,
  p.department,
  p.curr_size_of_product,
  tx.units,
  tx.baskets,
  tx.sales_value,
  tx.retail_disc,
  tx.coupon_disc,
  tx.coupon_match_disc,
  tx.sales_value / tx.units AS paid_price,
  (
    tx.sales_value + tx.retail_disc + tx.coupon_match_disc
  ) / tx.units AS shelf_price,
  COALESCE(c.display, '0') AS display_code,
  COALESCE(c.mailer, '0') AS mailer_code,
  CASE WHEN COALESCE(c.display, '0') <> '0' THEN 1 ELSE 0 END AS on_display,
  CASE WHEN COALESCE(c.mailer, '0') <> '0' THEN 1 ELSE 0 END AS on_mailer
FROM tx
JOIN `promo-rgm`.promo_rgm.products AS p
  USING (product_id)
LEFT JOIN `promo-rgm`.promo_rgm.causal AS c
  ON c.product_id = tx.product_id
  AND c.store_id = tx.store_id
  AND c.week_no = tx.week_no;
