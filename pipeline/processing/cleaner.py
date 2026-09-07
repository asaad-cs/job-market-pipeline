"""
Field-level cleaning functions and job_fingerprint generation.

Fingerprint is generated AFTER cleaning (not on raw data) so normalization
produces stable hashes across separate collection runs.

Per-source fingerprint strategy:
  - Sources WITH a reliable per-listing posting_date (e.g. Jadarat):
        SHA-256(title | company | city | posting_date)
  - Sources WITHOUT a reliable posting_date (Careerjet: `date` is the
    query timestamp, not the original posting date):
        SHA-256(title | company | city)
    Dropping the date makes the hash stable across runs but increases
    collision risk — see SOURCES_WITHOUT_RELIABLE_DATE for full rationale.
"""

import hashlib
import json
import re


# Sources whose `date` API field is a query timestamp rather than a per-listing
# posting date.  For these sources the date is excluded from the fingerprint
# to keep the hash stable across separate collection runs.
#
# Collision trade-off: a 3-component hash (no date) is more likely to collide
# than a 4-component hash.  Two different jobs with the same title + company +
# city posted on different real dates will hash identically and be incorrectly
# merged.  This is a documented limitation, not a silent acceptance.
# See §10a of the plan for full discussion.
SOURCES_WITHOUT_RELIABLE_DATE: frozenset[str] = frozenset({"careerjet"})


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


def _preserve_acronym_tokens(pre_title: str, titled: str) -> str:
    """Re-uppercase tokens that were all-caps and 3-5 alpha chars in pre_title.

    Heuristic (not exhaustive): catches known acronyms like AECOM, STC, KBR, SGS
    without a hard whitelist.  A token like 'ADDAR' (5 chars) is also preserved —
    accepted tradeoff; raw value is always available in company_name_raw.
    """
    acronyms = {
        t.lower()
        for t in pre_title.split()
        if t.isalpha() and t.isupper() and 3 <= len(t) <= 5
    }
    if not acronyms:
        return titled
    return " ".join(w.upper() if w.lower() in acronyms else w for w in titled.split())


