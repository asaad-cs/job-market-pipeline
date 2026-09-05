"""Unit tests for pipeline/processing/deduplicator.py"""

import sqlite3
import pathlib
import pytest

from pipeline.processing.deduplicator import deduplicate


def _insert_raw_job(db_url: str, source_name: str, source_job_id: str | None, source_url: str) -> None:
    db_path = db_url.removeprefix("sqlite:///")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO collection_runs VALUES (?,?,?,?,?,?)",
        ("run-seed", "2026-01-01T00:00:00", None, source_name, 1, None),
    )
    conn.execute(
        "INSERT INTO raw_jobs VALUES (?,?,?,?,?,?,?)",
        ("raw-seed-01", "run-seed", source_name, source_job_id, source_url,
         '{"title":"test"}', "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()


def _make_record(raw_id="r1", source_job_id=None, url="https://cj.com/1", fingerprint="fp1"):
    return {
        "raw_id": raw_id,
        "run_id": "run-test",
        "source_name": "careerjet",
        "source_job_id": source_job_id,
        "source_url": url,
        "job_fingerprint": fingerprint,
        "is_duplicate": False,
        "duplicate_of_job_id": None,
    }


class TestWithinRunDedup:
    def test_same_url_within_run_is_duplicate(self, use_test_db, monkeypatch):
        db_url = monkeypatch._env_changes.get("DB_URL") or __import__("os").getenv("DB_URL")
        records = [
            _make_record(raw_id="r1", url="https://cj.com/job/1", fingerprint="fp-a"),
            _make_record(raw_id="r2", url="https://cj.com/job/1", fingerprint="fp-b"),
        ]
        result = deduplicate(records)
        assert result[0]["is_duplicate"] is False
        assert result[1]["is_duplicate"] is True
        assert result[1]["duplicate_of_job_id"] == "r1"

    def test_same_fingerprint_within_run_is_duplicate(self, use_test_db):
        records = [
            _make_record(raw_id="r1", url="https://cj.com/job/1", fingerprint="fp-same"),
            _make_record(raw_id="r2", url="https://cj.com/job/2", fingerprint="fp-same"),
        ]
        result = deduplicate(records)
        assert result[1]["is_duplicate"] is True

    def test_different_urls_and_fingerprints_not_duplicates(self, use_test_db):
        records = [
            _make_record(raw_id="r1", url="https://cj.com/job/1", fingerprint="fp-1"),
            _make_record(raw_id="r2", url="https://cj.com/job/2", fingerprint="fp-2"),
        ]
        result = deduplicate(records)
        assert all(not r["is_duplicate"] for r in result)


class TestCrossRunDedup:
    def test_url_seen_in_db_is_duplicate(self, use_test_db, monkeypatch):
        db_url = __import__("os").getenv("DB_URL")
        _insert_raw_job(db_url, "careerjet", None, "https://cj.com/existing")

        records = [_make_record(raw_id="r-new", url="https://cj.com/existing", fingerprint="fp-new")]
        result = deduplicate(records)
        assert result[0]["is_duplicate"] is True

    def test_new_url_not_in_db_is_not_duplicate(self, use_test_db):
        records = [_make_record(raw_id="r-new", url="https://cj.com/brand-new", fingerprint="fp-new")]
        result = deduplicate(records)
        assert result[0]["is_duplicate"] is False
