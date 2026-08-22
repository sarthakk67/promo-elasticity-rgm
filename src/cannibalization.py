"""Cross-price elasticity and volume-theft decomposition for competing brands.

Two independent reads on the same question -- how much of a promotion's "lift" is
new demand, and how much is volume taken from a sibling brand on the same shelf?

  A. CROSS-PRICE ELASTICITY. Stack both national manufacturers as focal, regress
     focal log units on focal price AND rival price, with brand-pack and week FE.
     A POSITIVE cross-price coefficient means substitutes: when the rival gets
     cheaper, the focal brand loses volume.

  B. EVENT DECOMPOSITION. Find weeks where the focal brand-pack is promoted and
     the rival is not. Compare each side against its own non-promo baseline. The
     rival's shortfall is volume the promotion moved, not volume it created.
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

NATIONAL_A, NATIONAL_B = 103, 1208     # the two national duopolists
PRIVATE_LABEL = 69
PROMO_CUT = 0.20                        # display/mailer share above this = promoted


def build_pairs(mfr_a, mfr_b):
    """One row per (focal brand, sub-commodity, week) with the rival's price attached."""
    con = duckdb.connect(str(DB), read_only=True)
    d = con.execute(
        "SELECT * FROM brandpack WHERE manufacturer IN (?, ?)", [mfr_a, mfr_b]
    ).df()
    con.close()

    # keep only sub-commodities where BOTH compete -- otherwise there is no rival
    both = (d.groupby("sub_commodity_desc").manufacturer.nunique() == 2)
    d = d[d.sub_commodity_desc.isin(both[both].index)].copy()

    rival = d.rename(columns={
        "manufacturer": "rival_mfr", "price_index": "rival_price",
        "units": "rival_units", "display_share": "rival_display",
        "mailer_share": "rival_mailer"})[
        ["rival_mfr", "sub_commodity_desc", "week_no", "rival_price",
         "rival_units", "rival_display", "rival_mailer"]]

    p = d.merge(rival, on=["sub_commodity_desc", "week_no"])
    p = p[p.manufacturer != p.rival_mfr].copy()      # drop self-matches

    p["bp"] = p.manufacturer.astype(str) + "|" + p.sub_commodity_desc
    p["log_units"] = np.log(p.units)
    p["log_price"] = np.log(p.price_index)
    p["log_rival_price"] = np.log(p.rival_price)
    return p[p.groupby("bp").week_no.transform("size") >= 30].copy()


def cross_elasticity(p, label):
    f = ("log_units ~ log_price + log_rival_price + display_share + mailer_share "
         "+ rival_display + rival_mailer | bp + week_no")
    t = pf.feols(f, data=p, vcov={"CRV1": "bp"}).tidy()
    own, cross = t.loc["log_price", "Estimate"], t.loc["log_rival_price", "Estimate"]
    print(f"\n--- {label} ---")
    print(f"  cells {len(p):,} | brand-packs {p.bp.nunique()} | "
          f"sub-commodities {p.sub_commodity_desc.nunique()}")
    print(f"  own-price elasticity    {own:+.3f}  (se {t.loc['log_price','Std. Error']:.3f}, "
          f"p={t.loc['log_price','Pr(>|t|)']:.4f})")
    print(f"  cross-price elasticity  {cross:+.3f}  (se {t.loc['log_rival_price','Std. Error']:.3f}, "
          f"p={t.loc['log_rival_price','Pr(>|t|)']:.4f})")
    # a positive point estimate means nothing if the interval spans zero
    crse = t.loc["log_rival_price", "Std. Error"]
    lo, hi = cross - 1.96 * crse, cross + 1.96 * crse
    if lo > 0:
        verdict = "SUBSTITUTES -- rival volume is contestable"
    elif hi < 0:
        verdict = "COMPLEMENTS"
    else:
        verdict = (f"NO detectable substitution -- 95% CI [{lo:+.3f}, {hi:+.3f}] spans zero; "
                   f"rules out substitution above {hi:.2f}")
    print(f"  -> {verdict}")
    return {"pair": label, "own_elasticity": own, "cross_elasticity": cross,
            "own_se": t.loc["log_price", "Std. Error"],
            "cross_se": t.loc["log_rival_price", "Std. Error"],
            "cross_p": t.loc["log_rival_price", "Pr(>|t|)"], "n_cells": len(p)}


