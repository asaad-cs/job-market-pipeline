"""
Integration test: run the full pipeline against a small fixture of sample records.
Verifies schema populated correctly, quality flags set, no silent drops.

Live API calls and Snowflake loading are skipped — fixtures stand in for those stages.
"""

import json
import pytest

from pipeline.processing.cleaner import clean_records
from pipeline.processing.standardizer import standardize_records
from pipeline.processing.deduplicator import deduplicate
from pipeline.quality.validator import validate, flush_quality_log


FIXTURES = [
    {   # Clean record
        "raw_id": "int-r1", "run_id": "int-run-1", "source_name": "careerjet",
        "source_job_id": None, "source_url": "https://cj.com/job/1",
        "raw_payload": json.dumps({
            "title": "Data Engineer", "company": "Saudi Aramco",
            "locations": "Dhahran, Saudi Arabia", "date": "2026-08-15",
            "description": "Join our data team.", "url": "https://cj.com/job/1",
        }),
        "collected_at": "2026-09-05T00:00:00+00:00",
    },
    {   # Record with SAUDI NATIONAL flag
        "raw_id": "int-r2", "run_id": "int-run-1", "source_name": "careerjet",
        "source_job_id": None, "source_url": "https://cj.com/job/2",
        "raw_payload": json.dumps({
            "title": "Project Manager (SAUDI NATIONAL)", "company": "ADDAR GROUP",
            "locations": "Riyadh, Saudi Arabia", "date": "2026-08-10",
            "description": "PM role.", "url": "https://cj.com/job/2",
        }),
        "collected_at": "2026-09-05T00:00:00+00:00",
    },
    {   # Duplicate of record 1 (same URL)
        "raw_id": "int-r3", "run_id": "int-run-1", "source_name": "careerjet",
        "source_job_id": None, "source_url": "https://cj.com/job/1",
        "raw_payload": json.dumps({
            "title": "Data Engineer", "company": "Saudi Aramco",
            "locations": "Dhahran, Saudi Arabia", "date": "2026-08-15",
            "description": "Join our data team.", "url": "https://cj.com/job/1",
        }),
        "collected_at": "2026-09-05T00:00:00+00:00",
    },
    {   # Record with missing title — will be rejected
        "raw_id": "int-r4", "run_id": "int-run-1", "source_name": "careerjet",
        "source_job_id": None, "source_url": "https://cj.com/job/4",
        "raw_payload": json.dumps({
            "title": None, "company": "Unknown Co",
            "locations": "Riyadh, Saudi Arabia", "date": "2026-08-01",
            "description": "No title.", "url": "https://cj.com/job/4",
        }),
        "collected_at": "2026-09-05T00:00:00+00:00",
    },
]


def test_full_pipeline_stages():
    cleaned = clean_records(FIXTURES)
    assert len(cleaned) == 4

    standardized = standardize_records(cleaned)
    assert len(standardized) == 4
    for rec in standardized:
        assert "quality_flags" in rec
        assert isinstance(rec["quality_flags"], list)

    deduped = deduplicate(standardized)
    assert len(deduped) == 4
    dup = next(r for r in deduped if r["raw_id"] == "int-r3")
    assert dup["is_duplicate"] is True
    assert dup["duplicate_of_job_id"] == "int-r1"

    validated = validate(deduped)
    rejected = [r for r in validated if r["is_rejected"]]
    assert len(rejected) == 1
    assert rejected[0]["raw_id"] == "int-r4"

    quality_log = flush_quality_log()
    assert len(quality_log) > 0
    assert all(e["rule_name"] for e in quality_log)


def test_no_silent_drops():
    cleaned = clean_records(FIXTURES)
    standardized = standardize_records(cleaned)
    deduped = deduplicate(standardized)
    validated = validate(deduped)

    # All input records must appear in output (never dropped)
    assert len(validated) == len(FIXTURES)


def test_saudi_national_flag():
    cleaned = clean_records(FIXTURES)
    pm_record = next(r for r in cleaned if "int-r2" == r["raw_id"])
    assert pm_record["saudi_national_only"] is True
    assert "SAUDI NATIONAL" not in pm_record["title"]


def test_fingerprints_generated():
    cleaned = clean_records(FIXTURES)
    for rec in cleaned:
        assert rec["job_fingerprint"] is not None
        assert len(rec["job_fingerprint"]) == 64
