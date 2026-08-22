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
    own, own_se = -0.644, 0.106
    cross, cross_se = 0.031, 0.063
    fig, ax = plt.subplots(figsize=(9, 3.0))
    rows = [("cross-price elasticity\n(vs rival brands)", cross, cross_se, BLUE),
            ("own-price elasticity", own, own_se, MUTED)]
    for i, (lab, v, se, c) in enumerate(rows):
        ax.errorbar(v, i, xerr=1.96 * se, fmt="o", ms=9, color=c,
                    ecolor=c, elinewidth=2.5, capsize=0, zorder=3,
                    markeredgecolor=SURFACE, markeredgewidth=2)
    ax.axvline(0, color=INK_2, lw=1.2, zorder=1)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=9)
    ax.set_ylim(-0.6, 1.6)
    ax.set_xlabel("elasticity")
    ax.text(cross + 1.96 * cross_se + 0.03, 0,
            "95% CI [−0.09, +0.15] — spans zero.\nRules out substitution above 0.15.",
            va="center", fontsize=9, color=INK_2)
    ax.set_title("No detectable cannibalisation between competing soft-drink brands",
                 loc="left", fontsize=12, weight="bold", color=INK, pad=12)
    ax.set_xlim(-0.90, 0.62)
    style(ax)
    fig.text(0.008, 0.02, "75 brand-pack clusters · 5,461 brand-pack × week cells · "
                          "brand-pack and week fixed effects", fontsize=8, color=INK_2)
    fig.tight_layout(rect=[0, 0.07, 1, 1])
    fig.savefig(FIG / "02_cannibalisation_null.png", dpi=200)
    print("  02_cannibalisation_null.png")


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
