{{ config(materialized='view') }}

-- Applies all quality rules from validator.py (§11 of the plan).
-- Builds quality_flags array, sets is_rejected and rejection_reason.
-- Records are never dropped — rejections are flagged, not deleted.

with src as (
    select * from {{ ref('int_jobs_deduplicated') }}
),

-- Helper: count null fingerprint components (for WARN-005 threshold)
flagged as (
    select
        *,
        (case when title        is null then 1 else 0 end
         + case when company_name  is null then 1 else 0 end
         + case when location_city is null then 1 else 0 end) as _fp_null_count
    from src
)

select
    * exclude (_fp_null_count),

    -- ── quality_flags: VARIANT array of {rule, severity, message} objects ─────
    -- NULL entries are compacted out; empty array means the record is clean.
    array_compact(array_construct(

        -- REQ-003: source_url null
        case when source_url is null
             then object_construct('rule','REQ-003','severity','error',
                  'message','source_url is null')
             else null end,

        -- REQ-004: collected_at null
        case when collected_at is null
             then object_construct('rule','REQ-004','severity','error',
                  'message','collected_at is null')
             else null end,

        -- ERR-002: inverted salary range
        case when salary_min is not null and salary_max is not null and salary_min > salary_max
             then object_construct('rule','ERR-002','severity','error',
                  'message','salary_min (' || salary_min::varchar
                  || ') > salary_max (' || salary_max::varchar || ')')
             else null end,

        -- ERR-003: title too long (likely scraping artifact)
        case when length(coalesce(title,'')) > 300
             then object_construct('rule','ERR-003','severity','error',
                  'message','title length ' || length(title)::varchar || ' exceeds 300 chars')
             else null end,

        -- ERR-004: explicit non-Saudi country
        case when location_country is not null
              and lower(location_country) not in ('saudi arabia','ksa')
             then object_construct('rule','ERR-004','severity','warning',
                  'message','location_country ''' || location_country || ''' is not Saudi Arabia')
             else null end,

        -- WARN-001: company_name null
        case when company_name is null
             then object_construct('rule','WARN-001','severity','warning',
                  'message','company_name is null')
             else null end,

        -- WARN-002: location_raw null
        case when location_raw is null
             then object_construct('rule','WARN-002','severity','warning',
                  'message','location_raw is null')
             else null end,

        -- WARN-003: career_level could not be mapped
        case when career_level = 'Unspecified'
             then object_construct('rule','WARN-003','severity','info',
                  'message','career_level could not be mapped')
             else null end,

        -- WARN-004: posting_date null (fires on every Careerjet record)
        case when posting_date is null
             then object_construct('rule','WARN-004','severity','info',
                  'message','posting_date is null')
             else null end,

        -- WARN-005: low-confidence fingerprint (≥2 of 3 components null)
        case when _fp_null_count >= 2
             then object_construct('rule','WARN-005','severity','warning',
                  'message','low-confidence fingerprint: ' || _fp_null_count::varchar
                  || '/3 fingerprint components (title, company_name, location_city) are null/empty')
             else null end

    ))                                                          as quality_flags,

    -- ── is_rejected: any fatal rule fires ────────────────────────────────────
    (
        title is null                                           -- REQ-001
        or (source_job_id is null and job_fingerprint is null) -- REQ-002
        or source_url is null                                   -- REQ-003
        or collected_at is null                                 -- REQ-004
        or length(coalesce(title,'')) > 300                     -- ERR-003
        or (salary_min is not null and salary_max is not null
            and salary_min > salary_max)                        -- ERR-002
    )                                                           as is_rejected,

    -- ── rejection_reason: first fatal rule (Python's priority order) ─────────
    case
        when title is null
            then 'REQ-001: title is null or empty'
        when source_job_id is null and job_fingerprint is null
            then 'REQ-002: no source_job_id and no job_fingerprint'
        when source_url is null
            then 'REQ-003: source_url is null'
        when collected_at is null
            then 'REQ-004: collected_at is null'
        when length(coalesce(title,'')) > 300
            then 'ERR-003: title length > 300 chars'
        when salary_min is not null and salary_max is not null and salary_min > salary_max
            then 'ERR-002: salary_min > salary_max'
        else null
    end                                                         as rejection_reason

from flagged
