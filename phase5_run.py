"""
Phase 5 — Validation run on the 495-record production dataset.
Runs the full clean → standardize → dedup → validate pipeline,
logs quality findings, and writes a collision-audit caveat to quality_log.
"""
import io, json, sqlite3, sys, uuid
from datetime import datetime, timezone
from collections import Counter, defaultdict
sys.path.insert(0, ".")
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv()

from pipeline.processing.cleaner import clean_records
from pipeline.processing.standardizer import standardize_records
from pipeline.processing.deduplicator import deduplicate
from pipeline.quality.validator import validate, flush_quality_log

DB_PATH = "./data/pipeline.db"

# ── Load raw records ──────────────────────────────────────────────────────────
conn = sqlite3.connect(DB_PATH)
row = conn.execute(
    "SELECT run_id FROM collection_runs ORDER BY started_at DESC LIMIT 1"
).fetchone()
if not row:
    sys.exit("ERROR: No collection runs found in DB. Run collect_full.py first.")
run_id = row[0]
rows = conn.execute(
    "SELECT raw_id, run_id, source_name, source_job_id, source_url, raw_payload, collected_at "
    "FROM raw_jobs WHERE run_id=?", (run_id,)
).fetchall()
conn.close()

cols = ["raw_id","run_id","source_name","source_job_id","source_url","raw_payload","collected_at"]
raw_records = [dict(zip(cols, r)) for r in rows]

# ── Pipeline stages ───────────────────────────────────────────────────────────
cleaned      = clean_records(raw_records)
standardized = standardize_records(cleaned)
deduped      = deduplicate(standardized)
validated    = validate(deduped)
quality_entries = flush_quality_log()

# ── Collision caveat: add a quality_log entry for the false-merge finding ─────
# Manual audit of 10 sampled collision pairs found:
#   9/10 true duplicates (same posting, Careerjet formatting variants)
#   1/10 false merge: "Mechanical Engineer" (null company, null city)
# The null+null case degenerates the 3-component fingerprint to title-only,
# making it near-useless for generic titles.
collision_caveat = {
    "log_id":    str(uuid.uuid4()),
    "job_id":    None,
    "rule_name": "DEDUP-FINGERPRINT-AUDIT",
    "severity":  "warning",
    "message": (
        "Phase 4 collision audit (10 sampled pairs, 61 total collision groups, 125 records): "
        "9/10 pairs are true duplicates (same posting with Careerjet 'Job Description:' prefix "
        "or en-dash/hyphen formatting variants). 1/10 is a confirmed false merge: "
        "'Mechanical Engineer' with null company and null city — the 3-component fingerprint "
        "degenerates to title-only when both company and city are null, colliding any two "
        "identically-titled listings. Estimated real false-merge rate: ~10% of collision "
        "records (~13 records, ~2.6% of 495 total). Documented per §10a known limitation."
    ),
    "logged_at": datetime.now(timezone.utc).isoformat(),
}
quality_entries.append(collision_caveat)

# ── Write quality_log to DB ───────────────────────────────────────────────────
conn = sqlite3.connect(DB_PATH)
for entry in quality_entries:
    try:
        conn.execute(
            "INSERT OR IGNORE INTO quality_log VALUES (?,?,?,?,?,?)",
            (entry["log_id"], entry.get("job_id"), entry["rule_name"],
             entry["severity"], entry["message"], entry["logged_at"])
        )
    except Exception as e:
        pass  # duplicate log_id on re-run — safe to skip
conn.commit()
total_logged = conn.execute("SELECT COUNT(*) FROM quality_log").fetchone()[0]
conn.close()

# ── Summarise results ─────────────────────────────────────────────────────────
total    = len(validated)
rejected = sum(1 for r in validated if r.get("is_rejected"))
dup      = sum(1 for r in validated if r.get("is_duplicate"))
clean_r  = total - rejected - dup

rule_counts = Counter()
severity_counts = Counter()
for entry in quality_entries:
    rule_counts[entry["rule_name"]] += 1
    severity_counts[entry["severity"]] += 1

print(f"\n{'='*60}")
print(f"PHASE 5 — VALIDATION RESULTS")
print(f"{'='*60}")
print(f"  Total records          : {total}")
print(f"  Rejected (is_rejected) : {rejected}")
print(f"  Duplicates (is_dup)    : {dup}")
print(f"  Clean / non-dup        : {clean_r}")
print(f"")
print(f"  Quality log entries    : {len(quality_entries)}")
print(f"    error                : {severity_counts['error']}")
print(f"    warning              : {severity_counts['warning']}")
print(f"    info                 : {severity_counts['info']}")
print(f"  quality_log DB total   : {total_logged}")
print(f"")
print(f"  Rule breakdown (top 10 by frequency):")
print(f"  {'Rule':<28}  {'Count':>6}")
print(f"  {'-'*36}")
for rule, count in rule_counts.most_common(10):
    print(f"  {rule:<28}  {count:>6}")

# ── Career level distribution ─────────────────────────────────────────────────
level_dist = Counter(r.get("career_level") for r in validated)
print(f"\n  Career level distribution (all {total} records):")
for level, count in sorted(level_dist.items(), key=lambda x: -x[1]):
    print(f"    {level or 'None':<16}: {count:>4}  ({100.0*count/total:.1f}%)")

# ── Salary parse results ──────────────────────────────────────────────────────
sal_populated = sum(1 for r in validated if r.get("salary_min") is not None)
sal_usd = sum(1 for r in validated if r.get("salary_currency") == "USD")
sal_sar = sum(1 for r in validated if r.get("salary_currency") == "SAR")
print(f"\n  Salary parse results (from 23 non-null salary_raw values):")
print(f"    salary_min populated : {sal_populated}")
print(f"    currency=SAR         : {sal_sar}")
print(f"    currency=USD         : {sal_usd}")
print(f"\n{'='*60}")
