"""Turn the result tables into a category promo brief, with a verification layer.

An LLM that writes prose over numbers will occasionally invent one. A brief that
says "elasticity of -0.58" when the table says -0.571 is worse than no brief at
all, because it reads exactly as authoritative. So generation is only half of this
module; the other half checks it.

How the guardrail works:
  1. Every figure the model is allowed to use is extracted from the result CSVs
     into a FACTS dict with stable keys.
  2. The model must return structured output -- not free prose -- in which every
     figure it cites is declared as {fact_key, value_as_written}. Validation runs
     against those declarations rather than a regex over prose, so it is exact.
  3. Each declared figure is reconciled against FACTS numerically, tolerating
     rounding and percent/decimal rendering.
  4. A secondary sweep scans the prose for numeric tokens that were never declared,
     which is how a hallucinated figure would slip past step 3.

Non-zero exit on any unreconciled figure. A brief that cannot be verified is not
shipped.

    export ANTHROPIC_API_KEY=sk-ant-...
    ./.venv/bin/python src/generate_brief.py
"""
from pathlib import Path
from typing import List
import re
import sys

import pandas as pd
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
TAB = ROOT / "outputs" / "tables"
OUT = ROOT / "outputs" / "brief.md"
MODEL = "claude-opus-5"
TOL = 0.005         # relative tolerance when reconciling a cited figure


# ---------------------------------------------------------------- facts

def build_facts() -> dict:
    """Every number the model is permitted to use, keyed and sourced from disk."""
    lad = pd.read_csv(TAB / "elasticity_ladder_brandpack.csv")
    xel = pd.read_csv(TAB / "cross_elasticity.csv")     # pooled design -- the quotable one
    hair = pd.read_csv(TAB / "pantry_haircut.csv").iloc[0]
    inc = pd.read_csv(TAB / "incremental_by_mechanic.csv")
    rec = pd.read_csv(TAB / "recommendation.csv")

    naive, pref = lad.elasticity.iloc[0], lad.elasticity.iloc[-1]
    dn = lad.display_coef.dropna().iloc[0]
    dp = lad.display_coef.dropna().iloc[-1]
    combo_i = inc[(inc.mechanic == "display + mailer") & (inc.counterfactual == "GBM")].iloc[0]
    combo_r = rec[(rec.mechanic == "display + mailer") & (rec.counterfactual == "GBM")].iloc[0]
    total_spend = inc[inc.counterfactual == "GBM"].discount_spend.sum()
    import numpy as np

    return {
        "category": "SOFT DRINKS",
        "own_elasticity_naive": round(float(naive), 3),
        "own_elasticity_preferred": round(float(pref), 3),
        "elasticity_understatement_x": round(float(pref / naive), 2),
        "naive_elasticity_p_value": round(float(lad.p_value.iloc[0]), 3),
        "display_lift_naive_pct": round(float(np.exp(dn) - 1) * 100, 1),
        "display_lift_preferred_pct": round(float(np.exp(dp) - 1) * 100, 1),
        "cross_price_elasticity": round(float(xel.cross_elasticity.iloc[0]), 3),
        "cross_price_ci_low": round(float(xel.cross_ci_lo.iloc[0]), 3),
        "cross_price_ci_high": round(float(xel.cross_ci_hi.iloc[0]), 3),
        "cross_elasticity_clusters": int(xel.clusters.iloc[0]),
        "pantry_units_effect_pct": round(float(hair.units_effect) * 100, 1),
        "pantry_gap_effect_pct": round(float(hair.gap_effect) * 100, 1),
        "pantry_haircut_pct": round(float(hair.haircut_share) * 100, 0),
        "incremental_share_of_promoted_volume_pct": round(float(combo_i.incr_share_of_volume) * 100, 1),
        "combo_discount_spend_usd": round(float(combo_i.discount_spend), 0),
        "combo_share_of_all_promo_spend_pct": round(float(combo_i.discount_spend / total_spend) * 100, 0),
        "combo_incremental_units_per_dollar": round(float(combo_i.incr_units_per_dollar), 3),
        "breakeven_gross_margin_pct": round(float(combo_r.breakeven_gross_margin) * 100, 0),
        "volume_giveup_pct_of_category": round(float(combo_r.volume_giveup_pct_of_category) * 100, 1),
        "net_gain_at_25pct_margin_usd": round(float(combo_r.net_gain_at_25pct), 0),
    }


# ---------------------------------------------------------------- schema

class Figure(BaseModel):
    fact_key: str          # must exist in FACTS
    value_as_written: str  # exactly as it appears in the prose


class Section(BaseModel):
    title: str
    body: str


class Brief(BaseModel):
    headline: str
    sections: List[Section]
    figures_cited: List[Figure]
    caveats: List[str]


