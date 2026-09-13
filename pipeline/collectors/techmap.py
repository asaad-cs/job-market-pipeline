"""
Techmap Saudi Arabia job collector — pipeline collector interface.

SAMPLE-BASED COLLECTOR — reads from a static file, not a live API call.
No TECHMAP_API_KEY exists in .env yet. To convert to live collection,
implement the RapidAPI call using the endpoint tested in the playground,
and add rate limiting/pagination per Techmap's actual quota (unconfirmed
— ToS not fully verified, see docs/source_investigation.md Techmap entry).

Source: data/raw/techmap_sample.json — 10 records collected by a teammate
via the RapidAPI Techmap endpoint on 2026-09-07. This file is committed
as a static sample; it does not grow on repeated runs.

source_job_id: No native job ID is present in this export. A synthetic
"fp-<fingerprint>" ID is used as a placeholder so records can be referenced
in quality_log and dedup state. The "fp-" prefix distinguishes it from a
real platform ID. Replace with the native ID field once a live key is
configured and the API response schema is confirmed.
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

SAMPLE_FILE = Path(__file__).resolve().parents[2] / "data" / "raw" / "techmap_sample.json"


def _fingerprint(title: str | None, company: str | None, city: str | None) -> str:
    def norm(v):
        return (v or "").upper().strip() or "NULL"
    raw = f"{norm(title)}|{norm(company)}|{norm(city)}"
    return hashlib.sha256(raw.encode()).hexdigest()


def collect(run_id: str) -> list[dict]:
    """
    Load Techmap sample records and return standard raw_jobs records.

    Reads from the static sample file — no network calls are made.

    Returns a list of dicts with keys:
        raw_id, run_id, source_name, source_job_id, source_url,
        raw_payload (JSON string), collected_at (ISO-8601 UTC)
    """
    if not SAMPLE_FILE.exists():
        raise FileNotFoundError(
            f"Techmap sample file not found: {SAMPLE_FILE}\n"
            "Run the STEP A preparation script to regenerate it, or check the path."
        )

    with open(SAMPLE_FILE, encoding="utf-8") as f:
        records = json.load(f)

    log.info("Techmap collect: reading %d records from static sample (run_id=%s)",
             len(records), run_id)

    collected_at = datetime.now(timezone.utc).isoformat()
    raw_records = []

    for rec in records:
        title   = rec.get("title")
        company = rec.get("company")
        city    = rec.get("city")

        fp = _fingerprint(title, company, city)
        # "fp-" prefix marks this as a synthetic ID — replace when native ID is confirmed
        synthetic_job_id = f"fp-{fp}"

        # raw_payload carries everything the staging model will need to extract
        payload = {
            "title":        title,
            "company":      company,
            "city":         city,
            "country":      rec.get("country"),
            "date_created": rec.get("date_created"),   # full ISO-8601 UTC timestamp
            "occupation":   rec.get("occupation"),
            "industry":     rec.get("industry"),
            "work_place":   rec.get("work_place"),
            "work_type":    rec.get("work_type"),
            "career_level": rec.get("career_level"),
            "portal":       rec.get("portal"),
            "has_salary":   rec.get("has_salary"),
            "is_duplicate": rec.get("is_duplicate"),
        }

        raw_records.append({
            "raw_id":       str(uuid.uuid4()),
            "run_id":       run_id,
            "source_name":  "techmap",
            "source_job_id": synthetic_job_id,
            "source_url":   rec.get("job_url"),
            "raw_payload":  json.dumps(payload, ensure_ascii=False),
            "collected_at": collected_at,
        })

    log.info("Techmap collect done: %d records loaded from sample", len(raw_records))
    return raw_records
