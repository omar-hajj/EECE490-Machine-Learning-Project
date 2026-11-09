"""Score paired held-out predictions, grouped by site and prediction target.

This command consumes actual experiment outputs. It does not generate sample
forecasts, train models, or approve location-only mode for deployment.
"""

import argparse
from collections import defaultdict
import csv
from datetime import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lebanon_energy.evaluation import compare_modes


def compare_csv(path):
    groups, keys = defaultdict(list), set()
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"site_id", "timestamp", "target", "actual", "history_prediction", "location_prediction"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Missing prediction columns: " + ", ".join(sorted(required - set(reader.fieldnames or []))))
        for number, row in enumerate(reader, 2):
            if not row["site_id"].strip() or row["target"] not in {"load", "pv"}:
                raise ValueError(f"Row {number}: a site identifier and load/pv target are required")
            timestamp = datetime.fromisoformat(row["timestamp"])
            if timestamp.tzinfo is None:
                raise ValueError(f"Row {number}: timestamp must include a timezone offset")
            key = (row["site_id"], timestamp, row["target"])
            if key in keys:
                raise ValueError(f"Row {number}: repeated site/timestamp/target")
            keys.add(key)
            try:
                values = tuple(float(row[column]) for column in ("actual", "history_prediction", "location_prediction"))
            except (TypeError, ValueError) as error:
                raise ValueError(f"Row {number}: both modes must predict the same observed value") from error
            groups[(row["site_id"], row["target"])].append(values)
    if not groups:
        raise ValueError("No paired predictions supplied")
    comparisons = []
    for (site_id, target), values in sorted(groups.items()):
        actual, history, location = zip(*values)
        comparisons.append({"site_id": site_id, "target": target,
                            **compare_modes(actual, history, location)})
    return {"comparisons": comparisons, "deployment_approved": False,
            "limitations": ["Training provenance, unseen-site separation, forecast issue times and evaluation coverage must be verified separately.",
                            "No acceptance cutoff has been chosen by the user.",
                            "No per-site actual demand may be used to scale location-only predictions before evaluation."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.output.suffix.lower() != ".json":
        parser.error("Output must be a .json report")
    if arguments.output.resolve() == arguments.predictions.resolve():
        parser.error("The report cannot overwrite the prediction file")
    result = compare_csv(arguments.predictions)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Compared {len(result['comparisons'])} site/target groups. Report: {arguments.output}")


if __name__ == "__main__":
    main()
