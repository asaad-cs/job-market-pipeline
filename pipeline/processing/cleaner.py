"""
Field-level cleaning functions and job_fingerprint generation.

Fingerprint is generated AFTER cleaning (not on raw data) so normalization
produces stable hashes across separate collection runs.

Fingerprint formula:
    SHA-256(normalized_title | normalized_company | location_city | posting_date)
    "NULL" is used as the literal string when a field is unavailable.
"""

import hashlib
import json
import re


# -- Title cleaning -----------------------------------------------------------

_SAUDI_NATIONAL_RE = re.compile(
    r"\s*\(?\s*SAUDI\s*NATIONAL[S]?\s*ONLY\s*\)?"
    r"|\s*\(?\s*SAUDI\s*NATIONAL[S]?\s*\)?"
    r"|\s*\(?\s*Saudi\s*Only\s*\)?"
    r"|\s*\(?\s*Saudis?\s*Only\s*\)?",
    re.IGNORECASE,
)

_SAUDI_ARABIC_FLAG_RE = re.compile(r"متاح\s*للسعوديين", re.UNICODE)


def clean_title(raw: str | None) -> tuple[str | None, bool]:
    """
    Returns (cleaned_title, saudi_national_only_flag).
    Strips SAUDI NATIONAL qualifiers and normalises whitespace.
    """
    if not raw:
        return None, False

    saudi_only = bool(_SAUDI_NATIONAL_RE.search(raw) or _SAUDI_ARABIC_FLAG_RE.search(raw))
    cleaned = _SAUDI_NATIONAL_RE.sub("", raw)
    cleaned = _SAUDI_ARABIC_FLAG_RE.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned or None, saudi_only


# -- Company name cleaning ----------------------------------------------------

_LEGAL_SUFFIXES_RE = re.compile(
    r"\s*,?\s*\b(Ltd\.?|LLC\.?|L\.L\.C\.?|Co\.?|Corp\.?|Inc\.?|PLC\.?|GmbH|S\.A\.)\s*$",
    re.IGNORECASE,
)

_ABBREVIATIONS = {
    r"\bIntl\b\.?": "International",
    r"\bMgmt\b\.?": "Management",
    r"\bGrp\b\.?": "Group",
}


def clean_company_name(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = _LEGAL_SUFFIXES_RE.sub("", raw).strip()
    for pattern, replacement in _ABBREVIATIONS.items():
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    return cleaned.title() or None


# -- Location parsing ---------------------------------------------------------

_CITY_ALIASES: dict[str, str] = {
    "ar riyadh": "Riyadh",
    "الرياض": "Riyadh",
    "jedda": "Jeddah",
    "jiddah": "Jeddah",
    "jiddah": "Jeddah",
    "جدة": "Jeddah",
    "dammam": "Dammam",
    "الدمام": "Dammam",
    "al khobar": "Al Khobar",
    "الخبر": "Al Khobar",
    "makkah": "Mecca",
    "mecca": "Mecca",
    "مكة": "Mecca",
    "madinah": "Medina",
    "medina": "Medina",
    "المدينة": "Medina",
}

_COUNTRY_ALIASES: set[str] = {"saudi arabia", "ksa", "المملكة العربية السعودية"}


def parse_location(raw: str | None) -> tuple[str | None, str | None]:
    """
    Returns (location_city, location_country).
    Input format: "City, Country" or "City" or "Country" alone.
    """
    if not raw:
        return None, None

    parts = [p.strip() for p in raw.split(",", 1)]
    city_raw = parts[0] if parts else None
    country_raw = parts[1] if len(parts) > 1 else None

    city = _CITY_ALIASES.get(city_raw.lower(), city_raw.title()) if city_raw else None
    country = "Saudi Arabia" if (country_raw and country_raw.strip().lower() in _COUNTRY_ALIASES) else country_raw

    return city, country


# -- Fingerprint generation ---------------------------------------------------

def generate_fingerprint(
    title: str | None,
    company: str | None,
    city: str | None,
    posting_date: str | None,
) -> str:
    """
    Compute SHA-256 fingerprint from normalized fields.
    Used as surrogate dedup key for sources without a native job ID (e.g. Careerjet).
    """
    components = [
        (title or "NULL").upper().strip(),
        (company or "NULL").upper().strip(),
        (city or "NULL").upper().strip(),
        (posting_date or "NULL"),
    ]
    raw_string = "|".join(components)
    return hashlib.sha256(raw_string.encode("utf-8")).hexdigest()


# -- Main batch entry point ---------------------------------------------------

def clean_records(raw_records: list[dict]) -> list[dict]:
    """
    Apply field-level cleaning to a list of raw record dicts.
    Parses raw_payload JSON and populates cleaned fields alongside _raw originals.

    Returns a list of partially-structured dicts ready for standardizer.py.
    """
    cleaned = []
    for rec in raw_records:
        payload = json.loads(rec["raw_payload"])

        title_raw = payload.get("title") or payload.get("Title")
        company_raw = payload.get("company") or payload.get("Company")
        location_raw = payload.get("locations") or payload.get("location") or payload.get("Location")
        date_raw = payload.get("date") or payload.get("Date")
        description_raw = payload.get("description") or payload.get("Description")
        url = rec.get("source_url") or payload.get("url")

        title, saudi_only = clean_title(title_raw)
        company = clean_company_name(company_raw)
        city, country = parse_location(location_raw)

        fingerprint = generate_fingerprint(title, company, city, date_raw)

        cleaned.append({
            **rec,
            "title": title,
            "title_raw": title_raw,
            "company_name": company,
            "company_name_raw": company_raw,
            "location_city": city,
            "location_country": country,
            "location_raw": location_raw,
            "description": description_raw,
            "posting_date": date_raw,
            "source_url": url,
            "saudi_national_only": saudi_only,
            "job_fingerprint": fingerprint,
            # Fields standardizer.py will populate
            "career_level": None,
            "career_level_raw": None,
            "job_category": None,
            "job_category_raw": None,
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "salary_period": None,
            "salary_raw": None,
        })

    return cleaned
