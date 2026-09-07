"""Unit tests for pipeline/processing/standardizer.py"""

import pytest
from pipeline.processing.standardizer import parse_salary, normalize_career_level


class TestParseSalary:
    # --- Formats observed in the 495-record Phase 2 dataset ---

    def test_range_per_month_no_currency(self):
        r = parse_salary("10000 - 16000 per month")
        assert r["salary_min"] == 10000.0
        assert r["salary_max"] == 16000.0
        assert r["salary_currency"] == "SAR"   # default for Saudi market
        assert r["salary_period"] == "monthly"

    def test_single_value_per_year(self):
        r = parse_salary("95000 per year")
        assert r["salary_min"] == 95000.0
        assert r["salary_max"] is None
        assert r["salary_currency"] == "SAR"
        assert r["salary_period"] == "annual"

    def test_usd_dollar_sign_per_month(self):
        r = parse_salary("$4000 per month")
        assert r["salary_min"] == 4000.0
        assert r["salary_currency"] == "USD"
        assert r["salary_period"] == "monthly"

    def test_usd_dollar_sign_per_year(self):
        r = parse_salary("$15000 per year")
        assert r["salary_currency"] == "USD"
        assert r["salary_period"] == "annual"

    def test_large_annual_range(self):
        r = parse_salary("144000 - 180000 per year")
        assert r["salary_min"] == 144000.0
        assert r["salary_max"] == 180000.0
        assert r["salary_period"] == "annual"

    def test_tight_range(self):
        r = parse_salary("4500 - 4700 per month")
        assert r["salary_min"] == 4500.0
        assert r["salary_max"] == 4700.0

    # --- Null / edge cases ---

    def test_null_input(self):
        r = parse_salary(None)
        assert all(v is None for v in r.values())

    def test_empty_string(self):
        r = parse_salary("")
        assert all(v is None for v in r.values())

    def test_negotiable_returns_null(self):
        r = parse_salary("Negotiable")
        assert r["salary_min"] is None

    def test_undisclosed_returns_null(self):
        r = parse_salary("Undisclosed")
        assert r["salary_min"] is None

    def test_legacy_slash_format(self):
        # Keep backward-compatible with "SAR 5,000 / month" style (other future sources)
        r = parse_salary("SAR 5000 / month")
        assert r["salary_min"] == 5000.0
        assert r["salary_currency"] == "SAR"
        assert r["salary_period"] == "monthly"

    def test_no_period_gives_unspecified(self):
        r = parse_salary("8000")
        assert r["salary_min"] == 8000.0
        assert r["salary_period"] == "unspecified"


class TestNormalizeCareerLevel:
    # --- Patterns confirmed in the 495-record Phase 2 dataset ---

    def test_senior(self):
        assert normalize_career_level("Senior Software Engineer") == "Senior"

    def test_sr_abbreviation(self):
        assert normalize_career_level("Sr. Data Analyst") == "Senior"

    def test_lead(self):
        assert normalize_career_level("Lead DevOps Engineer") == "Senior"

    def test_manager(self):
        assert normalize_career_level("Project Manager") == "Manager"

    def test_head_of(self):
        assert normalize_career_level("Head of Engineering") == "Manager"

    def test_director(self):
        assert normalize_career_level("Director of Finance") == "Executive"

    def test_executive(self):
        assert normalize_career_level("Chief Executive Officer") == "Executive"

    def test_junior(self):
        assert normalize_career_level("Junior Developer") == "Entry"

    def test_intern(self):
        assert normalize_career_level("Marketing Intern") == "Entry"

    def test_trainee(self):
        assert normalize_career_level("Co-op Trainee (Computer Engineering)") == "Entry"

    def test_fresh_graduate(self):
        assert normalize_career_level("Fresh Graduate - Accounting") == "Entry"

    def test_mid_level(self):
        assert normalize_career_level("Mid-Level Java Developer") == "Mid"

    def test_unrecognized_maps_to_unspecified(self):
        assert normalize_career_level("Cashier") == "Unspecified"

    def test_null_maps_to_unspecified(self):
        assert normalize_career_level(None) == "Unspecified"

    def test_empty_maps_to_unspecified(self):
        assert normalize_career_level("") == "Unspecified"

    def test_executive_beats_manager_by_order(self):
        # "Executive Director" should match Executive (listed after Manager in map)
        # Verify order: Executive pattern is checked after Manager, but since patterns
        # are checked in order, "Executive" title will match "executive" first if listed first.
        # Current order: Entry, Mid, Senior, Manager, Executive
        # "Executive Director" → Manager matches first (contains "director"? No — no "manager")
        # → Executive matches "executive"
        result = normalize_career_level("Executive Director")
        assert result == "Executive"
