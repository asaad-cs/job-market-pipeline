"""Unit tests for pipeline/processing/cleaner.py"""

import pytest
from pipeline.processing.cleaner import (
    clean_title,
    clean_company_name,
    parse_location,
    generate_fingerprint,
    clean_records,
    SOURCES_WITHOUT_RELIABLE_DATE,
)


class TestCleanTitle:
    def test_strips_saudi_national_at_end(self):
        title, flag = clean_title("Project Manager (SAUDI NATIONAL)")
        assert title == "Project Manager"
        assert flag is True

    def test_strips_saudi_national_at_start(self):
        title, flag = clean_title("(SAUDI NATIONAL) Project Manager")
        assert "SAUDI NATIONAL" not in title
        assert flag is True

    def test_no_flag_when_absent(self):
        title, flag = clean_title("Software Engineer")
        assert title == "Software Engineer"
        assert flag is False

    def test_arabic_flag(self):
        title, flag = clean_title("مهندس برمجيات متاح للسعوديين")
        assert flag is True
        assert "متاح للسعوديين" not in title

    def test_null_input(self):
        title, flag = clean_title(None)
        assert title is None
        assert flag is False

    def test_normalises_whitespace(self):
        title, _ = clean_title("Senior   Data  Engineer")
        assert title == "Senior Data Engineer"


class TestCleanCompanyName:
    def test_title_case_long_words(self):
        # Words longer than 5 chars are title-cased normally
        assert clean_company_name("INTERNATIONAL TRADING CORPORATION") == "International Trading Corporation"

    def test_preserves_short_allcaps_acronym(self):
        # 3-5 char all-caps alpha tokens are preserved as-is (heuristic)
        assert clean_company_name("AECOM") == "AECOM"
        assert clean_company_name("STC") == "STC"
        assert clean_company_name("KBR") == "KBR"
        assert clean_company_name("SGS") == "SGS"

    def test_acronym_in_compound_name(self):
        assert clean_company_name("STC Communications") == "STC Communications"

    def test_strips_llc(self):
        result = clean_company_name("Acme Solutions LLC")
        assert "LLC" not in result

    def test_strips_ltd(self):
        result = clean_company_name("Global Tech Ltd.")
        assert "Ltd" not in result

    def test_expands_intl(self):
        result = clean_company_name("ARAMCO INTL")
        assert "International" in result

    def test_null_returns_none(self):
        assert clean_company_name(None) is None

    def test_empty_string_returns_none(self):
        # Careerjet returns "" (not null) for missing company
        assert clean_company_name("") is None


class TestParseLocation:
    # --- Patterns that worked before ---
    def test_city_country(self):
        city, country = parse_location("Riyadh, Saudi Arabia")
        assert city == "Riyadh"
        assert country == "Saudi Arabia"

    def test_arabic_city(self):
        city, country = parse_location("الرياض, Saudi Arabia")
        assert city == "Riyadh"

    def test_jeddah_variant(self):
        city, _ = parse_location("Jedda, Saudi Arabia")
        assert city == "Jeddah"

    def test_ksa_alias(self):
        _, country = parse_location("Dammam, KSA")
        assert country == "Saudi Arabia"

    def test_city_only(self):
        city, country = parse_location("Riyadh")
        assert city == "Riyadh"
        assert country is None

    def test_null_returns_nones(self):
        city, country = parse_location(None)
        assert city is None
        assert country is None

    # --- Careerjet-specific patterns from Phase 1 test sample ---
    def test_country_only_string(self):
        # "Saudi Arabia" alone → no city, country identified
        city, country = parse_location("Saudi Arabia")
        assert city is None
        assert country == "Saudi Arabia"

    def test_city_saudi_region_second_token(self):
        # "City, Region" — region is NOT a country
        city, country = parse_location("Dammam, Ash Sharqiyah")
        assert city == "Dammam"
        assert country == "Saudi Arabia"

    def test_city_region_second_token_jubayl(self):
        city, country = parse_location("Al Jubayl, Ash Sharqiyah")
        assert city == "Al Jubayl"
        assert country == "Saudi Arabia"

    def test_multi_part_dash_format(self):
        # "City, Region - City2" → take first segment only
        city, country = parse_location("Al Khubar, Ash Sharqiyah - Riyadh")
        assert city == "Al Khobar"      # alias applied
        assert country == "Saudi Arabia"

    def test_city_alias_al_khubar(self):
        city, _ = parse_location("Al Khubar")
        assert city == "Al Khobar"

    # --- Patterns found in the full 495-record dataset (Phase 2 audit) ---
    def test_jeddah_makkah_region(self):
        # 58 records in production: "Makkah" is a region, not a country
        city, country = parse_location("Jeddah, Makkah")
        assert city == "Jeddah"
        assert country == "Saudi Arabia"

    def test_yanbu_al_madinah_region(self):
        city, country = parse_location("Yanbu' al Bahr, Al Madinah")
        assert country == "Saudi Arabia"

    def test_al_qurayyat_al_jawf_region(self):
        city, country = parse_location("Al Qurayyat, Al Jawf")
        assert city == "Al Qurayyat"
        assert country == "Saudi Arabia"

    def test_diriyah_riyadh_region(self):
        # "Riyadh" as second token is the region, not the city
        city, country = parse_location("Diriyah, Riyadh")
        assert city == "Diriyah"
        assert country == "Saudi Arabia"


