"""
Standardization: career level mapping, salary parsing, location country validation.
Runs after cleaner.py; populates career_level, salary_*, and out_of_region flag.
"""

import re


# -- Career level mapping -----------------------------------------------------
# Patterns are tested in order; first match wins.
# Sources like Careerjet have no dedicated career-level field — inferred from title.

_CAREER_LEVEL_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"entry\s*level|fresh\s*grad|junior|\bintern\b|\btrainee\b", re.I), "Entry"),
    (re.compile(r"intermediate|mid[\s\-]level|mid$", re.I), "Mid"),
    (re.compile(r"\bsenior\b|\bsr\.?\b|\blead\b", re.I), "Senior"),
    (re.compile(r"\bmanager\b|management|\bhead\s+of\b", re.I), "Manager"),
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
# Observed Careerjet formats (Phase 2 profiling, 23 non-null values):
#   "10000 - 16000 per month"   — range, no currency, "per month"
#   "95000 per year"            — single value, annual
#   "$4000 per month"           — USD dollar sign
#   "144000 - 180000 per year"  — large annual range
# No thousands-separator commas; space-dash-space range separator.
# Currency defaults to SAR when absent (Saudi market assumption).

_SALARY_RE = re.compile(
    r"(?P<symbol>[$£€])?"                               # optional currency symbol
    r"(?P<currency_code>[A-Z]{2,3})?\s*"                # optional ISO code (SAR, USD…)
    r"(?P<min>[\d,]+)"
    r"(?:\s*[-–]\s*(?P<max>[\d,]+))?"                  # optional range max
    r"(?:"
        r"\s+per\s+(?P<period_per>month|year|hour)"     # "per month" / "per year"
        r"|\s*/\s*(?P<period_slash>month|year|annual|hour)"  # "/ month" legacy format
    r")?",
    re.IGNORECASE,
)

_SYMBOL_TO_CURRENCY = {"$": "USD", "£": "GBP", "€": "EUR"}
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

    symbol = m.group("symbol") or ""
    currency_code = m.group("currency_code") or ""
    currency = _SYMBOL_TO_CURRENCY.get(symbol) or currency_code.upper() or "SAR"

    period_raw = m.group("period_per") or m.group("period_slash") or ""
    period = _PERIOD_MAP.get(period_raw.lower(), "unspecified")

    return {
        "salary_min": to_num(m.group("min")),
        "salary_max": to_num(m.group("max")),
        "salary_currency": currency,
        "salary_period": period,
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
