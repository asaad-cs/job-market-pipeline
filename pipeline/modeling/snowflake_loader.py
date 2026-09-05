"""
Snowflake loader — Phase 6.
Loads non-duplicate, non-rejected curated records into the Snowflake `jobs` table.

Prerequisites (OQ-11 must be resolved before this module is used):
  SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD,
  SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE, SNOWFLAKE_SCHEMA

The `jobs` table DDL is defined here and created on first run if it does not exist.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# Snowflake jobs table DDL (OLAP — curated layer)
_CREATE_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id              VARCHAR(36)   PRIMARY KEY,
    raw_id              VARCHAR(36),
    source_name         VARCHAR(100)  NOT NULL,
    source_job_id       VARCHAR(500),
    job_fingerprint     VARCHAR(64),
    source_url          TEXT,
    title               TEXT          NOT NULL,
    title_raw           TEXT,
    company_name        TEXT,
    company_name_raw    TEXT,
    location_city       VARCHAR(200),
    location_country    VARCHAR(200),
    location_raw        TEXT,
    career_level        VARCHAR(50),
    career_level_raw    TEXT,
    job_category        VARCHAR(200),
    job_category_raw    TEXT,
    salary_min          NUMBER(15,2),
    salary_max          NUMBER(15,2),
    salary_currency     VARCHAR(10),
    salary_period       VARCHAR(20),
    salary_raw          TEXT,
    description         TEXT,
    posting_date        DATE,
    expiry_date         DATE,
    saudi_national_only BOOLEAN       DEFAULT FALSE,
    collected_at        TIMESTAMP_NTZ NOT NULL,
    processed_at        TIMESTAMP_NTZ,
    is_duplicate        BOOLEAN       DEFAULT FALSE,
    duplicate_of_job_id VARCHAR(36),
    quality_flags       VARIANT,
    is_rejected         BOOLEAN       DEFAULT FALSE,
    rejection_reason    TEXT
)
"""


def _get_snowflake_conn():
    required = [
        "SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD",
        "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise RuntimeError(
            f"Snowflake credentials not configured. Missing env vars: {missing}. "
            "See OQ-11 — resolve Snowflake account setup before Phase 6."
        )

    import snowflake.connector
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
    )


def _ensure_table(conn) -> None:
    conn.cursor().execute(_CREATE_JOBS_TABLE)


def _to_row(rec: dict) -> tuple:
    return (
        str(uuid.uuid4()),                          # job_id
        rec.get("raw_id"),
        rec.get("source_name"),
        rec.get("source_job_id"),
        rec.get("job_fingerprint"),
        rec.get("source_url"),
        rec.get("title"),
        rec.get("title_raw"),
        rec.get("company_name"),
        rec.get("company_name_raw"),
        rec.get("location_city"),
        rec.get("location_country"),
        rec.get("location_raw"),
        rec.get("career_level"),
        rec.get("career_level_raw"),
        rec.get("job_category"),
        rec.get("job_category_raw"),
        rec.get("salary_min"),
        rec.get("salary_max"),
        rec.get("salary_currency"),
        rec.get("salary_period"),
        rec.get("salary_raw"),
        rec.get("description"),
        rec.get("posting_date"),
        rec.get("expiry_date"),
        bool(rec.get("saudi_national_only", False)),
        rec.get("collected_at"),
        datetime.now(timezone.utc).isoformat(),     # processed_at
        bool(rec.get("is_duplicate", False)),
        rec.get("duplicate_of_job_id"),
        json.dumps(rec.get("quality_flags", [])),   # stored as VARIANT in Snowflake
        bool(rec.get("is_rejected", False)),
        rec.get("rejection_reason"),
    )


_INSERT_SQL = """
INSERT INTO jobs (
    job_id, raw_id, source_name, source_job_id, job_fingerprint, source_url,
    title, title_raw, company_name, company_name_raw,
    location_city, location_country, location_raw,
    career_level, career_level_raw, job_category, job_category_raw,
    salary_min, salary_max, salary_currency, salary_period, salary_raw,
    description, posting_date, expiry_date,
    saudi_national_only, collected_at, processed_at,
    is_duplicate, duplicate_of_job_id, quality_flags, is_rejected, rejection_reason
) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
"""


def load_to_snowflake(records: list[dict]) -> int:
    """
    Load non-duplicate, non-rejected records to Snowflake jobs table.
    Returns the count of records successfully inserted.
    """
    to_load = [r for r in records if not r.get("is_rejected") and not r.get("is_duplicate")]
    if not to_load:
        log.info("No records to load to Snowflake (all duplicates or rejected)")
        return 0

    conn = _get_snowflake_conn()
    try:
        _ensure_table(conn)
        rows = [_to_row(r) for r in to_load]
        cur = conn.cursor()
        cur.executemany(_INSERT_SQL, rows)
        conn.commit()
        log.info("Loaded %d records to Snowflake jobs table", len(rows))
        return len(rows)
    finally:
        conn.close()
