# -*- coding: utf-8 -*-
"""
Tanqeeb Saudi Arabia Job Scraper
Collects ~150 real job postings via:
  1. Homepage seed (16 jobs)
  2. BFS expansion via similar_jobs.php API
  3. Detail page scraping (server-rendered, no Playwright needed)

robots.txt: No prohibition on target paths.
ToS: No anti-scraping language found (employer posting rules only).
Rate limit: 2s delay between all requests.
"""

import requests
from bs4 import BeautifulSoup
import json
import csv
import time
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# ── Config ─────────────────────────────────────────────────────────────────
BASE_URL = 'https://saudi.tanqeeb.com'
DELAY = 2.0          # seconds between requests
TARGET_JOBS = 160    # collect at least this many unique job IDs
MAX_BFS_DEPTH = 2    # how many levels of similar_jobs expansion
OUTPUT_DIR = Path('data/raw')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
}

session = requests.Session()
session.headers.update(HEADERS)

# ── Helpers ─────────────────────────────────────────────────────────────────

def safe_get(url, params=None, retries=2):
    """GET with retry and delay."""
    for attempt in range(retries + 1):
        try:
            time.sleep(DELAY)
            r = session.get(url, params=params, timeout=20)
            if r.status_code == 200:
                return r
            print(f"  [HTTP {r.status_code}] {url}")
            return None
        except Exception as e:
            print(f"  [Error attempt {attempt+1}] {url}: {e}")
            if attempt < retries:
                time.sleep(DELAY * 2)
    return None


def extract_job_ids_from_html(html):
    """Extract unique job IDs from any HTML page."""
    return list(dict.fromkeys(re.findall(r'/jobs-in-saudi/all/jobs/0(\d+)\.html', html)))


def get_seed_jobs():
    """Collect seed job IDs from the homepage."""
    print("Fetching seed jobs from homepage...")
    r = safe_get(f'{BASE_URL}/')
    if not r:
        return []
    soup = BeautifulSoup(r.text, 'lxml')
    # Extract job IDs from save-form data-job-id attributes
    ids = [f.get('data-job-id') for f in soup.select('[data-job-id]') if f.get('data-job-id')]
    ids = list(dict.fromkeys(ids))  # dedupe, preserve order
    print(f"  Found {len(ids)} seed job IDs: {ids}")
    return ids


def get_similar_jobs(job_id, job_name=''):
    """Call similar_jobs.php and return list of job IDs + location info."""
    r = safe_get(f'{BASE_URL}/tanqeeb_2020/similar_jobs.php',
                 params={'job_id': job_id, 'ar': '0', 'cid': '54', 'job_name': job_name})
    if not r:
        return []
    soup = BeautifulSoup(r.text, 'lxml')
    results = []
    for item in soup.select('.similar-job-item'):
        link = item.select_one('a[href]')
        if not link:
            continue
        match = re.search(r'0(\d+)\.html', link.get('href', ''))
        if match:
            results.append(match.group(1))
    return results


def parse_location(location_items):
    """Parse country and city from meta items like 'Saudi                    , Jeddah'."""
    country, city = 'Saudi Arabia', None
    for item in location_items:
        # Remove icon text (FontAwesome i tags produce no text, but just in case)
        clean = re.sub(r'\s+', ' ', item).strip()
        if ',' in clean:
            parts = clean.split(',', 1)
            country_part = parts[0].strip()
            city_part = parts[1].strip()
            if city_part and city_part.lower() not in ('saudi arabia', 'saudi', ''):
                city = city_part
        elif clean and clean.lower() not in ('saudi', 'saudi arabia'):
            city = clean
    return country, city


