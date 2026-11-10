"""Re-download Azm's two weather files from Open-Meteo and compare them with the supplied copies.

Roadmap Week 1, stream A: "Script every weather download ... so one command
re-fetches the exact data". The data ZIP contains two hand-downloaded files:

- azm_weather_observed.csv.csv: Open-Meteo Historical Weather (archive) API.
- azm_weather_forecast_day1.csv.csv: Open-Meteo Previous Runs API, the
  forecast issued one day earlier (`_previous_day1` variables).

Both use the Azm map pin from config/sites.json, Beirut local time and the
same six variables. This script requests them in the same CSV layout, saves
each response with its request and SHA-256 hash, and reports how many hours
match the supplied file. The Previous Runs service was intermittently
unreachable from the AUB network in November 2026; the script then says so,
and the forecast part can be retried later or on another network.

Finding of 2026-11-10: the observed file is reproduced (4,029 of 4,032 hours
identical). The forecast file is not: Open-Meteo's default blend returns the
same grid point, but the values it serves today differ from the supplied
copy, and no single model matches it either. The provider has updated
its archive since the original download, so the saved copy with its hash is
what makes the forecast input reproducible.
"""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zipfile import ZipFile

VARIABLES = ("temperature_2m", "relative_humidity_2m", "shortwave_radiation", "cloud_cover",
             "diffuse_radiation", "direct_radiation")
SOURCES = {
    "observed": {"url": "https://archive-api.open-meteo.com/v1/archive", "suffix": "",
                 "supplied": "azm_weather_observed.csv.csv"},
    "forecast": {"url": "https://previous-runs-api.open-meteo.com/v1/forecast", "suffix": "_previous_day1",
                 "supplied": "azm_weather_forecast_day1.csv.csv"},
}
START, END = "2026-04-16", "2026-09-30"


def request_parameters(kind, latitude, longitude, start=START, end=END):
    suffix = SOURCES[kind]["suffix"]
    return {"latitude": latitude, "longitude": longitude, "start_date": start, "end_date": end,
            "hourly": ",".join(name + suffix for name in VARIABLES), "timezone": "Asia/Beirut", "format": "csv"}


def parse_open_meteo_csv(text):
    """Return (metadata dict, header list, {time: [values]}) from Open-Meteo's CSV layout."""
    lines = text.splitlines()
    metadata = dict(zip(lines[0].split(","), lines[1].split(",")))
    table = list(csv.reader(lines[3:]))
    return metadata, table[0], {row[0]: row[1:] for row in table[1:] if row}


def compare(downloaded_text, supplied_text):
    """Hour-by-hour comparison of two files in Open-Meteo's CSV layout."""
    meta_new, header_new, new = parse_open_meteo_csv(downloaded_text)
    meta_old, header_old, old = parse_open_meteo_csv(supplied_text)
    differing = []
    for stamp in sorted(set(new) | set(old)):
        if new.get(stamp) != old.get(stamp):
            differing.append({"time": stamp, "downloaded": new.get(stamp), "supplied": old.get(stamp)})
    same_grid = (meta_new.get("latitude"), meta_new.get("longitude")) == (meta_old.get("latitude"), meta_old.get("longitude"))
    mean_abs = {}
    for index, column in enumerate(header_new[1:]):
        gaps = [abs(float(new[t][index]) - float(old[t][index])) for t in set(new) & set(old)
                if new[t][index] not in ("", None) and old[t][index] not in ("", None)]
        mean_abs[column] = sum(gaps) / len(gaps) if gaps else None
    return {"same_columns": header_new == header_old, "same_grid_point": same_grid,
            "mean_absolute_difference": mean_abs,
            "grid_point": [meta_new.get("latitude"), meta_new.get("longitude")],
            "hours_downloaded": len(new), "hours_supplied": len(old),
            "identical_hours": len(set(new) & set(old)) - sum(1 for d in differing if d["downloaded"] and d["supplied"]),
            "differing_hours": differing[:50], "differing_hours_total": len(differing)}


def download(url, parameters, timeout=120):
    request = Request(url + "?" + urlencode(parameters), headers={"User-Agent": "eece490-weather-script"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def run(kinds, latitude, longitude, output_dir, archive=None, fetch=download):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    supplied = {}
    if archive:
        with ZipFile(archive) as zipped:
            for kind in kinds:
                name = next(m for m in zipped.namelist() if Path(m).name == SOURCES[kind]["supplied"])
                supplied[kind] = zipped.read(name).decode("utf-8")
    manifest = {"site_id": "azm", "latitude": latitude, "longitude": longitude, "files": {}}
    for kind in kinds:
        parameters = request_parameters(kind, latitude, longitude)
        entry = {"url": SOURCES[kind]["url"], "parameters": parameters,
                 "requested_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        try:
            text = fetch(SOURCES[kind]["url"], parameters)
        except OSError as error:
            host = SOURCES[kind]["url"].split("/")[2]
            entry.update(status="failed", error=str(error),
                         advice=f"Could not reach {host}. It is intermittently blocked on some networks "
                                f"(AUB in November 2026); retry `python scripts/download_azm_weather.py --only {kind}` "
                                f"later or on another network.")
        else:
            path = output_dir / f"azm_weather_{kind}.csv"
            path.write_text(text, encoding="utf-8", newline="")
            entry.update(status="downloaded", file=path.name,
                         sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
            if kind in supplied:
                entry["comparison_with_supplied_file"] = compare(text, supplied[kind])
        manifest["files"][kind] = entry
    previous = output_dir / "manifest.json"
    if previous.is_file():  # keep results of a part not re-run this time
        old = json.loads(previous.read_text(encoding="utf-8")).get("files", {})
        manifest["files"] = {**{k: v for k, v in old.items() if k not in kinds}, **manifest["files"]}
    previous.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sites", type=Path, default=Path("config/sites.json"))
    parser.add_argument("--archive", type=Path, help="Data ZIP; when given, compare with the supplied files")
    parser.add_argument("--only", choices=sorted(SOURCES), help="Download one part only")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/weather_azm"))
    args = parser.parse_args()
    azm = next(s for s in json.loads(args.sites.read_text(encoding="utf-8"))["sites"] if s["site_id"] == "azm")
    kinds = [args.only] if args.only else list(SOURCES)
    manifest = run(kinds, azm["latitude"], azm["longitude"], args.output_dir, args.archive)
    failed = False
    for kind in kinds:
        entry = manifest["files"][kind]
        if entry["status"] != "downloaded":
            failed = True
            print(f"{kind}: FAILED. {entry['advice']}")
            continue
        line = f"{kind}: saved {entry['file']} (sha256 {entry['sha256'][:12]}...)"
        result = entry.get("comparison_with_supplied_file")
        if result:
            line += (f" | {result['identical_hours']}/{result['hours_supplied']} hours identical to the supplied file"
                     f" | same grid point: {result['same_grid_point']} | same columns: {result['same_columns']}")
        print(line)
    print(f"Manifest: {args.output_dir / 'manifest.json'}")
    if failed:
        raise SystemExit(1)
