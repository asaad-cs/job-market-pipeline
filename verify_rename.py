"""Verify row counts and equivalence after BRONZE/SILVER/GOLD rename."""
import os, sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(dotenv_path=".env")
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

print("=== ROW COUNT VERIFICATION ===")
checks = [
    ("BRONZE.raw_jobs",               1109),
    ("SILVER.stg_careerjet__raw_jobs", 1109),
    ("SILVER.int_jobs_cleaned",        1109),
    ("SILVER.int_jobs_standardized",   1109),
    ("SILVER.int_jobs_deduplicated",   1109),
    ("SILVER.int_jobs_quality_flags",  1109),
    ("GOLD.fct_jobs",                   829),
]
all_ok = True
for table, expected in checks:
    cur.execute(f"SELECT COUNT(*) FROM JOB_PIPELINE_DB.{table}")
    actual = cur.fetchone()[0]
    status = "PASS" if actual == expected else "FAIL"
    if status == "FAIL":
        all_ok = False
    print(f"  {status}  {table:<45} expected={expected}  actual={actual}")

print()
print("=== EQUIVALENCE CHECK ===")
cur.execute("SELECT COUNT(*) FROM JOB_PIPELINE_DB.GOLD.fct_jobs")
gold_count = cur.fetchone()[0]
print(f"  GOLD.fct_jobs total                  : {gold_count}  (expected 829)")

cur.execute("""
    SELECT COUNT(*)
    FROM JOB_PIPELINE_DB.GOLD.fct_jobs f
    JOIN JOB_PIPELINE_DB.PUBLIC.jobs p
      ON f.job_fingerprint = p.job_fingerprint
""")
matched = cur.fetchone()[0]
print(f"  Fingerprint matches with PUBLIC.jobs : {matched}  (expected 824)")

cur.execute("""
    SELECT COUNT(*)
    FROM JOB_PIPELINE_DB.GOLD.fct_jobs f
    LEFT JOIN JOB_PIPELINE_DB.PUBLIC.jobs p
      ON f.job_fingerprint = p.job_fingerprint
    WHERE p.job_fingerprint IS NULL
""")
gold_only = cur.fetchone()[0]
print(f"  In GOLD only (run-1 additions)       : {gold_only}  (expected 5)")

print()
equiv_ok = (gold_count == 829 and matched == 824 and gold_only == 5)
print("=== OVERALL RESULT ===")
print("  Row counts  :", "PASS" if all_ok else "FAIL")
print("  Equivalence :", "PASS" if equiv_ok else "FAIL")
if all_ok and equiv_ok:
    print("  ALL CHECKS PASS — rename verified complete")
else:
    print("  INVESTIGATE FAILURES ABOVE")

cur.close()
conn.close()
