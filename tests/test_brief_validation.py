"""Does the brief validator actually catch a hallucinated figure?

A verification layer that has never been shown to reject anything is decoration.
These cases feed the validator briefs that a real model plausibly could produce --
a number nudged just past rounding, a fabricated fact key, a figure smuggled into
prose without being declared -- and assert each one is caught.

Runs offline: no API key, no network.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from generate_brief import Brief, Figure, Section, build_facts, validate

FACTS = build_facts()


def _brief(body, figures):
    return Brief(headline="Soft drinks promo review",
                 sections=[Section(title="Finding", body=body)],
                 figures_cited=figures, caveats=[])


def test_clean_brief_passes():
    b = _brief("Own-price elasticity is -0.571, which is inelastic.",
               [Figure(fact_key="own_elasticity_preferred", value_as_written="-0.571")])
    assert validate(b, FACTS) == [], "a correct brief must pass"


def test_catches_nudged_number():
    """-0.58 instead of -0.571: the classic LLM rounding drift."""
    b = _brief("Own-price elasticity is -0.58.",
               [Figure(fact_key="own_elasticity_preferred", value_as_written="-0.58")])
    problems = validate(b, FACTS)
    assert any("own_elasticity_preferred" in p for p in problems), problems


def test_catches_invented_fact_key():
    b = _brief("Category margin is 32%.",
               [Figure(fact_key="gross_margin_pct", value_as_written="32%")])
    problems = validate(b, FACTS)
    assert any("unknown fact_key" in p for p in problems), problems


def test_catches_undeclared_number_in_prose():
    """The dangerous case: a figure that never appears in figures_cited at all."""
    b = _brief("Elasticity is -0.571 and the promo returned 3.7x on spend.",
               [Figure(fact_key="own_elasticity_preferred", value_as_written="-0.571")])
    problems = validate(b, FACTS)
    assert any("undeclared number" in p and "3.7" in p for p in problems), problems


def test_catches_wrong_value_for_right_key():
    b = _brief("The combo mechanic absorbed $91,000 of discount.",
               [Figure(fact_key="combo_discount_spend_usd", value_as_written="$91,000")])
    problems = validate(b, FACTS)
    assert any("combo_discount_spend_usd" in p for p in problems), problems


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  PASS  {t.__name__}")
    print(f"\n  {len(tests)}/{len(tests)} passed -- the validator rejects what it should.")
