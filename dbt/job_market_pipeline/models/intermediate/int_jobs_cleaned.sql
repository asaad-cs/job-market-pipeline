{{ config(materialized='view') }}

-- Replicates pipeline/processing/cleaner.py logic in SQL.
-- Applied uniformly to all three sources (Careerjet, Tanqeeb, Jooble) via UNION ALL.
--
-- Known divergence (display only, does not affect fingerprints):
--   Python re-uppercases 3-5 char all-caps tokens after title-casing company names
--   (e.g., "AECOM" stays "AECOM"). SQL uses INITCAP which lowercases them ("Aecom").
--   Fingerprints are unaffected because SHA2 input always uses UPPER() on cleaned values.

with all_sources as (
    -- All three staging models share the same 13-column canonical shape.
    -- The UNION ALL here is the single merge point: one cleaning/standardization/
    -- dedup/quality pipeline runs against all sources together.
    select * from {{ ref('stg_careerjet__raw_jobs') }}
    union all
    select * from {{ ref('stg_tanqeeb__raw_jobs') }}
    union all
    select * from {{ ref('stg_jooble__raw_jobs') }}
),

stg as (
    select * from all_sources
),

-- ── Step 1: Clean title & detect Saudi-national flag ──────────────────────
title_work as (
    select
        *,
        -- Flag: title contains any Saudi-national qualifier (case-insensitive search)
        (regexp_instr(
            coalesce(title_raw, ''),
            '\\(?\\s*SAUDI\\s*NATIONALS?\\s*ONLY\\s*\\)?'
            || '|\\(?\\s*SAUDI\\s*NATIONALS?\\s*\\)?'
            || '|\\(?\\s*Saudi\\s*Only\\s*\\)?'
            || '|\\(?\\s*Saudis?\\s*Only\\s*\\)?'
            || '|متاح\\s*للسعوديين',
            1, 1, 0, 'i'
        ) > 0) as saudi_national_only,
        -- Strip all Saudi-national qualifiers, collapse whitespace, then NULLIF empty
        nullif(
            trim(regexp_replace(
                regexp_replace(
                    coalesce(title_raw, ''),
                    '\\s*\\(?\\s*SAUDI\\s*NATIONALS?\\s*ONLY\\s*\\)?'
                    || '|\\s*\\(?\\s*SAUDI\\s*NATIONALS?\\s*\\)?'
                    || '|\\s*\\(?\\s*Saudi\\s*Only\\s*\\)?'
                    || '|\\s*\\(?\\s*Saudis?\\s*Only\\s*\\)?'
                    || '|متاح\\s*للسعوديين',
                    '', 1, 0, 'i'
                ),
                '\\s{2,}', ' '
            )),
            ''
        ) as title
    from stg
),

-- ── Step 2: Clean company name ────────────────────────────────────────────
-- Python order: strip legal suffixes → expand abbreviations → title-case →
--   re-uppercase acronyms (3-5 alpha all-caps tokens, display only).
-- SQL uses INITCAP for title-case; acronym re-uppercasing is the known divergence.
company_work as (
    select
        *,
        nullif(
            trim(initcap(
                regexp_replace(
                    regexp_replace(
                        regexp_replace(
                            -- 1. Strip trailing legal suffixes
                            regexp_replace(
                                coalesce(company_raw, ''),
                                '\\s*,?\\s*\\b(Ltd\\.?|LLC\\.?|L\\.L\\.C\\.?|Co\\.?|Corp\\.?|Inc\\.?|PLC\\.?|GmbH|S\\.A\\.)\\s*$',
                                '', 1, 0, 'i'
                            ),
                            -- 2. Expand abbreviations
                            '\\bIntl\\.?\\b', 'International', 1, 0, 'i'
                        ),
                        '\\bMgmt\\.?\\b', 'Management', 1, 0, 'i'
                    ),
                    '\\bGrp\\.?\\b', 'Group', 1, 0, 'i'
                )
            )),
            ''
        ) as company_name
    from title_work
),

-- ── Step 3: Parse location into city + country tokens ─────────────────────
-- Python: primary = raw.split(" - ")[0].strip()   → strip multi-city suffix
--         parts   = primary.split(",", 1)           → split on first comma only
location_tokens as (
    select
        *,
        -- Primary: everything before the first " - " separator
        trim(split_part(coalesce(location_raw, ''), ' - ', 1)) as primary_loc
    from company_work
),

