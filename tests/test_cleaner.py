"""Unit tests for pipeline/processing/cleaner.py"""

import pytest
from pipeline.processing.cleaner import (
    clean_title,
    clean_company_name,
    parse_location,
    generate_fingerprint,
    clean_records,
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
    def test_title_case(self):
        assert clean_company_name("ADDAR GROUP") == "Addar Group"

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


class TestParseLocation:
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


class TestGenerateFingerprint:
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
        fp1 = generate_fingerprint("Engineer", "Co", "Riyadh", "2026-08-01")
        fp2 = generate_fingerprint("Engineer", "Co", "Riyadh", "2026-08-02")
        assert fp1 != fp2


class TestCleanRecords:
    def test_processes_careerjet_record(self, sample_raw_record):
        result = clean_records([sample_raw_record])
        assert len(result) == 1
        rec = result[0]
        assert rec["title"] == "Software Engineer"
        assert rec["saudi_national_only"] is True
        assert rec["company_name"] == "Addar Group"
        assert rec["location_city"] == "Riyadh"
        assert rec["location_country"] == "Saudi Arabia"
        assert rec["job_fingerprint"] is not None
        assert len(rec["job_fingerprint"]) == 64
