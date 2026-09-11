# -*- coding: utf-8 -*-
"""Find additional seed job IDs from multiple entry points."""
import requests
from bs4 import BeautifulSoup
import sys, re, json

sys.stdout.reconfigure(encoding='utf-8')

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}
session = requests.Session()
session.headers.update(headers)

def get_ids(html):
    return list(dict.fromkeys(re.findall(r'/jobs-in-saudi/all/jobs/0(\d+)\.html', html)))

known_ids = set()
with open('data/raw/tanqeeb_jobs.json', encoding='utf-8') as f:
    for job in json.load(f):
        m = re.search(r'0(\d+)\.html', job.get('job_url',''))
        if m:
            known_ids.add(m.group(1))
print(f"Already collected: {len(known_ids)} jobs")

new_seeds = set()

# Strategy 1: jobs/with-salaries page
print("\n--- Strategy 1: /jobs/with-salaries ---")
r = session.get('https://saudi.tanqeeb.com/jobs/with-salaries', timeout=15)
ids = get_ids(r.text)
new = [i for i in ids if i not in known_ids]
print(f"  IDs found: {ids}, new: {new}")
new_seeds.update(new)

# Strategy 2: Sitemap position sub-files
print("\n--- Strategy 2: sitemap-positions-en.xml ---")
r = session.get('https://saudi.tanqeeb.com/sitemap-positions-en.xml', timeout=15)
soup = BeautifulSoup(r.text, 'xml')
urls = [loc.text for loc in soup.find_all('loc')]
print(f"  Total sitemap URLs: {len(urls)}")
print(f"  Sample URLs: {urls[:10]}")
job_urls = [u for u in urls if '/jobs-in-saudi/all/jobs/' in u]
job_ids_from_sitemap = [re.search(r'0(\d+)\.html', u).group(1) for u in job_urls if re.search(r'0(\d+)\.html', u)]
print(f"  Job detail URLs in sitemap: {len(job_ids_from_sitemap)}")

# Strategy 3: sitemap-positions-states-en.xml (city-specific)
print("\n--- Strategy 3: sitemap-positions-states-en.xml ---")
r2 = session.get('https://saudi.tanqeeb.com/sitemap-positions-states-en.xml', timeout=15)
soup2 = BeautifulSoup(r2.text, 'xml')
urls2 = [loc.text for loc in soup2.find_all('loc')]
print(f"  Total sitemap URLs: {len(urls2)}")
print(f"  Sample URLs: {urls2[:10]}")

# Strategy 4: related_searches API with our existing job IDs
print("\n--- Strategy 4: related_searches.php (company links) ---")
r3 = session.get('https://saudi.tanqeeb.com/tanqeeb_2020/related_searches.php',
                 params={'job_id': '21222470', 'ar': '0', 'cid': '54', 'nid': '', 'isf': '', 'job_name': 'Finance Director'},
                 timeout=15)
soup3 = BeautifulSoup(r3.text, 'lxml')
company_links = [a['href'] for a in soup3.select('a[href*="company="]')]
print(f"  Company links: {company_links[:5]}")

# Strategy 5: Fetch one company page to get more job IDs
if company_links:
    print("\n--- Strategy 5: Company job page ---")
    company_url = 'https://saudi.tanqeeb.com' + company_links[0] if company_links[0].startswith('/') else company_links[0]
    r4 = session.get(company_url, timeout=15)
    company_ids = get_ids(r4.text)
    print(f"  Company URL: {company_url}")
    print(f"  Job IDs found: {company_ids}")
    new = [i for i in company_ids if i not in known_ids]
    new_seeds.update(new)

# Strategy 6: Fetch the similar_jobs for several of our already-collected jobs
# but with DIFFERENT job_names to get different clusters
print("\n--- Strategy 6: Different title seeds for similar_jobs ---")
import time
seed_titles = [
    ('21223400', 'Customs Tariff Classifier'),  # Jeddah
    ('21222789', 'EPMS Engineer'),               # Tabuk
    ('21221843', 'Restaurant Hostess'),           # Riyadh hospitality
    ('21196083', 'Sales Representative'),         # Jeddah
    ('21191709', 'Civil Engineer'),               # Qatif
]
for jid, title in seed_titles:
    time.sleep(1)
    r = session.get('https://saudi.tanqeeb.com/tanqeeb_2020/similar_jobs.php',
                    params={'job_id': jid, 'ar': '0', 'cid': '54', 'job_name': title},
                    timeout=15)
    ids = get_ids(r.text)
    new = [i for i in ids if i not in known_ids]
    print(f"  {title}: found {len(ids)}, {len(new)} new → {new}")
    new_seeds.update(new)

print(f"\n=== Total new seeds found: {len(new_seeds)} ===")
print(list(new_seeds)[:30])
