"""Build the store-wide panel, then rank commodities on fitness for this study.

Run after src/load.py. Prints the screen and writes it to outputs/tables/.
"""
from pathlib import Path
import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "processed" / "journey.duckdb"
SQL = ROOT / "sql"
OUT = ROOT / "outputs" / "tables"


def main():
    con = duckdb.connect(str(DB))

    print("building panel_all ...")
    con.execute((SQL / "01_panel.sql").read_text())
    n = con.execute("SELECT COUNT(*) FROM panel_all").fetchone()[0]
    print(f"  panel_all: {n:,} product x store x week rows\n")

    # sanity: the price reconstruction must not produce shelf < paid
    bad = con.execute(
        "SELECT COUNT(*) FROM panel_all WHERE shelf_price < paid_price - 0.001"
    ).fetchone()[0]
    if bad:
        print(f"  WARNING: {bad:,} rows where shelf_price < paid_price -- "
              "check the discount sign convention in your CSVs\n")

    screen = con.execute((SQL / "02_category_screen.sql").read_text()).df()
    OUT.mkdir(parents=True, exist_ok=True)
    screen.to_csv(OUT / "category_screen.csv", index=False)

    # the shortlist: enough promo variation to identify, and a real #2 manufacturer
    ok = screen[(screen.within_sw_variation > 0.30)
                & (screen.promo_share.between(0.05, 0.70))
                & (screen.manufacturers >= 3)]

    pd.set_option("display.width", 200, "display.max_columns", 20)
    print("=== top 15 by within-store-week promo variation ===")
    print(screen.head(15).to_string(index=False))
    print(f"\n=== shortlist ({len(ok)} categories clear all three filters) ===")
    print(ok.head(10).to_string(index=False))
    con.close()


if __name__ == "__main__":
    main()
