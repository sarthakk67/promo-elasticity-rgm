"""Do the two cannibalisation estimates actually agree? No. This quantifies by how much.

The aggregate spec says no substitution (cross-price +0.031, CI [-0.093, +0.154]).
The household spec says a rival promotion moves switch probability +7.3pp. It is
tempting to wave these together as "different grains, same story." They are not the
same story, and the honest move is to convert one into the other's units and show
the conflict rather than assert a reconciliation.

  1. Convert the household effect into an implied cross-price elasticity and check
     it against the aggregate confidence interval.
  2. Test the leading explanation: the pooled spec fits ONE cross-price coefficient
     across brand pairs whose true coefficients differ wildly. Estimate it
     separately per sub-commodity and show the dispersion the pooling hides.
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
TAB = ROOT / "outputs" / "tables"

SPEC = ("log_units ~ log_price + log_rival_price + display_share + mailer_share "
        "| bp + week_no")


def implied_cross_elasticity():
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    from brand_switching import build

    d = build()
    sw = pd.read_csv(TAB / "brand_switching.csv")
    xel = pd.read_csv(TAB / "cross_elasticity.csv").iloc[0]

    con = duckdb.connect(str(DB), read_only=True)
    depth = con.execute("""
        SELECT 1 - SUM(sales_value) / SUM(sales_value + retail_disc)
        FROM brandpack WHERE display_share > 0.20 OR mailer_share > 0.20
    """).fetchone()[0]
    con.close()

    s0 = d[d.rival_promoted == 0].switched.mean()
    eff = sw[sw.spec == "4. + week FE"].rival_promoted.iloc[0]
    r0, r1 = 1 - s0, 1 - s0 - eff              # incumbent retention, before and after
    dlnq, dlnp = np.log(r1 / r0), np.log(1 - depth)
    implied = dlnq / dlnp

    print("=== converting the household effect into the aggregate's units ===")
    print(f"  base switch rate (rival not promoted)  {s0:.3f}")
    print(f"  effect of a rival promotion            {eff:+.4f} ({eff/s0:+.1%} relative)")
    print(f"  incumbent retention {r0:.3f} -> {r1:.3f}    dln(q) = {dlnq:+.4f}")
    print(f"  mean discount depth, promoted weeks    {depth:.1%}    dln(p) = {dlnp:+.4f}")
    print(f"\n  IMPLIED cross-price elasticity         {implied:+.3f}")
    print(f"  aggregate estimate                     {xel.cross_elasticity:+.3f} "
          f"CI [{xel.cross_ci_lo:+.3f}, {xel.cross_ci_hi:+.3f}]")
    verdict = "OUTSIDE" if implied > xel.cross_ci_hi else "inside"
    print(f"  -> {verdict} the aggregate CI ({implied/xel.cross_ci_hi:.1f}x its upper bound)")
    print("\n  NOTE: the household treatment is 'rival on display or mailer', which bundles"
          "\n  merchandising with the price cut. The implied figure is therefore an upper"
          "\n  bound on the pure price channel. Even discounted for that, the two specs"
          "\n  do not overlap -- this is a specification conflict, not a power gap.")
    return {"base_switch_rate": s0, "household_effect": eff, "promo_depth": depth,
            "implied_cross_elasticity": implied,
            "aggregate_cross_elasticity": xel.cross_elasticity,
            "aggregate_ci_hi": xel.cross_ci_hi,
            "outside_ci": bool(implied > xel.cross_ci_hi)}


def heterogeneity():
    """The pooled spec fits one coefficient. What is it pooling over?"""
    con = duckdb.connect(str(DB), read_only=True)
    b = con.execute("SELECT * FROM brandpack").df()
    con.close()

    agg = b.groupby(["sub_commodity_desc", "week_no"]).agg(
        tu=("units", "sum"), ts=("sales_value", "sum")).reset_index()
    m = b.merge(agg, on=["sub_commodity_desc", "week_no"])
    m = m[(m.tu - m.units) > 0].copy()
    m["rival_price"] = (m.ts - m.sales_value) / (m.tu - m.units)
    m["bp"] = m.manufacturer.astype(str) + "|" + m.sub_commodity_desc
    m = m[m.groupby("bp").week_no.transform("size") >= 30].copy()
    m["log_units"] = np.log(m.units)
    m["log_price"] = np.log(m.price_index)
    m["log_rival_price"] = np.log(m.rival_price)

    rows = []
    print("\n=== what the single pooled coefficient is averaging over ===")
    for sc, g in m.groupby("sub_commodity_desc"):
        if g.bp.nunique() < 3 or len(g) < 300:
            continue
        try:
            t = pf.feols(SPEC, data=g, vcov={"CRV1": "bp"}).tidy()
        except Exception:
            continue
        v = t.loc["log_rival_price", "Estimate"]
        rows.append({"sub_commodity": sc, "cross_elasticity": v,
                     "se": t.loc["log_rival_price", "Std. Error"],
                     "n_cells": len(g), "brand_packs": g.bp.nunique()})
        print(f"  {sc[:34]:<36}{v:+.3f}  (n={len(g):,}, {g.bp.nunique()} brand-packs)")
    r = pd.DataFrame(rows)
    print(f"\n  min {r.cross_elasticity.min():+.3f}   max {r.cross_elasticity.max():+.3f}   "
          f"mean {r.cross_elasticity.mean():+.3f}   pooled estimate +0.031")
    print("  Individually these are noisy -- few clusters each. The point is the SPREAD:")
    print("  the pooled coefficient is not the average of the parts, because pooling")
    print("  weights by within-cell variance rather than equally.")
    return r


def main():
    summary = implied_cross_elasticity()
    het = heterogeneity()
    TAB.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([summary]).to_csv(TAB / "grain_reconciliation.csv", index=False)
    het.to_csv(TAB / "cross_elasticity_by_subcommodity.csv", index=False)
    print(f"\nwrote {TAB/'grain_reconciliation.csv'} and "
          f"{TAB/'cross_elasticity_by_subcommodity.csv'}")


if __name__ == "__main__":
    main()
