"""Own-price elasticity for one category, estimated four ways.

The point of this module is not the elasticity. It is the LADDER: the same
coefficient re-estimated under progressively harder controls, so the gap between
the naive number and the defensible one is visible rather than asserted.

  (1) naive        log q ~ log p                      -- what a generic notebook reports
  (2) + promo      log q ~ log p + display + mailer   -- strips the merchandising bundled with the price cut
  (3) + product FE                                    -- strips cross-SKU price-level confounding
  (4) + store x week FE                               -- strips the promo calendar and seasonality  <- preferred

Standard errors are clustered on product_id throughout: promo decisions are made
per SKU and persist across weeks, so residuals within a SKU are not independent.
"""
from pathlib import Path
import argparse
import duckdb
import numpy as np
import pandas as pd
import pyfixest as pf

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "processed" / "journey.duckdb"
OUT = ROOT / "outputs" / "tables"

MIN_WEEKS_PER_SKU = 20      # a SKU needs history before it can inform an elasticity
PRICE_WINSOR = (0.01, 0.99) # unit-value outliers are a data artefact, not demand


def load_category(category: str) -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute(
        "SELECT * FROM panel_all WHERE commodity_desc = ?", [category]
    ).df()
    con.close()
    if df.empty:
        raise SystemExit(f"No rows for commodity_desc = {category!r}. Run src/screen.py first.")
    return df


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Clean the panel and build model variables. Every filter here is a data-quality
    decision that changes the estimate, so each one is counted and reported."""
    n0 = len(df)
    steps = []

    df = df[df.paid_price > 0]
    steps.append(("non-positive price", n0 - len(df)))

    # winsorise price within SKU -- a 10x unit value is a pack-size artefact
    n1 = len(df)
    lo = df.groupby("product_id").paid_price.transform(lambda s: s.quantile(PRICE_WINSOR[0]))
    hi = df.groupby("product_id").paid_price.transform(lambda s: s.quantile(PRICE_WINSOR[1]))
    df = df[(df.paid_price >= lo) & (df.paid_price <= hi)]
    steps.append(("price winsorised out", n1 - len(df)))

    # a SKU with no price variation contributes nothing once product FE are in
    n2 = len(df)
    counts = df.groupby("product_id").week_no.transform("size")
    varies = df.groupby("product_id").paid_price.transform("nunique") > 1
    df = df[(counts >= MIN_WEEKS_PER_SKU) & varies]
    steps.append(("thin or constant-price SKUs", n2 - len(df)))

    df = df.assign(
        log_units=np.log(df.units),
        log_price=np.log(df.paid_price),
        store_week=df.store_id.astype(str) + "_" + df.week_no.astype(str),
        discount_depth=1 - (df.paid_price / df.shelf_price.where(df.shelf_price > 0)),
    )

    print(f"  rows: {n0:,} -> {len(df):,}")
    for label, dropped in steps:
        print(f"    -{dropped:>8,}  {label}")
    print(f"  SKUs: {df.product_id.nunique():,}   stores: {df.store_id.nunique():,}   "
          f"weeks: {df.week_no.nunique()}")
    return df


SPECS = [
    ("1. naive",              "log_units ~ log_price",                                        None),
    ("2. + display/mailer",   "log_units ~ log_price + on_display + on_mailer",               None),
    ("3. + product FE",       "log_units ~ log_price + on_display + on_mailer | product_id",  None),
    ("4. + store x week FE",  "log_units ~ log_price + on_display + on_mailer | product_id + store_week", None),
]


def run_ladder(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, formula, _ in SPECS:
        fit = pf.feols(formula, data=df, vcov={"CRV1": "product_id"})
        tidy = fit.tidy()
        rows.append({
            "spec": label,
            "elasticity": tidy.loc["log_price", "Estimate"],
            "std_error": tidy.loc["log_price", "Std. Error"],
            "p_value": tidy.loc["log_price", "Pr(>|t|)"],
            "display_coef": tidy.loc["on_display", "Estimate"] if "on_display" in tidy.index else np.nan,
            "mailer_coef": tidy.loc["on_mailer", "Estimate"] if "on_mailer" in tidy.index else np.nan,
            "n_obs": int(fit._N),
        })
    out = pd.DataFrame(rows)
    naive, preferred = out.elasticity.iloc[0], out.elasticity.iloc[-1]
    out["pct_of_naive"] = (out.elasticity / naive * 100).round(1)
    print(f"\n  naive     {naive:+.3f}")
    print(f"  preferred {preferred:+.3f}")
    print(f"  the naive estimate overstates response by {abs(naive/preferred):.2f}x"
          if abs(naive) > abs(preferred) else
          f"  the naive estimate UNDERSTATES response by {abs(preferred/naive):.2f}x")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", required=True, help="COMMODITY_DESC value, e.g. 'COLD CEREAL'")
    args = ap.parse_args()

    print(f"category: {args.category}")
    df = prepare(load_category(args.category))
    result = run_ladder(df)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "elasticity_ladder.csv"
    result.to_csv(path, index=False)
    print(f"\n{result.to_string(index=False)}\n\nwrote {path}")


if __name__ == "__main__":
    main()
