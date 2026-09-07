# Saudi Arabia Job Market Data Pipeline

**WeCloudData / SDA Data Engineering Capstone — Ahmed Saad Al-Faidi**

A repeatable data engineering pipeline that collects Saudi Arabia job postings from the Careerjet Partner API, stores them raw, cleans and standardizes the data, deduplicates across collection runs, validates quality, and loads the curated records into a Snowflake analytical table.

The deliverable is the **pipeline and curated dataset**, not a downstream application.

---

## Architecture

```
Careerjet Partner API  (primary source — locale_code=en_SA)
         │
         ▼
┌─────────────────────────────────────────────────┐
│              COLLECTION STAGE                   │
│  pipeline/collectors/careerjet.py               │
│  Paginates API, stores raw JSON payload         │
└──────────────────┬──────────────────────────────┘
                   │ writes to
                   ▼
┌─────────────────────────────────────────────────┐
│           OLTP TIER  (SQLite dev / PG prod)     │
│  raw_jobs            — append-only raw storage  │
│  collection_runs     — run tracking             │
│  processed_fingerprints — cross-run dedup state │
│  quality_log         — all flags and rejections │
└──────────────────┬──────────────────────────────┘
                   │ read by
                   ▼
┌─────────────────────────────────────────────────┐
│           PROCESSING STAGES                     │
│  cleaner.py       — normalize fields, generate  │
│                     job_fingerprint             │
│  standardizer.py  — career level, salary parse  │
│  deduplicator.py  — 2-stage dedup (fingerprint  │
│                     then URL); marks is_duplicate│
│  validator.py     — 15 quality rules; writes to │
│                     quality_log                 │
└──────────────────┬──────────────────────────────┘
                   │ non-dup, non-rejected records
                   ▼
┌─────────────────────────────────────────────────┐
│           OLAP TIER  (Snowflake)                │
│  jobs table — curated analytical dataset        │
│  431 records loaded (first production run)      │
└─────────────────────────────────────────────────┘
```

---

## Repository Structure

```
job-market-pipeline/
├── pipeline/
│   ├── collectors/
│   │   └── careerjet.py          Careerjet Partner API collector
│   ├── processing/
│   │   ├── cleaner.py            Field normalization + fingerprint generation
│   │   ├── standardizer.py       Career level mapping, salary parsing
│   │   └── deduplicator.py       2-stage deduplication with cross-run persistence
│   ├── quality/
│   │   └── validator.py          15 quality rules; populates quality_flags
│   ├── modeling/
│   │   └── snowflake_loader.py   Loads curated records into Snowflake jobs table
│   └── runner.py                 Main orchestrator — runs all stages in sequence
├── db/
│   ├── schema.sql                SQLite/PostgreSQL table definitions
│   └── init_db.py                Creates tables from schema.sql
├── scripts/
│   └── backfill_warn005.sql      Retroactive WARN-005 backfill (run 2026-09-08)
├── tests/
│   ├── conftest.py               Shared fixtures; temp SQLite DB per test
│   ├── test_cleaner.py
│   ├── test_deduplicator.py
│   ├── test_standardizer.py
│   ├── test_validator.py
│   └── test_pipeline_integration.py
├── data/
│   └── samples/                  Small committed fixtures (review_sample.csv)
├── collect_full.py               5-page collection runner (495 records)
├── phase5_run.py                 Validation runner; writes quality_log to DB
├── phase6_load.py                Snowflake load runner
├── snowflake_connection_test.py  Smoke test for Snowflake credentials
├── pyproject.toml
├── .env.example
└── docs/
    └── source_investigation.md   Source evaluation report (2026-08-27)
```

---

## Setup

### 1. Clone and install

```bash
git clone <repo-url>
cd job-market-pipeline
pip install -e ".[dev]"
```

Dependencies (from `pyproject.toml`): `requests`, `pandas`, `psycopg2-binary`,
`snowflake-connector-python`, `python-dotenv`. Dev extras: `pytest`, `rapidfuzz`.

### 2. Configure environment

```bash
cp .env.example .env
# then edit .env with your credentials
```

Required variables:

