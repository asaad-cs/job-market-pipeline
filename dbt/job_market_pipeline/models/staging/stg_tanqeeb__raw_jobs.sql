{{ config(materialized='view') }}

-- Extracts Tanqeeb-specific fields from BRONZE.raw_jobs VARIANT payload
-- and maps them to the canonical staging shape shared by all three sources.
--
-- Tanqeeb native fields used:
--   job_title, company, city, country, job_description, salary,
--   posting_date (real listing date), scraped_at

with source as (
    select * from {{ source('raw', 'raw_jobs') }}
    where source_name = 'tanqeeb'
)

select
    raw_id,
    run_id,
    source_name,
    source_job_id,
    source_url,
    collected_at,

    -- Title
    nullif(raw_payload:job_title::string, '')                               as title_raw,

    -- Company
    nullif(raw_payload:company::string, '')                                 as company_raw,

    -- Location: reconstruct "city, country" so int_jobs_cleaned's comma-split logic
    -- produces the correct location_city / location_country tokens.
    -- Tanqeeb stores city and country as separate fields; "None" becomes SQL NULL via VARIANT.
    case
        when nullif(raw_payload:city::string, '') is not null
            then nullif(raw_payload:city::string, '')
                 || ', '
                 || coalesce(nullif(raw_payload:country::string, ''), 'Saudi Arabia')
        else nullif(raw_payload:country::string, '')
    end                                                                     as location_raw,

    -- Description (full job description text)
    nullif(raw_payload:job_description::string, '')                         as description,

    -- Salary (sparse — often null for Tanqeeb listings)
    nullif(raw_payload:salary::string, '')                                  as salary_raw,

    -- api_date_raw: scrape timestamp (analogous to Careerjet's query timestamp)
    raw_payload:scraped_at::string                                          as api_date_raw,

    -- posting_date_raw: real listing date — unique advantage over Careerjet
    raw_payload:posting_date::string                                        as posting_date_raw

from source
