"""
HRDF / Jadarat Open Data collector.

Source: open.data.gov.sa — "Private/Public/Semigov Sector Job Listings on Jadarat Platform"
Format: CSV / XLSX, quarterly, Open Data License.
Language: Arabic.

Status: CSV columns not yet inspected (OQ-3). This module is a stub.
Implement after confirming: (1) column names, (2) individual listings vs. aggregate rows,
(3) Arabic field values that need normalization.
"""

import logging

log = logging.getLogger(__name__)


def collect(run_id: str, csv_path: str | None = None) -> list[dict]:
    """
    Load Jadarat job listings from a locally downloaded CSV/XLSX file.

    Args:
        run_id: UUID for this collection run.
        csv_path: Path to the downloaded Jadarat CSV/XLSX file.

    Returns:
        List of raw record dicts (same shape as careerjet.collect output).

    Raises:
        NotImplementedError: Until OQ-3 (column inspection) is resolved.
    """
    raise NotImplementedError(
        "Jadarat CSV collector is not yet implemented. "
        "First inspect the CSV columns (OQ-3) to confirm field names, then implement."
    )
