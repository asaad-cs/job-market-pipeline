{{ config(materialized='view') }}

with source as (
    select * from {{ source('raw', 'raw_jobs') }}
    where source_name = 'careerjet'
)

select
    raw_id,
    run_id,
    source_name,
    source_job_id,
    source_url,
    collected_at,
    nullif(raw_payload:title::string,       '') as title_raw,
    nullif(raw_payload:company::string,     '') as company_raw,
    nullif(raw_payload:locations::string,   '') as location_raw,
    nullif(raw_payload:description::string, '') as description,
    nullif(raw_payload:salary::string,      '') as salary_raw,
    raw_payload:date::string                    as api_date_raw,
    cast(null as varchar)                       as posting_date_raw  -- Careerjet date field is query timestamp, not listing date
from source
