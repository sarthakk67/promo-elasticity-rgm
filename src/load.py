"""Load the dunnhumby Complete Journey CSVs into a local DuckDB database.

Column names are normalised to lowercase so the SQL downstream is stable across
the raw dunnhumby distribution and the tidied `completejourney` naming.
"""
from pathlib import Path
import sys
import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "processed" / "journey.duckdb"

# canonical table name -> candidate filename stems seen in the wild
TABLES = {
    "transactions": ["transaction_data", "transactions"],
    "products":     ["product", "products"],
    "causal":       ["causal_data", "promotions"],
    "demographics": ["hh_demographic", "demographics"],
    "campaigns":    ["campaign_table", "campaigns"],
    "campaign_desc":["campaign_desc", "campaign_descriptions"],
    "coupons":      ["coupon", "coupons"],
    "coupon_redempt":["coupon_redempt", "coupon_redemptions"],
}


def find_csv(stems):
    """Locate a CSV by stem anywhere under data/raw (the zip nests a folder)."""
    for stem in stems:
        hits = sorted(RAW.rglob(f"{stem}.csv")) + sorted(RAW.rglob(f"{stem}.csv.gz"))
        if hits:
            return hits[0]
    return None


def main():
    if not any(RAW.rglob("*.csv")) and not any(RAW.rglob("*.csv.gz")):
        sys.exit(f"No CSVs found under {RAW}. Unzip the Complete Journey files there first.")

    DB.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))

    for table, stems in TABLES.items():
        path = find_csv(stems)
        if path is None:
            print(f"  skip  {table:<16} (no file)")
            continue
        con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_csv_auto('{path}')")
        # normalise column names to lowercase
        cols = [c[0] for c in con.execute(f"DESCRIBE {table}").fetchall()]
        for c in cols:
            if c != c.lower():
                con.execute(f'ALTER TABLE {table} RENAME COLUMN "{c}" TO "{c.lower()}"')
        n = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  load  {table:<16} {n:>12,} rows   <- {path.name}")

    print(f"\nDatabase: {DB}")
    con.close()


if __name__ == "__main__":
    main()
