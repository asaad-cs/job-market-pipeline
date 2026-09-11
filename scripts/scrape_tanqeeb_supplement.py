# -*- coding: utf-8 -*-
"""
Supplement scraper: adds new seeds to reach 100+ jobs.
Reads existing tanqeeb_jobs.json, scrapes new IDs, merges and saves.
"""

import requests
from bs4 import BeautifulSoup
import json, csv, time, re, sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = 'https://saudi.tanqeeb.com'
DELAY = 2.0
OUTPUT_DIR = Path('data/raw')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}
session = requests.Session()
session.headers.update(HEADERS)

def safe_get(url, params=None, retries=2):
    for attempt in range(retries + 1):
        try:
            time.sleep(DELAY)
            r = session.get(url, params=params, timeout=20)
            if r.status_code == 200:
                return r
            return None
        except Exception as e:
            if attempt < retries:
                time.sleep(DELAY * 2)
    return None

def get_ids(html):
    return list(dict.fromkeys(re.findall(r'/jobs-in-saudi/all/jobs/0(\d+)\.html', html)))

def get_similar(jid, title=''):
    r = safe_get(f'{BASE_URL}/tanqeeb_2020/similar_jobs.php',
                 params={'job_id': jid, 'ar': '0', 'cid': '54', 'job_name': title})
    if not r:
        return []
    return get_ids(r.text)

def parse_location(items):
    country, city = 'Saudi Arabia', None
    for item in items:
        clean = re.sub(r'\s+', ' ', item).strip()
        if ',' in clean:
            parts = clean.split(',', 1)
            cp = parts[1].strip()
            if cp and cp.lower() not in ('saudi arabia', 'saudi', ''):
                city = cp
        elif clean and clean.lower() not in ('saudi', 'saudi arabia'):
            city = clean
    return country, city

def scrape_job(job_id):
    url = f'{BASE_URL}/jobs-in-saudi/all/jobs/0{job_id}.html'
    r = safe_get(url)
    if not r:
        return None
    soup = BeautifulSoup(r.text, 'lxml')

    ld_data = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string)
            if isinstance(data, dict) and data.get('@type') == 'JobPosting':
                ld_data = data; break
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get('@type') == 'JobPosting':
                        ld_data = item; break
        except Exception:
            pass

    title_el = soup.select_one('.job-title-text')
    title = title_el.get_text(strip=True) if title_el else ld_data.get('title')

    company_el = soup.select_one('.job-meta-company')
    company = company_el.get_text(strip=True) if company_el else (
        ld_data.get('hiringOrganization', {}) or {}).get('name')

    meta_items = [m.get_text(separator=' ', strip=True) for m in soup.select('.job-meta-item')]
    country, city = parse_location(meta_items)
    if not city:
        jl = ld_data.get('jobLocation', {})
        if isinstance(jl, dict):
            addr = jl.get('address', {})
            if isinstance(addr, dict):
                city = addr.get('addressLocality') or addr.get('addressRegion')
    location_str = f'{country}, {city}' if city else country

    date_el = soup.select_one('.job-date')
    posting_date = (date_el.get('data-datetime') if date_el else None) or ld_data.get('datePosted')

    skip = {'translat', 'arabic', 'original', 'show', 'عربي'}
    tags = [t.get_text(strip=True) for t in soup.select('.job-tag')
            if not any(w in t.get_text(strip=True).lower() for w in skip)]
    employment_type = next((t for t in tags if t.lower() in
                            ('full time','part time','internship','freelance','contract','temporary')), None)
    work_mode = next((t for t in tags if t.lower() in ('on-site','remote','hybrid')), None)

    # Description from JSON-LD
    description = None
    if ld_data.get('description'):
        d_soup = BeautifulSoup(ld_data['description'], 'lxml')
        description = d_soup.get_text(separator='\n', strip=True)
    if not description or len(description) < 50:
        th = soup.select_one('.text-html.ltr, .text-html')
        if th:
            description = th.get_text(separator='\n', strip=True)

    # Structured meta fields
    meta_c = soup.select_one('div.meta-data')
    experience = category = education = salary = industry = None
    if meta_c:
        for pair in re.split(r'\n(?=[A-Z])', meta_c.get_text(separator='\n', strip=True)):
            lines = [l.strip() for l in pair.split('\n') if l.strip()]
            if len(lines) >= 2:
                k, v = lines[0].lower(), lines[1]
                if 'experience' in k: experience = v
                elif 'education' in k: education = v
                elif 'category' in k: category = v
                elif 'industry' in k: industry = v
                elif 'salary' in k: salary = v

    if not salary:
        sal = ld_data.get('baseSalary', {})
        if isinstance(sal, dict):
            val = sal.get('value', {})
            if isinstance(val, dict):
                mn, mx = val.get('minValue'), val.get('maxValue')
                cur = sal.get('currency', 'SAR')
                if mn or mx:
                    salary = f'{mn}-{mx} {cur}' if (mn and mx) else f'{mn or mx} {cur}'

    apply_el = soup.select_one('.apply-btn')
    src_path = apply_el.get('data-url') if apply_el else None
    apply_url = f'{BASE_URL}{src_path}' if src_path else url

    return {
        'source': 'tanqeeb',
        'source_job_id': job_id,
        'job_title': title,
        'company': company,
        'location': location_str,
        'city': city,
        'country': country,
        'posting_date': posting_date,
        'job_url': url,
        'job_apply_url': apply_url,
        'employment_type': employment_type,
        'work_mode': work_mode,
        'salary': salary,
        'category': category,
        'industry': industry,
        'experience': experience,
        'education': education,
        'gender': None,
        'required_skills': None,
        'job_description': description,
        'description_length': len(description) if description else 0,
        'source_page': 'tanqeeb_scraper_v1',
        'scraped_at': datetime.now(timezone.utc).isoformat(),
    }

