{{ config(materialized='view') }}

-- Extracts Jooble-specific fields from BRONZE.raw_jobs VARIANT payload
-- and maps them to the canonical staging shape shared by all three sources.
--
-- Jooble native fields used:
--   title, company, location, snippet (description excerpt), salary (empty),
--   updated (listing update date), id (native job ID already in source_job_id)
--
-- Known limitations:
--   salary: 0% coverage for Saudi Arabia listings — always maps to NULL
--   snippet: contains HTML entities (&nbsp;, <b>) — passed as-is

with source as (
    select * from {{ source('raw', 'raw_jobs') }}
    where source_name = 'jooble'
)

select
    raw_id,
    run_id,
    source_name,
    source_job_id,
    source_url,
    collected_at,

    -- Title
    nullif(raw_payload:title::string, '')                                   as title_raw,

    -- Company
    nullif(raw_payload:company::string, '')                                 as company_raw,

    -- Location (Jooble returns city name only, e.g. "Riyadh" — no country token)
    nullif(raw_payload:location::string, '')                                as location_raw,

    -- Description (HTML-entity snippet, ~200 chars)
    nullif(raw_payload:snippet::string, '')                                 as description,

    -- Salary: always empty string for SA listings — map to NULL explicitly
    nullif(nullif(raw_payload:salary::string, ''), 'null')                  as salary_raw,

    -- api_date_raw: updated timestamp (same as posting_date_raw for Jooble)
    raw_payload:updated::string                                             as api_date_raw,

    -- posting_date_raw: real listing update date
    raw_payload:updated::string                                             as posting_date_raw

from source