def clean_company_name(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = _LEGAL_SUFFIXES_RE.sub("", raw).strip()
    for pattern, replacement in _ABBREVIATIONS.items():
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
    titled = cleaned.title()
    return _preserve_acronym_tokens(cleaned, titled) or None


# -- Location parsing ---------------------------------------------------------

_CITY_ALIASES: dict[str, str] = {
    "ar riyadh": "Riyadh",
    "الرياض": "Riyadh",
    "jedda": "Jeddah",
    "jiddah": "Jeddah",
    "جدة": "Jeddah",
    "dammam": "Dammam",
    "الدمام": "Dammam",
    "al khobar": "Al Khobar",
    "al khubar": "Al Khobar",
    "الخبر": "Al Khobar",
    "makkah": "Mecca",
    "mecca": "Mecca",
    "مكة": "Mecca",
    "madinah": "Medina",
    "medina": "Medina",
    "al madinah": "Medina",
    "المدينة": "Medina",
}

_COUNTRY_ALIASES: frozenset[str] = frozenset({"saudi arabia", "ksa", "المملكة العربية السعودية"})

# Saudi administrative regions that appear as the second comma-delimited token
# in Careerjet location strings (e.g. "Dammam, Ash Sharqiyah").
# When the second token is one of these, the country is Saudi Arabia — the region
# name itself is NOT stored as location_country.
_SAUDI_REGIONS: frozenset[str] = frozenset({
    "ash sharqiyah", "eastern province",
    "al qasim", "qassim",
    "makkah", "makkah al mukarramah",          # 59 records: "Jeddah, Makkah"
    "al madinah", "madinah",                    # 2 records:  "Yanbu' al Bahr, Al Madinah"
    "al jawf", "al jouf",                       # 2 records:  "Al Qurayyat, Al Jawf"
    "riyadh",                                   # 1 record:   "Diriyah, Riyadh" (region token)
    "jizan", "jazan",
    "aseer", "asir",
    "najran",
    "al baha",
    "tabuk",
    "hail",
    "northern borders",
})


def parse_location(raw: str | None) -> tuple[str | None, str | None]:
    """
    Returns (location_city, location_country).

    Handles Careerjet location string patterns observed in the Phase 1 test sample:
      "Saudi Arabia"                    → (None, "Saudi Arabia")
      "Riyadh"                          → ("Riyadh", None)
      "Dammam, Ash Sharqiyah"           → ("Dammam", "Saudi Arabia")
      "Al Khubar, Ash Sharqiyah - Riyadh" → ("Al Khobar", "Saudi Arabia")
      "Riyadh, Saudi Arabia"            → ("Riyadh", "Saudi Arabia")  [Jadarat / other]
    """
    if not raw:
        return None, None

    # Strip multi-city suffixes: "City, Region - City2" → "City, Region"
    primary = raw.split(" - ")[0].strip()

    parts = [p.strip() for p in primary.split(",", 1)]
    token1 = parts[0]
    token2 = parts[1] if len(parts) > 1 else None

    # Entire string is a country identifier (e.g. "Saudi Arabia")
    if token1.lower() in _COUNTRY_ALIASES:
        return None, "Saudi Arabia"

    city = _CITY_ALIASES.get(token1.lower(), token1.title()) if token1 else None

    if token2:
        t2 = token2.strip().lower()
        if t2 in _COUNTRY_ALIASES:
            country = "Saudi Arabia"
        elif t2 in _SAUDI_REGIONS:
            # Known Saudi region — confirms country without storing region as country
            country = "Saudi Arabia"
        else:
            country = token2.strip()
    else:
        country = None

    return city, country


# -- Fingerprint generation ---------------------------------------------------

def generate_fingerprint(
    title: str | None,
    company: str | None,
    city: str | None,
    posting_date: str | None = None,
    *,
    include_date: bool = True,
) -> str:
    """
    Compute SHA-256 fingerprint from normalized fields.
    Used as surrogate dedup key for sources without a native job ID.

    include_date=True  (default): 4-component hash — title | company | city | date
    include_date=False           : 3-component hash — title | company | city
                                   Used for sources where `date` is a query timestamp
                                   (see SOURCES_WITHOUT_RELIABLE_DATE).

    Collision trade-off: include_date=False increases collision probability because
    two genuinely different jobs with the same title + company + city posted on
    different real dates will produce the same fingerprint.
    """
    components = [
        (title or "NULL").upper().strip(),
        (company or "NULL").upper().strip(),
        (city or "NULL").upper().strip(),
    ]
    if include_date:
        components.append(posting_date or "NULL")

    return hashlib.sha256("|".join(components).encode("utf-8")).hexdigest()


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
        source_name = rec.get("source_name", "")

        title_raw = payload.get("title") or payload.get("Title")
        company_raw = payload.get("company") or payload.get("Company")
        location_raw = payload.get("locations") or payload.get("location") or payload.get("Location")
        date_raw = payload.get("date") or payload.get("Date")
        description_raw = payload.get("description") or payload.get("Description")
        salary_raw = payload.get("salary") or payload.get("Salary") or None
        url = rec.get("source_url") or payload.get("url")

        title, saudi_only = clean_title(title_raw)
        company = clean_company_name(company_raw)
        city, country = parse_location(location_raw)

        # For sources where `date` is a query timestamp (not a posting date),
        # discard it rather than storing misleading temporal metadata.
        include_date = source_name not in SOURCES_WITHOUT_RELIABLE_DATE
        posting_date = None if not include_date else date_raw

        fingerprint = generate_fingerprint(title, company, city, date_raw,
                                           include_date=include_date)

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
            "posting_date": posting_date,
            "source_url": url,
            "saudi_national_only": saudi_only,
            "job_fingerprint": fingerprint,
            # Fields standardizer.py will populate.
            # career_level_raw is the INFERENCE SOURCE (the job title text), not a raw
            # level string from the source — Careerjet has no dedicated career-level
            # field, so the title is used as input for normalize_career_level().
            # This differs from sources (e.g. Jadarat) that may supply a level directly.
            "career_level": None,
            "career_level_raw": title_raw,
            "job_category": None,
            "job_category_raw": None,
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "salary_period": None,
            "salary_raw": salary_raw,
            # Pipeline state fields — populated by later stages.
            "quality_flags": [],
            "is_rejected": False,
            "is_duplicate": False,
            "duplicate_of_job_id": None,
        })

    return cleaned
