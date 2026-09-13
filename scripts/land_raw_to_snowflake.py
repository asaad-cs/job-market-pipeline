"""
Land four-source sample into Snowflake BRONZE.

Sources loaded:
  Careerjet : 99 records from SQLite run dfa8e653 (2026-09-06, single 1-page pull)
  Tanqeeb   : 117 records from data/raw/tanqeeb_jobs.json
  Jooble    : 109 records from data/raw/jooble_combined_2026-09-12.json
  Techmap   : 10 records from data/raw/techmap_sample.json (static sample,
              teammate RapidAPI pull 2026-09-07; no live key; ToS unverified)

Idempotency: TRUNCATEs BRONZE.raw_jobs and BRONZE.collection_runs before
loading. Safe to re-run — always produces a clean state.

No hardcoded count assertions. Actual counts are reported at the end.
"""
import io, json, os, sqlite3, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

import snowflake.connector

# ── Paths ─────────────────────────────────────────────────────────────────────
SQLITE_PATH   = "./data/pipeline.db"
TANQEEB_JSON  = "./data/raw/tanqeeb_jobs.json"
JOOBLE_JSON   = "./data/raw/jooble_combined_2026-09-12.json"
CAREERJET_RUN = "dfa8e653"   # prefix of the target run_id in SQLite

# ── DDL ───────────────────────────────────────────────────────────────────────
_CREATE_SCHEMA = "CREATE SCHEMA IF NOT EXISTS BRONZE"

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

_INSERT_RUN = """
INSERT INTO BRONZE.collection_runs
    (run_id, started_at, completed_at, source_name, records_fetched, notes)
VALUES (%s, %s, %s, %s, %s, %s)
"""

_INSERT_RAW_JOB = """
INSERT INTO BRONZE.raw_jobs
    (raw_id, run_id, source_name, source_job_id, source_url, raw_payload, collected_at)
SELECT %s, %s, %s, %s, %s, PARSE_JSON(%s), %s
"""


# ── Source loaders ────────────────────────────────────────────────────────────

def _load_careerjet():
    """Read run dfa8e653 from SQLite. Returns (run_row, job_rows)."""
    conn = sqlite3.connect(SQLITE_PATH)
    run = conn.execute(
        "SELECT run_id, started_at, completed_at, source_name, records_fetched, notes "
        "FROM collection_runs WHERE run_id LIKE ?",
        (CAREERJET_RUN + "%",)
    ).fetchone()
    if not run:
        conn.close()
        sys.exit(f"ERROR: no collection_run found with prefix {CAREERJET_RUN!r}")

    jobs = conn.execute(
        "SELECT raw_id, run_id, source_name, source_job_id, source_url, raw_payload, collected_at "
        "FROM raw_jobs WHERE run_id = ?",
        (run[0],)
    ).fetchall()
    conn.close()

    print(f"  Careerjet (SQLite) : run {run[0][:8]}  {len(jobs)} records  {str(run[1])[:19]}")
    return run, jobs


def _load_tanqeeb():
    """Read tanqeeb_jobs.json. Returns (run_row, job_rows)."""
    with open(TANQEEB_JSON, encoding="utf-8") as f:
        records = json.load(f)

    run_id = str(uuid.uuid4())
    timestamps = [r["scraped_at"] for r in records if r.get("scraped_at")]
    started_at   = min(timestamps) if timestamps else datetime.now(timezone.utc).isoformat()
    completed_at = max(timestamps) if timestamps else started_at

    run_row = (
        run_id, started_at, completed_at, "tanqeeb", len(records),
        "Initial scrape via scripts/scrape_tanqeeb.py (2026-09-09)"
    )

    job_rows = []
    for rec in records:
        job_rows.append((
            str(uuid.uuid4()),
            run_id,
            "tanqeeb",
            str(rec.get("source_job_id", "") or ""),
            rec.get("job_url", ""),
            json.dumps(rec, ensure_ascii=False),
            rec.get("scraped_at", started_at),
        ))

    print(f"  Tanqeeb (JSON)     : run {run_id[:8]}  {len(job_rows)} records  {started_at[:19]}")
    return run_row, job_rows


def _load_techmap():
    """Read techmap_sample.json via the collector. Returns (run_row, job_rows)."""
    import sys as _sys
    _sys.path.insert(0, ".")
    from pipeline.collectors.techmap import collect

    run_id = str(uuid.uuid4())
    # Teammate collected this sample on 2026-09-07; use that as the run timestamp
    collection_date = "2026-09-07T00:00:00+00:00"

    raw = collect(run_id=run_id)

    run_row = (
        run_id, collection_date, collection_date, "techmap", len(raw),
        "Static 10-record sample collected by teammate via RapidAPI Techmap endpoint "
        "(2026-09-07). No live API key configured. ToS not fully verified."
    )

    job_rows = []
    for rec in raw:
        job_rows.append((
            rec["raw_id"],
            rec["run_id"],
            rec["source_name"],
            rec["source_job_id"],
            rec["source_url"] or "",
            rec["raw_payload"],
            collection_date,    # use teammate collection date, not today's load time
        ))

    print(f"  Techmap (JSON)     : run {run_id[:8]}  {len(job_rows)} records  {collection_date[:19]}")
    return run_row, job_rows


