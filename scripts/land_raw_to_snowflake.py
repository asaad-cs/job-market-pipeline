"""
Phase A — Land existing SQLite raw data into Snowflake BRONZE layer.

Reads from data/pipeline.db (no API calls) and creates:
  JOB_PIPELINE_DB.BRONZE.collection_runs   (4 rows)
  JOB_PIPELINE_DB.BRONZE.raw_jobs          (1,109 rows)

raw_payload is stored as VARIANT (PARSE_JSON applied on insert) so that
downstream dbt staging models can use Snowflake path syntax directly.

Idempotency: aborts if BRONZE.raw_jobs already contains rows. To re-run from
scratch, TRUNCATE both tables first.
"""
import io, os, sqlite3, sys

sys.path.insert(0, ".")
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

import snowflake.connector

SQLITE_PATH = "./data/pipeline.db"

_CREATE_RAW_SCHEMA = "CREATE SCHEMA IF NOT EXISTS BRONZE"

_CREATE_COLLECTION_RUNS = """
CREATE TABLE IF NOT EXISTS BRONZE.collection_runs (
    run_id          VARCHAR(36)   NOT NULL,
    started_at      VARCHAR(50),
    completed_at    VARCHAR(50),
    source_name     VARCHAR(100),
    records_fetched INTEGER,
    notes           TEXT
)
"""

_CREATE_RAW_JOBS = """
CREATE TABLE IF NOT EXISTS BRONZE.raw_jobs (
    raw_id          VARCHAR(36)   NOT NULL,
    run_id          VARCHAR(36)   NOT NULL,
    source_name     VARCHAR(100)  NOT NULL,
    source_job_id   VARCHAR(500),
    source_url      TEXT          NOT NULL,
    raw_payload     VARIANT       NOT NULL,
    collected_at    VARCHAR(50)   NOT NULL
)
"""

_INSERT_COLLECTION_RUN = """
INSERT INTO BRONZE.collection_runs
    (run_id, started_at, completed_at, source_name, records_fetched, notes)
VALUES (%s, %s, %s, %s, %s, %s)
"""

_INSERT_RAW_JOB = """
INSERT INTO BRONZE.raw_jobs
    (raw_id, run_id, source_name, source_job_id, source_url, raw_payload, collected_at)
SELECT %s, %s, %s, %s, %s, PARSE_JSON(%s), %s
"""


def _get_snowflake_conn():
    required = [
        "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD",
        "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        sys.exit(f"ERROR: Missing Snowflake env vars: {missing}")
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
    )


def main():
    # ── Step 1: Read from SQLite ──────────────────────────────────────────────
    print("Reading from SQLite...")
    sqlite_conn = sqlite3.connect(SQLITE_PATH)

    runs = sqlite_conn.execute(
        "SELECT run_id, started_at, completed_at, source_name, records_fetched, notes "
        "FROM collection_runs ORDER BY started_at"
    ).fetchall()

    raw_jobs = sqlite_conn.execute(
        "SELECT raw_id, run_id, source_name, source_job_id, source_url, raw_payload, collected_at "
        "FROM raw_jobs"
    ).fetchall()
    sqlite_conn.close()

    print(f"  collection_runs : {len(runs)} rows")
    print(f"  raw_jobs        : {len(raw_jobs)} rows")

    if len(runs) != 4 or len(raw_jobs) != 1109:
        print(f"WARNING: unexpected source counts (expected 4 runs, 1109 raw_jobs)")

    # ── Step 2: Connect to Snowflake ──────────────────────────────────────────
    print("\nConnecting to Snowflake...")
    sf = _get_snowflake_conn()
    cur = sf.cursor()

    # ── Step 3: Create RAW schema and tables ──────────────────────────────────
    print("Creating BRONZE schema and tables if not exist...")
    cur.execute(_CREATE_RAW_SCHEMA)
    cur.execute(_CREATE_COLLECTION_RUNS)
    cur.execute(_CREATE_RAW_JOBS)

    # ── Step 4: Idempotency guard ─────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) FROM BRONZE.raw_jobs")
    existing = cur.fetchone()[0]
    if existing > 0:
        print(f"\nABORT: BRONZE.raw_jobs already contains {existing} rows.")
        print("To re-run: TRUNCATE TABLE BRONZE.raw_jobs; TRUNCATE TABLE BRONZE.collection_runs;")
        cur.close()
        sf.close()
        sys.exit(1)

    # ── Step 5: Load collection_runs ──────────────────────────────────────────
    print(f"\nLoading {len(runs)} collection_runs rows...")
    for row in runs:
        cur.execute(_INSERT_COLLECTION_RUN, row)
    sf.commit()
    print("  Done.")

    # ── Step 6: Load raw_jobs ─────────────────────────────────────────────────
    print(f"\nLoading {len(raw_jobs)} raw_jobs rows (PARSE_JSON on each — ~60-90s)...")
    inserted = 0
    failed: list[tuple[str, str]] = []

    for i, row in enumerate(raw_jobs):
        raw_id, run_id, source_name, source_job_id, source_url, raw_payload, collected_at = row
        try:
            cur.execute(
                _INSERT_RAW_JOB,
                (raw_id, run_id, source_name, source_job_id, source_url, raw_payload, collected_at),
            )
            inserted += 1
        except Exception as e:
            failed.append((raw_id, str(e)))

        if (i + 1) % 100 == 0 or (i + 1) == len(raw_jobs):
            print(f"  {i + 1:>4}/{len(raw_jobs)} rows ...")

    sf.commit()

    # ── Step 7: Verify ────────────────────────────────────────────────────────
    cur.execute("SELECT COUNT(*) FROM BRONZE.collection_runs")
    sf_run_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM BRONZE.raw_jobs")
    sf_raw_count = cur.fetchone()[0]

    cur.execute(
        "SELECT run_id, source_name, records_fetched, started_at "
        "FROM BRONZE.collection_runs ORDER BY started_at"
    )
    sf_runs = cur.fetchall()

    cur.execute(
        "SELECT run_id, COUNT(*) AS cnt FROM BRONZE.raw_jobs "
        "GROUP BY run_id ORDER BY MIN(collected_at)"
    )
    sf_per_run = cur.fetchall()

    cur.close()
    sf.close()

    # ── Step 8: Report ────────────────────────────────────────────────────────
    print(f"\n{'=' * 55}")
    print("PHASE A — LANDING COMPLETE")
    print(f"{'=' * 55}")
    print(f"  BRONZE.collection_runs : {sf_run_count} rows")
    print(f"  BRONZE.raw_jobs        : {sf_raw_count} rows")
    if failed:
        print(f"  FAILED              : {len(failed)} rows")
        for raw_id, err in failed:
            print(f"    {raw_id[:8]}: {err[:80]}")
    print()
    print("  collection_runs breakdown:")
    for run_id, source, count, started in sf_runs:
        print(f"    {str(run_id)[:8]}  {source}  {count} records  {str(started)[:19]}")
    print()
    print("  raw_jobs per run:")
    for run_id, cnt in sf_per_run:
        print(f"    {str(run_id)[:8]}  {cnt} records")
    print()

    passed = sf_run_count == 4 and sf_raw_count == 1109 and not failed
    if passed:
        print("PASS — all 1,109 raw_jobs and 4 collection_runs landed. Ready for Phase B.")
    else:
        print(f"FAIL — expected 4 runs and 1,109 raw_jobs. Review output above.")
    print(f"{'=' * 55}")


if __name__ == "__main__":
    main()
