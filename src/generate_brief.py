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

    export GEMINI_API_KEY=...        # aistudio.google.com/apikey
    ./.venv/bin/python src/generate_brief.py

The provider is incidental. Everything that matters here -- the facts extraction, the
structured schema, the reconciliation and the prose sweep -- is provider-agnostic;
swapping models touches only the request block below.
"""
from pathlib import Path
from typing import List
import os
import re
import sys

import pandas as pd
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
TAB = ROOT / "outputs" / "tables"
OUT = ROOT / "outputs" / "brief.md"
# Pinned for reproducibility. If this 404s in future, the handler below lists what
# the key can reach; "gemini-flash-latest" is the rolling alias if you prefer it not
# to go stale at the cost of a fixed model version.
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
TOL = 0.005         # relative tolerance when reconciling a cited figure


# ---------------------------------------------------------------- facts

def build_facts() -> dict:
    """Every number the model is permitted to use, keyed and sourced from disk."""
    lad = pd.read_csv(TAB / "elasticity_ladder_brandpack.csv")
    xel = pd.read_csv(TAB / "cross_elasticity.csv")     # pooled design -- the quotable one
    hair = pd.read_csv(TAB / "pantry_haircut.csv").iloc[0]
    inc = pd.read_csv(TAB / "incremental_by_mechanic.csv")
    rec = pd.read_csv(TAB / "recommendation.csv")
    swi = pd.read_csv(TAB / "brand_switching.csv")
    rg = pd.read_csv(TAB / "grain_reconciliation.csv").iloc[0]
    sw4 = swi[swi.spec == "4. + week FE"].iloc[0]

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
        # the aggregate null is SUPERSEDED -- see direction_* facts below
        "household_switch_effect_pp": round(float(sw4.rival_promoted) * 100, 1),
        "household_switch_ci_lo_pp": round(float(sw4.ci_lo) * 100, 1),
        "household_switch_ci_hi_pp": round(float(sw4.ci_hi) * 100, 1),
        "household_base_switch_rate_pct": round(float(rg.base_switch_rate) * 100, 1),
        "incumbent_promo_effect_pp": round(float(sw4.incumbent_promoted) * 100, 1),
        "implied_cross_elasticity_from_household": round(float(rg.implied_cross_elasticity), 3),
        "pantry_units_effect_pct": round(float(hair.units_effect) * 100, 1),
        "pantry_gap_effect_pct": round(float(hair.gap_effect) * 100, 1),
        "pantry_haircut_pct": round(float(hair.haircut_share) * 100, 0),
        "incremental_share_of_promoted_volume_pct": round(float(combo_i.incr_share_of_volume) * 100, 1),
        "combo_discount_spend_usd": round(float(combo_i.discount_spend), 0),
        "combo_share_of_all_promo_spend_pct": round(float(combo_i.discount_spend / total_spend) * 100, 0),
        "combo_incremental_units_per_dollar": round(float(combo_i.incr_units_per_dollar), 3),
        "breakeven_gross_margin_pct": round(float(combo_r.breakeven_gross_margin) * 100, 0),
        "assumed_gross_margin_pct": 25.0,        # the margin the $ figures below assume
        "combo_current_depth_pct": round(float(combo_r.current_depth) * 100, 1),
        "combo_breakeven_depth_pct": round(float(combo_r.breakeven_depth_at_25pct) * 100, 1),
        "volume_giveup_pct_of_category": round(float(combo_r.volume_giveup_pct_of_category) * 100, 1),
        "net_gain_from_STOPPING_entirely_at_25pct_usd":
            round(float(combo_r.net_gain_at_25pct), 0),
        # ---- DIRECTION. These are conclusions, not measurements. State them as given.
        "direction_recommendation":
            "CUT THE DISCOUNT DEPTH on the display+mailer mechanic. Do not expand it, "
            "do not reallocate budget toward it. Use combo_current_depth_pct and "
            "combo_breakeven_depth_pct for the figures: it is run at roughly two and a "
            "half times its break-even depth.",
        "direction_breakeven_meaning":
            "A break-even gross margin above 100% means the mechanic cannot pay for "
            "itself at ANY margin: the discount spent exceeds the incremental revenue "
            "generated, before cost of goods is considered. This is a core argument for "
            "the recommendation, not a limitation.",
        "direction_dollar_figure_scope":
            "The dollar net gain measures stopping the mechanic outright. The "
            "recommendation is to cut its depth, a smaller change worth less. So the "
            "dollar figure is an upper bound on what the recommendation is worth. Say "
            "it in exactly that order: what the figure measures, then that the "
            "recommended action is worth less than it. The depth-cut gain was not "
            "computed and must not be stated.",
        "direction_cannibalisation":
            "The aggregate cross-price null is SUPERSEDED by the household result. "
            "Promotion DOES steal volume from rival brands. Report the aggregate null "
            "only as a measurement failure that the household test corrected.",
        # ---- CAVEAT facts belong in the caveats list, not the body.
        "caveat_elasticity_level":
            "-0.571 is a lower bound on the true magnitude; aggregation attenuates it. "
            "The promo conclusions do not depend on the elasticity level.",
        "caveat_incrementality_grain":
            "Incremental share is measured per brand, so a unit switched from a rival "
            "counts as incremental. For the retailer it is not. Retailer-level "
            "incrementality is materially below the figure quoted.",
        "caveat_no_cogs":
            "The dataset has no cost-of-goods field, so gross margin is assumed. That is "
            "why the argument is framed as a break-even threshold rather than a profit "
            "forecast.",
        "caveat_pantry_identification":
            "The pantry-loading result does not control for households timing an "
            "intended stock-up to a promotion. Treat it as an upper bound on "
            "forward-buying, not a point estimate.",
        "caveat_depth_response":
            "The break-even depth calculation holds incremental share fixed as depth "
            "falls, which will not hold exactly. It is a first-order bound.",
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
- If the evidence does not support a claim, put it in caveats instead of asserting it.
- FACTS keys beginning `direction_` are CONCLUSIONS already reached by the analyst.
  State them as given, IN THE BODY. Never infer a different recommendation from the raw
  numbers -- a large spend figure is not evidence that spending more is good.
- FACTS keys beginning `caveat_` belong in the caveats list, never the body. Include all
  of them. Nothing else belongs in caveats.
- Attach every dollar figure to the action it actually measures. Read the key name.
- Where two results conflict, FACTS says which supersedes. Report both and the
  resolution; never present a superseded result as the current answer.
- Write figures readably: $73,110 not 73110.0; 54% not 0.542."""


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
        if isinstance(v, str):
            # string facts (the direction_* conclusions) carry figures in prose;
            # those are sourced too, so admit them rather than flag a false positive
            allowed |= set(re.findall(r"-?\d+(?:,\d{3})*(?:\.\d+)?", v))
        else:
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
    facts = build_facts()
    print(f"loaded {len(facts)} facts from {TAB}")

    payload = "\n".join(f"{k}: {v}" for k, v in facts.items())
    prompt = (f"FACTS\n-----\n{payload}\n\n"
              "Write the promo brief for this category. Four to five sections: "
              "what the elasticity says, whether promotion steals from rivals, "
              "where the lift actually comes from, and the recommendation with its cost.")

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("\nNo API key. Set one:\n"
                 "  export GEMINI_API_KEY=...\n"
                 "Get it at https://aistudio.google.com/apikey (free tier, no card).")

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=key)
    try:
        resp = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                response_schema=Brief,
                # the SDK warns about automatic function calling whenever a Pydantic
                # response_schema is passed; we are not calling tools, so turn it off
                # rather than ship the warning
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True),
            ),
        )
    except Exception as e:
        msg = str(e).lower()
        # Point at the actual cause. An earlier version of this handler blamed the
        # API key for a billing error, which sent the user to fix the wrong thing.
        if "not_found" in msg or "not found" in msg or "404" in msg:
            try:
                avail = [m.name.split("/")[-1] for m in client.models.list()
                         if "generateContent" in (m.supported_actions or [])]
                hint = (f"Model {MODEL!r} is not available to this key. Try one of:\n  "
                        + "\n  ".join(avail)
                        + "\n\nThen: export GEMINI_MODEL=<name>")
            except Exception:
                hint = f"Model {MODEL!r} not found, and listing models also failed."
        elif "api key" in msg or "unauthenticated" in msg or "permission" in msg:
            hint = ("Key rejected. Check it at https://aistudio.google.com/apikey\n"
                    "  export GEMINI_API_KEY=...")
        elif "quota" in msg or "resource_exhausted" in msg or "429" in msg:
            hint = "Free-tier rate limit hit. Wait a minute and re-run."
        else:
            hint = "Unexpected failure -- the message above is the API's own."
        sys.exit(f"\nAPI call failed: {type(e).__name__}\n  {e}\n\n{hint}")

    brief = resp.parsed
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
