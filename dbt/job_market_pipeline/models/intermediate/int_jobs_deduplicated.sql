{{ config(materialized='view') }}

-- Fingerprint-based deduplication across all records.
-- The earliest-collected record (by collected_at) for each job_fingerprint is canonical;
-- subsequent records with the same fingerprint are marked is_duplicate = true.
--
-- Pre-declared divergence from Python:
--   Python's deduplicator processes one run at a time; the canonical version of a
--   cross-run duplicate is whichever run was loaded first to processed_fingerprints.
--   SQL picks globally-earliest collected_at, which may differ for the ~20 run-1
--   records that Python never processed through phase6_load.py.

with src as (
    select * from {{ ref('int_jobs_standardized') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by job_fingerprint
            order by collected_at asc
        )                                                       as _fp_rank,
        -- raw_id of the earliest (canonical) record for this fingerprint
        first_value(raw_id) over (
            partition by job_fingerprint
            order by collected_at asc
            rows between unbounded preceding and unbounded following
        )                                                       as _canonical_raw_id
    from src
)

select
    * exclude (_fp_rank, _canonical_raw_id),
    (_fp_rank > 1)                                              as is_duplicate,
    case when _fp_rank > 1 then _canonical_raw_id else null end as duplicate_of_raw_id
from ranked