location_split as (
    select
        *,
        -- token1: city candidate (before first comma)
        trim(split_part(primary_loc, ',', 1)) as loc_token1,
        -- token2: everything after first comma (NULL if no comma present)
        -- Use REGEXP_SUBSTR with a capture group so we get "after first comma",
        -- not just the second CSV field (matches Python's split(",", 1)[1]).
        nullif(
            trim(coalesce(regexp_substr(primary_loc, ',\\s*(.*)', 1, 1, 'e', 1), '')),
            ''
        ) as loc_token2
    from location_tokens
),

-- ── Step 4: Resolve city alias and infer country ──────────────────────────
location_resolved as (
    select
        *,
        -- City: apply _CITY_ALIASES dict; fallback to INITCAP (Python's .title())
        case
            when location_raw is null                                   then null
            when lower(loc_token1) in (
                'saudi arabia', 'ksa', 'المملكة العربية السعودية'
            )                                                           then null
            when lower(loc_token1) = 'ar riyadh'                       then 'Riyadh'
            when lower(loc_token1) = 'الرياض'                          then 'Riyadh'
            when lower(loc_token1) in ('jedda', 'jiddah')              then 'Jeddah'
            when lower(loc_token1) = 'جدة'                             then 'Jeddah'
            when lower(loc_token1) = 'الدمام'                          then 'Dammam'
            when lower(loc_token1) in ('al khobar', 'al khubar')       then 'Al Khobar'
            when lower(loc_token1) = 'الخبر'                           then 'Al Khobar'
            when lower(loc_token1) in ('makkah', 'mecca')              then 'Mecca'
            when lower(loc_token1) = 'مكة'                             then 'Mecca'
            when lower(loc_token1) in ('madinah', 'medina', 'al madinah') then 'Medina'
            when lower(loc_token1) = 'المدينة'                         then 'Medina'
            else initcap(loc_token1, ' ''')
        end as location_city,

        -- Country: infer from token2 (country name or Saudi administrative region)
        case
            when location_raw is null                                   then null
            -- token1 was a country name → city is null, country is Saudi Arabia
            when lower(loc_token1) in (
                'saudi arabia', 'ksa', 'المملكة العربية السعودية'
            )                                                           then 'Saudi Arabia'
            -- no token2 → country unknown
            when loc_token2 is null                                     then null
            -- token2 is an explicit country name
            when lower(loc_token2) in (
                'saudi arabia', 'ksa', 'المملكة العربية السعودية'
            )                                                           then 'Saudi Arabia'
            -- token2 is a Saudi administrative region → country is Saudi Arabia
            when lower(loc_token2) in (
                'ash sharqiyah', 'eastern province',
                'al qasim', 'qassim',
                'makkah', 'makkah al mukarramah',
                'al madinah', 'madinah',
                'al jawf', 'al jouf',
                'riyadh',
                'jizan', 'jazan',
                'aseer', 'asir',
                'najran', 'al baha', 'tabuk', 'hail',
                'northern borders'
            )                                                           then 'Saudi Arabia'
            else loc_token2
        end as location_country
    from location_split
)

-- ── Final SELECT ──────────────────────────────────────────────────────────
select
    raw_id,
    run_id,
    source_name,
    source_job_id,
    source_url,
    collected_at,

    -- Cleaned fields
    title,
    title_raw,
    company_name,
    company_raw                                         as company_name_raw,
    location_city,
    location_country,
    location_raw,
    description,
    try_to_date(posting_date_raw)                       as posting_date,  -- NULL for Careerjet; real date for Tanqeeb + Jooble
    api_date_raw,
    salary_raw,
    saudi_national_only,
    title_raw                                           as career_level_raw,  -- Careerjet has no career-level field; Python uses title_raw as placeholder

    -- Fingerprint: SHA2(UPPER(title)|UPPER(company)|UPPER(city), 256)
    -- Matches Python: hashlib.sha256("|".join(components).encode()).hexdigest()
    -- where components = [(x or "NULL").upper().strip() for x in (title, company_name, location_city)]
    sha2(
        concat(
            coalesce(upper(trim(title)),        'NULL'), '|',
            coalesce(upper(trim(company_name)), 'NULL'), '|',
            coalesce(upper(trim(location_city)),'NULL')
        ),
        256
    )                                                   as job_fingerprint

from location_resolved
