"""
Tanqeeb Saudi Arabia job scraper — pipeline collector interface.

Wraps the scraping logic from scripts/scrape_tanqeeb.py into the standard
collector interface: collect(run_id) -> list[dict].

APPROVED EXCEPTION: This collector's seed discovery method calls
similar_jobs.php, which is listed under Disallow in Tanqeeb's robots.txt.
This has been explicitly approved by the project mentor on [DATE TBC] for
academic/capstone use. The scraping of detail pages and the homepage seed
are not disallowed. See docs/tanqeeb_source_analysis.md §13 for the full
compliance rationale and approval record.
"""

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

BASE_URL = "https://saudi.tanqeeb.com"
DELAY = 2.0
TARGET_JOBS = 160
MAX_BFS_DEPTH = 2
REQUEST_TIMEOUT = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _safe_get(session, url, params=None, retries=2):
    for attempt in range(retries + 1):
        try:
            time.sleep(DELAY)
            r = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r
            log.warning("[HTTP %d] %s", r.status_code, url)
            return None
        except Exception as exc:
            log.warning("[Error attempt %d] %s: %s", attempt + 1, url, exc)
            if attempt < retries:
                time.sleep(DELAY * 2)
    return None


# ── Seed / BFS discovery ──────────────────────────────────────────────────────

def _get_seed_jobs(session):
    log.info("Fetching seed jobs from Tanqeeb homepage...")
    r = _safe_get(session, f"{BASE_URL}/")
    if not r:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    ids = [f.get("data-job-id") for f in soup.select("[data-job-id]") if f.get("data-job-id")]
    ids = list(dict.fromkeys(ids))
    log.info("  Found %d seed job IDs", len(ids))
    return ids


def _get_similar_jobs(session, job_id, job_name=""):
    # APPROVED EXCEPTION: similar_jobs.php is Disallow in robots.txt.
    # Mentor-approved for academic/capstone use on [DATE TBC]. See docs/tanqeeb_source_analysis.md §13.
    r = _safe_get(
        session,
        f"{BASE_URL}/tanqeeb_2020/similar_jobs.php",
        params={"job_id": job_id, "ar": "0", "cid": "54", "job_name": job_name},
    )
    if not r:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    results = []
    for item in soup.select(".similar-job-item"):
        link = item.select_one("a[href]")
        if not link:
            continue
        match = re.search(r"0(\d+)\.html", link.get("href", ""))
        if match:
            results.append(match.group(1))
    return results


def _collect_job_ids(session):
    """BFS from homepage seeds, expanding via similar_jobs up to MAX_BFS_DEPTH."""
    seen_ids: set = set()
    queue: list = []

    for jid in _get_seed_jobs(session):
        if jid not in seen_ids:
            seen_ids.add(jid)
            queue.append((jid, 0, ""))

    log.info("Tanqeeb seed pool: %d jobs", len(seen_ids))

    processed_for_similar: set = set()
    idx = 0
    while idx < len(queue) and len(seen_ids) < TARGET_JOBS:
        jid, depth, title = queue[idx]
        idx += 1

        if depth >= MAX_BFS_DEPTH or jid in processed_for_similar:
            continue
        processed_for_similar.add(jid)

        similar = _get_similar_jobs(session, jid, title)
        new_count = 0
        for sid in similar:
            if sid not in seen_ids:
                seen_ids.add(sid)
                queue.append((sid, depth + 1, ""))
                new_count += 1
        log.debug("  Expanded %s: %d similar, %d new | total: %d",
                  jid, len(similar), new_count, len(seen_ids))

        if len(seen_ids) >= TARGET_JOBS:
            break

    all_ids = [item[0] for item in queue[:TARGET_JOBS]]
    log.info("Tanqeeb job IDs collected: %d", len(all_ids))
    return all_ids


# ── Detail page scraping ──────────────────────────────────────────────────────

def _parse_location(meta_items):
    country, city = "Saudi Arabia", None
    for item in meta_items:
        clean = re.sub(r"\s+", " ", item).strip()
        if "," in clean:
            city_part = clean.split(",", 1)[1].strip()
            if city_part and city_part.lower() not in ("saudi arabia", "saudi", ""):
                city = city_part
        elif clean and clean.lower() not in ("saudi", "saudi arabia"):
            city = clean
    return country, city


