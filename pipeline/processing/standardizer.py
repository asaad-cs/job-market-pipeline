"""
Standardization: career level mapping, salary parsing, location country validation.
Runs after cleaner.py; populates career_level, salary_*, and out_of_region flag.
"""

import re


# -- Career level mapping -----------------------------------------------------

_CAREER_LEVEL_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"entry\s*level|fresh\s*grad|junior", re.I), "Entry"),
    (re.compile(r"intermediate|mid[\s\-]level|mid$", re.I), "Mid"),
    (re.compile(r"\bsenior\b", re.I), "Senior"),
    (re.compile(r"\bmanager\b|management", re.I), "Manager"),
    (re.compile(r"executive|director|c[\s\-]?level|vp\b|vice\s*president", re.I), "Executive"),
]


def normalize_career_level(raw: str | None) -> str:
    if not raw:
        return "Unspecified"
    for pattern, level in _CAREER_LEVEL_MAP:
        if pattern.search(raw):
            return level
    return "Unspecified"


# -- Salary parsing -----------------------------------------------------------

_SALARY_RE = re.compile(
    r"(?P<currency>[A-Z]{2,3})?\s*"
    r"(?P<min>[\d,]+)"
    r"(?:\s*[-–]\s*(?P<max>[\d,]+))?"
    r"(?:\s*/\s*(?P<period>month|year|annual|hour))?",
    re.IGNORECASE,
)

_PERIOD_MAP = {"month": "monthly", "year": "annual", "annual": "annual", "hour": "hourly"}
_NULL_SALARY_TERMS = {"negotiable", "undisclosed", "competitive", "tbd", "n/a", "na"}


def parse_salary(raw: str | None) -> dict:
    """Returns dict with keys: salary_min, salary_max, salary_currency, salary_period."""
    empty = {"salary_min": None, "salary_max": None, "salary_currency": None, "salary_period": None}
    if not raw:
        return empty
    if raw.strip().lower() in _NULL_SALARY_TERMS:
        return empty

    m = _SALARY_RE.search(raw)
    if not m:
        return empty

    def to_num(s: str | None) -> float | None:
        return float(s.replace(",", "")) if s else None

    return {
        "salary_min": to_num(m.group("min")),
        "salary_max": to_num(m.group("max")),
        "salary_currency": m.group("currency") or "SAR",
        "salary_period": _PERIOD_MAP.get((m.group("period") or "").lower(), "unspecified"),
    }


# -- Main batch entry point ---------------------------------------------------

_KSA_COUNTRIES = {"saudi arabia", "ksa"}


def standardize_records(cleaned_records: list[dict]) -> list[dict]:
    """
    Apply career level mapping and salary parsing to cleaned records.
    Adds quality_flags list (populated further by validator.py).
    """
    standardized = []
    for rec in cleaned_records:
        career_raw = rec.get("career_level_raw")
        career = normalize_career_level(career_raw)

        salary_parsed = parse_salary(rec.get("salary_raw"))

        out_of_region = (
            rec.get("location_country", "").lower() not in _KSA_COUNTRIES
            if rec.get("location_country")
            else False
        )

        standardized.append({
            **rec,
            "career_level": career,
            **salary_parsed,
            "out_of_region": out_of_region,
            "quality_flags": [],
            "is_duplicate": False,
            "duplicate_of_job_id": None,
            "is_rejected": False,
            "rejection_reason": None,
        })

    return standardized
