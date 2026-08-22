"""Does the ladder actually recover a known elasticity from confounded data?

We simulate the exact pathology the project claims to fix: promotions are NOT
randomly assigned. They land on high-demand store-weeks and arrive bundled with
display and mailer support. If spec 4 cannot recover TRUE_ELASTICITY from this,
the whole identification argument is decoration.
"""
import numpy as np
import pandas as pd
import pyfixest as pf

TRUE_ELASTICITY = -1.8
rng = np.random.default_rng(7)

N_PROD, N_STORE, N_WEEK = 40, 30, 100


def simulate():
    prod = np.arange(N_PROD)
    store = np.arange(N_STORE)
    week = np.arange(N_WEEK)
    idx = pd.MultiIndex.from_product([prod, store, week],
                                     names=["product_id", "store_id", "week_no"])
    df = idx.to_frame(index=False)

    # latent structure
    prod_fe = rng.normal(0, 0.8, N_PROD)[df.product_id]
    sw_shock = rng.normal(0, 0.6, (N_STORE, N_WEEK))[df.store_id, df.week_no]
    base_price = np.exp(rng.normal(1.0, 0.35, N_PROD))[df.product_id]

    # THE CONFOUNDING: promo probability rises with the store-week demand shock
    promo_p = 1 / (1 + np.exp(-(-1.2 + 2.2 * sw_shock)))
    promoted = rng.random(len(df)) < promo_p

    # promos cut price AND bring display/mailer support
    depth = np.where(promoted, rng.uniform(0.15, 0.40, len(df)), 0.0)
    price = base_price * (1 - depth)
    on_display = (promoted & (rng.random(len(df)) < 0.7)).astype(int)
    on_mailer = (promoted & (rng.random(len(df)) < 0.6)).astype(int)

    log_units = (2.5 + prod_fe + sw_shock
                 + TRUE_ELASTICITY * np.log(price)
                 + 0.35 * on_display + 0.20 * on_mailer
                 + rng.normal(0, 0.30, len(df)))

    return df.assign(log_price=np.log(price), log_units=log_units,
                     on_display=on_display, on_mailer=on_mailer,
                     store_week=df.store_id.astype(str) + "_" + df.week_no.astype(str))


def test_ladder_recovers_truth():
    df = simulate()
    specs = {
        "1. naive": "log_units ~ log_price",
        "2. + display/mailer": "log_units ~ log_price + on_display + on_mailer",
        "3. + product FE": "log_units ~ log_price + on_display + on_mailer | product_id",
        "4. + store x week FE": "log_units ~ log_price + on_display + on_mailer | product_id + store_week",
    }
    est = {}
    for label, f in specs.items():
        fit = pf.feols(f, data=df, vcov={"CRV1": "product_id"})
        est[label] = fit.tidy().loc["log_price", "Estimate"]
        print(f"  {label:<22} {est[label]:+.3f}")

    print(f"\n  truth                  {TRUE_ELASTICITY:+.3f}")
    naive, preferred = est["1. naive"], est["4. + store x week FE"]
    print(f"  naive bias             {naive - TRUE_ELASTICITY:+.3f}")
    print(f"  preferred bias         {preferred - TRUE_ELASTICITY:+.3f}")

    assert abs(preferred - TRUE_ELASTICITY) < 0.05, "spec 4 failed to recover truth"
    assert abs(naive - TRUE_ELASTICITY) > abs(preferred - TRUE_ELASTICITY), \
        "naive should be more biased than the controlled spec"
    print("\n  PASS: spec 4 recovers the truth; naive does not.")


if __name__ == "__main__":
    test_ladder_recovers_truth()
