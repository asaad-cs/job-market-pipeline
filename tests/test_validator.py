"""Unit tests for pipeline/quality/validator.py"""

import pytest
from pipeline.quality.validator import validate


def _base_record(**overrides):
    rec = {
        "raw_id": "r1",
        "source_name": "careerjet",
        "source_job_id": None,
        "source_url": "https://cj.com/job/1",
        "job_fingerprint": "abc123",
        "title": "Software Engineer",
        "title_raw": "Software Engineer",
        "company_name": "Acme",
        "location_raw": "Riyadh, Saudi Arabia",
        "location_country": "Saudi Arabia",
        "career_level": "Mid",
        "salary_min": None,
        "salary_max": None,
        "posting_date": "2026-08-01",
        "collected_at": "2026-09-05T00:00:00+00:00",
        "quality_flags": [],
        "is_rejected": False,
        "rejection_reason": None,
        "is_duplicate": False,
    }
    rec.update(overrides)
    return rec


class TestRequiredFields:
    def test_null_title_rejects(self):
        rec = _base_record(title=None)
        [result] = validate([rec])
        assert result["is_rejected"] is True
        assert "REQ-001" in result["rejection_reason"]

    def test_no_id_and_no_fingerprint_rejects(self):
        rec = _base_record(source_job_id=None, job_fingerprint=None)
        [result] = validate([rec])
        assert result["is_rejected"] is True
        assert "REQ-002" in result["rejection_reason"]

    def test_null_source_url_rejects(self):
        rec = _base_record(source_url=None)
        [result] = validate([rec])
        assert result["is_rejected"] is True
        assert "REQ-003" in result["rejection_reason"]

    def test_valid_record_not_rejected(self):
        [result] = validate([_base_record()])
        assert result["is_rejected"] is False


class TestWarningFlags:
    def test_null_company_warns(self):
        rec = _base_record(company_name=None)
        [result] = validate([rec])
        rules = [f["rule"] for f in result["quality_flags"]]
        assert "WARN-001" in rules

    def test_null_location_raw_warns(self):
        rec = _base_record(location_raw=None)
        [result] = validate([rec])
        rules = [f["rule"] for f in result["quality_flags"]]
        assert "WARN-002" in rules

    def test_unspecified_career_level_flags_info(self):
        rec = _base_record(career_level="Unspecified")
        [result] = validate([rec])
        rules = [f["rule"] for f in result["quality_flags"]]
        assert "WARN-003" in rules


class TestErrorFlags:
    def test_inverted_salary_rejects(self):
        rec = _base_record(salary_min=10000, salary_max=5000)
        [result] = validate([rec])
        assert result["is_rejected"] is True
        assert "ERR-002" in result["rejection_reason"]

    def test_title_too_long_rejects(self):
        rec = _base_record(title="A" * 301)
        [result] = validate([rec])
        assert result["is_rejected"] is True
        assert "ERR-003" in result["rejection_reason"]

    def test_out_of_region_flags_warning(self):
        rec = _base_record(location_country="Egypt")
        [result] = validate([rec])
        rules = [f["rule"] for f in result["quality_flags"]]
        assert "ERR-004" in rules

    def test_stale_posting_flags_warning(self):
        rec = _base_record(posting_date="2025-12-01", collected_at="2026-09-05T00:00:00+00:00")
        [result] = validate([rec])
        rules = [f["rule"] for f in result["quality_flags"]]
        assert "STALE-001" in rules

    def test_future_posting_date_flags_error(self):
        rec = _base_record(posting_date="2027-01-01", collected_at="2026-09-05T00:00:00+00:00")
        [result] = validate([rec])
        rules = [f["rule"] for f in result["quality_flags"]]
        assert "ERR-001" in rules


class TestLowConfidenceFingerprint:
    def test_null_company_and_city_flags_warn005(self):
        # 2 of 3 fingerprint components null → LOW-CONFIDENCE-FINGERPRINT
        rec = _base_record(company_name=None, location_city=None)
        [result] = validate([rec])
        rules = [f["rule"] for f in result["quality_flags"]]
        assert "WARN-005" in rules
        assert result["is_rejected"] is False  # flagged, not rejected

    def test_only_one_null_component_does_not_flag_warn005(self):
        # 1 of 3 null (company only) → still 2 components present → no flag
        rec = _base_record(company_name=None, location_city="Riyadh")
        [result] = validate([rec])
        rules = [f["rule"] for f in result["quality_flags"]]
        assert "WARN-005" not in rules