SYSTEM = """You write revenue-growth-management briefs for grocery category managers.

Rules you must follow exactly:
- Use ONLY figures supplied in the FACTS block. Never introduce a number that is
  not in FACTS, including ones you could compute yourself.
- Every figure appearing anywhere in your prose must also be declared in
  figures_cited, with the matching fact_key and the value exactly as written.
- Do not round differently from FACTS.
- A negative elasticity between -1 and 0 means INELASTIC: volume does not respond
  enough to pay for a price cut. Do not describe such a category as price-sensitive.
- Be direct. State the recommendation and what it costs. No hedging, no filler.
- If the evidence does not support a claim, put it in caveats instead of asserting it."""


# ---------------------------------------------------------------- validation

def _renderings(v: float) -> set:
    """Plausible string forms of a numeric fact, for the prose sweep."""
    out = set()
    for x in (v, abs(v)):
        for s in (f"{x:g}", f"{x:.0f}", f"{x:.1f}", f"{x:.2f}", f"{x:.3f}"):
            out.add(s.lstrip("+"))
        if abs(x) >= 1000:
            out.add(f"{x:,.0f}")
    return out


def validate(brief: Brief, facts: dict) -> list:
    problems = []

    # 1. every declared figure reconciles against FACTS
    for fig in brief.figures_cited:
        if fig.fact_key not in facts:
            problems.append(f"cites unknown fact_key {fig.fact_key!r} "
                            f"(value written: {fig.value_as_written!r})")
            continue
        truth = facts[fig.fact_key]
        if isinstance(truth, str):
            continue
        nums = re.findall(r"-?\d+(?:,\d{3})*(?:\.\d+)?", fig.value_as_written)
        if not nums:
            problems.append(f"{fig.fact_key}: no number in {fig.value_as_written!r}")
            continue
        written = float(nums[0].replace(",", ""))
        # Allow only the rounding the model's OWN written precision implies. A flat
        # floor is useless here: 0.05 is nothing against 73,110 and everything
        # against -0.571, which is exactly the figure most likely to drift.
        decimals = len(nums[0].split(".")[1]) if "." in nums[0] else 0
        allowed = max(0.5 * 10 ** (-decimals), TOL * abs(float(truth)))
        if abs(abs(written) - abs(float(truth))) > allowed:
            problems.append(f"{fig.fact_key}: wrote {written}, table says {truth} "
                            f"(tolerance {allowed:.4g} at {decimals}dp)")

    # 2. prose sweep -- catches a figure that was never declared at all
    allowed = {"0", "1", "2", "3", "4", "5", "95", "100"}
    for v in facts.values():
        if not isinstance(v, str):
            allowed |= _renderings(float(v))
    prose = " ".join(s.body for s in brief.sections) + " " + brief.headline
    for tok in set(re.findall(r"-?\d+(?:,\d{3})*(?:\.\d+)?", prose)):
        if tok.lstrip("-").replace(",", "") not in {a.replace(",", "") for a in allowed}:
            problems.append(f"undeclared number in prose: {tok!r}")
    return problems


# ---------------------------------------------------------------- main

def render(brief: Brief) -> str:
    md = [f"# {brief.headline}", ""]
    for s in brief.sections:
        md += [f"## {s.title}", "", s.body, ""]
    if brief.caveats:
        md += ["## What this does not support", ""]
        md += [f"- {c}" for c in brief.caveats] + [""]
    md += ["---", "", "*Generated by `src/generate_brief.py` from the result tables. "
           "Every figure is machine-reconciled against source before this file is written.*"]
    return "\n".join(md)


def main():
    import anthropic

    facts = build_facts()
    print(f"loaded {len(facts)} facts from {TAB}")

    payload = "\n".join(f"{k}: {v}" for k, v in facts.items())
    try:
        client = anthropic.Anthropic()
        resp = client.messages.parse(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content":
                       f"FACTS\n-----\n{payload}\n\n"
                       "Write the promo brief for this category. Four to five sections: "
                       "what the elasticity says, whether promotion steals from rivals, "
                       "where the lift actually comes from, and the recommendation with "
                       "its cost."}],
            output_format=Brief,
        )
    except Exception as e:
        sys.exit(f"\nAPI call failed: {type(e).__name__}: {e}\n\n"
                 "Set a key first:  export ANTHROPIC_API_KEY=sk-ant-...\n"
                 "Get one at https://console.anthropic.com/settings/keys")

    brief = resp.parsed_output
    problems = validate(brief, facts)
    print(f"cited {len(brief.figures_cited)} figures")
    if problems:
        print("\nVERIFICATION FAILED -- brief not written:")
        for p in problems:
            print(f"  - {p}")
        sys.exit(1)

    OUT.write_text(render(brief))
    print(f"all {len(brief.figures_cited)} figures reconcile against source")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
