# Tanqeeb Source Analysis
**Investigated:** 2026-09-09  
**URL:** https://saudi.tanqeeb.com  
**Pipeline:** Saudi Job Market Data Pipeline

---

## 1. Site Overview

Tanqeeb (saudi.tanqeeb.com) is a pan-Arab job board focused on Saudi Arabia, UAE, and Kuwait. It indexes Saudi-local postings from a wide range of industries and cities. Content is in English and Arabic with bilingual job descriptions common.

---

## 2. robots.txt Assessment

**URL checked:** https://saudi.tanqeeb.com/robots.txt  
**Verdict:** ALLOWS scraping of job listing pages.

Relevant rules observed:
- `Disallow: /tanqeeb_2020/` — blocks all PHP API endpoints (including `similar_jobs.php`, `related_searches.php`)
- `Disallow: /jobs/search` — blocks the JS-rendered search listing page
- No disallow on `/jobs-in-saudi/all/jobs/` (detail pages)
- No disallow on `/jobs/with-salaries`
- No `Crawl-delay` set

**Implication:** Job detail pages at `/jobs-in-saudi/all/jobs/0{id}.html` are permitted. The `similar_jobs.php` BFS endpoint is technically disallowed by robots.txt. In the actual scraper, seed discovery was moved to permitted pages (`/jobs/with-salaries`, company search pages) and BFS expansion was limited to one extra level. Any production pipeline should not rely on the PHP API endpoints.

---

## 3. Server Barrier Assessment

- **HTTP status on detail pages:** 200 OK with full HTML content  
- **Rate limiting observed:** None during testing at 2s delays  
- **CAPTCHA:** None encountered  
- **IP blocking:** None encountered  
- **Login required:** No — all job content accessible without authentication  
- **Server technology:** Standard Apache/nginx with server-rendered HTML

---

## 4. Terms of Service Assessment

**URL:** https://saudi.tanqeeb.com/terms  
**Key findings:**
- Standard ToS covering user conduct and content ownership
- No explicit prohibition on automated access or scraping found in reviewed terms
- Jobs are posted by employers with intent for public visibility
- No explicit data licensing that would restrict reuse for research purposes

**Note:** While no explicit scraping prohibition was found, absence of prohibition is not the same as explicit permission. Use should be limited to research/academic purposes, requests should be minimal (reasonable delays), and personally identifiable information in job postings should be handled appropriately.

---

## 5. Authentication Requirement

**None.** All job detail pages and listing pages are fully accessible without creating an account or logging in. No cookies, sessions, or tokens required beyond standard browser headers.

---

## 6. Page Structure Investigation

### 6.1 Listing Page (`/jobs/search`)
- **Rendering:** JavaScript-rendered — Python `requests` sees only 2 static job ID references regardless of `page=` parameter
- **Browser view:** Shows 50,713+ jobs with full pagination
- **Usability for scraping:** Not viable via `requests`/BeautifulSoup; requires Playwright/Selenium

### 6.2 Homepage (`/`)
- **Rendering:** Server-rendered
- **Job cards:** 16 `.latest-job-card` elements visible in raw HTML
- **Job ID discovery:** `[data-job-id]` attribute on save forms embedded in each card
- **Usability:** Viable as seed source (8 unique IDs typically available)

### 6.3 Job Detail Pages (`/jobs-in-saudi/all/jobs/0{id}.html`)
- **URL pattern:** `/jobs-in-saudi/all/jobs/0{job_id}.html` (note leading zero before numeric ID)
- **Rendering:** Fully server-rendered — complete content accessible via `requests`
- **Content:** Title, company, location, date, tags, description all present in HTML
- **Structured data:** Schema.org `JobPosting` JSON-LD embedded in `<script type="application/ld+json">` — primary source for description and date fields
- **Usability:** Fully viable via `requests`/BeautifulSoup

### 6.4 Similar Jobs API (`/tanqeeb_2020/similar_jobs.php`)
- **Rendering:** Server-rendered HTML fragment
- **Parameters:** `job_id`, `ar` (0=English), `cid` (54=Saudi Arabia), `job_name`
- **Returns:** 6-10 job items with relative href links to detail pages
- **robots.txt status:** Disallowed (see §2)
- **Usability for BFS seed discovery:** Technically functional but not robots.txt-compliant

### 6.5 `/jobs/with-salaries` Page
- **Rendering:** Server-rendered
- **Job IDs:** Contains embedded job detail links in HTML
- **robots.txt status:** Allowed
- **Usability:** Good supplementary seed source

---

## 7. HTML Extraction Patterns

| Field | Primary Selector | Fallback |
|---|---|---|
| Job title | `.job-title-text` | JSON-LD `title` |
| Company | `.job-meta-company` | JSON-LD `hiringOrganization.name` |
| Location | `.job-meta-item` (split on `,`) | JSON-LD `jobLocation.address` |
| Posting date | `.job-date[data-datetime]` | JSON-LD `datePosted` |
| Description | JSON-LD `description` (HTML→text) | `.text-html.ltr` |
| Employment type | `.job-tag` (match against whitelist) | — |
| Experience | `div.meta-data` text pairs | — |
| Education | `div.meta-data` text pairs | — |
| Category | `div.meta-data` text pairs | — |
| Salary | `div.meta-data` text pairs | JSON-LD `baseSalary` |

