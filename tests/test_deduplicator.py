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
    def test_same_url_within_run_is_duplicate(self, use_test_db):
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
    def test_url_seen_in_previous_run_is_duplicate(self, use_test_db):
        # Seed uses run-seed; new record uses run-test → different run → URL match is cross-run
        db_url = __import__("os").getenv("DB_URL")
        _insert_raw_job(db_url, "careerjet", None, "https://cj.com/existing")

        records = [_make_record(raw_id="r-new", url="https://cj.com/existing", fingerprint="fp-new")]
        result = deduplicate(records)
        assert result[0]["is_duplicate"] is True

    def test_same_run_url_not_a_cross_run_duplicate(self, use_test_db):
        # Both records share run_id="run-test"; first is unique, second is within-run dup
        records = [
            _make_record(raw_id="r1", url="https://cj.com/job/same", fingerprint="fp-a"),
            _make_record(raw_id="r2", url="https://cj.com/job/same", fingerprint="fp-b"),
        ]
        result = deduplicate(records)
        # r1 is NOT a cross-run dup; r2 is a within-run URL dup of r1
        assert result[0]["is_duplicate"] is False
        assert result[1]["is_duplicate"] is True
        assert result[1]["duplicate_of_job_id"] == "r1"

    def test_fingerprint_seen_in_previous_run_is_duplicate(self, use_test_db):
        # Simulate a fingerprint already recorded from a prior pipeline run
        db_url = __import__("os").getenv("DB_URL")
        db_path = db_url.removeprefix("sqlite:///")
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO processed_fingerprints VALUES (?,?,?,?)",
            ("fp-prior-run", "raw-prior-001", "careerjet", "2026-09-05T00:00:00"),
        )
        conn.commit()
        conn.close()

        records = [_make_record(raw_id="r-new", url="https://cj.com/new-url", fingerprint="fp-prior-run")]
        result = deduplicate(records)
        assert result[0]["is_duplicate"] is True
        assert result[0]["duplicate_of_job_id"] == "raw-prior-001"

    def test_new_fingerprint_recorded_after_dedup(self, use_test_db):
        # Non-duplicate records should be written to processed_fingerprints
        db_url = __import__("os").getenv("DB_URL")
        db_path = db_url.removeprefix("sqlite:///")
        records = [
            _make_record(raw_id="r1", url="https://cj.com/job/1", fingerprint="fp-alpha"),
            _make_record(raw_id="r2", url="https://cj.com/job/2", fingerprint="fp-beta"),
        ]
        deduplicate(records)
        import sqlite3
        conn = sqlite3.connect(db_path)
        stored = [r[0] for r in conn.execute("SELECT fingerprint FROM processed_fingerprints").fetchall()]
        conn.close()
        assert "fp-alpha" in stored
        assert "fp-beta" in stored

    def test_new_url_not_in_db_is_not_duplicate(self, use_test_db):
        records = [_make_record(raw_id="r-new", url="https://cj.com/brand-new", fingerprint="fp-new")]
        result = deduplicate(records)
        assert result[0]["is_duplicate"] is False

    def test_rerun_on_same_batch_does_not_self_match(self, use_test_db):
        """Re-running dedup on a batch whose fingerprints are already in
        processed_fingerprints (recorded by a prior run of the same input)
        must NOT flag those records as cross-run duplicates of themselves."""
        db_url = __import__("os").getenv("DB_URL")
        db_path = db_url.removeprefix("sqlite:///")

        records = [
            _make_record(raw_id="r-alpha", url="https://cj.com/1", fingerprint="fp-alpha"),
            _make_record(raw_id="r-beta",  url="https://cj.com/2", fingerprint="fp-beta"),
        ]

        # Simulate a prior pipeline run that stored these exact fingerprints
        # with the same raw_ids (re-running on the same raw input batch).
        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO processed_fingerprints VALUES (?,?,?,?)",
                     ("fp-alpha", "r-alpha", "careerjet", "2026-09-05T00:00:00"))
        conn.execute("INSERT INTO processed_fingerprints VALUES (?,?,?,?)",
                     ("fp-beta", "r-beta", "careerjet", "2026-09-05T00:00:00"))
        conn.commit()
        conn.close()

        result = deduplicate(records)
        assert result[0]["is_duplicate"] is False, "r-alpha should not be a duplicate of itself"
        assert result[1]["is_duplicate"] is False, "r-beta should not be a duplicate of itself"