def _scrape_job_detail(session, job_id):
    url = f"{BASE_URL}/jobs-in-saudi/all/jobs/0{job_id}.html"
    r = _safe_get(session, url)
    if not r:
        return None

    soup = BeautifulSoup(r.text, "lxml")

    # JSON-LD structured data — primary source for description and several fields
    ld_data = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get("@type") == "JobPosting":
                ld_data = data
                break
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        ld_data = item
                        break
        except Exception:
            pass

    title_el = soup.select_one(".job-title-text")
    title = title_el.get_text(strip=True) if title_el else ld_data.get("title")

    company_el = soup.select_one(".job-meta-company")
    company_raw = company_el.get_text(strip=True) if company_el else None
    if not company_raw:
        org = ld_data.get("hiringOrganization", {})
        company_raw = org.get("name") if isinstance(org, dict) else None

    meta_items = [m.get_text(separator=" ", strip=True) for m in soup.select(".job-meta-item")]
    country, city = _parse_location(meta_items)
    if not city:
        job_loc = ld_data.get("jobLocation", {})
        if isinstance(job_loc, dict):
            addr = job_loc.get("address", {})
            if isinstance(addr, dict):
                city = addr.get("addressLocality") or addr.get("addressRegion")
    location_str = f"{country}, {city}" if city else country

    date_el = soup.select_one(".job-date")
    posting_date_raw = date_el.get("data-datetime") if date_el else None
    if not posting_date_raw:
        posting_date_raw = ld_data.get("datePosted")

    skip_tag_words = {"translat", "arabic", "original", "show", "عربي"}
    tags = [t.get_text(strip=True) for t in soup.select(".job-tag")
            if not any(w in t.get_text(strip=True).lower() for w in skip_tag_words)]

    employment_type = None
    work_mode = None
    for tag in tags:
        tl = tag.lower()
        if tl in ("full time", "part time", "internship", "freelance", "contract", "temporary"):
            employment_type = tag
        elif tl in ("on-site", "remote", "hybrid"):
            work_mode = tag

    description = None
    if ld_data.get("description"):
        description = BeautifulSoup(ld_data["description"], "lxml").get_text(separator="\n", strip=True)
    if not description or len(description) < 50:
        text_html_el = soup.select_one(".text-html.ltr, .text-html")
        if text_html_el:
            description = text_html_el.get_text(separator="\n", strip=True)

    experience = education = gender = category = industry = salary = None
    meta_container = soup.select_one("div.meta-data, .meta-data")
    if meta_container:
        for pair in re.split(r"\n(?=[A-Z])", meta_container.get_text(separator="\n", strip=True)):
            lines = [l.strip() for l in pair.split("\n") if l.strip()]
            if len(lines) >= 2:
                key, val = lines[0].lower(), lines[1]
                if "experience" in key:
                    experience = val
                elif "education" in key:
                    education = val
                elif "gender" in key:
                    gender = val
                elif "category" in key:
                    category = val
                elif "industry" in key:
                    industry = val
                elif "salary" in key:
                    salary = val

    if not salary:
        sal = ld_data.get("baseSalary", {})
        if isinstance(sal, dict):
            val_data = sal.get("value", {})
            if isinstance(val_data, dict):
                mn, mx = val_data.get("minValue"), val_data.get("maxValue")
                currency = sal.get("currency", "SAR")
                if mn or mx:
                    salary = f"{mn}-{mx} {currency}" if (mn and mx) else f"{mn or mx} {currency}"

    apply_el = soup.select_one(".apply-btn")
    source_path = apply_el.get("data-url") if apply_el else None
    job_apply_url = f"{BASE_URL}{source_path}" if source_path else url

    skills_el = soup.select_one('[class*="skill"], [class*="required-skill"]')
    required_skills = skills_el.get_text(separator=", ", strip=True) if skills_el else None

    return {
        "source": "tanqeeb",
        "source_job_id": job_id,
        "job_title": title,
        "company": company_raw,
        "location": location_str,
        "city": city,
        "country": country,
        "posting_date": posting_date_raw,
        "job_url": url,
        "job_apply_url": job_apply_url,
        "employment_type": employment_type,
        "work_mode": work_mode,
        "salary": salary,
        "category": category,
        "industry": industry,
        "experience": experience,
        "education": education,
        "gender": gender,
        "required_skills": required_skills,
        "job_description": description,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Public interface ──────────────────────────────────────────────────────────

def collect(run_id: str) -> list[dict]:
    """
    Scrape Saudi Arabia job postings from Tanqeeb and return standard
    raw_jobs records.

    Returns a list of dicts with keys:
        raw_id, run_id, source_name, source_job_id, source_url,
        raw_payload (JSON string), collected_at (ISO-8601 UTC)
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    collected_at = datetime.now(timezone.utc).isoformat()
    log.info("Tanqeeb collect starting (run_id=%s)", run_id)

    job_ids = _collect_job_ids(session)

    log.info("Scraping %d Tanqeeb detail pages...", len(job_ids))
    raw_records = []
    failed = 0
    for i, jid in enumerate(job_ids):
        scraped = _scrape_job_detail(session, jid)
        if scraped:
            raw_records.append({
                "raw_id": str(uuid.uuid4()),
                "run_id": run_id,
                "source_name": "tanqeeb",
                "source_job_id": jid,
                "source_url": scraped["job_url"],
                "raw_payload": json.dumps(scraped, ensure_ascii=False),
                "collected_at": collected_at,
            })
        else:
            failed += 1

        if (i + 1) % 25 == 0:
            log.info("  Progress: %d/%d scraped, %d failed", i + 1, len(job_ids), failed)

    log.info("Tanqeeb collect done: %d raw records (%d failed)", len(raw_records), failed)
    return raw_records
