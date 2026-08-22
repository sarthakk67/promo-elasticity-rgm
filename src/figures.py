"""Three figures for the README. Reads only the saved result tables, so the charts
can never drift from the numbers the analysis actually produced."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TAB, FIG = ROOT / "outputs" / "tables", ROOT / "outputs" / "figures"

SURFACE   = "#fcfcfb"
INK       = "#0b0b0b"
INK_2     = "#52514e"
GRID      = "#e4e3df"
MUTED     = "#b9b8b3"      # de-emphasised marks
BLUE      = "#2a78d6"      # categorical slot 1
ORANGE    = "#eb6834"      # categorical slot 2

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE, "font.size": 10,
    "text.color": INK, "axes.labelcolor": INK_2, "axes.edgecolor": GRID,
    "xtick.color": INK_2, "ytick.color": INK_2,
    "font.family": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
})


def style(ax, xgrid=True):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(length=0)
    if xgrid:
        ax.set_axisbelow(True)
        ax.grid(axis="x", color=GRID, lw=0.8)


def fig1_ladder():
    d = pd.read_csv(TAB / "elasticity_ladder_brandpack.csv")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.2), width_ratios=[1.25, 1])

    y = np.arange(len(d))[::-1]
    colors = [MUTED] * (len(d) - 1) + [BLUE]
    a1.barh(y, d.elasticity, height=0.55, color=colors,
            xerr=1.96 * d.std_error, error_kw=dict(ecolor=INK_2, lw=1, capsize=0))
    a1.axvline(0, color=INK_2, lw=1)
    a1.set_yticks(y, d.spec, fontsize=9)
    a1.set_xlabel("own-price elasticity")
    a1.set_title("Price response is 1.7× larger than the naive estimate",
                 loc="left", fontsize=11, color=INK, pad=10)
    # labels live in their own column right of zero -- inside the plot they get
    # struck through by the CI whiskers
    for yi, v, p in zip(y, d.elasticity, d.p_value):
        tag = f"{v:.2f}" + ("   n.s." if p >= 0.05 else "")
        a1.text(0.12, yi, tag, va="center", ha="left", fontsize=9, color=INK_2)
    a1.set_xlim(-0.95, 0.36)
    a1.set_xticks([-0.8, -0.6, -0.4, -0.2, 0.0])
    style(a1)

    dd = d.dropna(subset=["display_coef"]).reset_index(drop=True)
    lift = np.exp(dd.display_coef) - 1
    y2 = np.arange(len(dd))[::-1]
    a2.barh(y2, lift * 100, height=0.55, color=[MUTED] * (len(dd) - 1) + [ORANGE])
    a2.set_yticks(y2, dd.spec, fontsize=9)
    a2.set_xlabel("display lift, % (0 → 100% display coverage)")
    a2.set_title("…while display lift is 4.1× smaller", loc="left",
                 fontsize=11, color=INK, pad=10)
    for yi, v in zip(y2, lift * 100):
        a2.text(v + 6, yi, f"+{v:.0f}%", va="center", fontsize=9, color=INK_2)
    a2.set_xlim(0, 340)
    style(a2)

    fig.suptitle("Both naive errors push the same way: promote more",
                 x=0.008, ha="left", fontsize=13, weight="bold", color=INK)
    fig.text(0.008, 0.005,
             "dunnhumby Complete Journey · SOFT DRINKS · brand-pack × week, 6,058 cells · "
             "bars show 95% CI, SEs clustered on brand-pack",
             fontsize=8, color=INK_2, ha="left")
    fig.tight_layout(rect=[0, 0.045, 1, 0.93])
    fig.savefig(FIG / "01_elasticity_ladder.png", dpi=200)
    print("  01_elasticity_ladder.png")


def fig2_cannibalisation():
    """Same question, two grains, opposite answers. Separate panels because the
    units differ (elasticity vs percentage points) -- never a shared axis."""
    xel = pd.read_csv(TAB / "cross_elasticity.csv").iloc[0]
    sw = pd.read_csv(TAB / "brand_switching.csv")
    sw4 = sw[sw.spec == "4. + week FE"].iloc[0]

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 3.4))

    # aggregate: the null
    a1.errorbar(xel.cross_elasticity, 0, xerr=1.96 * xel.cross_se, fmt="o", ms=10,
                color=MUTED, ecolor=MUTED, elinewidth=3, capsize=0,
                markeredgecolor=SURFACE, markeredgewidth=2, zorder=3)
    a1.axvline(0, color=INK_2, lw=1.2)
    a1.set_yticks([0], ["cross-price\nelasticity"], fontsize=9)
    a1.set_ylim(-0.9, 0.9)
    a1.set_xlabel("elasticity")
    a1.set_xlim(-0.30, 0.30)
    a1.set_title("Brand-pack × week: nothing", loc="left", fontsize=11, color=INK, pad=10)
    a1.text(0, -0.62, f"{xel.cross_elasticity:+.3f}   CI [{xel.cross_ci_lo:+.2f}, "
            f"{xel.cross_ci_hi:+.2f}] spans zero",
            ha="center", fontsize=9, color=INK_2,
            bbox=dict(facecolor=SURFACE, edgecolor="none", pad=2))
    style(a1)

    # household: the finding
    a2.errorbar(sw4.rival_promoted * 100, 0, xerr=1.96 * sw4.se * 100, fmt="o", ms=10,
                color=BLUE, ecolor=BLUE, elinewidth=3, capsize=0,
                markeredgecolor=SURFACE, markeredgewidth=2, zorder=3)
    a2.axvline(0, color=INK_2, lw=1.2)
    a2.set_yticks([0], ["switch away from\nincumbent brand"], fontsize=9)
    a2.set_ylim(-0.9, 0.9)
    a2.set_xlabel("change in switch probability, percentage points")
    a2.set_xlim(-2, 10)
    a2.set_title("Household trip: +7.3pp", loc="left", fontsize=11, color=INK, pad=10)
    a2.text(sw4.rival_promoted * 100, -0.62,
            f"+{sw4.rival_promoted*100:.1f}pp   CI [+{sw4.ci_lo*100:.1f}, "
            f"+{sw4.ci_hi*100:.1f}]   p < 0.001",
            ha="center", fontsize=9, color=INK_2,
            bbox=dict(facecolor=SURFACE, edgecolor="none", pad=2))
    style(a2)

    fig.suptitle("The same question at two grains gives opposite answers",
                 x=0.008, ha="left", fontsize=13, weight="bold", color=INK)
    fig.text(0.008, 0.005,
             "Aggregating to brand-pack × week cancels households switching in opposite "
             "directions · 57,152 trips, 1,644 households · household and week FE · "
             "placebo (next week's rival promo) is null at p = 0.25",
             fontsize=8, color=INK_2)
    fig.tight_layout(rect=[0, 0.06, 1, 0.90])
    fig.savefig(FIG / "02_cannibalisation_two_grains.png", dpi=200)
    print("  02_cannibalisation_two_grains.png")


def fig3_mechanics():
    d = pd.read_csv(TAB / "incremental_by_mechanic.csv")
    spend = d[d.counterfactual == "GBM"].set_index("mechanic").discount_spend
    piv = d.pivot_table(index="mechanic", columns="counterfactual",
                        values="incr_units_per_dollar")
    order = spend.sort_values(ascending=True).index
    spend, piv = spend.loc[order], piv.loc[order]
    y = np.arange(len(order))

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 3.6))
    a1.barh(y, spend / 1000, height=0.5, color=[MUTED, MUTED, BLUE])
    a1.set_yticks(y, order, fontsize=9)
    a1.set_xlabel("discount spend, $000")
    a1.set_title("87% of promo spend goes to one mechanic",
                 loc="left", fontsize=11, color=INK, pad=10)
    tot = spend.sum()
    for yi, v in zip(y, spend):
        a1.text(v / 1000 + 1.5, yi, f"${v/1000:.0f}k  ({v/tot:.0%})",
                va="center", fontsize=9, color=INK_2)
    a1.set_xlim(0, 96)
    style(a1)

    h = 0.28                      # thin marks, with a visible gap between the pair
    a2.barh(y + h / 2 + 0.015, piv["GBM"], height=h, color=BLUE, label="GBM")
    a2.barh(y - h / 2 - 0.015, piv["FE"], height=h, color=ORANGE, label="fixed effects")
    a2.set_yticks(y, order, fontsize=9)
    a2.set_xlabel("incremental units per discount dollar")
    a2.set_title("…and it is no more efficient than display alone",
                 loc="left", fontsize=11, color=INK, pad=10)
    # legend sits in the empty right-hand third: no bar reaches past 0.66
    a2.legend(frameon=False, fontsize=9, labelcolor=INK_2, loc="center right",
              handlelength=1.1, title="counterfactual", alignment="left")
    a2.get_legend().get_title().set_fontsize(8.5)
    a2.get_legend().get_title().set_color(INK_2)
    a2.set_xlim(0, 1.0)
    style(a2)

    fig.suptitle("The budget is concentrated in the mechanic with no efficiency edge",
                 x=0.008, ha="left", fontsize=13, weight="bold", color=INK)
    fig.text(0.008, 0.005,
             "1,275 promoted brand-pack × weeks · two independent counterfactuals shown "
             "because they disagree at mechanic level (aggregate r = 0.99)",
             fontsize=8, color=INK_2)
    fig.tight_layout(rect=[0, 0.05, 1, 0.91])
    fig.savefig(FIG / "03_mechanic_efficiency.png", dpi=200)
    print("  03_mechanic_efficiency.png")


if __name__ == "__main__":
    FIG.mkdir(parents=True, exist_ok=True)
    fig1_ladder(); fig2_cannibalisation(); fig3_mechanics()
    print(f"\nwrote to {FIG}")
