"""
Deduplication: four-stage strategy.

Stage 1a — Native ID:      source_name + source_job_id exact match (raw_jobs)
Stage 1b — Fingerprint:    job_fingerprint match (processed_fingerprints)
            For sources without a native source_job_id (e.g. Careerjet), this is
            the primary cross-run dedup mechanism.
Stage 2  — URL:            exact source_url match (within-run then DB)
Stage 3  — Structured:     title + company + city + date (cross-source; add when 2nd source active)
Stage 4  — Fuzzy:          defer until profiling shows a need

Records are never deleted — duplicates are marked with is_duplicate=True.
After each run, fingerprints of non-duplicate records are written to
processed_fingerprints so subsequent runs can detect cross-run duplicates.
"""

import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)


def _get_conn():
    url = os.getenv("DB_URL", "")
    if url.startswith("sqlite:///"):
        import sqlite3
        return sqlite3.connect(url.removeprefix("sqlite:///"))
    if url.startswith(("postgresql://", "postgres://")):
        import psycopg2
        return psycopg2.connect(url)
    raise RuntimeError(f"Unsupported DB_URL: {url!r}")


# ── Stage 1a — native source ID ──────────────────────────────────────────────

def _seen_by_native_id(conn, source_name: str, source_job_id: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM raw_jobs WHERE source_name=? AND source_job_id=? LIMIT 1",
        (source_name, source_job_id),
    )
    return cur.fetchone() is not None


# ── Stage 1b — fingerprint (cross-run, primary for Careerjet) ────────────────

def _seen_by_fingerprint(conn, fingerprint: str, current_raw_ids: frozenset[str] = frozenset()) -> str | None:
    """Return first_raw_id from processed_fingerprints if this fingerprint was seen in a PRIOR run.

    Excludes matches whose first_raw_id belongs to the current batch so that
    re-running the pipeline on the same input records does not incorrectly flag
    them as cross-run duplicates.
    """
    cur = conn.execute(
        "SELECT first_raw_id FROM processed_fingerprints WHERE fingerprint=? LIMIT 1",
        (fingerprint,)
    )
    row = cur.fetchone()
    if not row:
        return None
    prior_raw_id = row[0]
    return None if prior_raw_id in current_raw_ids else prior_raw_id


def _record_processed_fingerprints(conn, records: list[dict]) -> int:
    """
    Persist fingerprints of non-duplicate records so future runs can detect cross-run dups.
    Uses INSERT OR IGNORE so records already in the table are silently skipped.
    Returns number of new fingerprints inserted.
    """
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        (rec["job_fingerprint"], rec["raw_id"], rec["source_name"], now)
        for rec in records
        if rec.get("job_fingerprint") and not rec.get("is_duplicate")
    ]
    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO processed_fingerprints VALUES (?,?,?,?)",
            rows,
        )
        conn.commit()
    return len(rows)


# ── Stage 2 — URL exact match ────────────────────────────────────────────────

def _seen_by_url(conn, url: str, current_run_id: str = "") -> str | None:
    """Return existing raw_id if this URL appeared in a PREVIOUS run's raw_jobs.

    Excludes current_run_id so records already stored this run don't self-match.
    Note: Careerjet URLs are dynamic jobviewtrack.com tokens — they regenerate on
    every API query, making cross-run URL matching unreliable for that source.
    Stage 1b fingerprint matching is the reliable cross-run mechanism for Careerjet.
    """
    cur = conn.execute(
        "SELECT raw_id FROM raw_jobs WHERE source_url=? AND run_id!=? LIMIT 1",
        (url, current_run_id),
    )
    row = cur.fetchone()
    return row[0] if row else None


# ── Main entry point ─────────────────────────────────────────────────────────