def event_decomposition(p, label):
    """Focal promoted, rival not: measure both sides against their own baselines."""
    p = p.copy()
    p["focal_promo"] = ((p.display_share > PROMO_CUT) | (p.mailer_share > PROMO_CUT))
    p["rival_promo"] = ((p.rival_display > PROMO_CUT) | (p.rival_mailer > PROMO_CUT))

    base_f = p[~p.focal_promo].groupby("bp").units.median().rename("focal_base")
    p["rival_bp"] = p.rival_mfr.astype(str) + "|" + p.sub_commodity_desc
    base_r = p[~p.rival_promo].groupby("rival_bp").rival_units.median().rename("rival_base")

    ev = p[p.focal_promo & ~p.rival_promo].join(base_f, on="bp").join(base_r, on="rival_bp")
    ev = ev.dropna(subset=["focal_base", "rival_base"])

    focal_lift = (ev.units - ev.focal_base).sum()
    rival_loss = (ev.rival_base - ev.rival_units).sum()
    net = focal_lift - rival_loss
    share = rival_loss / focal_lift if focal_lift > 0 else np.nan

    print(f"\n  event decomposition ({len(ev):,} clean promo weeks)")
    print(f"    focal lift over baseline        {focal_lift:>10,.0f} units")
    print(f"    rival shortfall vs its baseline {rival_loss:>10,.0f} units")
    print(f"    net incremental to the category {net:>10,.0f} units")
    print(f"    -> {share:.0%} of the observed lift was volume moved, not created")
    return {"pair": label, "events": len(ev), "focal_lift": focal_lift,
            "rival_loss": rival_loss, "net_incremental": net, "cannibalised_share": share}


def pooled_cross_elasticity():
    """Rival = the rest of the sub-commodity, not a single named competitor.

    The head-to-head pair test runs on ~16 brand-pack clusters. Cluster-robust
    inference needs roughly 40+ clusters to be trustworthy, so that specification
    cannot support an inference either way regardless of what it reports. Pooling
    every manufacturer against the rest of its sub-commodity raises the cluster
    count enough for the standard errors to mean something. THIS is the estimate
    the writeup should quote.
    """
    con = duckdb.connect(str(DB), read_only=True)
    d = con.execute("SELECT * FROM brandpack").df()
    con.close()

    agg = d.groupby(["sub_commodity_desc", "week_no"]).agg(
        tot_units=("units", "sum"), tot_sales=("sales_value", "sum")).reset_index()
    m = d.merge(agg, on=["sub_commodity_desc", "week_no"])
    m["rival_units"] = m.tot_units - m.units
    m["rival_sales"] = m.tot_sales - m.sales_value
    m = m[m.rival_units > 0].copy()
    m["rival_price"] = m.rival_sales / m.rival_units
    m["bp"] = m.manufacturer.astype(str) + "|" + m.sub_commodity_desc
    m = m[m.groupby("bp").week_no.transform("size") >= 30].copy()
    m["log_units"] = np.log(m.units)
    m["log_price"] = np.log(m.price_index)
    m["log_rival_price"] = np.log(m.rival_price)

    f = ("log_units ~ log_price + log_rival_price + display_share + mailer_share "
         "| bp + week_no")
    t = pf.feols(f, data=m, vcov={"CRV1": "bp"}).tidy()
    cross = t.loc["log_rival_price", "Estimate"]
    se = t.loc["log_rival_price", "Std. Error"]
    lo, hi = cross - 1.96 * se, cross + 1.96 * se
    print(f"\n--- pooled: each brand-pack vs the rest of its sub-commodity ---")
    print(f"  clusters {m.bp.nunique()} | cells {len(m):,}")
    print(f"  own-price elasticity    {t.loc['log_price','Estimate']:+.3f} "
          f"(se {t.loc['log_price','Std. Error']:.3f})")
    print(f"  cross-price elasticity  {cross:+.3f} (se {se:.3f}, "
          f"p={t.loc['log_rival_price','Pr(>|t|)']:.4f})")
    print(f"  95% CI [{lo:+.3f}, {hi:+.3f}]")
    print(f"  -> {'SUBSTITUTES' if lo > 0 else 'NO detectable substitution; rules out substitution above ' + f'{hi:.2f}'}")
    return pd.DataFrame([{
        "design": "pooled (rival = rest of sub-commodity)",
        "clusters": m.bp.nunique(), "n_cells": len(m),
        "own_elasticity": t.loc["log_price", "Estimate"],
        "cross_elasticity": cross, "cross_se": se,
        "cross_p": t.loc["log_rival_price", "Pr(>|t|)"],
        "cross_ci_lo": lo, "cross_ci_hi": hi,
    }])


def main():
    rows_x, rows_e = [], []
    for a, b, label in [(NATIONAL_A, NATIONAL_B, f"National {NATIONAL_A} vs National {NATIONAL_B}"),
                        (NATIONAL_A, PRIVATE_LABEL, f"National {NATIONAL_A} vs Private label {PRIVATE_LABEL}")]:
        p = build_pairs(a, b)
        rows_x.append(cross_elasticity(p, label))
        rows_e.append(event_decomposition(p, label))

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_x).to_csv(OUT / "cross_elasticity_pairs.csv", index=False)
    pooled = pooled_cross_elasticity()
    pooled.to_csv(OUT / "cross_elasticity.csv", index=False)   # the quotable one
    pd.DataFrame(rows_e).to_csv(OUT / "cannibalisation.csv", index=False)
    print(f"\nwrote {OUT/'cross_elasticity.csv'} (pooled, quotable), "
          f"{OUT/'cross_elasticity_pairs.csv'} (underpowered pair tests), "
          f"{OUT/'cannibalisation.csv'}")


if __name__ == "__main__":
    main()
