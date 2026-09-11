"""
build_combined_demo.py — EXPLORATORY ONLY.

Combines Careerjet, Jooble, and Tanqeeb sample records into one unified
canonical schema for review. Does NOT write to raw_jobs, dbt models, or
any production schema.

Output: data/samples/combined_sources_demo.csv
"""

import csv
import hashlib
import json
from pathlib import Path

# -- Paths --------------------------------------------------------------------─
CAREERJET_CSV = Path("data/samples/review_sample.csv")
JOOBLE_CSV    = Path("data/raw/jooble_sample_2026-09-09.csv")
TANQEEB_CSV   = Path("data/raw/tanqeeb_jobs.csv")
OUT_CSV       = Path("data/samples/combined_sources_demo.csv")

CANONICAL_FIELDS = [
    "source_name",
    "source_job_id",
    "job_fingerprint",
    "title",
    "company_name",
    "location_city",
    "location_country",
    "posting_date",
    "source_url",
]


def fingerprint(title, company, city):
    """SHA-256(UPPER(title)|UPPER(company)|UPPER(city)) — §10a formula."""
    def norm(v):
        return (v or "").upper().strip() or "NULL"
    raw = f"{norm(title)}|{norm(company)}|{norm(city)}"
    return hashlib.sha256(raw.encode()).hexdigest()


def null_if_empty(v):
    """Return None for empty/whitespace strings so CSV writes as blank."""
    return v.strip() if v and v.strip() else None


def date_part(iso_str):
    """Extract YYYY-MM-DD from an ISO timestamp; return None if blank."""
    v = null_if_empty(iso_str)
    return v[:10] if v else None


# -- Careerjet ----------------------------------------------------------------─
def read_careerjet():
    rows = []
    with open(CAREERJET_CSV, encoding="utf-8-sig", newline="") as f:
        for rec in csv.DictReader(f):
            raw_loc = null_if_empty(rec.get("locations", ""))
            if raw_loc and "," in raw_loc:
                parts = raw_loc.split(",", 1)
                city    = null_if_empty(parts[0])
                country = null_if_empty(parts[1])
            else:
                city    = raw_loc
                country = None

            title   = null_if_empty(rec.get("title", ""))
            company = null_if_empty(rec.get("company", ""))
            fp      = fingerprint(title, company, city)

            rows.append({
                "source_name":    "careerjet",
                "source_job_id":  None,           # no native ID
                "job_fingerprint": fp,
                "title":          title,
                "company_name":   company,
                "location_city":  city,
                "location_country": country,
                "posting_date":   None,           # date field is query timestamp
                "source_url":     null_if_empty(rec.get("url", "")),
            })
    return rows


# -- Jooble --------------------------------------------------------------------
def read_jooble():
    rows = []
    with open(JOOBLE_CSV, encoding="utf-8-sig", newline="") as f:
        for rec in csv.DictReader(f):
            rows.append({
                "source_name":    "jooble",
                "source_job_id":  null_if_empty(rec.get("id", "")),
                "job_fingerprint": None,          # has native ID
                "title":          null_if_empty(rec.get("title", "")),
                "company_name":   null_if_empty(rec.get("company", "")),
                "location_city":  null_if_empty(rec.get("location", "")),
                "location_country": None,         # no country field in response
                "posting_date":   date_part(rec.get("updated", "")),
                "source_url":     null_if_empty(rec.get("link", "")),
            })
    return rows


# -- Tanqeeb ------------------------------------------------------------------─
def read_tanqeeb():
    rows = []
    with open(TANQEEB_CSV, encoding="utf-8-sig", newline="") as f:
        for rec in csv.DictReader(f):
            rows.append({
                "source_name":    "tanqeeb",
                "source_job_id":  null_if_empty(rec.get("source_job_id", "")),
                "job_fingerprint": None,          # has native ID
                "title":          null_if_empty(rec.get("job_title", "")),
                "company_name":   null_if_empty(rec.get("company", "")),
                "location_city":  null_if_empty(rec.get("city", "")),
                "location_country": null_if_empty(rec.get("country", "")),
                "posting_date":   date_part(rec.get("posting_date", "")),
                "source_url":     null_if_empty(rec.get("job_url", "")),
            })
    return rows


# -- Build & write ------------------------------------------------------------─
careerjet_rows = read_careerjet()
jooble_rows    = read_jooble()
tanqeeb_rows   = read_tanqeeb()

all_rows = careerjet_rows + jooble_rows + tanqeeb_rows

OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=CANONICAL_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in all_rows:
        writer.writerow({k: ("" if v is None else v) for k, v in row.items()})

# -- Summary ------------------------------------------------------------------─
print(f"Saved: {OUT_CSV}")
print()
print("-- ROW COUNT BY SOURCE --")
for source, rows in [("careerjet", careerjet_rows),
                     ("jooble",    jooble_rows),
                     ("tanqeeb",   tanqeeb_rows)]:
    print(f"  {source:<12}: {len(rows):>4} rows")
print(f"  {'TOTAL':<12}: {len(all_rows):>4} rows")

print()
print("-- DEDUP KEY COVERAGE --")
with_native_id = sum(1 for r in all_rows if r["source_job_id"])
with_fp_only   = sum(1 for r in all_rows if not r["source_job_id"] and r["job_fingerprint"])
neither        = sum(1 for r in all_rows if not r["source_job_id"] and not r["job_fingerprint"])
print(f"  source_job_id populated  : {with_native_id:>4}  (Jooble + Tanqeeb)")
print(f"  job_fingerprint only     : {with_fp_only:>4}  (Careerjet)")
print(f"  neither (unexpected)     : {neither:>4}")

print()
print("-- NULL RATES FOR KEY FIELDS --")
for field in ["title", "company_name", "location_city", "location_country", "posting_date"]:
    nulls = sum(1 for r in all_rows if not r[field])
    pct   = 100 * nulls / len(all_rows)
    print(f"  {field:<20}: {nulls:>4} null / {len(all_rows)} ({pct:.0f}%)")