def scrape_job_detail(job_id):
    """
    Scrape a job detail page. Returns a dict with all available fields.
    Uses JSON-LD schema.org data as primary source for description.
    """
    url = f'{BASE_URL}/jobs-in-saudi/all/jobs/0{job_id}.html'
    r = safe_get(url)
    if not r:
        return None

    soup = BeautifulSoup(r.text, 'lxml')

    # ── JSON-LD structured data (primary source for description & fields) ──
    ld_data = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get('@type') == 'JobPosting':
                ld_data = data
                break
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get('@type') == 'JobPosting':
                        ld_data = item
                        break
        except Exception:
            pass

    # ── Title ──
    title_el = soup.select_one('.job-title-text')
    title = (title_el.get_text(strip=True) if title_el
             else ld_data.get('title'))

    # ── Company ──
    company_el = soup.select_one('.job-meta-company')
    company_raw = company_el.get_text(strip=True) if company_el else None
    if not company_raw:
        org = ld_data.get('hiringOrganization', {})
        company_raw = org.get('name') if isinstance(org, dict) else None

    # ── Location ──
    meta_items = [m.get_text(separator=' ', strip=True) for m in soup.select('.job-meta-item')]
    country, city = parse_location(meta_items)
    # Fallback: JSON-LD jobLocation
    if not city:
        job_loc = ld_data.get('jobLocation', {})
        if isinstance(job_loc, dict):
            addr = job_loc.get('address', {})
            if isinstance(addr, dict):
                city = addr.get('addressLocality') or addr.get('addressRegion')
    location_str = f'{country}, {city}' if city else country

    # ── Posting Date ──
    date_el = soup.select_one('.job-date')
    posting_date_raw = date_el.get('data-datetime') if date_el else None
    if not posting_date_raw:
        posting_date_raw = ld_data.get('datePosted')

    # ── Tags / Employment type / Work mode ──
    skip_tag_words = {'translat', 'arabic', 'original', 'show', 'عربي'}
    tags = [t.get_text(strip=True) for t in soup.select('.job-tag')
            if not any(w in t.get_text(strip=True).lower() for w in skip_tag_words)]

    employment_type = None
    work_mode = None
    for tag in tags:
        if tag.lower() in ('full time', 'part time', 'internship', 'freelance', 'contract', 'temporary'):
            employment_type = tag
        elif tag.lower() in ('on-site', 'remote', 'hybrid'):
            work_mode = tag

    # ── Description ──
    # Primary: JSON-LD description field (HTML)
    description = None
    if ld_data.get('description'):
        desc_html = ld_data['description']
        desc_soup = BeautifulSoup(desc_html, 'lxml')
        description = desc_soup.get_text(separator='\n', strip=True)
    # Fallback: .text-html.ltr element
    if not description or len(description) < 50:
        text_html_el = soup.select_one('.text-html.ltr, .text-html')
        if text_html_el:
            description = text_html_el.get_text(separator='\n', strip=True)

    # ── Additional structured fields from detail page meta section ──
    meta_container = soup.select_one('div.meta-data, .meta-data')
    experience = None
    education = None
    gender = None
    category = None
    industry = None
    salary = None

    if meta_container:
        meta_text = meta_container.get_text(separator='\n', strip=True)
        # Parse key-value pairs from meta block
        pairs = re.split(r'\n(?=[A-Z])', meta_text)
        for pair in pairs:
            lines = [l.strip() for l in pair.split('\n') if l.strip()]
            if len(lines) >= 2:
                key = lines[0].lower()
                val = lines[1]
                if 'experience' in key:
                    experience = val
                elif 'education' in key:
                    education = val
                elif 'gender' in key:
                    gender = val
                elif 'category' in key:
                    category = val
                elif 'industry' in key:
                    industry = val
                elif 'salary' in key:
                    salary = val

    # Also check JSON-LD for salary
    if not salary:
        sal = ld_data.get('baseSalary', {})
        if isinstance(sal, dict):
            val = sal.get('value', {})
            if isinstance(val, dict):
                mn = val.get('minValue')
                mx = val.get('maxValue')
                currency = sal.get('currency', 'SAR')
                if mn or mx:
                    salary = f'{mn}-{mx} {currency}' if (mn and mx) else f'{mn or mx} {currency}'

    # ── Source URL (external apply link) ──
    apply_el = soup.select_one('.apply-btn')
    source_path = apply_el.get('data-url') if apply_el else None
    job_apply_url = f'{BASE_URL}{source_path}' if source_path else url

    # ── Skills ──
    skills_el = soup.select_one('[class*="skill"], [class*="required-skill"]')
    required_skills = skills_el.get_text(separator=', ', strip=True) if skills_el else None

    return {
        'source': 'tanqeeb',
        'source_job_id': job_id,
        'job_title': title,
        'company': company_raw,
        'location': location_str,
        'city': city,
        'country': country,
        'posting_date': posting_date_raw,
        'job_url': url,
        'job_apply_url': job_apply_url,
        'employment_type': employment_type,
        'work_mode': work_mode,
        'salary': salary,
        'category': category,
        'industry': industry,
        'experience': experience,
        'education': education,
        'gender': gender,
        'required_skills': required_skills,
        'job_description': description,
        'description_length': len(description) if description else 0,
        'source_page': 'tanqeeb_scraper_v1',
        'scraped_at': datetime.now(timezone.utc).isoformat(),
    }


# ── Main Collection Loop ────────────────────────────────────────────────────

def collect_job_ids():
    """BFS from homepage seeds through similar_jobs API."""
    print(f"\n{'='*60}")
    print("PHASE 1: Collecting job IDs")
    print('='*60)

    seen_ids = set()
    queue = []

    # Seed from homepage
    seed_ids = get_seed_jobs()
    for jid in seed_ids:
        if jid not in seen_ids:
            seen_ids.add(jid)
            queue.append((jid, 0, ''))  # (id, depth, title)

    print(f"Seed pool: {len(seen_ids)} jobs")

    # BFS expansion
    processed_for_similar = set()
    idx = 0
    while idx < len(queue) and len(seen_ids) < TARGET_JOBS:
        jid, depth, title = queue[idx]
        idx += 1

        if depth >= MAX_BFS_DEPTH or jid in processed_for_similar:
            continue
        processed_for_similar.add(jid)

        print(f"  Expanding job {jid} (depth={depth}, total={len(seen_ids)})...")
        similar = get_similar_jobs(jid, title)
        new = 0
        for sid in similar:
            if sid not in seen_ids:
                seen_ids.add(sid)
                queue.append((sid, depth + 1, ''))
                new += 1
        print(f"    Got {len(similar)} similar, {new} new | total: {len(seen_ids)}")

        if len(seen_ids) >= TARGET_JOBS:
            break

    all_ids = [item[0] for item in queue[:TARGET_JOBS]]
    print(f"\nTotal unique job IDs collected: {len(all_ids)}")
    return all_ids


