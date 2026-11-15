"""Append experiment scores to one CSV so every reported number has a logged run.

results/run_log.csv is kept in Git. It holds scores only, never measurements.
"""

import csv
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "results" / "run_log.csv"
COLUMNS = ("run_time_utc", "script", "site_id", "split", "method", "metric", "value", "hours", "identifier_sha256")


def append(rows, path=DEFAULT_PATH):
    """rows are dicts with the COLUMNS keys; unknown keys are an error."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.is_file()
    with path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)
    return len(rows)
