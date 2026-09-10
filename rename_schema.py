"""
One-off script: rename Snowflake schema RAW → BRONZE.
Writes all output to rename_schema.log (not stdout) to work around disk-full temp issues.
"""
import os, sys, traceback
sys.path.insert(0, ".")

log_lines = []
def log(msg):
    log_lines.append(msg)
    print(msg)

from dotenv import load_dotenv
load_dotenv()

acct = os.getenv("SNOWFLAKE_ACCOUNT", "")
user = os.getenv("SNOWFLAKE_USER", "")
db   = os.getenv("SNOWFLAKE_DATABASE", "")
wh   = os.getenv("SNOWFLAKE_WAREHOUSE", "")
pw   = os.getenv("SNOWFLAKE_PASSWORD", "")
schema = os.getenv("SNOWFLAKE_SCHEMA", "")

log(f"SNOWFLAKE_ACCOUNT  = {acct[:8]}..." if acct else "SNOWFLAKE_ACCOUNT  = NOT SET")
log(f"SNOWFLAKE_USER     = {user}" if user else "SNOWFLAKE_USER     = NOT SET")
log(f"SNOWFLAKE_DATABASE = {db}" if db else "SNOWFLAKE_DATABASE = NOT SET")
log(f"SNOWFLAKE_WAREHOUSE= {wh}" if wh else "SNOWFLAKE_WAREHOUSE= NOT SET")
log(f"SNOWFLAKE_SCHEMA   = {schema}")

import snowflake.connector

try:
    conn = snowflake.connector.connect(
        account=acct, user=user, password=pw,
        warehouse=wh, database=db, schema=schema,
    )
    log("Connection: OK")
    cur = conn.cursor()

    # Pre-rename: verify RAW exists with data
    cur.execute("SELECT COUNT(*) FROM JOB_PIPELINE_DB.RAW.raw_jobs")
    pre_count = cur.fetchone()[0]
    log(f"RAW.raw_jobs rows before rename: {pre_count}")

    # Execute rename
    cur.execute("ALTER SCHEMA JOB_PIPELINE_DB.RAW RENAME TO BRONZE")
    log("ALTER SCHEMA RAW RENAME TO BRONZE — executed")

    # Post-rename: verify BRONZE has the data
    cur.execute("SELECT COUNT(*) FROM JOB_PIPELINE_DB.BRONZE.raw_jobs")
    post_count = cur.fetchone()[0]
    log(f"BRONZE.raw_jobs rows after rename: {post_count}")

    # Confirm RAW is gone
    cur.execute("SHOW SCHEMAS LIKE 'RAW' IN DATABASE JOB_PIPELINE_DB")
    old_schema_rows = cur.fetchall()
    log(f"RAW schema still exists: {len(old_schema_rows) > 0}")

    cur.close()
    conn.close()
    log("RESULT: PASS" if pre_count == post_count and pre_count > 0 else "RESULT: MISMATCH — check counts")

except Exception as e:
    log(f"ERROR: {e}")
    log(traceback.format_exc())
    log("RESULT: FAIL")

# Write to log file
with open("rename_schema.log", "w", encoding="utf-8") as f:
    f.write("\n".join(log_lines) + "\n")
