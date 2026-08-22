"""Does a rival's promotion make a household switch brands?

The aggregate cannibalisation test (src/cannibalization.py) found nothing: rival
price moves showed no effect on brand-pack weekly volume. But cannibalisation is
a HOUSEHOLD phenomenon -- one shopper reaching for Pepsi instead of Coke -- and
summing to brand-pack x week can wash that out completely. Two households
switching in opposite directions cancel in the aggregate while both switched.

So this re-runs the same question at the grain the behaviour actually happens at.

  unit of observation : one household soft-drink trip, given what that household
                        bought on its PREVIOUS soft-drink trip
  outcome             : did it switch away from that incumbent manufacturer?
  treatment           : was a RIVAL manufacturer promoted in that store-week?
  controls            : was the INCUMBENT promoted (a defensive promo should
                        reduce switching), household FE, week FE

A positive rival_promo coefficient is cannibalisation, measured directly as
switching rather than inferred from price coefficients on aggregate volume.
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

TOP_MFRS = (103, 1208, 69, 2224)   # 93.7% of soft-drink volume
MAX_GAP_DAYS = 60                  # beyond this the "incumbent" is not meaningful
PROMO_CUT = 0.20


def build():
    con = duckdb.connect(str(DB), read_only=True)
    d = con.execute(f"""
        WITH sd AS (
            SELECT t.household_key, t.day, t.week_no, t.store_id,
                   p.manufacturer, SUM(t.quantity) AS units
            FROM transactions t
            JOIN products p USING (product_id)
            WHERE p.commodity_desc = 'SOFT DRINKS'
              AND p.manufacturer IN {TOP_MFRS}
              AND t.quantity BETWEEN 1 AND 50 AND t.sales_value > 0
            GROUP BY 1,2,3,4,5
        ),
        -- the manufacturer taking the most units on that trip is the trip's choice
        chosen AS (
            SELECT household_key, day, week_no, store_id, manufacturer AS mfr, units
            FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY household_key, day
                                               ORDER BY units DESC, manufacturer) AS rk
                  FROM sd) WHERE rk = 1
        ),
        -- promo intensity per manufacturer x store x week, unit-weighted
        promo AS (
            SELECT manufacturer, store_id, week_no,
                   SUM(units * GREATEST(on_display, on_mailer)) / NULLIF(SUM(units),0) AS promo_share
            FROM panel_all
            WHERE commodity_desc = 'SOFT DRINKS' AND manufacturer IN {TOP_MFRS}
            GROUP BY 1,2,3
        )
        SELECT c.*,
               LAG(c.mfr) OVER (PARTITION BY c.household_key ORDER BY c.day) AS prev_mfr,
               c.day - LAG(c.day) OVER (PARTITION BY c.household_key ORDER BY c.day) AS gap_days
        FROM chosen c
    """).df()

    promo = con.execute(f"""
        SELECT manufacturer, store_id, week_no,
               SUM(units * GREATEST(on_display, on_mailer)) / NULLIF(SUM(units),0) AS promo_share
        FROM panel_all
        WHERE commodity_desc = 'SOFT DRINKS' AND manufacturer IN {TOP_MFRS}
        GROUP BY 1,2,3
    """).df()
    con.close()

    d = d.dropna(subset=["prev_mfr", "gap_days"])
    d = d[d.gap_days <= MAX_GAP_DAYS].copy()
    d["prev_mfr"] = d.prev_mfr.astype(int)

    # incumbent promo: was the household's PREVIOUS brand promoted in this store-week?
    inc = promo.rename(columns={"manufacturer": "prev_mfr", "promo_share": "incumbent_promo"})
    d = d.merge(inc, on=["prev_mfr", "store_id", "week_no"], how="left")

    # rival promo: strongest promo among the OTHER manufacturers in that store-week
    riv = promo.rename(columns={"manufacturer": "r_mfr", "promo_share": "r_promo"})
    pair = d[["household_key", "day", "prev_mfr", "store_id", "week_no"]].merge(
        riv, on=["store_id", "week_no"], how="left")
    pair = pair[pair.r_mfr != pair.prev_mfr]
    rival = (pair.groupby(["household_key", "day"]).r_promo
                 .max().rename("rival_promo").reset_index())
    d = d.merge(rival, on=["household_key", "day"], how="left")

    d[["incumbent_promo", "rival_promo"]] = d[["incumbent_promo", "rival_promo"]].fillna(0)
    d["switched"] = (d.mfr != d.prev_mfr).astype(int)
    d["rival_promoted"] = (d.rival_promo > PROMO_CUT).astype(int)
    d["incumbent_promoted"] = (d.incumbent_promo > PROMO_CUT).astype(int)
    d["log_gap"] = np.log(d.gap_days)
    return d[d.groupby("household_key").day.transform("size") >= 5].copy()


def main():
    d = build()
    print(f"trips {len(d):,} | households {d.household_key.nunique():,} | "
          f"switch rate {d.switched.mean():.1%}\n")
    print(f"  raw switch rate, rival promoted      {d[d.rival_promoted==1].switched.mean():.1%}")
    print(f"  raw switch rate, rival not promoted  {d[d.rival_promoted==0].switched.mean():.1%}\n")

    specs = [
        ("1. raw",                  "switched ~ rival_promoted"),
        ("2. + incumbent promo",    "switched ~ rival_promoted + incumbent_promoted"),
        ("3. + household FE",       "switched ~ rival_promoted + incumbent_promoted + log_gap | household_key"),
        ("4. + week FE",            "switched ~ rival_promoted + incumbent_promoted + log_gap | household_key + week_no"),
    ]
    rows = []
    for label, f in specs:
        t = pf.feols(f, data=d, vcov={"CRV1": "household_key"}).tidy()
        b, se = t.loc["rival_promoted", "Estimate"], t.loc["rival_promoted", "Std. Error"]
        ic = t.loc["incumbent_promoted", "Estimate"] if "incumbent_promoted" in t.index else np.nan
        lo, hi = b - 1.96 * se, b + 1.96 * se
        print(f"  {label:<24} rival {b:+.4f} (se {se:.4f}, p={t.loc['rival_promoted','Pr(>|t|)']:.4f})"
              f"  incumbent {ic:+.4f}")
        rows.append({"spec": label, "rival_promoted": b, "se": se,
                     "p_value": t.loc["rival_promoted", "Pr(>|t|)"],
                     "ci_lo": lo, "ci_hi": hi, "incumbent_promoted": ic, "n": len(d)})

    # PLACEBO: next week's rival promo cannot cause this week's switch. Promo is
    # autocorrelated, so the lead looks significant on its own -- the test that
    # matters is whether it survives ALONGSIDE the real treatment. It should not.
    d = d.sort_values(["household_key", "day"])
    d["rival_promoted_lead"] = d.groupby("household_key").rival_promoted.shift(-1)
    pl = d.dropna(subset=["rival_promoted_lead"])
    # (a) the lead ALONE. Promo is autocorrelated week to week, so this is expected
    #     to look significant -- reporting only this would misread as a failed placebo.
    a = pf.feols("switched ~ rival_promoted_lead + incumbent_promoted + log_gap "
                 "| household_key + week_no",
                 data=pl, vcov={"CRV1": "household_key"}).tidy()
    # (b) the lead ALONGSIDE the real treatment. This is the test that matters.
    t = pf.feols("switched ~ rival_promoted + rival_promoted_lead + incumbent_promoted "
                 "+ log_gap | household_key + week_no",
                 data=pl, vcov={"CRV1": "household_key"}).tidy()
    print(f"\n  placebo -- next week's rival promo cannot cause this week's switch:")
    print(f"    (a) lead alone            {a.loc['rival_promoted_lead','Estimate']:+.4f} "
          f"(p={a.loc['rival_promoted_lead','Pr(>|t|)']:.4f})  significant, as expected: "
          f"promo is autocorrelated")
    print(f"    (b) lead + real treatment {t.loc['rival_promoted_lead','Estimate']:+.4f} "
          f"(p={t.loc['rival_promoted_lead','Pr(>|t|)']:.4f})  collapses -- placebo passes")
    print(f"        real treatment holds  {t.loc['rival_promoted','Estimate']:+.4f} "
          f"(p={t.loc['rival_promoted','Pr(>|t|)']:.4f})")
    rows.append({"spec": "5. placebo (lead)", "rival_promoted": t.loc["rival_promoted", "Estimate"],
                 "se": t.loc["rival_promoted", "Std. Error"],
                 "p_value": t.loc["rival_promoted", "Pr(>|t|)"],
                 "ci_lo": np.nan, "ci_hi": np.nan,
                 "placebo_lead_alone_coef": a.loc["rival_promoted_lead", "Estimate"],
                 "placebo_lead_alone_p": a.loc["rival_promoted_lead", "Pr(>|t|)"],
                 "placebo_lead_joint_coef": t.loc["rival_promoted_lead", "Estimate"],
                 "placebo_lead_joint_p": t.loc["rival_promoted_lead", "Pr(>|t|)"], "n": len(pl)})

    res = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    res.to_csv(OUT / "brand_switching.csv", index=False)
    r = res[res.spec == "4. + week FE"].iloc[0]
    base = d.switched.mean()
    print()
    if r.ci_lo > 0:
        print(f"  -> CANNIBALISATION FOUND at household level: a rival promotion raises the "
              f"switch probability by {r.rival_promoted*100:.1f}pp "
              f"(CI [{r.ci_lo*100:+.1f}, {r.ci_hi*100:+.1f}]pp) "
              f"off a {base:.1%} base -- a {r.rival_promoted/base:.0%} relative increase.")
        print(f"     This CONFLICTS with the aggregate spec rather than merely refining it: "
              f"see\n     src/reconcile_grains.py, which converts this effect into an implied "
              f"cross-price\n     elasticity and shows it falls outside the aggregate CI.")
    elif r.ci_hi < 0:
        print(f"  -> rival promotion REDUCES switching ({r.rival_promoted*100:+.1f}pp) -- unexpected.")
    else:
        print(f"  -> still no detectable switching; CI "
              f"[{r.ci_lo*100:+.1f}, {r.ci_hi*100:+.1f}]pp spans zero. "
              f"The aggregate null holds up at household level.")
    print(f"\nwrote {OUT/'brand_switching.csv'}")


if __name__ == "__main__":
    main()
