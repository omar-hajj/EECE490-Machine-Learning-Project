"""Prepare Azm weather features with explicit clock and interval semantics."""

import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lebanon_energy.data.preparation import file_sha256
from lebanon_energy.data.weather import VARIABLES, aligned_features, read_forecast_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--sites", required=True, type=Path)
    parser.add_argument("--baseline-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    sites = json.loads(args.sites.read_text(encoding="utf-8"))["sites"]
    azm = next(site for site in sites if site["site_id"] == "azm")
    if azm.get("meter_clock") != "Asia/Beirut" or not azm.get("meter_clock_observes_dst"):
        raise ValueError("Azm meter clock must be explicitly confirmed before joining weather")
    baseline_report = json.loads((args.baseline_dir / "results.json").read_text())
    group = next(group for group in baseline_report["groups"] if group["site_id"] == "azm")
    cutoff = datetime.fromisoformat(group["validation_end_exclusive"])
    hours = set()
    with (args.baseline_dir / "hourly_data.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["site_id"] == "azm":
                hour = datetime.fromisoformat(row["timestamp_local_unverified"])
                if hour >= cutoff:
                    raise ValueError("Reserved test hour appears in baseline input")
                hours.add(hour)
    with ZipFile(args.archive) as archive:
        names = [name for name in archive.namelist() if name.endswith("azm_weather_forecast_day1.csv.csv")]
        if len(names) != 1:
            raise ValueError("Expected the supplied day-ahead forecast CSV")
        content = archive.read(names[0])
    metadata, values = read_forecast_csv(content, cutoff)
    records, missing = [], []
    for hour in sorted(hours):
        aligned = aligned_features(values, hour, azm["meter_clock"])
        if aligned is None:
            missing.append(hour.isoformat())
            continue
        records.append({"site_id": "azm", "timestamp_local": hour.isoformat(),
                        **aligned["features"],
                        "nominal_available_at_local": aligned["nominal_available_at_local"].isoformat(),
                        "nominal_available_at_utc": aligned["nominal_available_at_utc"].isoformat(),
                        "nominal_margin_hours": aligned["nominal_margin_hours"],
                        "publication_availability_verified": False})
    if not records:
        raise ValueError("No aligned weather features available")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "features.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    report = {"site_id": "azm", "meter_clock": azm["meter_clock"], "clock_confirmed_by_user": True,
              "weather_metadata": metadata, "forecast_csv_sha256": hashlib.sha256(content).hexdigest(),
              "source_sha256": file_sha256(args.archive), "reserved_test_weather_values_analyzed": False,
              "feature_names": list(VARIABLES), "aligned_hours": len(records),
              "missing_weather_hours": missing, "publication_availability_verified": False,
              "nominal_margin_range_hours": [min(row["nominal_margin_hours"] for row in records),
                                             max(row["nominal_margin_hours"] for row in records)],
              "alignment": {"instantaneous_fields": "Use valid time at meter-hour start, converting fixed CSV UTC offset to Asia/Beirut",
                            "radiation_fields": "Use valid time at meter-hour end because radiation is averaged over the preceding hour"},
              "availability_limitation": "previous_day1 implies nominal valid time minus 24 hours; exact publication times were not supplied.",
              "references": ["https://open-meteo.com/en/docs", "https://open-meteo.com/en/docs/previous-runs-api"]}
    (args.output_dir / "metadata.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Prepared {len(records)} aligned Azm weather hours; {len(missing)} missing. Publication availability remains unverified.")


if __name__ == "__main__":
    main()