| Variable | Description |
|---|---|
| `DB_URL` | SQLite: `sqlite:///./data/pipeline.db` · PostgreSQL: `postgresql://user:pass@host:5432/db` |
| `CAREERJET_API_KEY` | Careerjet Partner API affiliation ID — register at careerjet.com/partners/api/ |
| `SNOWFLAKE_ACCOUNT` | Snowflake account identifier (e.g. `abc12345.us-east-1`) |
| `SNOWFLAKE_USER` | Snowflake username |
| `SNOWFLAKE_PASSWORD` | Snowflake password |
| `SNOWFLAKE_WAREHOUSE` | Compute warehouse name (e.g. `COMPUTE_WH`) |
| `SNOWFLAKE_DATABASE` | Target database (e.g. `JOB_PIPELINE_DB`) |
| `SNOWFLAKE_SCHEMA` | Target schema (e.g. `PUBLIC`) |

The Careerjet `Referer` header defaults to `https://www.careerjet.com.sa/` (hardcoded
in `pipeline/collectors/careerjet.py` as `DEFAULT_REFERRER`). Set `CAREERJET_REFERRER`
in `.env` only if you need to override this default.

### 3. Initialise the local database

```bash
python db/init_db.py
```

Creates the SQLite tables: `collection_runs`, `raw_jobs`, `quality_log`,
`processed_fingerprints`.

### 4. Verify Snowflake connection (optional but recommended)

```bash
python snowflake_connection_test.py
```

Creates the `jobs` table if it does not exist, inserts and queries one test row,
then deletes it. Reports PASS/FAIL with the exact error if any step fails.

---

## Running the Pipeline

### Option A — Unified runner (intended entry point for repeat runs)

```bash
python -m pipeline.runner --source careerjet
```

Runs all stages in sequence: collect → clean → standardize → deduplicate →
validate → load to Snowflake. Assigns a new `run_id` (UUID) per execution.
Duplicate records are detected via fingerprint and URL matching and are marked
`is_duplicate = True` but never deleted.

> **Note:** `runner.py` was not tested end-to-end during the initial build — the
> per-stage scripts below are the only workflow verified end-to-end. `runner.py`
> also does not write collected records to `raw_jobs`, so there is no raw-layer
> audit trail for runner.py runs. For Careerjet this does not affect deduplication
> correctness (fingerprint dedup uses `processed_fingerprints`, not `raw_jobs`, and
> Careerjet's dynamic tracking URLs make URL-based cross-run dedup unreliable
> regardless), but it is a known gap.

### Option B — Stage-by-stage (used during initial build)

```bash
# Stage 1: collect (5 pages × 99 records from Careerjet Saudi Arabia)
python collect_full.py

# Stage 2–5: clean, dedup, validate, write quality_log to SQLite
python phase5_run.py

# Stage 6: load non-duplicate, non-rejected records to Snowflake
python phase6_load.py
```

Use this form to inspect intermediate results between stages or to re-run a
single stage after a bug fix.

---

## Data Model

### OLTP tables (SQLite / PostgreSQL)

| Table | Purpose |
|---|---|
| `collection_runs` | One row per pipeline execution; tracks run_id, timestamps, record counts |
| `raw_jobs` | Append-only raw storage; full API response in `raw_payload` JSON; never modified |
| `processed_fingerprints` | Persists fingerprints from processed runs; enables cross-run dedup without Snowflake |
| `quality_log` | Every quality rule violation and rejection; queryable audit trail |

### OLAP table (Snowflake)

`jobs` — curated analytical dataset. Non-duplicate, non-rejected records only.
Key fields: `job_id` (PK), `raw_id` (FK to OLTP), `title`, `company_name`,
`location_city`, `location_country`, `career_level`, `salary_min/max/currency`,
`job_fingerprint`, `quality_flags` (VARIANT array), `is_duplicate`,
`is_rejected`, `collected_at`, `processed_at`.

---

## Production Run Results (2026-09-07)

| Metric | Count |
|---|---|
| Raw records collected | 495 |
| Duplicate records detected | 64 (12.9%) |
| Records rejected by validation | 0 |
| Records loaded to Snowflake | **431** |
| Records flagged WARN-005 (low-confidence fingerprint) | 36 (8.3% of loaded) |
| Tests passing | **97** |

---

## Testing

```bash
pytest tests/ -v
```

97 tests across 5 files covering: title/company/location cleaning, fingerprint
generation, salary parsing, career level mapping, all 15 validation rules
(including both firing and non-firing cases for each), deduplication stages
(within-run URL, within-run fingerprint, cross-run URL, cross-run fingerprint,
self-match prevention), and full pipeline integration.