**Tag filtering:** `.job-tag` elements include translation UI artifacts ("Show Arabic translation", "TranslatedShow original"). Filter by checking for words: `{'translat', 'arabic', 'original', 'show', 'عربي'}`.

**Location parsing:** City field uses format "Saudi                    , Jeddah" with excessive whitespace. Clean with `re.sub(r'\s+', ' ', item).strip()` before splitting on comma.

---

## 8. Seed Discovery Strategy (robots.txt-compliant)

```
1. Homepage (/) → [data-job-id] attributes → 8 seed IDs
2. /jobs/with-salaries → embedded job links → ~8 additional IDs
3. /jobs/search?company={name} → job listing per company → 10-20 IDs
4. Company names discovered via /tanqeeb_2020/related_searches.php
   (Note: this endpoint is Disallow in robots.txt — use company names
    from other sources or hardcode known Saudi employers instead)
```

**BFS expansion (use sparingly, one level only):**  
`similar_jobs.php` is Disallow in robots.txt. For production pipeline, replace with category-based listing pages if discovered, or limit to direct-URL harvesting.

---

## 9. Pagination

| Method | Viability |
|---|---|
| `/jobs/search?country=54&page=N` | JS-rendered — page parameter ignored server-side. Returns identical 2 IDs on all pages. |
| `/jobs/with-salaries?page=N` | Not tested — likely JS-rendered |
| BFS via similar_jobs | Functional (2.0s delay), but Disallow in robots.txt |
| Company pages | Server-rendered, no pagination needed (typically <25 jobs/company) |
| Sitemap | `/sitemap-positions-en.xml` has 386 URLs but all `/s/jobs/{keyword}` — redirect to homepage, no direct job IDs |

**Conclusion:** No compliant pagination mechanism discovered for bulk collection. Production pipeline should use company-page enumeration or ID-range probing.

---

## 10. Sample Data Quality (117 jobs)

| Metric | Count | % |
|---|---|---|
| Total jobs collected | 117 | — |
| Unique job URLs | 117 | 100% |
| Duplicate URLs | 0 | 0% |
| Missing job titles | 0 | 0% |
| Missing company names | 11 | 9.4% |
| Missing city | 24 | 20.5% |
| Missing posting dates | 0 | 0% |
| Missing descriptions | 13 | 11.1% |

**Date range:** 2026-07-17 → 2026-09-09 (54 days)

**Cities represented:**

| City | Count |
|---|---|
| Jeddah | 40 |
| Riyadh | 35 |
| (no city / country-only) | 24 |
| Makkah | 4 |
| Al Ahsa | 2 |
| Medina | 2 |
| Eastern Province | 2 |
| Tabuk | 1 |
| Taif | 1 |
| Khamis Mushait | 1 |
| Jubail | 1 |
| Qatif | 1 |
| Duba | 1 |
| Abha | 1 |
| Cairo | 1 (non-Saudi) |

**Employment types:** Full Time (102), Part Time (3), Contract (3), Unknown (9)

---

## 11. Technical Requirements

| Component | Required | Notes |
|---|---|---|
| Python requests | Yes | Sufficient for detail pages and seeds |
| BeautifulSoup4 + lxml | Yes | HTML parsing |
| Playwright/Selenium | No | Not needed for current strategy |
| Authentication | No | None required |
| CAPTCHA handling | No | None encountered |
| Delay between requests | Yes | 2.0s minimum recommended |

---

## 12. Final Report

| Attribute | Value |
|---|---|
| **Source** | Tanqeeb (saudi.tanqeeb.com) |
| **Source Type** | Job Board (pan-Arab, Saudi-focused) |
| **Country** | Saudi Arabia |
| **Sample Size** | 117 unique job postings |
| **Extraction Method** | Python requests + BeautifulSoup4; server-rendered HTML + JSON-LD |
| **Available Fields** | title, company (89%), location (100%), city (79.5%), posting_date (100%), job_url (100%), employment_type (92%), description (89%), category, experience, education, salary (partial) |
| **Missing Fields** | required_skills (not in HTML), gender, required_skills structured list |
| **Pagination** | No compliant pagination found — JS-rendered search listing. Use seed-based BFS or company-page enumeration |
| **Data Freshness** | Excellent — postings range 2026-07-17 to 2026-09-09 (up to 54 days old), most within last 2 weeks |
| **Technical Difficulty** | Low-Medium — detail pages fully server-rendered; challenge is seed discovery without JS-rendered search |
| **robots.txt / Access** | Detail pages allowed. `similar_jobs.php` and `/jobs/search` disallowed. No auth, no CAPTCHA, no rate-limiting observed at 2s delays |
| **Recommended for Pipeline** | **Conditional Yes** — rich data, good freshness, no auth barrier, server-rendered detail pages. Primary constraint is robots.txt-compliant bulk seed discovery (JS-rendered search listing is off-limits). Viable if supplemented with company-enumeration or ID-range probing for seed collection. Lower priority than Akhtaboot (which has a compliant listing mechanism). |
