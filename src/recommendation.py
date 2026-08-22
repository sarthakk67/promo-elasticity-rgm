"""The call: what to stop, what it saves, and the volume you give up doing it.

There is NO cost-of-goods field in Complete Journey, so gross margin has to be
assumed. Rather than pick a number and hide it, we solve for the BREAK-EVEN margin
-- the gross margin at which stopping a mechanic is exactly neutral. If the
break-even sits far above any plausible grocery margin, the call is robust to the
assumption instead of resting on it.
"""
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TAB = ROOT / "outputs" / "tables"
MARGINS = [0.20, 0.25, 0.30, 0.35]
PANTRY_HAIRCUT = 0.14      # share of promo volume given back as a longer repurchase gap


def main():
    inc = pd.read_csv(TAB / "incremental_by_mechanic.csv")
    con = duckdb.connect(str(ROOT / "data/processed/journey.duckdb"), read_only=True)
    avg_price, cat_units = con.execute(
        "SELECT SUM(sales_value)/SUM(units), SUM(units) FROM brandpack").fetchone()
    con.close()
    print(f"category: SOFT DRINKS | {cat_units:,.0f} units | avg price ${avg_price:.2f}")
    print(f"pantry-loading haircut applied to incremental volume: {PANTRY_HAIRCUT:.0%}\n")

    rows = []
    for (mech, cf), g in inc.groupby(["mechanic", "counterfactual"]):
        r = g.iloc[0]
        gross_incr = r.incremental_units
        net_incr = gross_incr * (1 - PANTRY_HAIRCUT)     # borrowed volume is not incremental
        spend = r.discount_spend
        # stopping the mechanic: you keep the discount, you lose the net incremental margin
        breakeven = spend / (net_incr * avg_price) if net_incr > 0 else np.nan
        row = {"mechanic": mech, "counterfactual": cf,
               "discount_spend": spend, "gross_incremental": gross_incr,
               "net_incremental": net_incr,
               "volume_giveup_pct_of_category": net_incr / cat_units,
               "breakeven_gross_margin": breakeven}
        for m in MARGINS:
            row[f"net_gain_at_{int(m*100)}pct"] = spend - net_incr * avg_price * m
        rows.append(row)

    res = pd.DataFrame(rows).sort_values(["mechanic", "counterfactual"])
    res.to_csv(TAB / "recommendation.csv", index=False)

    show = ["mechanic", "counterfactual", "discount_spend", "net_incremental",
            "volume_giveup_pct_of_category", "breakeven_gross_margin",
            "net_gain_at_25pct"]
    d = res[show].copy()
    d.discount_spend = d.discount_spend.map("${:,.0f}".format)
    d.net_incremental = d.net_incremental.map("{:,.0f}".format)
    d.volume_giveup_pct_of_category = d.volume_giveup_pct_of_category.map("{:.1%}".format)
    d.breakeven_gross_margin = d.breakeven_gross_margin.map("{:.0%}".format)
    d.net_gain_at_25pct = d.net_gain_at_25pct.map("${:,.0f}".format)
    print(d.to_string(index=False))

    combo = res[(res.mechanic == "display + mailer") & (res.counterfactual == "GBM")].iloc[0]
    print(f"\n--- the call ---")
    print(f"  STOP 'display + mailer'. It absorbs ${combo.discount_spend:,.0f} of discount, "
          f"{combo.discount_spend/res[res.counterfactual=='GBM'].discount_spend.sum():.0%} of all promo spend.")
    print(f"  You give up {combo.net_incremental:,.0f} incremental units "
          f"({combo.volume_giveup_pct_of_category:.1%} of category volume).")
    print(f"  It only pays for itself above a {combo.breakeven_gross_margin:.0%} gross margin.")
    print(f"  Grocery carbonated soft drinks run roughly 20-30%, so at 25% "
          f"stopping is worth ${combo.net_gain_at_25pct:,.0f}.")


if __name__ == "__main__":
    main()
