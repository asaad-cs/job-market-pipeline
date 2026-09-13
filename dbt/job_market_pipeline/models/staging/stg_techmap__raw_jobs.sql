{{ config(materialized='view') }}

-- Extracts Techmap-specific fields from BRONZE.raw_jobs VARIANT payload
-- and maps them to the canonical staging shape shared by all four sources.
--
-- Techmap native fields used:
--   title, company, city (raw — messy Arabic concatenated strings for rows 4-10),
--   country (always "Saudi Arabia" / "sa"), date_created (full ISO-8601 UTC timestamp)
--
-- Known limitations:
--   description : not present in this export (no full text; has_salary is a flag only)
--   salary_raw  : not present in this export (has_salary boolean only)
--   city        : rows 4-10 contain concatenated Arabic region/city/country strings
--                 (e.g. "الشرقية الظهران السعودية"); left as-is per sample decision
--   title       : rows 1-3 (Manatal portal) include " — Riyadh, Saudi Arabia" suffix
--                 appended by the Techmap aggregator; not stripped here
--   source      : static 10-record sample (teammate RapidAPI pull 2026-09-07);
--                 no live API key configured; ToS not fully verified

with source as (
    select * from {{ source('raw', 'raw_jobs') }}
    where source_name = 'techmap'
)

select
    raw_id,
    run_id,
    source_name,
    source_job_id,
    source_url,
    collected_at,

    -- Title (includes " — Riyadh, Saudi Arabia" suffix on Manatal portal rows)
    nullif(raw_payload:title::string, '')                                   as title_raw,

    -- Company
    nullif(raw_payload:company::string, '')                                 as company_raw,

    -- Location: city + country combined into a single token for the shared
    -- location-parsing logic in int_jobs_cleaned.sql.
    -- city is the raw Techmap city field (Arabic concatenated string for rows 4-10).
    -- country is always "Saudi Arabia" from the collector mapping of countryCode="sa".
    case
        when nullif(raw_payload:city::string, '') is not null
            then nullif(raw_payload:city::string, '')
                 || ', '
                 || coalesce(nullif(raw_payload:country::string, ''), 'Saudi Arabia')
        else nullif(raw_payload:country::string, '')
    end                                                                     as location_raw,

    -- No description field in this export
    cast(null as varchar)                                                   as description,

    -- No salary value in this export (has_salary is a boolean flag only)
    cast(null as varchar)                                                   as salary_raw,

    -- api_date_raw: full ISO-8601 UTC timestamp from dateCreated field
    raw_payload:date_created::string                                        as api_date_raw,

    -- posting_date_raw: same as date_created — timestamps vary across a 4.5-hour
    -- window (02:20–06:48 UTC), ruling out a single-call collection artifact.
    -- Treated as likely real posting times; not empirically validated with
    -- a multi-day dataset. TRY_TO_DATE() in int_jobs_cleaned handles conversion.
    raw_payload:date_created::string                                        as posting_date_raw

from source
