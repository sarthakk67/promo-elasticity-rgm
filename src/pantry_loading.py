"""Does a promo purchase buy new demand, or borrow next month's?

Cannibalisation came back a null: promoting one soft-drink brand does not measurably
take volume from its rivals. So the lift has to come from somewhere else. The
candidate is PURCHASE ACCELERATION -- the same household buying sooner and bigger
than it otherwise would, then staying away longer.

Test: for every household soft-drink purchase, measure the gap to that household's
NEXT soft-drink purchase. If promo buys are followed by longer gaps, the volume was
pulled forward rather than created.

  spec A  gap ~ promo                      -- total effect, incl. buying more
  spec B  gap ~ promo + log(units)         -- promo effect HOLDING basket size fixed
  both with household FE (heavy buyers shop more often) and week FE (seasonality)
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

MIN_TRIPS = 5   # a household needs a purchase history before gaps mean anything


def build():
    con = duckdb.connect(str(DB), read_only=True)
    d = con.execute("""
        WITH sd AS (
            SELECT t.household_key, t.day, t.week_no, t.store_id, t.product_id,
                   t.quantity, t.sales_value,
                   GREATEST(-t.retail_disc, 0) AS disc
            FROM transactions t
            JOIN products p USING (product_id)
            WHERE p.commodity_desc = 'SOFT DRINKS'
              AND t.quantity BETWEEN 1 AND 50 AND t.sales_value > 0
        ),
        flagged AS (
            SELECT sd.*,
                   CASE WHEN COALESCE(c.display,'0') <> '0'
                          OR COALESCE(c.mailer,'0')  <> '0' THEN 1 ELSE 0 END AS on_promo
            FROM sd LEFT JOIN causal c
                   ON c.product_id = sd.product_id AND c.store_id = sd.store_id
                  AND c.week_no = sd.week_no
        ),
        trips AS (
            SELECT household_key, day, ANY_VALUE(week_no) AS week_no,
                   SUM(quantity) AS units, SUM(sales_value) AS spend, SUM(disc) AS disc,
                   MAX(on_promo) AS on_promo
            FROM flagged GROUP BY household_key, day
        )
        SELECT *, LEAD(day) OVER (PARTITION BY household_key ORDER BY day) - day AS gap_next
        FROM trips
    """).df()
    con.close()

    d = d.dropna(subset=["gap_next"])
    d = d[d.gap_next.between(1, 180)]
    d = d[d.groupby("household_key").day.transform("size") >= MIN_TRIPS].copy()
    d["log_gap"] = np.log(d.gap_next)
    d["log_units"] = np.log(d.units)
    d["disc_depth"] = d.disc / (d.spend + d.disc)
    return d


def main():
    d = build()
    promo, nonp = d[d.on_promo == 1], d[d.on_promo == 0]
    print(f"trips {len(d):,} | households {d.household_key.nunique():,} | "
          f"promo trips {len(promo):,} ({len(promo)/len(d):.0%})\n")
    print(f"  raw median gap  after promo trip     {promo.gap_next.median():.0f} days")
    print(f"  raw median gap  after non-promo trip {nonp.gap_next.median():.0f} days")
    print(f"  median units    on promo trip        {promo.units.median():.0f}")
    print(f"  median units    on non-promo trip    {nonp.units.median():.0f}\n")

    specs = [
        ("A. gap ~ promo | hh + week",   "log_gap ~ on_promo | household_key + week_no"),
        ("B. + control for basket size", "log_gap ~ on_promo + log_units | household_key + week_no"),
    ]
    rows = []
    for label, f in specs:
        t = pf.feols(f, data=d, vcov={"CRV1": "household_key"}).tidy()
        b, se, p = (t.loc["on_promo", "Estimate"], t.loc["on_promo", "Std. Error"],
                    t.loc["on_promo", "Pr(>|t|)"])
        lo, hi = b - 1.96 * se, b + 1.96 * se
        print(f"  {label:<34} {b:+.4f} (se {se:.4f}, p={p:.4f})  "
              f"=> gap {np.exp(b)-1:+.1%}  CI [{np.exp(lo)-1:+.1%}, {np.exp(hi)-1:+.1%}]")
        rows.append({"spec": label, "coef": b, "se": se, "p_value": p,
                     "gap_pct_change": np.exp(b) - 1,
                     "ci_lo": np.exp(lo) - 1, "ci_hi": np.exp(hi) - 1,
                     "units_coef": t.loc["log_units", "Estimate"] if "log_units" in t.index else np.nan})

    res = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT / "pantry_loading.csv", index=False)
    a = res.iloc[0]
    print()
    if a.ci_lo > 0:
        print(f"  -> ACCELERATION CONFIRMED: promo trips are followed by gaps "
              f"{a.gap_pct_change:.1%} longer. The lift is partly borrowed from future weeks.")
    elif a.ci_hi < 0:
        print(f"  -> promo trips are followed by SHORTER gaps ({a.gap_pct_change:.1%}) -- "
              f"promo buyers return sooner, not later.")
    else:
        print(f"  -> NO detectable acceleration; CI spans zero [{a.ci_lo:+.1%}, {a.ci_hi:+.1%}].")
    print(f"\nwrote {OUT/'pantry_loading.csv'}")


if __name__ == "__main__":
    main()
