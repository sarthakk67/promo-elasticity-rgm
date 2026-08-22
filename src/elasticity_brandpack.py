"""Own-price elasticity at brand-pack x week, estimated five ways.

The ladder is the deliverable, not the coefficient. Each rung strips one source of
confounding, and the movement between rungs is the finding:

  1 naive (unit value)  -- sales/units, the number a generic notebook reports
  2 naive (price index) -- fixed-weight index; isolates how much of rung 1 was MIX
  3 + display/mailer    -- strips the merchandising bundled with the price cut
  4 + brand-pack FE     -- strips cross-brand price-level confounding
  5 + week FE           -- strips the promo calendar and seasonality   <- preferred

SEs clustered on brand-pack: promo decisions persist across weeks within a brand.
"""
from pathlib import Path
import warnings
import duckdb
import numpy as np
import pandas as pd
import pyfixest as pf

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "processed" / "journey.duckdb"
OUT = ROOT / "outputs" / "tables"

MIN_WEEKS = 30

SPECS = [
    ("1. naive (unit value)",  "log_units ~ log_uv"),
    ("2. naive (price index)", "log_units ~ log_price"),
    ("3. + display/mailer",    "log_units ~ log_price + display_share + mailer_share"),
    ("4. + brand-pack FE",     "log_units ~ log_price + display_share + mailer_share | bp"),
    ("5. + week FE",           "log_units ~ log_price + display_share + mailer_share | bp + week_no"),
]


def load():
    con = duckdb.connect(str(DB), read_only=True)
    d = con.execute("SELECT * FROM brandpack").df()
    con.close()
    d["bp"] = d.manufacturer.astype(str) + "|" + d.sub_commodity_desc
    d = d[d.groupby("bp").week_no.transform("size") >= MIN_WEEKS].copy()
    d["log_units"] = np.log(d.units)
    d["log_price"] = np.log(d.price_index)
    d["log_uv"] = np.log(d.unit_value)
    return d


def run(d):
    rows = []
    for label, formula in SPECS:
        t = pf.feols(formula, data=d, vcov={"CRV1": "bp"}).tidy()
        pk = [i for i in t.index if i.startswith("log_")][0]
        rows.append({
            "spec": label,
            "elasticity": t.loc[pk, "Estimate"],
            "std_error": t.loc[pk, "Std. Error"],
            "p_value": t.loc[pk, "Pr(>|t|)"],
            "display_coef": t.loc["display_share", "Estimate"] if "display_share" in t.index else np.nan,
            "mailer_coef": t.loc["mailer_share", "Estimate"] if "mailer_share" in t.index else np.nan,
            "n_cells": len(d),
        })
    return pd.DataFrame(rows)


def main():
    d = load()
    print(f"cells {len(d):,} | brand-packs {d.bp.nunique()} | weeks {d.week_no.nunique()}\n")
    res = run(d)
    naive, pref = res.elasticity.iloc[0], res.elasticity.iloc[-1]
    dn, dp = res.display_coef.dropna().iloc[0], res.display_coef.dropna().iloc[-1]

    OUT.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT / "elasticity_ladder_brandpack.csv", index=False)
    print(res.to_string(index=False))
    print(f"\nprice elasticity : naive {naive:+.3f} -> preferred {pref:+.3f}  ({pref/naive:.2f}x)")
    print(f"display lift     : naive {np.exp(dn)-1:+.1%} -> preferred {np.exp(dp)-1:+.1%}  "
          f"({(np.exp(dn)-1)/(np.exp(dp)-1):.2f}x overstated)")
    print(f"\nwrote {OUT/'elasticity_ladder_brandpack.csv'}")


if __name__ == "__main__":
    main()
