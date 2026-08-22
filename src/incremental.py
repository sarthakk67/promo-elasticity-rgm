"""Baseline vs incremental volume, and what each promo dollar actually buys.

Observed promoted-week volume is not incremental volume. Most of it would have sold
anyway. We build the counterfactual two independent ways and compare -- if a boosted
tree and a fixed-effects model disagree badly, neither number is trustworthy.

  GBM   HistGradientBoosting on brand-pack, seasonality, price and promo state.
        Counterfactual = same cell re-predicted at that brand-pack's own non-promo
        baseline price with display and mailer set to zero.
        Validated on HELD-OUT non-promo weeks so the baseline is not just fitted noise.

  FE    The spec-5 elasticity model run backwards: strip the estimated price and
        merchandising effects off the observed volume.

Then: incremental units per discount dollar, split BY MECHANIC, which is what the
"stop doing X" recommendation has to rest on.
"""
from pathlib import Path
import warnings
import duckdb
import numpy as np
import pandas as pd
import pyfixest as pf
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_absolute_percentage_error

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "processed" / "journey.duckdb"
OUT = ROOT / "outputs" / "tables"
PROMO_CUT = 0.20


def load():
    con = duckdb.connect(str(DB), read_only=True)
    d = con.execute("SELECT * FROM brandpack").df()
    con.close()
    d["bp"] = d.manufacturer.astype(str) + "|" + d.sub_commodity_desc
    d = d[d.groupby("bp").week_no.transform("size") >= 30].copy()
    d["log_units"] = np.log(d.units)
    d["log_price"] = np.log(d.price_index)
    d["promoted"] = (d.display_share > PROMO_CUT) | (d.mailer_share > PROMO_CUT)
    # each brand-pack's own non-promo price level = the counterfactual price
    base_p = d[~d.promoted].groupby("bp").log_price.median().rename("base_log_price")
    d = d.join(base_p, on="bp")
    d["base_log_price"] = d.base_log_price.fillna(d.log_price)
    d["woy"] = d.week_no % 52
    d["mechanic"] = np.select(
        [(d.display_share > PROMO_CUT) & (d.mailer_share > PROMO_CUT),
         (d.display_share > PROMO_CUT),
         (d.mailer_share > PROMO_CUT)],
        ["display + mailer", "display only", "mailer only"], default="none")
    return d


FEATS = ["bp_code", "woy", "week_no", "log_price", "display_share", "mailer_share"]


def gbm_counterfactual(d):
    d = d.copy()
    d["bp_code"] = d.bp.astype("category").cat.codes

    # validate the baseline on held-out NON-PROMO weeks
    nonp = d[~d.promoted]
    tr, te = train_test_split(nonp, test_size=0.25, random_state=7)
    m = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.06,
                                      categorical_features=[0], random_state=7)
    m.fit(tr[FEATS], tr.log_units)
    pred_te = m.predict(te[FEATS])
    print(f"  baseline validation on held-out non-promo weeks: "
          f"R2={r2_score(te.log_units, pred_te):.3f}  "
          f"MAPE={mean_absolute_percentage_error(np.exp(te.log_units), np.exp(pred_te)):.1%}")

    # refit on all non-promo data, then predict the promo cells as if unpromoted
    m.fit(nonp[FEATS], nonp.log_units)
    cf = d.copy()
    cf["log_price"] = cf.base_log_price
    cf["display_share"] = 0.0
    cf["mailer_share"] = 0.0
    return np.exp(m.predict(cf[FEATS]))


def fe_counterfactual(d):
    f = "log_units ~ log_price + display_share + mailer_share | bp + week_no"
    t = pf.feols(f, data=d, vcov={"CRV1": "bp"}).tidy()
    e = t.loc["log_price", "Estimate"]
    dc = t.loc["display_share", "Estimate"]
    mc = t.loc["mailer_share", "Estimate"]
    delta = (e * (d.log_price - d.base_log_price)
             + dc * d.display_share + mc * d.mailer_share)
    return d.units / np.exp(delta)


def main():
    d = load()
    print(f"cells {len(d):,} | brand-packs {d.bp.nunique()} | "
          f"promoted cells {d.promoted.sum():,} ({d.promoted.mean():.0%})\n")

    d["base_gbm"] = gbm_counterfactual(d)
    d["base_fe"] = fe_counterfactual(d)

    p = d[d.promoted].copy()
    for src in ["gbm", "fe"]:
        p[f"incr_{src}"] = p.units - p[f"base_{src}"]

    print(f"\n  promoted-week volume            {p.units.sum():>12,.0f} units")
    for src, name in [("gbm", "GBM"), ("fe", "fixed-effects")]:
        base, incr = p[f"base_{src}"].sum(), p[f"incr_{src}"].sum()
        print(f"  {name:<15} baseline         {base:>12,.0f}   "
              f"incremental {incr:>10,.0f}  ({incr/p.units.sum():>5.1%} of promoted volume)")
    agree = np.corrcoef(p.incr_gbm, p.incr_fe)[0, 1]
    print(f"  agreement between the two counterfactuals: r = {agree:.3f}")

    print(f"\n=== incremental units per discount dollar, by mechanic ===")
    rows = []
    for mech, g in p.groupby("mechanic"):
        spend = g.retail_disc.sum()
        for src, name in [("gbm", "GBM"), ("fe", "FE")]:
            incr = g[f"incr_{src}"].sum()
            rows.append({"mechanic": mech, "counterfactual": name, "cells": len(g),
                         "promoted_units": g.units.sum(), "incremental_units": incr,
                         "discount_spend": spend,
                         "incr_units_per_dollar": incr / spend if spend > 0 else np.nan,
                         "incr_share_of_volume": incr / g.units.sum()})
    res = pd.DataFrame(rows)
    piv = res.pivot_table(index="mechanic", columns="counterfactual",
                          values="incr_units_per_dollar").round(3)
    sp = res[res.counterfactual == "GBM"].set_index("mechanic")[
        ["cells", "promoted_units", "discount_spend", "incr_share_of_volume"]]
    print(piv.join(sp).to_string())

    OUT.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT / "incremental_by_mechanic.csv", index=False)
    print(f"\nwrote {OUT/'incremental_by_mechanic.csv'}")


if __name__ == "__main__":
    main()
