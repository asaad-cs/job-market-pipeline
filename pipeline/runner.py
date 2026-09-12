"""
Main pipeline orchestrator.
Calls each stage in sequence for a single collection run.

Usage:
    python -m pipeline.runner
    python -m pipeline.runner --source careerjet
"""

import argparse
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ── SQLite helpers ────────────────────────────────────────────────────────────

def _sqlite_path() -> str | None:
    """Return SQLite file path from DB_URL, or None if not a SQLite URL."""
    url = os.getenv("DB_URL", "")
    return url.removeprefix("sqlite:///") if url.startswith("sqlite:///") else None


def _write_raw_to_db(db_path: str, run_id: str, started_at: datetime,
                     source: str, raw_records: list[dict]) -> None:
    """
    Write one collection_runs row and all raw_jobs records to SQLite.
    Called immediately after collection so the audit trail exists before
    deduplication reads from raw_jobs for cross-run URL matching.
    completed_at is left NULL here and updated by _finalize_run() at the end.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO collection_runs "
            "(run_id, started_at, source_name, records_fetched) "
            "VALUES (?, ?, ?, ?)",
            (run_id, started_at.isoformat(), source, len(raw_records)),
        )
        for rec in raw_records:
            conn.execute(
                "INSERT OR IGNORE INTO raw_jobs "
                "(raw_id, run_id, source_name, source_job_id, "
                " source_url, raw_payload, collected_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rec["raw_id"], rec["run_id"], rec["source_name"],
                 rec["source_job_id"], rec["source_url"],
                 rec["raw_payload"], rec["collected_at"]),
            )
        conn.commit()
        log.info("  DB write: %d raw_jobs + 1 collection_runs row", len(raw_records))
    except Exception as exc:
        conn.rollback()
        log.error("SQLite write failed: %s", exc)
        raise
    finally:
        conn.close()


def _write_quality_log(db_path: str, entries: list[dict]) -> None:
    """Persist quality_log entries produced by validator.flush_quality_log()."""
    if not entries:
        return
    conn = sqlite3.connect(db_path)
    try:
        for entry in entries:
            conn.execute(
                "INSERT OR IGNORE INTO quality_log "
                "(log_id, job_id, rule_name, severity, message, logged_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (entry["log_id"], entry.get("job_id"), entry["rule_name"],
                 entry["severity"], entry["message"], entry["logged_at"]),
            )
        conn.commit()
        log.info("  DB write: %d quality_log entries", len(entries))
    except Exception as exc:
        conn.rollback()
        log.error("SQLite quality_log write failed: %s", exc)
    finally:
        conn.close()


def _finalize_run(db_path: str, run_id: str) -> None:
    """Stamp completed_at on the collection_runs row."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE collection_runs SET completed_at=? WHERE run_id=?",
            (datetime.now(timezone.utc).isoformat(), run_id),
        )
        conn.commit()
    finally:
        conn.close()


# ── Main orchestrator ─────────────────────────────────────────────────────────

def run(source: str = "careerjet") -> None:
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    log.info("Pipeline run %s starting — source: %s", run_id, source)

    db_path = _sqlite_path()

    # Stage 1 — Collection
    log.info("[1/6] Collection")
    from pipeline.collectors.careerjet import collect as collect_careerjet
    from pipeline.collectors.jadarat_csv import collect as collect_jadarat
    from pipeline.collectors.tanqeeb import collect as collect_tanqeeb

    if source == "careerjet":
        raw_records = collect_careerjet(run_id=run_id)
    elif source == "jadarat":
        raw_records = collect_jadarat(run_id=run_id)
    elif source == "tanqeeb":
        raw_records = collect_tanqeeb(run_id=run_id)
    else:
        raise ValueError(f"Unknown source: {source!r}")

    log.info("  Collected %d raw records", len(raw_records))

    # Write to SQLite immediately — audit trail and cross-run dedup state
    if db_path and raw_records:
        _write_raw_to_db(db_path, run_id, started_at, source, raw_records)

    # Stage 2 — Cleaning & Standardization
    log.info("[2/6] Cleaning & Standardization")
    from pipeline.processing.cleaner import clean_records
    from pipeline.processing.standardizer import standardize_records

    cleaned = clean_records(raw_records)
    standardized = standardize_records(cleaned)

    # Stage 3 — Deduplication
    log.info("[3/6] Deduplication")
    from pipeline.processing.deduplicator import deduplicate
    deduped = deduplicate(standardized)

    # Stage 4 — Validation
    log.info("[4/6] Validation")
    from pipeline.quality.validator import validate, flush_quality_log
    validated = validate(deduped)

    if db_path:
        _write_quality_log(db_path, flush_quality_log())

    # Stage 5 — Snowflake Load
    log.info("[5/6] Snowflake Load")
    from pipeline.modeling.snowflake_loader import load_to_snowflake
    loaded_count, failed = load_to_snowflake(validated)
    if failed:
        for raw_id, err in failed:
            log.warning("  Load failure: raw_id=%s error=%s", raw_id, err)

    # Stamp completed_at on the collection_runs row
    if db_path:
        _finalize_run(db_path, run_id)

    log.info("[6/6] Done — %d records loaded to Snowflake", loaded_count)
    log.info("Run %s completed in %.1fs", run_id,
             (datetime.now(timezone.utc) - started_at).total_seconds())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Market Data Pipeline")
    parser.add_argument("--source", default="careerjet",
                        choices=["careerjet", "jadarat", "tanqeeb"],
                        help="Data source to collect from")
    args = parser.parse_args()
    run(source=args.source)