# ── Load existing data ─────────────────────────────────────────────────────
existing_path = OUTPUT_DIR / 'tanqeeb_jobs.json'
with open(existing_path, encoding='utf-8') as f:
    existing_jobs = json.load(f)
existing_ids = set(j['source_job_id'] for j in existing_jobs)
print(f"Loaded {len(existing_jobs)} existing jobs")

# ── New seeds (from find_more_seeds.py results) ─────────────────────────────
new_seeds = [
    # /jobs/with-salaries
    '21222959','21222961','21222962','21222966','21223383','21223388','21223389','21223400',
    # Company page (Red Sea Global)
    '21219368','21217105','21217023','21215901','21215900','21215392','21214309',
    '21212604','21212537','21211266','21209810','21209761','21206576','21204702',
    '21204650','21202173','21202168',
    # Customs/Logistics cluster
    '21218001','21197169','21183479','21181089','21180649','21169393','21169106','21164737',
    # EPMS
    '21174783',
    # Hospitality
    '21120951','21093162','21076790',
    # Sales cluster
    '21222780','21222759','21222746','21222706','21222585','21219794','21219781','21219674',
    # Civil engineering cluster
    '21222720','21222612','21219389','21216832','21214393','21214319','21213589','21213508',
]

# Filter to only truly new IDs
to_scrape = [jid for jid in new_seeds if jid not in existing_ids]
print(f"New IDs to scrape: {len(to_scrape)}")

# Also expand some new seeds with similar_jobs (1 level) for more variety
expansion_seeds = [
    ('21223400', 'Customs Tariff Classifier'),
    ('21222780', 'Sales Representative'),
    ('21222720', 'Civil Engineer'),
    ('21202173', 'Project Manager'),
    ('21174783', 'EPMS Engineer'),
]
all_known = existing_ids | set(to_scrape)
extra_ids = []
for jid, title in expansion_seeds:
    print(f"Expanding {title}...")
    sims = get_similar(jid, title)
    for sid in sims:
        if sid not in all_known:
            extra_ids.append(sid)
            all_known.add(sid)
print(f"Extra IDs from expansion: {len(extra_ids)}")
to_scrape.extend(extra_ids)
print(f"Total to scrape: {len(to_scrape)}")

# ── Scrape ─────────────────────────────────────────────────────────────────
new_jobs = []
failed = []
for i, jid in enumerate(to_scrape):
    print(f"  [{i+1}/{len(to_scrape)}] {jid}...", end=' ')
    data = scrape_job(jid)
    if data:
        new_jobs.append(data)
        print(f"OK — {data.get('job_title','?')[:40]} @ {data.get('city','?')}")
    else:
        failed.append(jid)
        print("FAILED")

# ── Merge and save ─────────────────────────────────────────────────────────
all_jobs = existing_jobs + new_jobs
print(f"\nTotal jobs: {len(all_jobs)} ({len(existing_jobs)} existing + {len(new_jobs)} new)")

with open(existing_path, 'w', encoding='utf-8') as f:
    json.dump(all_jobs, f, ensure_ascii=False, indent=2)
print(f"JSON saved: {existing_path}")

csv_fields = ['source','source_job_id','job_title','company','location','city','country',
              'posting_date','job_url','employment_type','work_mode','salary','category',
              'industry','experience','education','gender','required_skills',
              'description_length','source_page','scraped_at']
with open(OUTPUT_DIR / 'tanqeeb_jobs.csv', 'w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=csv_fields, extrasaction='ignore')
    w.writeheader(); w.writerows(all_jobs)
print(f"CSV saved: data/raw/tanqeeb_jobs.csv")

# ── Quality report ─────────────────────────────────────────────────────────
jobs = all_jobs
urls = [j['job_url'] for j in jobs]
dates = sorted([j['posting_date'] for j in jobs if j.get('posting_date')])
cities = {}
for j in jobs:
    c = j.get('city') or '(no city)'; cities[c] = cities.get(c,0)+1

print(f"\n{'='*55}")
print("DATA QUALITY REPORT")
print('='*55)
print(f"1.  Jobs collected:              {len(jobs)}")
print(f"2.  Unique job URLs:             {len(set(urls))}")
print(f"3.  Duplicate URLs:              {len(urls)-len(set(urls))}")
print(f"4.  Missing job titles:          {sum(1 for j in jobs if not j.get('job_title'))}")
print(f"5.  Missing company names:       {sum(1 for j in jobs if not j.get('company'))}")
print(f"6.  Missing locations (any):     {sum(1 for j in jobs if not j.get('location'))}")
print(f"    Missing city specifically:   {sum(1 for j in jobs if not j.get('city'))}")
print(f"7.  Missing posting dates:       {sum(1 for j in jobs if not j.get('posting_date'))}")
print(f"8.  Missing descriptions:        {sum(1 for j in jobs if not j.get('job_description') or j.get('description_length',0)<20)}")
print(f"9.  Date range:                  {dates[0][:10] if dates else '?'} → {dates[-1][:10] if dates else '?'}")
print(f"10. Cities:")
for c, n in sorted(cities.items(), key=lambda x:-x[1]):
    print(f"    {c:<30} {n}")
emp = {}
for j in jobs:
    et = j.get('employment_type') or '(unknown)'; emp[et] = emp.get(et,0)+1
print(f"\nEmployment types: {emp}")
print(f"\nFailed IDs: {failed}")
