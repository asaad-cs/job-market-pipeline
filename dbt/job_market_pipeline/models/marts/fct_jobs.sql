{{ config(materialized='table') }}

-- Final curated job postings table.
-- Filters to non-duplicate, non-rejected records only — mirrors what
-- phase6_load.py writes to PUBLIC.jobs in the Python pipeline.

with src as (
    select * from {{ ref('int_jobs_quality_flags') }}
)

select
    uuid_string()                   as job_id,
    raw_id,
    run_id,
    source_name,
    source_job_id,
    source_url,
    job_fingerprint,

    -- Cleaned fields
    title,
    title_raw,
    company_name,
    company_name_raw,
    location_city,
    location_country,
    location_raw,

    -- Standardized fields
    career_level,
    career_level_raw,
    salary_min,
    salary_max,
    salary_currency,
    salary_period,
    salary_raw,
    description,
    posting_date,
    api_date_raw,

    -- Derived flags
    saudi_national_only,
    out_of_region,

    -- Pipeline state
    is_duplicate,
    duplicate_of_raw_id,
    is_rejected,
    rejection_reason,
    quality_flags,

    -- Timestamps
    collected_at,
    current_timestamp()             as processed_at

from src
where is_duplicate = false
  and is_rejected  = false
