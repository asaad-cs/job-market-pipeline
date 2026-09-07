"""
Phase 6 — Snowflake full load.
Runs the complete pipeline on the 495-record production batch and loads
all 431 non-duplicate, non-rejected records into the Snowflake jobs table.
"""
import io, json, sqlite3, sys
sys.path.insert(0, ".")
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from pipeline.processing.cleaner import clean_records
from pipeline.processing.standardizer import standardize_records
from pipeline.processing.deduplicator import deduplicate
from pipeline.quality.validator import validate, flush_quality_log
from pipeline.modeling.snowflake_loader import load_to_snowflake

DB_PATH = "./data/pipeline.db"
RUN_ID_PREFIX = "685d09d4"

# ── Load raw records ──────────────────────────────────────────────────────────
print("Loading raw records from SQLite...")
conn = sqlite3.connect(DB_PATH)
run_id = conn.execute(
    "SELECT run_id FROM collection_runs WHERE run_id LIKE ?",
    (RUN_ID_PREFIX + "%",)
).fetchone()[0]
rows = conn.execute(
    "SELECT raw_id, run_id, source_name, source_job_id, source_url, raw_payload, collected_at "
    "FROM raw_jobs WHERE run_id=?", (run_id,)
).fetchall()
conn.close()

cols = ["raw_id","run_id","source_name","source_job_id","source_url","raw_payload","collected_at"]
raw_records = [dict(zip(cols, r)) for r in rows]
print(f"  Raw records loaded: {len(raw_records)}")

# ── Pipeline stages ───────────────────────────────────────────────────────────
print("Running pipeline stages...")
cleaned      = clean_records(raw_records)
standardized = standardize_records(cleaned)
deduped      = deduplicate(standardized)
validated    = validate(deduped)
flush_quality_log()  # discard — already written in Phase 5

total     = len(validated)
dups      = sum(1 for r in validated if r.get("is_duplicate"))
rejected  = sum(1 for r in validated if r.get("is_rejected"))
to_load   = total - dups - rejected
print(f"  Total: {total}  |  Duplicates: {dups}  |  Rejected: {rejected}  |  To load: {to_load}")

# ── Snowflake load ────────────────────────────────────────────────────────────
print(f"\nLoading {to_load} records to Snowflake...")
try:
    loaded, failed = load_to_snowflake(validated)
except Exception as e:
    print(f"FAIL — load error: {e}")
    sys.exit(1)

print(f"  Inserted: {loaded}")
if failed:
    print(f"  FAILED  : {len(failed)} records")
    for raw_id, err in failed:
        print(f"    raw_id={raw_id}  error={err}")

# ── Verify via SELECT COUNT(*) ─────────────────────────────────────────────────
print("\nVerifying row count in Snowflake...")
import os, snowflake.connector
sf = snowflake.connector.connect(
    account=os.getenv("SNOWFLAKE_ACCOUNT"),
    user=os.getenv("SNOWFLAKE_USER"),
    password=os.getenv("SNOWFLAKE_PASSWORD"),
    warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
    database=os.getenv("SNOWFLAKE_DATABASE"),
    schema=os.getenv("SNOWFLAKE_SCHEMA"),
)
cur = sf.cursor()
cur.execute("SELECT COUNT(*) FROM jobs")
sf_count = cur.fetchone()[0]

# Quick sample to confirm data integrity
cur.execute("""
    SELECT title, company_name, location_city, career_level, source_name
    FROM jobs
    ORDER BY collected_at DESC
    LIMIT 5
""")
sample_rows = cur.fetchall()
cur.close()
sf.close()

print(f"  SELECT COUNT(*) FROM jobs = {sf_count}")
print()
print("  Sample (5 most recent rows):")
print(f"  {'Title':<40} {'Company':<22} {'City':<14} {'Level':<12} {'Source'}")
print(f"  {'-'*40} {'-'*22} {'-'*14} {'-'*12} {'-'*10}")
for title, company, city, level, source in sample_rows:
    t = (title or "")[:39]
    c = (company or "(null)")[:21]
    ci = (city or "(null)")[:13]
    lv = (level or "(null)")[:11]
    print(f"  {t:<40} {c:<22} {ci:<14} {lv:<12} {source}")

# ── Final report ─────────────────────────────────────────────────────────────
print()
print("=" * 60)
if sf_count == loaded == to_load:
    print(f"PASS — Phase 6 complete.")
    print(f"  Pipeline output : {to_load} records to load")
    print(f"  Snowflake INSERT: {loaded} records inserted")
    print(f"  SELECT COUNT(*) : {sf_count} rows in jobs table")
else:
    print(f"WARNING — count mismatch")
    print(f"  Expected to load : {to_load}")
    print(f"  Inserted by loader: {loaded}")
    print(f"  Snowflake count  : {sf_count}")
print("=" * 60)
