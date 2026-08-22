"""Generate BigQuery SQL from the DuckDB source, so the two can never drift.

The analysis SQL is written once against DuckDB (fast local iteration, no cloud
bill) and mechanically transpiled to BigQuery standard SQL. Table references are
qualified with the target dataset at generation time.

    ./.venv/bin/python src/port_to_bigquery.py --dataset my_project.promo_rgm
"""
from pathlib import Path
import argparse
import sqlglot
from sqlglot import exp

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "sql"
DST = ROOT / "sql" / "bigquery"

# tables that live in the dataset (everything else is a CTE and must stay bare)
DATASET_TABLES = {"transactions", "products", "causal", "demographics", "campaigns",
                  "campaign_desc", "coupons", "coupon_redempt", "panel_all", "brandpack"}


def fix_bigquery_quirks(tree):
    """Repair constructs sqlglot emits that BigQuery rejects.

    ANY_VALUE: DuckDB ignores nulls implicitly, so sqlglot makes that explicit as
    ANY_VALUE(x IGNORE NULLS). BigQuery's ANY_VALUE also ignores nulls but refuses
    the modifier outright -- 'IGNORE NULLS ... not allowed for aggregate function
    any_value'. Dropping it is semantics-preserving.
    """
    for node in list(tree.find_all(exp.IgnoreNulls)):
        if isinstance(node.this, exp.AnyValue):
            node.replace(node.this)      # unwrap: ANY_VALUE(x IGNORE NULLS) -> ANY_VALUE(x)
    return tree


def qualify(tree, dataset):
    """Prefix real tables with the dataset; leave CTE references alone."""
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for tbl in tree.find_all(exp.Table):
        name = tbl.name.lower()
        if name in ctes or name not in DATASET_TABLES:
            continue
        tbl.set("db", exp.to_identifier(dataset.split(".")[-1]))
        if "." in dataset:
            tbl.set("catalog", exp.to_identifier(dataset.split(".")[0]))
    return tree


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True,
                    help="target as project.dataset, e.g. my-proj.promo_rgm")
    args = ap.parse_args()

    DST.mkdir(parents=True, exist_ok=True)
    for f in sorted(SRC.glob("*.sql")):
        trees = sqlglot.parse(f.read_text(), read="duckdb")
        out = []
        for t in trees:
            if t is None:
                continue
            t = fix_bigquery_quirks(qualify(t, args.dataset))
            out.append(t.sql(dialect="bigquery", pretty=True))
        text = ("-- GENERATED from sql/%s by src/port_to_bigquery.py -- do not edit.\n"
                "-- Regenerate after changing the DuckDB source.\n\n" % f.name)
        text += ";\n\n".join(out) + ";\n"
        (DST / f.name).write_text(text)
        print(f"  {f.name} -> sql/bigquery/{f.name}")


if __name__ == "__main__":
    main()
