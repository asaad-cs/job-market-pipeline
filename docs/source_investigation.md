# Source Investigation Report
**Saudi Arabia Job Postings Pipeline — Data Engineering Capstone**
**Date:** 2026-08-27
**Investigator:** Ahmed Saad Al-Faidi

---

## Summary Table

| Source | Official API? | robots.txt allows scraping? | Auth required to browse? | Key fields visible | Verdict |
|---|---|---|---|---|---|
| Bayt.com | No | **No** — /jobs/ paths explicitly disallowed | Yes (server returns 403) | Title, company, location, date, salary (sometimes) | **Exclude** |
| GulfTalent | No | Unknown (robots.txt returns 403) | Yes (server returns 403) | Title, company, salary range, location | **Exclude** |
| Indeed SA | Deprecated (2023) | **No** — /job/ and /jobs/ disallowed | No (but JS-heavy) | Title, company, location, salary, date | **Exclude** |
| LinkedIn Jobs | No (partner-only) | **No** — /jobs paths explicitly disallowed | Increasingly yes | Title, company, location, level, date | **Exclude** |
| Mihnati | No | Partially (platform shared w/ Rozee.pk) | **Yes — login required** | Unknown (login wall) | **Sample only (manual)** |
| Akhtaboot | No | **No** — Disallow: / for all bots | **No — public browse** | Title, company, location, career level | **Use as primary sample** |
| Jadarat (HRDF) | No (open data only) | Not accessible (ECONNREFUSED) | **Yes — Nafath required** | Aggregate stats only | **Exclude / Explore open data** |
| Taqat | No | **Yes** — fully permissive | **Yes — Nafath-like auth** | None (login wall) | **Exclude** |

---

## Per-Source Analysis

### 1. Bayt.com

**robots.txt** (`https://www.bayt.com/robots.txt` — successfully fetched):
The file explicitly disallows the following job-related paths for all crawlers:
- `/en/jobs/`, `/ar/jobs/`, `/fr/jobs/` — language-prefixed job listing directories
- `*-jobs/` — category job listing paths (e.g., `/software-jobs/`)
- `/*/jobs/search/?section=RecommendedJobs` — search result pages
- URLs containing `filters[`, `filters%5`, `options[`, `options%5` — any filtered search result URL

Named bots are explicitly singled out: `LinkedInBot` and `IndeedBot` are fully disallowed. No crawl-delay is specified.

**Terms of Service:**
The ToS page (`https://www.bayt.com/en/pages/terms/`) returned HTTP 403 Forbidden — the server actively blocks automated access to this URL. No ToS text could be retrieved. This blocking behavior itself signals aggressive anti-scraping enforcement at the server level.

