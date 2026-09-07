"""
Minimal Snowflake connection test.
Steps:
  1. Connect using SNOWFLAKE_* env vars
  2. CREATE TABLE IF NOT EXISTS jobs (full §8 DDL, Snowflake types)
  3. INSERT one test row
  4. SELECT it back
  5. DELETE the test row (clean up)
  6. Report pass/fail with exact error if any step fails
"""
import io, os, sys, uuid
sys.path.insert(0, ".")
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

REQUIRED_VARS = [
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_SCHEMA",
]

# ── 0. Validate env vars are set ─────────────────────────────────────────────
missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
if missing:
    print(f"FAIL — missing env vars: {', '.join(missing)}")
    sys.exit(1)

print("Env vars: all present")
print(f"  Account  : {os.getenv('SNOWFLAKE_ACCOUNT')}")
print(f"  User     : {os.getenv('SNOWFLAKE_USER')}")
print(f"  Database : {os.getenv('SNOWFLAKE_DATABASE')}")
print(f"  Schema   : {os.getenv('SNOWFLAKE_SCHEMA')}")
print(f"  Warehouse: {os.getenv('SNOWFLAKE_WAREHOUSE')}")
print()

# ── 1. Connect ────────────────────────────────────────────────────────────────
import snowflake.connector

print("Step 1: connecting...")
try:
    conn = snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
    )
    print("  Connected.")
except Exception as e:
    print(f"FAIL — connection error: {e}")
    sys.exit(1)

cur = conn.cursor()

# ── 2. CREATE TABLE IF NOT EXISTS jobs (§8 DDL — Snowflake types) ────────────
# Type mapping from plan §8:
#   UUID        → VARCHAR(36)
#   JSONB       → VARIANT         (Snowflake semi-structured)
#   TIMESTAMP   → TIMESTAMP_LTZ   (local timezone)
#   BOOLEAN     → BOOLEAN
#   TEXT/NUMERIC unchanged
JOBS_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id              VARCHAR(36)      NOT NULL PRIMARY KEY,
    raw_id              VARCHAR(36)      NOT NULL,

    -- Source identity
    source_name         VARCHAR          NOT NULL,
    source_job_id       VARCHAR,
    job_fingerprint     VARCHAR,
    source_url          VARCHAR,

    -- Core fields (cleaned)
    title               VARCHAR          NOT NULL,
    title_raw           VARCHAR,
    company_name        VARCHAR,
    company_name_raw    VARCHAR,
    location_city       VARCHAR,
    location_country    VARCHAR,
    location_raw        VARCHAR,
    career_level        VARCHAR,
    career_level_raw    VARCHAR,
    job_category        VARCHAR,
    job_category_raw    VARCHAR,

    -- Optional fields
    salary_min          NUMBER,
    salary_max          NUMBER,
    salary_currency     VARCHAR,
    salary_period       VARCHAR,
    salary_raw          VARCHAR,
    description         VARCHAR,
    posting_date        DATE,
    expiry_date         DATE,

    -- Derived flags
    saudi_national_only BOOLEAN          DEFAULT FALSE,

    -- Pipeline metadata
    collected_at        TIMESTAMP_LTZ    NOT NULL,
    processed_at        TIMESTAMP_LTZ,
    is_duplicate        BOOLEAN          DEFAULT FALSE,
    duplicate_of_job_id VARCHAR(36),
    quality_flags       VARIANT,
    is_rejected         BOOLEAN          DEFAULT FALSE,
    rejection_reason    VARCHAR
)
"""

print("Step 2: creating jobs table (IF NOT EXISTS)...")
try:
    cur.execute(JOBS_DDL)
    print("  Table ready.")
except Exception as e:
    print(f"FAIL — CREATE TABLE error: {e}")
    conn.close()
    sys.exit(1)

# ── 3. INSERT one test row ────────────────────────────────────────────────────
test_job_id = str(uuid.uuid4())
print(f"Step 3: inserting test row (job_id={test_job_id[:8]}...)...")
try:
    cur.execute("""
        INSERT INTO jobs (
            job_id, raw_id, source_name, source_url,
            title, title_raw,
            location_city, location_country, location_raw,
            collected_at, is_duplicate, is_rejected,
            quality_flags
        )
        SELECT
            %(job_id)s, %(raw_id)s, %(source_name)s, %(source_url)s,
            %(title)s, %(title_raw)s,
            %(city)s, %(country)s, %(location_raw)s,
            CURRENT_TIMESTAMP, FALSE, FALSE,
            PARSE_JSON('[]')
    """, {
        "job_id":       test_job_id,
        "raw_id":       str(uuid.uuid4()),
        "source_name":  "connection_test",
        "source_url":   "https://test.example.com/job/1",
        "title":        "Test Job — Pipeline Connection Smoke Test",
        "title_raw":    "Test Job — Pipeline Connection Smoke Test",
        "city":         "Riyadh",
        "country":      "Saudi Arabia",
        "location_raw": "Riyadh, Saudi Arabia",
    })
    print("  Row inserted.")
except Exception as e:
    print(f"FAIL — INSERT error: {e}")
    conn.close()
    sys.exit(1)

# ── 4. SELECT it back ─────────────────────────────────────────────────────────
print("Step 4: querying back...")
try:
    cur.execute("SELECT job_id, title, location_city, source_name FROM jobs WHERE job_id = %s",
                (test_job_id,))
    row = cur.fetchone()
    if not row:
        print("FAIL — SELECT returned no rows")
        conn.close()
        sys.exit(1)
    fetched_id, fetched_title, fetched_city, fetched_source = row
    print(f"  job_id      : {fetched_id}")
    print(f"  title       : {fetched_title}")
    print(f"  location_city: {fetched_city}")
    print(f"  source_name : {fetched_source}")
except Exception as e:
    print(f"FAIL — SELECT error: {e}")
    conn.close()
    sys.exit(1)

# ── 5. DELETE the test row (clean up) ─────────────────────────────────────────
print("Step 5: deleting test row...")
try:
    cur.execute("DELETE FROM jobs WHERE job_id = %s", (test_job_id,))
    print("  Cleaned up.")
except Exception as e:
    print(f"  WARNING — cleanup DELETE failed (non-fatal): {e}")

cur.close()
conn.close()

print()
print("=" * 50)
print("PASS — Snowflake connection, DDL, INSERT, SELECT all successful.")
print("Ready for Phase 6 full load.")
print("=" * 50)
