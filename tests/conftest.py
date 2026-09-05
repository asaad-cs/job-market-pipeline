"""
Shared test fixtures.
Uses a temporary SQLite database so tests never touch the dev DB.
"""

import os
import sqlite3
import pathlib
import pytest


@pytest.fixture(autouse=True)
def use_test_db(tmp_path, monkeypatch):
    """Point DB_URL at a fresh temp SQLite DB for every test."""
    db_path = tmp_path / "test_pipeline.db"
    monkeypatch.setenv("DB_URL", f"sqlite:///{db_path}")

    schema_sql = pathlib.Path(__file__).parent.parent / "db" / "schema.sql"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(schema_sql.read_text())
    conn.commit()
    conn.close()

    yield


@pytest.fixture
def sample_raw_record():
    """A minimal raw record dict as returned by a collector."""
    return {
        "raw_id": "test-raw-id-001",
        "run_id": "test-run-id-001",
        "source_name": "careerjet",
        "source_job_id": None,
        "source_url": "https://www.careerjet.com/jobad/sa12345",
        "raw_payload": '{"title": "Software Engineer (SAUDI NATIONAL)", "company": "ADDAR GROUP", '
                       '"locations": "Riyadh, Saudi Arabia", "description": "We are hiring a software engineer.", '
                       '"date": "2026-08-01", "url": "https://www.careerjet.com/jobad/sa12345"}',
        "collected_at": "2026-09-05T00:00:00+00:00",
    }