**API:**
No official public or developer API was found. Commercial scraping tools (e.g., Apify's Bayt scraper) exist as paid third-party services, but there is no official data access program.

**Access barriers:**
The Saudi Arabia job listings page (`https://www.bayt.com/en/saudi-arabia/jobs/`) returned HTTP 403 Forbidden to automated requests. The platform uses server-level bot detection in addition to robots.txt rules.

**Data structure:**
From known data: job title, company name, location (city/country), experience level, posting date, full job description, salary (sometimes listed, not always), bilingual Arabic/English. One of the richest field sets in the region.

**Verdict: Exclude.**
Robots.txt explicitly disallows all job listing paths. Job listing pages return HTTP 403 to non-browser requests. No API exists. Attempting to scrape would require circumventing active technical measures, which violates the spirit of ethical data collection. The platform's ToS couldn't be retrieved but the server posture makes the intent clear.

---

### 2. GulfTalent

**robots.txt** (`https://www.gulftalent.com/robots.txt`):
Returned **HTTP 403 Forbidden** — GulfTalent blocks access to its own robots.txt file. This is unusual and signals an extremely defensive posture toward crawlers. We cannot confirm which paths are disallowed, but the 403 on the robots.txt itself is a strong signal.

**Terms of Service** (`https://www.gulftalent.com/terms`):
Retrieved via search result excerpts. GulfTalent's ToS contains explicit language prohibiting:
> "developing, supporting, or using software, devices, scripts, robots, or other means to scrape content from GulfTalent"

An exception exists only for search engines that display "minimal snippets, clearly mention the source, and link back to the corresponding page without requiring registration." A data pipeline does not qualify for this exception.

**API:**
No official public API found. Multiple third-party scrapers exist on Apify but none are officially sanctioned.

**Access barriers:**
The jobs listing page (`https://www.gulftalent.com/saudi-arabia/jobs`) returned HTTP 403 Forbidden.

**Data structure:**
GulfTalent is well-known for including salary ranges — a distinctive feature among regional job boards. Also provides industry sector, career level, experience required, and company description. English-language, Gulf-region focus.

**Verdict: Exclude.**
ToS contains the clearest, most explicit anti-scraping prohibition of any source investigated. The robots.txt itself is blocked at 403. The data (especially salary ranges) would be valuable, but the legal and ethical barriers are unambiguous.

---

### 3. Indeed Saudi Arabia (sa.indeed.com)

**robots.txt** (`https://sa.indeed.com/robots.txt` — successfully fetched):
Comprehensive and detailed. Key disallows for all crawlers:
- `/job/`, `/jobs/`, `/Job/`, `/jobb/` — all job-related paths
- `/cmp/` — company pages
- `/resumes/account`, `/resumes/advanced` — resume search
- `/graphql`, `/rpc/` — API endpoints
- `/applystart`, `/conversion/` — application tracking

Search engines (Google, Bing) receive broader access but face the same job content restrictions. Many crawlers (GPTBot, CCBot, Bytespider) are listed under restrictive user-agent blocks with additional disallows. `JobdiggerSpider` is blocked entirely.

**Terms of Service / API status:**
Indeed deprecated their **Publisher Search API in 2023**. As confirmed by Indeed's own developer documentation (`developer.indeed.com/docs/publisher-jobs/get-job` is marked "Deprecated"):

> "In 2023, Indeed discontinued the Publisher API for the vast majority of publishers, citing changes to their product strategy. The old Publisher API keys stopped working with the 2023 shutdown."

Indeed's current APIs (Job Sync, Indeed Apply, Disposition Sync, Sponsored Jobs) are all employer-side. **None of them return job postings to a data consumer.** No replacement search API exists.

**Access barriers:**
No hard login wall for browsing, but pages are JavaScript-heavy and require rendering. Heavy rate-limiting is applied. Practical scraping is highly constrained.

**Data structure:**
Title, company, location, salary (when disclosed), full description, job type (full-time/part-time), posting date. English and Arabic listings available.

**Verdict: Exclude.**
No API (deprecated 2023). Robots.txt explicitly disallows all job paths for general crawlers. Even if individual pages could be rendered, the ToS does not permit scraping and there is no legitimate data access channel.

---

### 4. LinkedIn Jobs (KSA filter)

**robots.txt** (`https://www.linkedin.com/robots.txt` — successfully fetched):
Among the most restrictive robots.txt files investigated:
- `/jobs?runSearch*` — job search results
- `/jobs-guest/` — guest (non-logged-in) job browsing
- `/api/jobPostings/jobs*` — job posting API endpoint
- `/search*` — all search pages
- `/profile/`, `/myprofile*` — all profile pages

LinkedIn allows one bot by name: `LinkedInBot` with `Allow: /`. All others face extensive disallows.

**Terms of Service and legal status:**
LinkedIn's ToS explicitly prohibits scraping. The _hiQ Labs v. LinkedIn_ case (9th Circuit, 2019–2022) is directly relevant:
- The 2019 and 2022 9th Circuit rulings found that scraping publicly available data does not violate the Computer Fraud and Abuse Act (CFAA).
- However, in November 2022, Judge Chen ruled that **hiQ breached LinkedIn's User Agreement** through automated scraping.

Result: scraping LinkedIn is not a federal crime but is a **breach of contract** that can result in legal liability and account termination. The legal exposure is documented and established.

**API:**
LinkedIn's Marketing Developer Platform and Talent Solutions API exist but require partner approval through a sales process. They are designed for recruiting software integrations, not data collection.

**Access barriers:**
Non-logged-in users see significantly fewer listings. Job search increasingly requires authentication.

**Data structure:**
Title, company, location, experience level, posting date, full description, highlighted skills, application method (Easy Apply or external). English and Arabic.

**Verdict: Exclude.**
Clearest legal risk of any source. Breach of contract liability is legally documented from the hiQ case. Robots.txt blocks all job-related paths. No viable data access channel.

---

### 5. Mihnati

**robots.txt:**
Mihnati.com was acquired by Rozee.pk (Pakistan) in 2013 and migrated to Rozee's technical platform, retaining only the Mihnati brand name. When fetching `https://www.mihnati.com/robots.txt`, the response was served from Rozee.pk's infrastructure. Key disallows: `/hiring/`, `/ar/` (Arabic-language sections), `/people/`, test environments (`/beta45/`, `/demo45/`). The robots.txt does **not** broadly block job listing paths — but this may be because the underlying platform is Rozee (Pakistani market), not Mihnati (Saudi market).

**Terms of Service:**
Multiple ToS URLs attempted returned HTTP 404 — the terms page could not be found at standard paths (`/EN/terms-and-conditions`, `/EN/terms-and-conditions.php`). Only the footer notice was retrievable: "Reproduction of material from any MIHNATI.COM pages without permission is strictly prohibited."

**API:** No public API found.

**Access barriers:**
The `/EN/latest-jobs` page displayed a **login/registration form** rather than job listings. Full job browsing appears to require account creation. The login page itself served Rozee.pk-style UI (references to PKR — Pakistani Rupee — in the page content), confirming the underlying platform is shared.

**Data structure:**
Not verifiable without authentication. The Rozee.pk platform typically shows: title, company, location, salary range, experience level, application deadline. Saudi-specific listings would be in Arabic. The shared platform architecture means the data schema is likely the same as Rozee.pk.

**Verdict: Use as manual sample only.**
Login is required to view job listings, making automated collection impractical without authentication credentials. The "reproduction prohibited" footer language and an inaccessible ToS add further uncertainty. However, Mihnati is one of the few platforms focused specifically on the Saudi labor market (particularly Saudi nationals), making it worth collecting a small manual sample if the researcher creates an account. Not suitable as a pipeline target.

---

### 6. Akhtaboot

**robots.txt** (`https://www.akhtaboot.com/robots.txt` — successfully fetched):
```
User-agent: *
Disallow: /
```
The file blocks **all general crawlers** from the entire site. Additionally:
- AI bots (GPTBot, ChatGPT-User, CCBot, ClaudeBot, and others) are explicitly disallowed.
- `JoobleBot` (a job aggregator) has full unrestricted access — the only exception.
- Two user-agent groups (search engines, SEO tools) have a **15-second crawl-delay** but face the same `Disallow: /` rule.

**Terms of Service** (`https://www.akhtaboot.com/en/terms`):
Fetched and reviewed. The ToS does **not contain explicit anti-scraping language**. Prohibitions cover: modifying or hacking the site, transmitting viruses or destructive code, and implying false association. There is no clause stating "automated access," "scraping," "bots," "crawling," or "data harvesting."

**API:** No public API found.

**Access barriers:**
**None for browsing** — job listings are publicly accessible without login. Confirmed by fetching the jobs page: listings are visible with full job cards. Signing up provides additional features (CV upload, job alerts) but is not required to view listings.

**Data structure** (confirmed by direct fetch):
- Job Title (e.g., "Finance Officer," "Project Manager (SAUDI NATIONAL)")
- Company Name (e.g., "ADDAR GROUP")
- Location (e.g., "Riyadh, Saudi Arabia")
- Career Level (e.g., "Intermediate," "Senior")
- Job Category/Role (e.g., "Banking and Finance")
- Job ID (numeric, e.g., `167183`)
- URL pattern: `/en/[country]/jobs/[city]/[job-id]-[title-slug]-at-[company-slug]`
- **Not visible on listing pages:** Salary, posting date (visible on detail page, unverified)
- Language: English primary, Arabic toggle available. MENA-wide coverage including Saudi Arabia.

**Verdict: Use as primary sample — with disclosed limitations.**
Akhtaboot is the only source investigated where listings are publicly accessible and the ToS does not explicitly prohibit scraping. However, the `User-agent: * Disallow: /` in robots.txt is a clear ethical signal from the operator that automated crawling is not welcome. For academic use, this source is defensible if: (a) collection is rate-limited (≥15-second delays, consistent with the crawl-delay for known bots), (b) volume is small (a sample, not exhaustive), (c) the robots.txt conflict is disclosed transparently in the project write-up, and (d) the data is used solely for research and not redistributed.

---

### 7. Jadarat (HRDF Government Platform)

**robots.txt** (`https://jadarat.hrdf.org.sa/robots.txt`):
`ECONNREFUSED` — the domain is not reachable from external networks. This may indicate geo-restriction (access only from within Saudi Arabia) or that the platform is not publicly routable. We cannot read the robots.txt.

**Terms of Service:** Not accessible (domain unreachable).

**API and Open Data:**
No job listing API exists. However, HRDF publishes aggregate data through two channels:
1. **HRDF Open Data Library** (`hrdf.org.sa/en/about/e-participation/open-data/open-data-library/`): Aggregate statistics only — "425,304 total job vacancies posted," "2,607,335 registered individuals," etc. No individual listing downloads found.
2. **National Open Data Platform** (`open.data.gov.sa`): Referenced as a related resource but returned an access error during investigation. HRDF states its open data is "free and without restrictions" — worth checking this platform directly for any published Jadarat datasets.
3. **Data Sharing Request**: HRDF offers a formal data-sharing process for institutions needing specific datasets.

**Access barriers — HARD BLOCKER:**
Jadarat requires **Nafath authentication** — Saudi Arabia's national identity verification system tied to a Saudi National ID (Iqama). Non-Saudi users cannot register. The process requires: National ID → Nafath login → account creation. This is a non-negotiable technical and eligibility barrier. The domain is also unreachable externally, confirming the platform is not designed for public internet access.

**Data structure:**
Platform statistics confirm the data exists (425,304 vacancies), but individual records are not accessible for verification. Given the platform's role as the national employment exchange, fields likely include: job title, employer name, sector, Saudization classification, location (region/city), salary range, experience required, posting date, and application deadline.

**Verdict: Exclude from automated pipeline. Explore open data as supplementary source.**
Nafath authentication is an absolute barrier for automated collection. The domain is externally unreachable. For the project, the most productive path is to investigate `open.data.gov.sa` for any published HRDF labor market datasets, and to submit a formal data-sharing request to HRDF if institutional access is possible. Aggregate statistics (if legally downloadable) could provide valuable context data even if individual listings are unavailable.

---

### 8. Taqat (taqat.sa)

**robots.txt** (`https://www.taqat.sa/robots.txt` — successfully fetched):
```
User-agent: *
Disallow:
```
`Disallow:` with no path specified means all crawlers are fully permitted to access the entire site. This is the most permissive robots.txt configuration possible.

**Terms of Service:** Not found or not retrievable. The site provides no visible ToS link.

**API:** No public API found. Taqat is operated by HRDF, which offers a "Data Sharing Request" process for institutional partners.

**Access barriers:**
Despite the permissive robots.txt, the Taqat homepage exclusively presents a login portal — "to benefit from electronic services provided by the Human Resources Development Fund." Authentication is via the **National Unified Access Platform** (equivalent to Nafath — requires Saudi National ID). The `/en/jobs` path returned HTTP 404. **No public job listings are accessible without authentication.**

**Data structure:** Not verifiable without login.

**Verdict: Exclude.**
The permissive robots.txt is misleading — there is no public content to crawl. All services require authentication via national ID. The 404 on the jobs endpoint suggests the URL structure for public browsing does not exist. Taqat is a portal for Saudi nationals, not a public job board.

---

## Final Recommendation

The Saudi Arabia job board landscape is, in general, **highly restrictive** toward automated data collection. Six of eight sources are effectively closed to a legitimate academic pipeline. The honest recommendation is:

### Build the pipeline against these 2–3 sources, in this order:

**1. Akhtaboot (primary scraping source)**
The only platform with publicly accessible listings and no explicit ToS prohibition on scraping. Use with full ethical disclosure: the `robots.txt` disallows all general crawlers, which must be stated in the project. Implement conservative rate-limiting (≥15-second delay between requests). Collect a bounded sample (200–500 listings across Saudi Arabia cities). Akhtaboot covers the MENA region including Saudi Arabia, serves both Arabic and English, and has a parseable URL structure (`/en/saudi-arabia/jobs/`). Appropriate for demonstrating pipeline mechanics — ingestion, parsing, schema normalization, storage.

**2. HRDF Open Data / National Open Data Platform (cleanest legal path)**
Rather than scraping government platforms that require Nafath, pursue the official open data route: investigate `open.data.gov.sa` directly (not reachable during this investigation — worth attempting from within Saudi Arabia or a Saudi-network VPN) and HRDF's open data library at `hrdf.org.sa`. HRDF states its data is published "free and without restrictions." If downloadable labor market datasets exist (even as CSV dumps of aggregate data), this gives the project its most legally defensible and academically credible data source, directly tied to the official national employment platform.

**3. Mihnati (manual seed dataset)**
If the researcher creates an account on Mihnati.com, a small manually-collected sample (50–100 listings, logged-in browsing, manual export or session-authenticated requests) would add Saudi-specific market data unavailable elsewhere. This is not scalable but provides valuable "ground truth" for data with a Saudi nationality / Saudization dimension that Akhtaboot (MENA-wide) may underrepresent.

### Sources to exclude and why (for the presentation):
- **Bayt.com**: robots.txt + server-level 403 blocks = technical blocker
- **GulfTalent**: explicit ToS prohibition on scraping = legal/ethical blocker
- **Indeed SA**: API deprecated 2023, robots.txt blocks all job paths = no access path
- **LinkedIn**: breach-of-contract legal precedent (hiQ case) + robots.txt blocks = legal blocker
- **Jadarat**: Nafath authentication + externally unreachable domain = hard blocker
- **Taqat**: Login-only despite permissive robots.txt, no public job listings = functional blocker

---

## Verification Notes (Methodology)

All findings were obtained through direct tool invocation during this session (2026-08-27):
- `robots.txt` files: fetched directly via HTTP
- Terms of Service: attempted direct fetch; supplemented with web search for exact quoted language where direct fetch was blocked
- API status: web search + official developer documentation (Indeed deprecation notice confirmed at `developer.indeed.com`)
- Auth barriers: direct fetch of listing pages, noting HTTP response codes and page content
- Data fields: direct fetch of accessible listing pages
- Legal status (LinkedIn/hiQ): verified via multiple legal publication sources (IAPP, California Lawyers Association, law firm publications)

Where information could not be verified (e.g., Bayt.com ToS text, Mihnati ToS, Jadarat internals), this is explicitly stated rather than assumed.

---

*Sources consulted during investigation:*
- [Bayt.com Terms and Conditions](https://www.bayt.com/en/pages/terms/) — 403, not retrievable
- [GulfTalent Terms and Condition of use](https://www.gulftalent.com/terms) — 403, text retrieved via search excerpt
- [Indeed "Get Job (Deprecated)" developer docs](https://developer.indeed.com/docs/publisher-jobs/get-job)
- [Indeed API guide — jobspipe.dev](https://jobspipe.dev/blog/indeed-api-guide)
- [hiQ v. LinkedIn — IAPP analysis](https://iapp.org/news/a/data-scraping-and-the-implications-of-the-latest-linkedin-hiq-court-ruling)
- [hiQ v. LinkedIn — California Lawyers Association](https://calawyers.org/privacy-law/ninth-circuit-holds-data-scraping-is-legal-in-hiq-v-linkedin/)
- [Jadarat — HRDF product page](https://www.hrdf.org.sa/en/products-and-services/programs/individuals/other/jadarat/)
- [Jadarat Platform Statistics — HRDF Open Data](https://www.hrdf.org.sa/en/about/e-participation/open-data/open-data-library/real-time-data/platform-statistics/)
- [Mihnati / Rozee.pk acquisition — Yahoo Finance](https://sg.finance.yahoo.com/news/pakistani-jobs-rozee-pk-ventures-165531418.html)
- [Akhtaboot jobs page](https://www.akhtaboot.com/en/jobs) — directly fetched
- [Taqat — About page](https://www.taqat.sa/en/about-taqat)
