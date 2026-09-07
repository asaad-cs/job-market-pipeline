"""
Main pipeline orchestrator.
Calls each stage in sequence for a single collection run.

Usage:
    python -m pipeline.runner
    python -m pipeline.runner --source careerjet
"""

import argparse
import logging
import uuid
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def run(source: str = "careerjet") -> None:
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    log.info("Pipeline run %s starting — source: %s", run_id, source)

    # Stage 1 — Collection
    log.info("[1/6] Collection")
    from pipeline.collectors.careerjet import collect as collect_careerjet
    from pipeline.collectors.jadarat_csv import collect as collect_jadarat

    if source == "careerjet":
        raw_records = collect_careerjet(run_id=run_id)
    elif source == "jadarat":
        raw_records = collect_jadarat(run_id=run_id)
    else:
        raise ValueError(f"Unknown source: {source!r}")

    log.info("  Collected %d raw records", len(raw_records))

    # Stage 2 — Cleaning & Standardization
    log.info("[2/6] Cleaning & Standardization")
    from pipeline.processing.cleaner import clean_records
    from pipeline.processing.standardizer import standardize_records

    cleaned = clean_records(raw_records)
    standardized = standardize_records(cleaned)

    # Stage 3 — Deduplication
    log.info("[3/6] Deduplication")
    from pipeline.processing.deduplicator import deduplicate
    deduped = deduplicate(standardized)

    # Stage 4 — Validation
    log.info("[4/6] Validation")
    from pipeline.quality.validator import validate
    validated = validate(deduped)

    # Stage 5 — Snowflake Load
    log.info("[5/6] Snowflake Load")
    from pipeline.modeling.snowflake_loader import load_to_snowflake
    loaded_count, failed = load_to_snowflake(validated)
    if failed:
        for raw_id, err in failed:
            log.warning("  Load failure: raw_id=%s error=%s", raw_id, err)

    log.info("[6/6] Done — %d records loaded to Snowflake", loaded_count)
    log.info("Run %s completed in %.1fs", run_id,
             (datetime.now(timezone.utc) - started_at).total_seconds())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Market Data Pipeline")
    parser.add_argument("--source", default="careerjet",
                        choices=["careerjet", "jadarat"],
                        help="Data source to collect from")
    args = parser.parse_args()
    run(source=args.source)
