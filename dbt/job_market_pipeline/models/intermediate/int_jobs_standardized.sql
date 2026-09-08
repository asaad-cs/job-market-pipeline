{{ config(materialized='view') }}

-- Adds career level (inferred from title), salary components, and out_of_region flag.
-- Replicates standardizer.py logic.

with src as (
    select * from {{ ref('int_jobs_cleaned') }}
)

select
    *,

    -- ── Career level ──────────────────────────────────────────────────────────
    -- Careerjet has no dedicated field; inferred from job title text.
    -- Python _CAREER_LEVEL_MAP: patterns tested in order, first match wins.
    case
        when career_level_raw is null
            then 'Unspecified'
        when regexp_instr(career_level_raw,
             'entry\\s*level|fresh\\s*grad|junior|\\bintern\\b|\\btrainee\\b',
             1, 1, 0, 'i') > 0
            then 'Entry'
        when regexp_instr(career_level_raw,
             'intermediate|mid[\\s\\-]level|mid$',
             1, 1, 0, 'i') > 0
            then 'Mid'
        when regexp_instr(career_level_raw,
             '\\bsenior\\b|\\bsr\\.?\\b|\\blead\\b',
             1, 1, 0, 'i') > 0
            then 'Senior'
        when regexp_instr(career_level_raw,
             '\\bmanager\\b|management|\\bhead\\s+of\\b',
             1, 1, 0, 'i') > 0
            then 'Manager'
        when regexp_instr(career_level_raw,
             'executive|director|c[\\s\\-]?level|\\bvp\\b|vice\\s*president',
             1, 1, 0, 'i') > 0
            then 'Executive'
        else 'Unspecified'
    end                                                     as career_level,

    -- ── Salary parsing ────────────────────────────────────────────────────────
    -- Observed Careerjet formats: "10000 - 16000 per month", "$4000 per month",
    -- "95000 per year". Currency defaults to SAR when absent (Saudi market).
    -- Null terms (Negotiable, Undisclosed, Competitive, TBD, N/A) → all NULL.

    case
        when salary_raw is null
          or lower(trim(salary_raw)) in ('negotiable','undisclosed','competitive','tbd','n/a','na')
          or regexp_instr(salary_raw, '[\\d,]+') = 0
            then null
        else to_number(nullif(replace(regexp_substr(salary_raw, '[\\d,]+', 1, 1), ',', ''), ''))
    end                                                     as salary_min,

    case
        when salary_raw is null
          or lower(trim(salary_raw)) in ('negotiable','undisclosed','competitive','tbd','n/a','na')
            then null
        -- Extract number after " - " / " – " range separator
        else to_number(nullif(replace(
                regexp_substr(salary_raw, '[\\d,]+\\s*[-–]\\s*([\\d,]+)', 1, 1, 'e', 1),
                ',', ''), ''))
    end                                                     as salary_max,

    case
        when salary_raw is null
          or lower(trim(salary_raw)) in ('negotiable','undisclosed','competitive','tbd','n/a','na')
          or regexp_instr(salary_raw, '[\\d,]+') = 0
            then null
        when regexp_instr(salary_raw, '\\$') > 0            then 'USD'
        when regexp_instr(salary_raw, '£') > 0              then 'GBP'
        when regexp_instr(salary_raw, '€') > 0              then 'EUR'
        -- ISO code (2-3 uppercase letters) immediately before the first digit
        when regexp_substr(salary_raw, '^\\s*([A-Z]{2,3})\\s*[\\d,]', 1, 1, 'e', 1) is not null
            then regexp_substr(salary_raw, '^\\s*([A-Z]{2,3})\\s*[\\d,]', 1, 1, 'e', 1)
        else 'SAR'
    end                                                     as salary_currency,

    case
        when salary_raw is null
          or lower(trim(salary_raw)) in ('negotiable','undisclosed','competitive','tbd','n/a','na')
          or regexp_instr(salary_raw, '[\\d,]+') = 0
            then null
        when regexp_instr(salary_raw, 'per\\s+month|\\/\\s*month',    1, 1, 0, 'i') > 0 then 'monthly'
        when regexp_instr(salary_raw, 'per\\s+year|\\/\\s*year|\\/\\s*annual', 1, 1, 0, 'i') > 0 then 'annual'
        when regexp_instr(salary_raw, 'per\\s+hour|\\/\\s*hour',      1, 1, 0, 'i') > 0 then 'hourly'
        else 'unspecified'
    end                                                     as salary_period,

    -- ── Out-of-region flag ────────────────────────────────────────────────────
    -- Python: out_of_region = country not in {"saudi arabia","ksa"} if country else False
    iff(
        location_country is not null
        and lower(location_country) not in ('saudi arabia', 'ksa'),
        true, false
    )                                                       as out_of_region

from src
