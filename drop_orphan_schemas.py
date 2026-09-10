"""Drop orphan Snowflake schemas left behind after the BRONZE/SILVER/GOLD rename."""
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

print("=== DROPPING ORPHAN SCHEMAS ===")
for schema in ("STG", "INT", "MARTS"):
    try:
        cur.execute(f"DROP SCHEMA IF EXISTS JOB_PIPELINE_DB.{schema} CASCADE")
        print(f"  DROPPED  JOB_PIPELINE_DB.{schema}")
    except Exception as e:
        print(f"  ERROR    JOB_PIPELINE_DB.{schema} : {e}")

print()
print("=== REMAINING SCHEMAS IN JOB_PIPELINE_DB ===")
cur.execute("SHOW SCHEMAS IN DATABASE JOB_PIPELINE_DB")
rows = cur.fetchall()
for row in rows:
    print(f"  {row[1]}")

expected = {"BRONZE", "SILVER", "GOLD", "PUBLIC", "INFORMATION_SCHEMA"}
actual   = {row[1] for row in rows}
orphans  = actual - expected
print()
if orphans:
    print(f"  WARNING: unexpected schemas still present: {orphans}")
else:
    print("  PASS — only expected schemas remain (BRONZE, SILVER, GOLD, PUBLIC, INFORMATION_SCHEMA)")

cur.close()
conn.close()