def scrape_all_jobs(job_ids):
    """Fetch detail pages for all collected IDs."""
    print(f"\n{'='*60}")
    print(f"PHASE 2: Scraping {len(job_ids)} job detail pages")
    print('='*60)

    results = []
    failed = []

    for i, jid in enumerate(job_ids):
        print(f"  [{i+1}/{len(job_ids)}] Scraping job {jid}...", end=' ')
        data = scrape_job_detail(jid)
        if data:
            results.append(data)
            title = data.get('job_title') or '(no title)'
            city = data.get('city') or 'unknown city'
            print(f"OK — {title} @ {city}")
        else:
            failed.append(jid)
            print("FAILED")

    print(f"\nSuccessfully scraped: {len(results)}")
    print(f"Failed: {len(failed)}")
    if failed:
        print(f"Failed IDs: {failed[:10]}")
    return results


def save_output(jobs):
    """Save to JSON and CSV."""
    print(f"\n{'='*60}")
    print("PHASE 3: Saving output")
    print('='*60)

    # ── JSON ──
    json_path = OUTPUT_DIR / 'tanqeeb_jobs.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    print(f"JSON saved: {json_path} ({len(jobs)} records)")

    # ── CSV ──
    csv_fields = [
        'source', 'source_job_id', 'job_title', 'company', 'location',
        'city', 'country', 'posting_date', 'job_url', 'employment_type',
        'work_mode', 'salary', 'category', 'industry', 'experience',
        'education', 'gender', 'required_skills',
        'description_length', 'source_page', 'scraped_at'
    ]
    csv_path = OUTPUT_DIR / 'tanqeeb_jobs.csv'
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(jobs)
    print(f"CSV saved: {csv_path}")


def quality_report(jobs):
    """Print data quality summary."""
    print(f"\n{'='*60}")
    print("DATA QUALITY REPORT")
    print('='*60)

    urls = [j['job_url'] for j in jobs]
    unique_urls = set(urls)
    dupes = len(urls) - len(unique_urls)

    missing_title = sum(1 for j in jobs if not j.get('job_title'))
    missing_company = sum(1 for j in jobs if not j.get('company'))
    missing_location = sum(1 for j in jobs if not j.get('location'))
    missing_city = sum(1 for j in jobs if not j.get('city'))
    missing_date = sum(1 for j in jobs if not j.get('posting_date'))
    missing_desc = sum(1 for j in jobs if not j.get('job_description') or j.get('description_length', 0) < 20)

    dates = [j['posting_date'] for j in jobs if j.get('posting_date')]
    date_range = f"{min(dates)[:10]} → {max(dates)[:10]}" if dates else "unknown"

    cities = {}
    for j in jobs:
        c = j.get('city') or '(no city)'
        cities[c] = cities.get(c, 0) + 1
    top_cities = sorted(cities.items(), key=lambda x: -x[1])[:12]

    emp_types = {}
    for j in jobs:
        et = j.get('employment_type') or '(unknown)'
        emp_types[et] = emp_types.get(et, 0) + 1

    print(f"1. Jobs collected:              {len(jobs)}")
    print(f"2. Unique job URLs:             {len(unique_urls)}")
    print(f"3. Duplicate URLs:              {dupes}")
    print(f"4. Missing job titles:          {missing_title}")
    print(f"5. Missing company names:       {missing_company}")
    print(f"6. Missing locations (any):     {missing_location}")
    print(f"   Missing city specifically:   {missing_city}")
    print(f"7. Missing posting dates:       {missing_date}")
    print(f"8. Missing descriptions (<20c): {missing_desc}")
    print(f"9. Date range:                  {date_range}")
    print(f"10. Cities in sample:")
    for city, count in top_cities:
        print(f"    {city:<30} {count}")
    print(f"\nEmployment types: {emp_types}")


# ── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    start = time.time()
    print("Tanqeeb Scraper — Saudi Arabia Job Postings")
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Target: {TARGET_JOBS} jobs | Delay: {DELAY}s | BFS depth: {MAX_BFS_DEPTH}")

    job_ids = collect_job_ids()
    jobs = scrape_all_jobs(job_ids)

    if jobs:
        save_output(jobs)
        quality_report(jobs)
    else:
        print("No jobs collected — check errors above.")

    elapsed = time.time() - start
    print(f"\nTotal time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
