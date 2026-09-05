"""
Creates OLTP tables from schema.sql.
Run once before first pipeline execution.

Usage:
    python db/init_db.py
"""

import os
import pathlib
import sqlite3
import sys

from dotenv import load_dotenv

load_dotenv()

SCHEMA_FILE = pathlib.Path(__file__).parent / "schema.sql"


def _get_db_url() -> str:
    url = os.getenv("DB_URL")
    if not url:
        raise RuntimeError("DB_URL is not set. Copy .env.example to .env and configure it.")
    return url


def _init_sqlite(path: str) -> None:
    db_path = path.removeprefix("sqlite:///")
    pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA_FILE.read_text())
    conn.commit()
    conn.close()
    print(f"SQLite database initialised at {db_path}")


def _init_postgres(url: str) -> None:
    try:
        import psycopg2
    except ImportError:
        print("psycopg2-binary is not installed. Run: pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute(SCHEMA_FILE.read_text())
    conn.commit()
    cur.close()
    conn.close()
    print(f"PostgreSQL database initialised at {url.split('@')[-1]}")


def init_db() -> None:
    url = _get_db_url()
    if url.startswith("sqlite:///"):
        _init_sqlite(url)
    elif url.startswith(("postgresql://", "postgres://")):
        _init_postgres(url)
    else:
        raise ValueError(f"Unsupported DB_URL scheme: {url!r}. Expected sqlite:/// or postgresql://")


if __name__ == "__main__":
    init_db()
