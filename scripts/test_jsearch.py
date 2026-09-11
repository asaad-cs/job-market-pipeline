# -*- coding: utf-8 -*-
"""Single JSearch API test — reads key from .env, makes exactly one call."""

import requests, json, sys, os
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# Read .env manually (avoid requiring python-dotenv)
env = {}
env_path = Path(__file__).parent.parent / '.env'
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()

API_KEY = env.get('RAPIDAPI_KEY')
if not API_KEY:
    print("ERROR: RAPIDAPI_KEY not found in .env"); sys.exit(1)

print(f"Key loaded: {API_KEY[:6]}...{API_KEY[-4:]}")

url = "https://jsearch.p.rapidapi.com/search-v2"
headers = {
    "x-rapidapi-host": "jsearch.p.rapidapi.com",
    "x-rapidapi-key": API_KEY,
}
params = {
    "query": "jobs in Saudi Arabia",
    "country": "sa",
    "num_pages": "1",
    "date_posted": "all",
}

print(f"\nGET {url}")
print(f"Params: {params}\n")

r = requests.get(url, headers=headers, params=params, timeout=20)
print(f"HTTP {r.status_code}")

# Quota headers — RapidAPI uses various header names depending on plan
quota_keys = [k for k in r.headers if 'rate' in k.lower() or 'limit' in k.lower() or 'quota' in k.lower() or 'remaining' in k.lower()]
print("Quota/rate-limit headers in response:")
if quota_keys:
    for k in quota_keys:
        print(f"  {k}: {r.headers[k]}")
else:
    print("  (none found — plan may not expose quota headers)")

data = r.json()
print(f"Top-level keys: {list(data.keys())}")
status = data.get('status')
print(f"API status: {status}")

# Save raw response for inspection without additional API calls
import json as _json
with open('data/raw/jsearch_test_raw.json', 'w', encoding='utf-8') as _f:
    _json.dump(data, _f, ensure_ascii=False, indent=2)
print("Raw response saved: data/raw/jsearch_test_raw.json")

raw = data.get('data', [])
# search-v2 may return a dict with a nested jobs list, or a direct list
if isinstance(raw, list):
    jobs = raw
elif isinstance(raw, dict):
    # Try common nested keys
    jobs = raw.get('jobs') or raw.get('results') or raw.get('job_listings') or []
    if not jobs:
        print(f"data field is a dict — keys: {list(raw.keys())}")
        # Flatten: if values are lists of jobs, concatenate
        for v in raw.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                jobs = v; break
else:
    jobs = []
print(f"Jobs parsed: {len(jobs)}\n")

fields = [
    'job_id', 'job_title', 'employer_name', 'job_city',
    'job_country', 'job_posted_at_datetime_utc', 'job_apply_link',
    'job_seniority_level', 'job_required_skills',
]
for i, job in enumerate(jobs[:5]):
    print(f"--- Job {i+1} ---")
    for f in fields:
        val = job.get(f)
        if f == 'job_apply_link' and val and len(val) > 90:
            val = val[:90] + '...'
        print(f"  {f}: {val}")
    print()

# Coverage check
sa_count = sum(1 for j in jobs if (j.get('job_country') or '').upper() in ('SA', 'SAUDI ARABIA'))
print(f"Saudi Arabia jobs (job_country field): {sa_count}/{len(jobs)}")

cities = {}
for j in jobs:
    c = j.get('job_city') or '(none)'
    cities[c] = cities.get(c, 0) + 1
print(f"Cities: {dict(sorted(cities.items(), key=lambda x: -x[1]))}")
