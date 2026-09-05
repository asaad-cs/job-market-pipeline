"""
Careerjet Partner API collector.

API docs: https://www.careerjet.com/partners/api/
Authentication: affid (partner API key) read from CAREERJET_API_KEY env var.

Per-call required params: affid, user_ip, user_agent, keywords, locale_code, location
No native job ID — job_fingerprint (SHA-256) is the dedup key (see processing/cleaner.py).

IMPORTANT: Do NOT make live API calls until CAREERJET_API_KEY is set.
"""

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

BASE_URL = "https://public.api.careerjet.net/search"

# Confirmed after first test pull; update if Saudi Arabia uses a different locale
SAUDI_LOCALE = "en_SA"
SAUDI_LOCATION = "Saudi Arabia"

# Conservative rate limit: 1 request per 2 seconds
REQUEST_DELAY_SECONDS = 2

# Results per page (Careerjet max is 99; using 20 for safe initial testing)
PAGE_SIZE = 20


def _api_key() -> str:
    key = os.getenv("CAREERJET_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "CAREERJET_API_KEY is not set. "
            "Register at https://www.careerjet.com/partners/api/ and add the key to .env"
        )
    return key


def _fetch_page(affid: str, page: int, keywords: str = "") -> dict:
    params = {
        "affid": affid,
        "user_ip": "127.0.0.1",   # placeholder: replace with real user IP if required by ToS
        "user_agent": "JobMarketPipeline/0.1 (capstone research; contact: Ahmed.s.alfaidi@gmail.com)",
        "keywords": keywords,
        "location": SAUDI_LOCATION,
        "locale_code": SAUDI_LOCALE,
        "pagesize": PAGE_SIZE,
        "page": page,
    }
    response = requests.get(BASE_URL, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


def collect(run_id: str, max_pages: int = 25, keywords: str = "") -> list[dict]:
    """
    Fetch Saudi Arabia job postings from Careerjet API.
    Stores each posting as a raw_jobs dict (not yet written to DB here —
    that happens in runner.py or a dedicated storage helper).

    Returns a list of raw record dicts ready for the Cleaning stage.
    """
    affid = _api_key()
    raw_records = []
    collected_at = datetime.now(timezone.utc).isoformat()

    log.info("Careerjet collect starting (run_id=%s, max_pages=%d)", run_id, max_pages)

    for page in range(1, max_pages + 1):
        log.debug("Fetching page %d", page)
        try:
            data = _fetch_page(affid, page=page, keywords=keywords)
        except requests.HTTPError as exc:
            log.error("HTTP error on page %d: %s", page, exc)
            break

        jobs = data.get("jobs", [])
        if not jobs:
            log.info("No more results at page %d — stopping", page)
            break

        for job in jobs:
            raw_records.append({
                "raw_id": str(uuid.uuid4()),
                "run_id": run_id,
                "source_name": "careerjet",
                "source_job_id": None,          # Careerjet has no native job ID
                "source_url": job.get("url"),
                "raw_payload": json.dumps(job, ensure_ascii=False),
                "collected_at": collected_at,
            })

        total = data.get("hits", 0)
        log.info("Page %d: +%d records (total fetched: %d / %d available)",
                 page, len(jobs), len(raw_records), total)

        if len(raw_records) >= total:
            break

        time.sleep(REQUEST_DELAY_SECONDS)

    log.info("Careerjet collect done: %d raw records", len(raw_records))
    return raw_records