---

## Known Limitations

### 1. Fingerprint false-merge rate (~2.6% of collision records)

Careerjet provides no native job ID and no reliable per-listing posting date
(the `date` API field is the query timestamp). Deduplication therefore uses a
3-component SHA-256 fingerprint: `SHA-256(title | company_name | location_city)`.

A manual audit of 10 sampled fingerprint collision pairs (from 64 total
collision records across 495 collected) found:

- 9/10 pairs are true duplicates — the same posting appearing twice with
  minor Careerjet formatting variations (`"Job Description:"` prefix
  present/absent, en-dash vs hyphen).
- 1/10 is a genuine false merge — a `"Mechanical Engineer"` record where
  both `company_name` and `location_city` are null, reducing the fingerprint
  to a title-only hash. Any two listings with the same generic title and no
  company/city data will collide.

Extrapolating from that 10-record audit sample: an estimated ~10% of the 64
collision records are genuine false merges — roughly 13 records out of 495
(~2.6% of the full dataset). This figure is an extrapolation from a small
sample and should be treated as a rough estimate, not a precise count. These
records are logged with rule `DEDUP-FINGERPRINT-AUDIT` in `quality_log`.

### 2. Low-confidence fingerprints (WARN-005 — 36 records)

36 of the 431 loaded records (8.3%) have both `company_name` and
`location_city` null, causing the fingerprint to degrade toward a title-only
hash. These records are flagged `WARN-005 LOW-CONFIDENCE-FINGERPRINT` in
`quality_flags` and are queryable:

```sql
SELECT j.job_id, j.title, j.quality_flags
FROM jobs j,
     LATERAL FLATTEN(input => j.quality_flags) f
WHERE f.value:rule::STRING = 'WARN-005';
```

Records are retained and not rejected — the flag indicates reduced dedup
reliability, not data invalidity.

### 3. Salary sparsity (4.6% coverage)

Only 23 of 495 records (4.6%) include salary data from the Careerjet API.
This is an inherent characteristic of the source, not a parsing failure.
Where present, salaries are parsed to `salary_min`, `salary_max`,
`salary_currency` (SAR default, USD from `$` prefix), and `salary_period`
(monthly/annual).

### 4. No per-listing posting date from Careerjet

Careerjet's `date` API field returns the query timestamp (identical across all
records in a single API call), not the original posting date of each listing.
The field is discarded rather than stored as misleading metadata.
Consequently, `posting_date` is null for all Careerjet records and the
`WARN-004` flag fires on every record — this is expected and documented.
The `STALE-001` and `ERR-001` rules are therefore also inactive for this source.

### 5. Description is an excerpt, not full text

The Careerjet API returns a text excerpt (~242 character mean) rather than the
full job description. This is sufficient for profiling but cannot support
skills extraction or detailed NLP without fetching the detail page.

---

## Source Evaluation

A full evaluation of 10 candidate data sources against four criteria
(robots.txt, server barriers, Terms of Service, authentication requirements)
is documented in `docs/source_investigation.md`.

**Summary:** Careerjet Partner API was selected as the primary source
(official partner programme; no scraping required). Jadarat Open Data
(open.data.gov.sa) is a viable secondary source (Arabic-language,
government/public-sector coverage; quarterly CSV under Open Data License).
All other evaluated sources were excluded due to one or more criteria failures.

---

## Data Source Compliance

This pipeline uses the **Careerjet Partner API** under a registered partner
affiliation. The API key (`CAREERJET_API_KEY`) must be obtained through
Careerjet's official partner registration. Do not make API calls without a
valid key set in `.env`.

Batch/scheduled collection compliance: a direct question was submitted to
Careerjet support at the time of initial setup. Refer to any response received
before automating scheduled runs.

---

## Security Notes

- `.env` is gitignored and must never be committed.
- All credentials (`CAREERJET_API_KEY`, `SNOWFLAKE_*`) are read exclusively
  from environment variables. The Careerjet `Referer` header has a hardcoded
  default (`https://www.careerjet.com.sa/`) that can be overridden via
  `CAREERJET_REFERRER` in `.env`.
- `data/pipeline.db` (contains real collected data) is gitignored.
  Only `data/samples/review_sample.csv` (a 20-record anonymised fixture) is committed.
