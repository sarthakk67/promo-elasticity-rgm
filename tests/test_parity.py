"""DuckDB vs BigQuery parity.

The analysis SQL is authored against DuckDB and transpiled to BigQuery by
src/port_to_bigquery.py. A transpile that parses is not a transpile that is
CORRECT -- ANY_VALUE(x IGNORE NULLS) parsed fine and BigQuery rejected it at
runtime, and a silent dialect difference in LN/EXP would change the price index
without erroring at all.

So this asserts the two engines agree on the actual numbers, including the
float-sensitive ones that would expose a semantics drift.

Requires: the BigQuery tables built (src/bigquery_run.py) and DuckDB populated.
Skipped automatically when credentials or the local DB are absent.
"""
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "processed" / "journey.duckdb"
DATASET = "promo-rgm.promo_rgm"
TOL = 1e-4

CHECKS = [
    ("panel_all rows",      "SELECT COUNT(*) FROM {panel_all}"),
    ("brandpack cells",     "SELECT COUNT(*) FROM {brandpack}"),
    ("brand-packs >=30wk",  "SELECT COUNT(*) FROM (SELECT manufacturer, sub_commodity_desc "
                            "FROM {brandpack} GROUP BY 1,2 HAVING COUNT(*)>=30) x"),
    ("soft drinks units",   "SELECT ROUND(SUM(units),0) FROM {brandpack}"),
    ("total sales value",   "SELECT ROUND(SUM(sales_value),2) FROM {brandpack}"),
    ("mean price_index",    "SELECT ROUND(AVG(price_index),6) FROM {brandpack}"),
]


def _engines():
    duckdb = pytest.importorskip("duckdb")
    if not DB.exists():
        pytest.skip("local DuckDB not built")
    try:
        from google.cloud import bigquery
        bq = bigquery.Client(project=DATASET.split(".")[0])
        bq.query("SELECT 1").result()
    except Exception as e:
        pytest.skip(f"BigQuery unavailable: {type(e).__name__}")
    return duckdb.connect(str(DB), read_only=True), bq


def test_duckdb_bigquery_parity():
    dd, bq = _engines()
    local = {"panel_all": "panel_all", "brandpack": "brandpack"}
    cloud = {k: f"`{DATASET}.{k}`" for k in local}
    mismatches = []
    for name, tmpl in CHECKS:
        d = float(dd.execute(tmpl.format(**local)).fetchone()[0])
        b = float(list(bq.query(tmpl.format(**cloud)).result())[0][0])
        print(f"  {name:<22} duckdb={d:>16,.4f}  bigquery={b:>16,.4f}")
        if abs(d - b) >= TOL:
            mismatches.append(f"{name}: duckdb={d} bigquery={b}")
    assert not mismatches, "engines disagree:\n  " + "\n  ".join(mismatches)


if __name__ == "__main__":
    test_duckdb_bigquery_parity()
    print("\n  PASS: DuckDB and BigQuery agree on every check.")
