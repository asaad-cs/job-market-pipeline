"""
Phase 1 full collection — Careerjet API.
Collects 200-500 Saudi Arabia job postings, writes to raw_jobs and collection_runs.
Run from project root: python collect_full.py
"""

import io
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

load_dotenv()

DB_PATH = "./data/pipeline.db"
MAX_PAGES = 5   # 5 pages x 99 per page = up to 495 records


def _write_collection_run(conn, run_id, started_at, source_name, record_count, notes):
    conn.execute(
        "INSERT INTO collection_runs VALUES (?,?,?,?,?,?)",
        (run_id, started_at, datetime.now(timezone.utc).isoformat(),
         source_name, record_count, notes),
    )


def _write_raw_jobs(conn, records):
    for rec in records:
        conn.execute(
            "INSERT OR IGNORE INTO raw_jobs VALUES (?,?,?,?,?,?,?)",
            (rec["raw_id"], rec["run_id"], rec["source_name"], rec["source_job_id"],
             rec["source_url"], rec["raw_payload"], rec["collected_at"]),
        )


def main():
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    print(f"\n{'='*60}")
    print(f"Phase 1 Full Collection — Careerjet API")
    print(f"run_id : {run_id}")
    print(f"target : 200-500 records ({MAX_PAGES} pages x 99 per page)")
    print(f"{'='*60}\n")

    from pipeline.collectors.careerjet import collect

    try:
        raw_records = collect(run_id=run_id, max_pages=MAX_PAGES)
    except RuntimeError as exc:
        sys.exit(f"Collection aborted: {exc}")

    if not raw_records:
        sys.exit("ERROR: No records returned from API.")

    print(f"\nCollected {len(raw_records)} raw records — writing to DB...")

    conn = sqlite3.connect(DB_PATH)
    try:
        _write_collection_run(
            conn, run_id, started_at, "careerjet", len(raw_records),
            f"Phase 1 full collection — {MAX_PAGES} pages x 99 per page"
        )
        _write_raw_jobs(conn, raw_records)
        conn.commit()
    except Exception as exc:
        conn.rollback()
        conn.close()
        sys.exit(f"DB write failed: {exc}")
    finally:
        conn.close()

    # --- Verification ---
    conn = sqlite3.connect(DB_PATH)
    run_row = conn.execute(
        "SELECT run_id, source_name, records_fetched, started_at, completed_at, notes "
        "FROM collection_runs WHERE run_id=?",
        (run_id,)
    ).fetchone()
    raw_count = conn.execute(
        "SELECT COUNT(*) FROM raw_jobs WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    total_raw = conn.execute("SELECT COUNT(*) FROM raw_jobs").fetchone()[0]
    total_runs = conn.execute("SELECT COUNT(*) FROM collection_runs").fetchone()[0]

    # URL uniqueness check within this run
    unique_urls = conn.execute(
        "SELECT COUNT(DISTINCT source_url) FROM raw_jobs WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    conn.close()

    print(f"\n{'='*60}")
    print(f"COLLECTION COMPLETE")
    print(f"{'='*60}")
    print(f"  Records collected  : {run_row[2]}")
    print(f"  raw_jobs inserted  : {raw_count}")
    print(f"  Unique URLs        : {unique_urls}")
    print(f"  Duplicates skipped : {run_row[2] - raw_count}")
    print(f"")
    print(f"  collection_runs row:")
    print(f"    run_id       : {run_row[0][:8]}...")
    print(f"    source_name  : {run_row[1]}")
    print(f"    records      : {run_row[2]}")
    print(f"    started_at   : {run_row[3]}")
    print(f"    completed_at : {run_row[4]}")
    print(f"    notes        : {run_row[5]}")
    print(f"")
    print(f"  DB totals:")
    print(f"    collection_runs : {total_runs} total runs")
    print(f"    raw_jobs        : {total_raw} total records")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
