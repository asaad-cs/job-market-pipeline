"""
Deduplication: four-stage strategy.

Stage 1 — Exact source match: source_name + source_job_id (or job_fingerprint for sources without native ID)
Stage 2 — URL exact match: normalized source_url
Stage 3 — Structured field match: title + company + city + date (cross-source; add when 2nd source active)
Stage 4 — Fuzzy match: defer until profiling shows a need

Records are never deleted — duplicates are marked with is_duplicate=True and duplicate_of_job_id.
"""

import logging
import os
import sqlite3

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)


def _get_conn():
    url = os.getenv("DB_URL", "")
    if url.startswith("sqlite:///"):
        return sqlite3.connect(url.removeprefix("sqlite:///"))
    if url.startswith(("postgresql://", "postgres://")):
        import psycopg2
        return psycopg2.connect(url)
    raise RuntimeError(f"Unsupported DB_URL: {url!r}")


def _seen_raw_jobs(conn, source_name: str, source_job_id: str | None, fingerprint: str) -> bool:
    """
    Stage 1: Check if this record was already stored in raw_jobs.
    Uses native source_job_id if present, otherwise falls back to fingerprint match
    against already-processed jobs.
    """
    if source_job_id:
        cur = conn.execute(
            "SELECT 1 FROM raw_jobs WHERE source_name=? AND source_job_id=? LIMIT 1",
            (source_name, source_job_id),
        )
    else:
        # For sources without a native ID: fingerprint match requires the jobs table.
        # raw_jobs alone cannot detect cross-run duplicates without a native ID.
        # Return False here; Snowflake-level dedup handles this in the load stage.
        return False
    return cur.fetchone() is not None


def _seen_by_url(conn, url: str) -> str | None:
    """Stage 2: Return existing raw_id if URL already ingested."""
    cur = conn.execute(
        "SELECT raw_id FROM raw_jobs WHERE source_url=? LIMIT 1",
        (url,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def deduplicate(records: list[dict]) -> list[dict]:
    """
    Mark duplicate records in the record list.
    Also skips re-ingestion of records already in raw_jobs.

    Returns the records list with is_duplicate / duplicate_of_job_id populated.
    """
    if not records:
        return records

    conn = _get_conn()
    try:
        seen_urls: dict[str, str] = {}    # url → raw_id of first occurrence this run
        seen_fingerprints: dict[str, str] = {}  # fingerprint → raw_id of first occurrence

        deduped = []
        for rec in records:
            source_name = rec["source_name"]
            source_job_id = rec.get("source_job_id")
            fingerprint = rec.get("job_fingerprint", "")
            url = rec.get("source_url", "")

            # Stage 1: exact source match against raw_jobs
            if _seen_raw_jobs(conn, source_name, source_job_id, fingerprint):
                log.debug("Stage 1 dup (native ID): %s %s", source_name, source_job_id)
                rec["is_duplicate"] = True
                rec["duplicate_of_job_id"] = None  # existing raw_jobs record
                deduped.append(rec)
                continue

            # Stage 2: URL exact match (within this run first, then DB)
            if url in seen_urls:
                log.debug("Stage 2 dup (URL, this run): %s", url)
                rec["is_duplicate"] = True
                rec["duplicate_of_job_id"] = seen_urls[url]
                deduped.append(rec)
                continue

            existing_raw_id = _seen_by_url(conn, url)
            if existing_raw_id:
                log.debug("Stage 2 dup (URL, DB): %s", url)
                rec["is_duplicate"] = True
                rec["duplicate_of_job_id"] = existing_raw_id
                deduped.append(rec)
                continue

            # Within-run fingerprint dedup (for sources without native ID)
            if not source_job_id and fingerprint in seen_fingerprints:
                log.debug("Stage 2b dup (fingerprint, this run): %s", fingerprint)
                rec["is_duplicate"] = True
                rec["duplicate_of_job_id"] = seen_fingerprints[fingerprint]
                deduped.append(rec)
                continue

            # Not a duplicate — track for within-run dedup
            raw_id = rec["raw_id"]
            seen_urls[url] = raw_id
            if not source_job_id:
                seen_fingerprints[fingerprint] = raw_id

            deduped.append(rec)

        dup_count = sum(1 for r in deduped if r["is_duplicate"])
        log.info("Deduplication: %d total, %d duplicates marked", len(deduped), dup_count)
        return deduped

    finally:
        conn.close()
