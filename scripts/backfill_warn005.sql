-- backfill_warn005.sql
-- Retroactively applies the WARN-005 LOW-CONFIDENCE-FINGERPRINT quality flag
-- to the 431 records loaded in Phase 6 (2026-09-07), which predated the rule.
--
-- Condition: >=2 of the 3 fingerprint components (title, company_name,
-- location_city) are null.  Since all loaded records passed REQ-001 (title
-- not null), the only reachable case is company_name IS NULL AND
-- location_city IS NULL.
--
-- The UPDATE *appends* to the existing quality_flags VARIANT array using
-- ARRAY_APPEND so pre-existing flags (WARN-001, WARN-004, etc.) are preserved.
-- It does NOT overwrite the array.
--
-- Safe to re-run: records already carrying WARN-005 will receive a duplicate
-- entry; to make it idempotent wrap in a WHERE NOT EXISTS sub-select if
-- re-running is a concern.

-- Step 1: dry-run count (must equal 36 before proceeding)
-- Note: 37 records had null company+city across all 495 cleaned records,
-- but 1 was a duplicate and not loaded; the loaded table has 36.
SELECT COUNT(*) AS records_to_flag
FROM jobs
WHERE company_name IS NULL
  AND location_city IS NULL;

-- Step 2: UPDATE — append WARN-005 to quality_flags for those records
UPDATE jobs
SET quality_flags = ARRAY_APPEND(
    COALESCE(quality_flags, PARSE_JSON('[]')),
    PARSE_JSON('{
        "rule": "WARN-005",
        "severity": "warning",
        "message": "low-confidence fingerprint: 2/3 fingerprint components (title, company_name, location_city) are null/empty — deduplication reliability is degraded for this record"
    }')
)
WHERE company_name IS NULL
  AND location_city IS NULL;

-- Step 3a: verify flag count via FLATTEN (ARRAY_CONTAINS matches scalars only;
-- quality_flags contains objects so we unnest with LATERAL FLATTEN instead)
SELECT COUNT(DISTINCT j.job_id) AS flagged_records
FROM jobs j,
     LATERAL FLATTEN(input => j.quality_flags) f
WHERE f.value:rule::STRING = 'WARN-005';

-- Step 3b: confirm total row count unchanged
SELECT COUNT(*) AS total_rows FROM jobs;

-- Step 3c: spot-check 3 updated records — confirm WARN-005 coexists with
-- pre-existing flags (not overwritten)
SELECT job_id, title, quality_flags
FROM jobs
WHERE company_name IS NULL
  AND location_city IS NULL
LIMIT 3;