class TestGenerateFingerprint:
    # --- 4-component (include_date=True, the default) ---
    def test_deterministic(self):
        fp1 = generate_fingerprint("Software Engineer", "Acme", "Riyadh", "2026-08-01")
        fp2 = generate_fingerprint("Software Engineer", "Acme", "Riyadh", "2026-08-01")
        assert fp1 == fp2

    def test_case_insensitive(self):
        fp1 = generate_fingerprint("software engineer", "acme", "riyadh", "2026-08-01")
        fp2 = generate_fingerprint("SOFTWARE ENGINEER", "ACME", "RIYADH", "2026-08-01")
        assert fp1 == fp2

    def test_null_fields_produce_valid_hash(self):
        fp = generate_fingerprint(None, None, None, None)
        assert len(fp) == 64  # SHA-256 hex

    def test_different_dates_differ(self):
        # Only meaningful when include_date=True (the default)
        fp1 = generate_fingerprint("Engineer", "Co", "Riyadh", "2026-08-01", include_date=True)
        fp2 = generate_fingerprint("Engineer", "Co", "Riyadh", "2026-08-02", include_date=True)
        assert fp1 != fp2

    # --- 3-component (include_date=False — Careerjet strategy) ---
    def test_include_date_false_ignores_date(self):
        # Different date values produce the same hash when include_date=False
        fp1 = generate_fingerprint("Engineer", "Co", "Riyadh", "2026-08-01", include_date=False)
        fp2 = generate_fingerprint("Engineer", "Co", "Riyadh", "2026-08-02", include_date=False)
        assert fp1 == fp2

    def test_include_date_false_stable_without_date(self):
        # Core Careerjet dedup guarantee: same job → same fingerprint across runs
        fp1 = generate_fingerprint("Cashier", "Shahini Group", "Riyadh", include_date=False)
        fp2 = generate_fingerprint("Cashier", "Shahini Group", "Riyadh", include_date=False)
        assert fp1 == fp2

    def test_include_date_false_differs_from_include_date_true(self):
        # The two strategies produce different hashes — they are not compatible
        fp_with = generate_fingerprint("Engineer", "Co", "Riyadh", None, include_date=True)
        fp_without = generate_fingerprint("Engineer", "Co", "Riyadh", None, include_date=False)
        assert fp_with != fp_without

    def test_careerjet_in_sources_without_reliable_date(self):
        assert "careerjet" in SOURCES_WITHOUT_RELIABLE_DATE


class TestCleanRecords:
    def test_processes_careerjet_record(self, sample_raw_record):
        result = clean_records([sample_raw_record])
        assert len(result) == 1
        rec = result[0]
        assert rec["title"] == "Software Engineer"
        assert rec["saudi_national_only"] is True
        assert rec["company_name"] == "Hilton Hotels"
        assert rec["location_city"] == "Riyadh"
        assert rec["location_country"] == "Saudi Arabia"
        assert rec["job_fingerprint"] is not None
        assert len(rec["job_fingerprint"]) == 64

    def test_careerjet_posting_date_is_null(self, sample_raw_record):
        # Careerjet `date` is a query timestamp; must not be stored as posting_date
        result = clean_records([sample_raw_record])
        assert result[0]["posting_date"] is None

    def test_careerjet_fingerprint_excludes_date(self, sample_raw_record):
        # Run the same record twice with different `date` values;
        # fingerprints must be identical (date excluded for Careerjet).
        import json
        rec1 = dict(sample_raw_record)
        rec2 = dict(sample_raw_record)
        payload1 = json.loads(rec1["raw_payload"])
        payload2 = json.loads(rec2["raw_payload"])
        payload1["date"] = "Mon, 01 Sep 2026 00:00:00 GMT"
        payload2["date"] = "Fri, 05 Sep 2026 12:00:00 GMT"
        rec1["raw_payload"] = json.dumps(payload1)
        rec2["raw_payload"] = json.dumps(payload2)

        fp1 = clean_records([rec1])[0]["job_fingerprint"]
        fp2 = clean_records([rec2])[0]["job_fingerprint"]
        assert fp1 == fp2

    def test_non_careerjet_fingerprint_includes_date(self):
        # A source with a real posting date gets a 4-component fingerprint
        import json
        rec = {
            "raw_id": "test-jadarat-001",
            "run_id": "run-001",
            "source_name": "jadarat",
            "source_job_id": None,
            "source_url": "https://jadarat.sa/job/1",
            "raw_payload": json.dumps({
                "title": "Data Analyst",
                "company": "SABIC",
                "location": "Jubail, Saudi Arabia",
                "date": "2026-08-01",
                "description": "Analyze data.",
                "url": "https://jadarat.sa/job/1",
            }),
            "collected_at": "2026-09-05T00:00:00+00:00",
        }
        # Same record, different date → different fingerprints
        import copy
        rec2 = copy.deepcopy(rec)
        payload2 = json.loads(rec2["raw_payload"])
        payload2["date"] = "2026-08-15"
        rec2["raw_payload"] = json.dumps(payload2)

        fp1 = clean_records([rec])[0]["job_fingerprint"]
        fp2 = clean_records([rec2])[0]["job_fingerprint"]
        assert fp1 != fp2


class TestCleanRecordsPipelineState:
    def test_initializes_quality_flags_and_status_fields(self, sample_raw_record):
        """clean_records must initialise the pipeline-state fields that later stages
        expect.  Without them, validator._flag() raises KeyError on quality_flags and
        the deduplicator silently propagates uninitialised is_duplicate values."""
        [result] = clean_records([sample_raw_record])
        assert result["quality_flags"] == []
        assert result["is_rejected"] is False
        assert result["is_duplicate"] is False
        assert result["duplicate_of_job_id"] is None
