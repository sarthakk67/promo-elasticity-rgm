"""Load Complete Journey into BigQuery and run the panel build there.

The analysis SQL is authored against DuckDB and transpiled by src/port_to_bigquery.py;
this script only does the cloud-side work: create the dataset, load the CSVs, execute
the generated SQL, and report bytes billed.

    ./.venv/bin/python src/port_to_bigquery.py --dataset my-proj.promo_rgm
    ./.venv/bin/python src/bigquery_run.py --dataset my-proj.promo_rgm --dry-run
    ./.venv/bin/python src/bigquery_run.py --dataset my-proj.promo_rgm --load
    ./.venv/bin/python src/bigquery_run.py --dataset my-proj.promo_rgm

Everything here fits comfortably inside the BigQuery free tier: loads are free, the
whole dataset is ~850MB against 10GB free storage, and the panel build scans well
under the 1TB/month free query allowance.
"""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
GEN = ROOT / "sql" / "bigquery"

TABLES = {  # BigQuery table -> source CSV stem
    "transactions": "transaction_data", "products": "product", "causal": "causal_data",
    "demographics": "hh_demographic", "campaigns": "campaign_table",
    "campaign_desc": "campaign_desc", "coupons": "coupon",
    "coupon_redempt": "coupon_redempt",
}
GB = 1024 ** 3


def client_for(dataset):
    from google.cloud import bigquery
    project = dataset.split(".")[0]
    return bigquery.Client(project=project), bigquery


def do_load(dataset):
    client, bigquery = client_for(dataset)
    client.create_dataset(dataset, exists_ok=True)
    cfg = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV, skip_leading_rows=1,
        autodetect=True, write_disposition="WRITE_TRUNCATE")
    for table, stem in TABLES.items():
        hits = sorted(RAW.rglob(f"{stem}.csv"))
        if not hits:
            print(f"  skip  {table:<16} (no {stem}.csv under data/raw)")
            continue
        path = hits[0]
        with path.open("rb") as fh:
            job = client.load_table_from_file(fh, f"{dataset}.{table}", job_config=cfg)
        job.result()
        n = client.get_table(f"{dataset}.{table}").num_rows
        print(f"  load  {table:<16} {n:>12,} rows   <- {path.name}")
    # column names arrive uppercase from the raw CSVs; BigQuery is case-sensitive
    print("\n  normalising column names to lowercase ...")
    for table in TABLES:
        t = client.get_table(f"{dataset}.{table}")
        cols = ", ".join(f"`{f.name}` AS `{f.name.lower()}`" for f in t.schema)
        client.query(
            f"CREATE OR REPLACE TABLE `{dataset}.{table}` AS SELECT {cols} FROM `{dataset}.{table}`"
        ).result()
    print("  done")


def run_sql(dataset, dry_run):
    client, bigquery = client_for(dataset)
    files = sorted(GEN.glob("*.sql"))
    if not files:
        sys.exit("No generated SQL. Run src/port_to_bigquery.py first.")
    from google.api_core.exceptions import NotFound
    # tables this chain creates; a dry run creates nothing, so a later file that
    # reads one of them cannot be validated until the chain has actually run once
    creates = set()
    for f in files:
        for line in f.read_text().splitlines():
            if "CREATE OR REPLACE TABLE" in line.upper():
                creates.add(line.rstrip().split(".")[-1].strip(" `AS"))

    total, deferred = 0, []
    for f in files:
        sql = f.read_text()
        cfg = bigquery.QueryJobConfig(dry_run=dry_run, use_query_cache=False)
        try:
            job = client.query(sql, job_config=cfg)
        except NotFound as e:
            missing = [t for t in creates if t in str(e)]
            if dry_run and missing:
                print(f"  DEFER  {f.name:<26} reads {missing[0]}, created upstream "
                      f"-- validates after a real run")
                deferred.append(f.name)
                continue
            raise
        if dry_run:
            billed = job.total_bytes_processed or 0
            print(f"  VALID  {f.name:<26} would scan {billed/GB:6.3f} GB")
        else:
            job.result()
            billed = job.total_bytes_billed or 0
            print(f"  ran    {f.name:<26} billed     {billed/GB:6.3f} GB")
        total += billed
    if deferred:
        print(f"  ({len(deferred)} file(s) deferred: they read tables the chain "
              f"creates. Re-run --dry-run after a real run to validate them.)")
    label = "would scan" if dry_run else "billed"
    print(f"\n  total {label}: {total/GB:.3f} GB  "
          f"({total/GB/1024:.5f} of the 1 TB monthly free tier)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, help="project.dataset")
    ap.add_argument("--load", action="store_true", help="load the CSVs first")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate the SQL against BigQuery without running it")
    a = ap.parse_args()
    try:
        if a.load:
            do_load(a.dataset)
        run_sql(a.dataset, a.dry_run)
    except Exception as e:
        hint = ""
        if "DefaultCredentials" in type(e).__name__ or "Forbidden" in type(e).__name__:
            hint = ("\n\nCheck that you have run:  gcloud auth application-default login\n"
                    "and that the project has the BigQuery API enabled.")
        sys.exit(f"\nBigQuery error: {type(e).__name__}: {e}{hint}")


if __name__ == "__main__":
    main()
