"""
Execute backfill_warn005.sql against the live Snowflake jobs table.
Runs each step in sequence with confirmation checks.
"""
import io, os, sys
sys.path.insert(0, ".")
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()
import snowflake.connector

conn = snowflake.connector.connect(
    account=os.getenv("SNOWFLAKE_ACCOUNT"),
    user=os.getenv("SNOWFLAKE_USER"),
    password=os.getenv("SNOWFLAKE_PASSWORD"),
    warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
    database=os.getenv("SNOWFLAKE_DATABASE"),
    schema=os.getenv("SNOWFLAKE_SCHEMA"),
)
cur = conn.cursor()

# ── Step 1: dry-run count ─────────────────────────────────────────────────────
print("Step 1: dry-run — SELECT COUNT(*) WHERE company_name IS NULL AND location_city IS NULL")
cur.execute("""
    SELECT COUNT(*) FROM jobs
    WHERE company_name IS NULL
      AND location_city IS NULL
""")
dry_run_count = cur.fetchone()[0]
print(f"  Records matching WHERE clause: {dry_run_count}")

if dry_run_count != 36:
    print(f"ABORT — expected 36 records, got {dry_run_count}. Not proceeding with UPDATE.")
    conn.close()
    sys.exit(1)
print("  Count matches expected 36. Proceeding with UPDATE.\n")

# ── Step 2: UPDATE ────────────────────────────────────────────────────────────
print("Step 2: UPDATE — ARRAY_APPEND WARN-005 to quality_flags")
cur.execute("""
    UPDATE jobs
    SET quality_flags = ARRAY_APPEND(
        COALESCE(quality_flags, PARSE_JSON('[]')),
        PARSE_JSON('{
            "rule": "WARN-005",
            "severity": "warning",
            "message": "low-confidence fingerprint: 2/3 fingerprint components (title, company_name, location_city) are null/empty — deduplication reliability is degraded for this record"
        }')
    )
    WHERE company_name IS NULL
      AND location_city IS NULL
""")
conn.commit()
rows_updated = cur.rowcount
print(f"  Rows updated: {rows_updated}\n")

# ── Step 3a: verify flag count via FLATTEN ────────────────────────────────────
print("Step 3a: verify WARN-005 flag count via LATERAL FLATTEN")
cur.execute("""
    SELECT COUNT(DISTINCT j.job_id) AS flagged_records
    FROM jobs j,
         LATERAL FLATTEN(input => j.quality_flags) f
    WHERE f.value:rule::STRING = 'WARN-005'
""")
flagged_count = cur.fetchone()[0]
print(f"  Records with WARN-005 in quality_flags: {flagged_count}")
if flagged_count != 36:
    print(f"  WARNING — expected 36, got {flagged_count}")
else:
    print("  OK — 36 records carry WARN-005.\n")

# ── Step 3b: total row count ──────────────────────────────────────────────────
print("Step 3b: confirm total row count unchanged")
cur.execute("SELECT COUNT(*) FROM jobs")
total = cur.fetchone()[0]
print(f"  SELECT COUNT(*) FROM jobs = {total}")
if total != 431:
    print(f"  WARNING — expected 431, got {total}")
else:
    print("  OK — 431 rows, no rows added or deleted.\n")

# ── Step 3c: spot-check 3 records ────────────────────────────────────────────
print("Step 3c: spot-check 3 updated records")
cur.execute("""
    SELECT job_id, title, quality_flags
    FROM jobs
    WHERE company_name IS NULL
      AND location_city IS NULL
    LIMIT 3
""")
for job_id, title, flags in cur.fetchall():
    import json
    flag_rules = [f.get("rule") for f in (flags if isinstance(flags, list) else json.loads(str(flags)))]
    print(f"  job_id : {str(job_id)[:8]}...")
    print(f"  title  : {(title or '')[:60]}")
    print(f"  flags  : {flag_rules}")
    print()

cur.close()
conn.close()

# ── Final verdict ─────────────────────────────────────────────────────────────
print("=" * 55)
if dry_run_count == 36 and rows_updated == 36 and flagged_count == 36 and total == 431:
    print("PASS — backfill complete. All 4 checks confirmed.")
else:
    print("PARTIAL — review results above for discrepancies.")
print("=" * 55)