def deduplicate(records: list[dict]) -> list[dict]:
    """
    Mark duplicate records. Records are never dropped — duplicates get is_duplicate=True.

    Dedup order for sources WITHOUT source_job_id (e.g. Careerjet):
      1. Within-run fingerprint (seen_fingerprints dict) — avoids DB roundtrips
      2. Cross-run fingerprint (processed_fingerprints table)   ← Stage 1b
      3. Within-run URL (seen_urls dict)
      4. Cross-run URL (raw_jobs table)                          ← Stage 2

    Dedup order for sources WITH source_job_id (future sources):
      1. Native ID (raw_jobs table)                              ← Stage 1a
      2. Within-run URL
      3. Cross-run URL

    After processing, fingerprints of non-duplicates are written to
    processed_fingerprints for future cross-run checks.
    """
    if not records:
        return records

    # All records in a batch share the same run_id; used to exclude
    # current-run rows when querying raw_jobs for cross-run URL matches.
    current_run_id = records[0].get("run_id", "") if records else ""
    current_raw_ids = frozenset(r["raw_id"] for r in records if r.get("raw_id"))

    conn = _get_conn()
    try:
        seen_urls: dict[str, str] = {}         # url → raw_id (within this run)
        seen_fingerprints: dict[str, str] = {} # fingerprint → raw_id (within this run)

        deduped = []
        for rec in records:
            source_name = rec.get("source_name", "")
            source_job_id = rec.get("source_job_id")
            fingerprint = rec.get("job_fingerprint", "")
            url = rec.get("source_url", "")

            # ── Stage 1a: native source ID (sources with source_job_id) ──────
            if source_job_id and _seen_by_native_id(conn, source_name, source_job_id):
                log.debug("Stage 1a dup (native ID): %s %s", source_name, source_job_id)
                rec = {**rec, "is_duplicate": True, "duplicate_of_job_id": None}
                deduped.append(rec)
                continue

            # ── Stage 1b: fingerprint (cross-run; primary for Careerjet) ─────
            if not source_job_id and fingerprint:
                if fingerprint in seen_fingerprints:
                    log.debug("Stage 1b dup (fingerprint, within-run): %.16s", fingerprint)
                    rec = {**rec, "is_duplicate": True,
                           "duplicate_of_job_id": seen_fingerprints[fingerprint]}
                    deduped.append(rec)
                    continue
                prior_raw_id = _seen_by_fingerprint(conn, fingerprint, current_raw_ids)
                if prior_raw_id:
                    log.debug("Stage 1b dup (fingerprint, cross-run): %.16s", fingerprint)
                    rec = {**rec, "is_duplicate": True, "duplicate_of_job_id": prior_raw_id}
                    deduped.append(rec)
                    continue

            # ── Stage 2: URL exact match ──────────────────────────────────────
            if url in seen_urls:
                log.debug("Stage 2 dup (URL, within-run): %s", url)
                rec = {**rec, "is_duplicate": True, "duplicate_of_job_id": seen_urls[url]}
                deduped.append(rec)
                continue

            existing_raw_id = _seen_by_url(conn, url, current_run_id)
            if existing_raw_id:
                log.debug("Stage 2 dup (URL, cross-run DB): %s", url)
                rec = {**rec, "is_duplicate": True, "duplicate_of_job_id": existing_raw_id}
                deduped.append(rec)
                continue

            # ── Not a duplicate: track for within-run checks ─────────────────
            raw_id = rec["raw_id"]
            seen_urls[url] = raw_id
            if not source_job_id:
                seen_fingerprints[fingerprint] = raw_id

            deduped.append(rec)

        # ── Persist fingerprints for future runs ──────────────────────────────
        new_fp_count = _record_processed_fingerprints(conn, deduped)

        dup_count = sum(1 for r in deduped if r.get("is_duplicate"))
        log.info(
            "Deduplication complete: %d records, %d duplicates marked, %d new fingerprints recorded",
            len(deduped), dup_count, new_fp_count,
        )
        return deduped

    finally:
        conn.close()