def _load_jooble():
    """Read jooble_combined JSON. Returns (run_row, job_rows)."""
    with open(JOOBLE_JSON, encoding="utf-8") as f:
        records = json.load(f)

    run_id = str(uuid.uuid4())
    # Use the updated field from the records as a proxy for collection timestamp
    timestamps = [r["updated"] for r in records if r.get("updated")]
    started_at   = "2026-09-09T00:00:00+00:00"   # earliest API call date
    completed_at = "2026-09-12T00:00:00+00:00"   # step-B call date

    run_row = (
        run_id, started_at, completed_at, "jooble", len(records),
        "Combined from 9 API calls (Sep-09 5-call pull + Sep-12 step-B 4-call pull); "
        "500-call lifetime quota; 1 duplicate removed"
    )

    job_rows = []
    for rec in records:
        job_rows.append((
            str(uuid.uuid4()),
            run_id,
            "jooble",
            str(rec.get("id", "") or ""),
            rec.get("link", ""),
            json.dumps(rec, ensure_ascii=False),
            rec.get("updated", started_at),
        ))

    print(f"  Jooble (JSON)      : run {run_id[:8]}  {len(job_rows)} records  {started_at[:19]}")
    return run_row, job_rows


# ── Snowflake connection ──────────────────────────────────────────────────────

def _get_sf():
    required = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD",
                "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA"]
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # 1. Build in-memory record sets from all four sources
    print("Reading source data...")
    cj_run, cj_jobs = _load_careerjet()
    tq_run, tq_jobs = _load_tanqeeb()
    jb_run, jb_jobs = _load_jooble()
    tm_run, tm_jobs = _load_techmap()

    total_jobs = len(cj_jobs) + len(tq_jobs) + len(jb_jobs) + len(tm_jobs)
    print(f"  Total records to load : {total_jobs}")
    print()

    # 2. Connect to Snowflake
    print("Connecting to Snowflake...")
    sf = _get_sf()
    cur = sf.cursor()

    # 3. Create schema and tables if not exist
    print("Ensuring BRONZE schema and tables exist...")
    cur.execute(_CREATE_SCHEMA)
    cur.execute(_CREATE_COLLECTION_RUNS)
    cur.execute(_CREATE_RAW_JOBS)

    # 4. TRUNCATE — clean slate for the demo load
    print("Truncating BRONZE tables...")
    cur.execute("TRUNCATE TABLE BRONZE.collection_runs")
    cur.execute("TRUNCATE TABLE BRONZE.raw_jobs")
    sf.commit()
    print("  Done.")
    print()

    # 5. Load collection_runs (4 rows)
    print("Loading 4 collection_runs rows...")
    for run_row in [cj_run, tq_run, jb_run, tm_run]:
        cur.execute(_INSERT_RUN, run_row)
    sf.commit()
    print("  Done.")
    print()

    # 6. Load raw_jobs — all four sources
    def _insert_batch(label, job_rows):
        inserted = 0
        failed = []
        for i, row in enumerate(job_rows):
            try:
                cur.execute(_INSERT_RAW_JOB, row)
                inserted += 1
            except Exception as exc:
                failed.append((row[0], str(exc)))
            if (i + 1) % 50 == 0 or (i + 1) == len(job_rows):
                print(f"  {label}: {i+1}/{len(job_rows)} rows...")
        sf.commit()
        if failed:
            print(f"  FAILED ({len(failed)}):")
            for raw_id, err in failed[:5]:
                print(f"    {raw_id[:8]}: {err[:80]}")
        return inserted, len(failed)

    print(f"Loading Careerjet ({len(cj_jobs)} rows)...")
    cj_ok, cj_fail = _insert_batch("careerjet", cj_jobs)

    print(f"Loading Tanqeeb ({len(tq_jobs)} rows)...")
    tq_ok, tq_fail = _insert_batch("tanqeeb", tq_jobs)

    print(f"Loading Jooble ({len(jb_jobs)} rows)...")
    jb_ok, jb_fail = _insert_batch("jooble", jb_jobs)

    print(f"Loading Techmap ({len(tm_jobs)} rows)...")
    tm_ok, tm_fail = _insert_batch("techmap", tm_jobs)

    print()

    # 7. Verify — counts by source
    cur.execute("SELECT source_name, COUNT(*) FROM BRONZE.raw_jobs GROUP BY source_name ORDER BY source_name")
    by_source = cur.fetchall()

    cur.execute("SELECT COUNT(*) FROM BRONZE.raw_jobs")
    total_sf = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM BRONZE.collection_runs")
    runs_sf = cur.fetchone()[0]

    cur.close()
    sf.close()

    # 8. Report
    fail_by_source = {
        "careerjet": cj_fail,
        "tanqeeb":   tq_fail,
        "jooble":    jb_fail,
        "techmap":   tm_fail,
    }

    print("=" * 55)
    print("BRONZE LOAD COMPLETE")
    print("=" * 55)
    print(f"  collection_runs : {runs_sf} rows")
    print(f"  raw_jobs total  : {total_sf} rows")
    print()
    print("  raw_jobs by source_name:")
    for source, count in by_source:
        status = "OK" if fail_by_source.get(source, 0) == 0 else "PARTIAL"
        print(f"    {source:<12}: {count:>4} rows  [{status}]")
    print("=" * 55)


if __name__ == "__main__":
    main()
