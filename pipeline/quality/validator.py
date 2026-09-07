"""
Data quality rules engine.
All rules follow: Condition → Action → Reason.
Records are never silently dropped — every rejection is logged to quality_log.

Rule IDs from the plan (§11):
  REQ-001  title null/empty → Reject
  REQ-002  no source_job_id AND no job_fingerprint → Reject
  REQ-003  source_url null → Reject
  REQ-004  collected_at null → Reject
  WARN-001 company_name null → Flag (warning)
  WARN-002 location_raw null → Flag (warning)
  WARN-003 career_level = Unspecified → Flag (info)
  WARN-004 posting_date null → Flag (info)
  ERR-001  posting_date > collected_at → Flag (error)
  ERR-002  salary_min > salary_max → Quarantine
  ERR-003  title length > 300 → Quarantine
  ERR-004  location_country ≠ Saudi Arabia → Flag (warning)
  DUP-001  duplicate detected → Mark is_duplicate=True (handled in deduplicator.py)
  STALE-001 posting_date > 180 days before collected_at → Flag (warning)
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

_QUALITY_LOG: list[dict] = []   # in-memory buffer; flushed to DB by the caller


def _flag(rec: dict, rule: str, severity: str, message: str) -> None:
    rec["quality_flags"].append({"rule": rule, "severity": severity, "message": message})


def _reject(rec: dict, rule: str, message: str) -> None:
    rec["is_rejected"] = True
    rec["rejection_reason"] = f"{rule}: {message}"
    _flag(rec, rule, "error", message)
    _QUALITY_LOG.append({
        "log_id": str(uuid.uuid4()),
        "job_id": rec.get("raw_id"),
        "rule_name": rule,
        "severity": "error",
        "message": message,
        "logged_at": datetime.now(timezone.utc).isoformat(),
    })


def _warn(rec: dict, rule: str, severity: str, message: str) -> None:
    _flag(rec, rule, severity, message)
    _QUALITY_LOG.append({
        "log_id": str(uuid.uuid4()),
        "job_id": rec.get("raw_id"),
        "rule_name": rule,
        "severity": severity,
        "message": message,
        "logged_at": datetime.now(timezone.utc).isoformat(),
    })


def _parse_date(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    # Fallback for bare date strings
    try:
        return datetime.strptime(val[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def validate(records: list[dict]) -> list[dict]:
    """Apply all quality rules to each record. Returns the same list with flags populated."""
    _QUALITY_LOG.clear()

    for rec in records:
        collected_str = rec.get("collected_at", "")
        collected_at = _parse_date(collected_str)
        posting_date = _parse_date(rec.get("posting_date"))

        # REQ-001
        if not rec.get("title"):
            _reject(rec, "REQ-001", "title is null or empty")
            continue  # remaining rules not meaningful without a title

        # REQ-002
        if not rec.get("source_job_id") and not rec.get("job_fingerprint"):
            _reject(rec, "REQ-002", "no source_job_id and no job_fingerprint — cannot deduplicate")
            continue

        # REQ-003
        if not rec.get("source_url"):
            _reject(rec, "REQ-003", "source_url is null")

        # REQ-004
        if not collected_str:
            _reject(rec, "REQ-004", "collected_at is null")

        # ERR-003 (check before WARN flags to catch artifacts early)
        if len(rec.get("title", "")) > 300:
            _reject(rec, "ERR-003", f"title length {len(rec['title'])} exceeds 300 chars — likely scraping artifact")
            continue

        # ERR-002
        s_min, s_max = rec.get("salary_min"), rec.get("salary_max")
        if s_min is not None and s_max is not None and s_min > s_max:
            _reject(rec, "ERR-002", f"salary_min ({s_min}) > salary_max ({s_max}) — inverted range")

        # WARN-001
        if not rec.get("company_name"):
            _warn(rec, "WARN-001", "warning", "company_name is null")

        # WARN-002
        if not rec.get("location_raw"):
            _warn(rec, "WARN-002", "warning", "location_raw is null")

        # WARN-003
        if rec.get("career_level") == "Unspecified":
            _warn(rec, "WARN-003", "info", "career_level could not be mapped")

        # WARN-004
        if not rec.get("posting_date"):
            _warn(rec, "WARN-004", "info", "posting_date is null")

        # ERR-001
        if posting_date and collected_at and posting_date > collected_at:
            _warn(rec, "ERR-001", "error", f"posting_date {rec['posting_date']} is in the future")

        # ERR-004
        country = (rec.get("location_country") or "").lower()
        if country and country not in {"saudi arabia", "ksa"}:
            _warn(rec, "ERR-004", "warning", f"location_country '{rec['location_country']}' is not Saudi Arabia")

        # STALE-001
        if posting_date and collected_at and (collected_at - posting_date) > timedelta(days=180):
            _warn(rec, "STALE-001", "warning",
                  f"posting_date {rec['posting_date']} is more than 180 days before collection")

    rejected = sum(1 for r in records if r.get("is_rejected"))
    flagged = sum(1 for r in records if r.get("quality_flags"))
    log.info("Validation: %d records — %d rejected, %d flagged", len(records), rejected, flagged)

    return records


def flush_quality_log() -> list[dict]:
    """Return accumulated quality log entries and clear the buffer."""
    entries = list(_QUALITY_LOG)
    _QUALITY_LOG.clear()
    return entries
