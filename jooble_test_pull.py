"""
jooble_test_pull.py — EXPLORATORY ONLY. One-off test pull, not part of the pipeline.

Pulls 20-30 sample job listings from the Jooble Saudi Arabia API and saves:
  data/raw/jooble_raw_<date>.json   — full API responses (gitignored)
  data/raw/jooble_sample_<date>.csv — clean, shareable export (gitignored)

Does NOT write to raw_jobs, RAW schema, any Snowflake table, or any pipeline DB.

Prerequisites
-------------
1. Register at https://sa.jooble.org/api/about (name, email, website)
   → Jooble sends your SA-specific API key by email (typically within a day)
2. Add this line to .env:
      JOOBLE_SA_API_KEY=<your_key>
3. Run:  py jooble_test_pull.py

API facts (confirmed from https://help.jooble.org):
  Endpoint : POST https://sa.jooble.org/api/{key}
  Auth     : API key embedded in URL path — no header needed
  Body     : JSON   {"keywords": "...", "location": "...", "page": 1, ...}
  Quota    : 500 requests LIFETIME per key (free tier) — use sparingly
"""

import csv
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Configuration ─────────────────────────────────────────────────────────────

API_KEY = os.getenv("JOOBLE_SA_API_KEY", "")
if not API_KEY:
    sys.exit(
        "\nERROR: JOOBLE_SA_API_KEY not set.\n"
        "Register at https://sa.jooble.org/api/about to obtain a Saudi Arabia key,\n"
        "then add  JOOBLE_SA_API_KEY=<your_key>  to .env and re-run.\n"
    )

ENDPOINT = f"https://sa.jooble.org/api/{API_KEY}"

# Search terms chosen to sample a cross-section of SA job market:
# tech, finance, healthcare, general — keeping total calls low (quota is 500 lifetime).
SEARCHES = [
    {"keywords": "software engineer",    "location": "Riyadh"},
    {"keywords": "data analyst",         "location": "Jeddah"},
    {"keywords": "accountant",           "location": "Saudi Arabia"},
    {"keywords": "project manager",      "location": "Dammam"},
    {"keywords": "nurse",                "location": "Saudi Arabia"},
]
RESULTS_PER_PAGE = 6   # 5 searches × 6 = 30 records max

OUTPUT_DIR = Path("data/raw")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
today = date.today().isoformat()
JSON_OUT = OUTPUT_DIR / f"jooble_raw_{today}.json"
CSV_OUT  = OUTPUT_DIR / f"jooble_sample_{today}.csv"

# ── Pull ──────────────────────────────────────────────────────────────────────

def pull_search(keywords: str, location: str, results_per_page: int) -> dict:
    payload = {
        "keywords":      keywords,
        "location":      location,
        "page":          1,
        "ResultOnPage":  results_per_page,
    }
    resp = requests.post(ENDPOINT, json=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()

all_responses = []
all_jobs      = []

print(f"Endpoint : {ENDPOINT[:40]}{'...' if len(ENDPOINT) > 40 else ''}")
print(f"Searches : {len(SEARCHES)}  ×  {RESULTS_PER_PAGE} results each  (≤{len(SEARCHES)} API calls)\n")

for search in SEARCHES:
    kw  = search["keywords"]
    loc = search["location"]
    print(f"  Pulling: keywords='{kw}'  location='{loc}' ...", end=" ", flush=True)
    try:
        data = pull_search(kw, loc, RESULTS_PER_PAGE)
        total = data.get("totalCount", "?")
        jobs  = data.get("jobs", [])
        print(f"totalCount={total}  returned={len(jobs)}")
        all_responses.append({"search": search, "response": data})
        for job in jobs:
            job["_search_keywords"] = kw
            job["_search_location"] = loc
        all_jobs.extend(jobs)
    except requests.HTTPError as e:
        print(f"HTTP {e.response.status_code} — {e.response.text[:120]}")
    except Exception as e:
        print(f"ERROR — {e}")
    time.sleep(0.5)   # polite pause between calls

print(f"\nTotal records collected: {len(all_jobs)}")

# ── Save raw JSON ─────────────────────────────────────────────────────────────

with open(JSON_OUT, "w", encoding="utf-8") as f:
    json.dump(all_responses, f, ensure_ascii=False, indent=2)
print(f"Raw JSON saved : {JSON_OUT}")

if not all_jobs:
    sys.exit("\nNo jobs returned — check API key and quota.")

# ── Inspect fields ────────────────────────────────────────────────────────────

sample = all_jobs[0]
print("\n── FIELD NAMES IN RESPONSE ──")
for key, val in sample.items():
    if not key.startswith("_"):
        truncated = str(val)[:80]
        print(f"  {key:<20}: {truncated}")

# ── Save clean CSV ────────────────────────────────────────────────────────────

# Collect the union of all keys across all jobs (responses can vary)
all_keys = []
seen = set()
for job in all_jobs:
    for k in job.keys():
        if k not in seen:
            all_keys.append(k)
            seen.add(k)

with open(CSV_OUT, "w", encoding="utf-8-sig", newline="") as f:   # utf-8-sig for Excel compat
    writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(all_jobs)
print(f"Clean CSV saved: {CSV_OUT}")

# ── Summary report ────────────────────────────────────────────────────────────

print("\n── FIELD COVERAGE ACROSS ALL RECORDS ──")
for key in all_keys:
    if key.startswith("_"):
        continue
    non_null = sum(1 for j in all_jobs if j.get(key) not in (None, "", []))
    pct = 100 * non_null / len(all_jobs)
    print(f"  {key:<20}: {non_null}/{len(all_jobs)} non-null  ({pct:.0f}%)")

print("\n── LOCATION SAMPLES (first 10) ──")
for job in all_jobs[:10]:
    print(f"  {job.get('location','—')}")

print("\n── SALARY SAMPLES (non-null only, up to 10) ──")
salary_samples = [j.get("salary","") for j in all_jobs if j.get("salary") not in (None,"")]
for s in salary_samples[:10]:
    print(f"  {s}")
if not salary_samples:
    print("  (all null)")

print("\n── NATIVE JOB ID ('id' field, first 5) ──")
for job in all_jobs[:5]:
    print(f"  {job.get('id','NOT PRESENT')}")

print("\n── SOURCE SAMPLES (first 10) ──")
for job in all_jobs[:10]:
    print(f"  {job.get('source','—')}")

print(f"\nDone.  API calls used: {len(SEARCHES)} of your 500 lifetime quota.")
