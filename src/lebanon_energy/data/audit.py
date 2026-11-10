"""Inspect the supplied ZIP in memory without altering or extracting datasets."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, datetime
import hashlib
import io
import json
from pathlib import Path
import re
import warnings
from zipfile import ZipFile


MONTHS = {name: number for number, name in enumerate(
    ("January February March April May June July August September October November December").split(), 1
)}


def parse_timestamp(value, filename_month=None):
    """Return (timestamp, interpretation); leave ambiguity unresolved.

    For slash dates, a supplied filename month may resolve day/month order.
    This records an interpretation, not a confirmed timezone or meter clock.
    """
    if isinstance(value, datetime):
        return value, "excel_datetime"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time()), "excel_date"
    if not isinstance(value, str):
        return None, "unparsed"
    value = value.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", value):
        try:
            return datetime.fromisoformat(value), "iso_string"
        except ValueError:
            return None, "unparsed"
    candidates = set()
    for pattern in ("%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M",
                    "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
        try:
            candidate = datetime.strptime(value, pattern)
            if filename_month is None or candidate.month == filename_month:
                candidates.add(candidate)
        except ValueError:
            pass
    if len(candidates) == 1:
        interpretation = "slash_string_filename_month" if filename_month else "slash_string_unambiguous"
        return candidates.pop(), interpretation
    return None, "ambiguous" if candidates else "unparsed"


def inspect_workbook(content: bytes, label: str) -> list[dict]:
    # Import only for workbook inspection; scoring and generator modules have
    # no third-party runtime dependencies.
    from openpyxl import load_workbook

    filename_month = next((number for name, number in MONTHS.items() if name in Path(label).name), None)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Workbook contains no default style")
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    results = []
    try:
        for sheet in workbook.worksheets:
            rows = sheet.iter_rows(values_only=True)
            header = next(rows, ())
            columns = [str(value) if value is not None else f"unnamed_{index + 1}"
                       for index, value in enumerate(header)]
            result = {"source": label, "sheet": sheet.title, "columns": columns,
                      "records": 0, "first_timestamp": None, "last_timestamp": None,
                      "missing_by_column": dict.fromkeys(columns, 0),
                      "timestamp_interpretations": Counter(),
                      "repeated_timestamps": 0, "out_of_order_steps": 0,
                      "positive_interval_seconds": Counter()}
            fingerprint = hashlib.sha256()
            seen, previous = set(), None
            time_index = columns.index("Time") if "Time" in columns else None
            numeric_columns = {index: {"numeric_count": 0, "zero_count": 0, "negative_count": 0}
                               for index in range(len(columns)) if index != time_index}
            for row in rows:
                if not any(value is not None for value in row):
                    continue
                result["records"] += 1
                normalized = list(row)
                for index, name in enumerate(columns):
                    value = row[index] if index < len(row) else None
                    if value is None:
                        result["missing_by_column"][name] += 1
                    elif index in numeric_columns:
                        try:
                            number = float(value)
                        except (TypeError, ValueError):
                            continue
                        profile = numeric_columns[index]
                        profile["numeric_count"] += 1
                        profile["zero_count"] += number == 0
                        profile["negative_count"] += number < 0
                if time_index is not None:
                    timestamp, interpretation = parse_timestamp(row[time_index], filename_month)
                    result["timestamp_interpretations"][interpretation] += 1
                    if timestamp is not None:
                        # Retain offset information if it exists; do not infer
                        # Asia/Beirut or shift a source clock during inspection.
                        stamp = timestamp.isoformat(sep=" ")
                        normalized[time_index] = stamp
                        result["first_timestamp"] = min(result["first_timestamp"] or stamp, stamp)
                        result["last_timestamp"] = max(result["last_timestamp"] or stamp, stamp)
                        result["repeated_timestamps"] += stamp in seen
                        seen.add(stamp)
                        if previous is not None:
                            try:
                                seconds = (timestamp - previous).total_seconds()
                            except TypeError:
                                result["timestamp_interpretations"]["mixed_timezone_awareness"] += 1
                            else:
                                if seconds > 0:
                                    result["positive_interval_seconds"][str(seconds)] += 1
                                elif seconds < 0:
                                    result["out_of_order_steps"] += 1
                        previous = timestamp
                fingerprint.update(json.dumps(normalized, default=str, separators=(",", ":")).encode())
                fingerprint.update(b"\n")
            result["data_rows_sha256"] = fingerprint.hexdigest()
            result["numeric_profiles"] = {columns[index]: profile for index, profile in numeric_columns.items()}
            results.append(result)
    finally:
        workbook.close()
    return results


def inspect_weather(content: bytes, label: str) -> dict:
    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    header_index = next((index for index, row in enumerate(rows) if row and row[0] == "time"), None)
    if header_index is None:
        return {"source": label, "status": "unrecognized_csv_layout"}
    data = [row for row in rows[header_index + 1:] if row]
    return {"source": label, "metadata": dict(zip(rows[0], rows[1])),
            "columns": rows[header_index], "records": len(data),
            "first_timestamp": data[0][0] if data else None,
            "last_timestamp": data[-1][0] if data else None}


def audit_archive(path: Path) -> dict:
    report = {"archive_name": path.name, "archive_bytes": path.stat().st_size,
              "source_modified": False, "files_extracted": False,
              "workbooks": [], "weather": [], "other_members": [],
              "limitations": ["Source units, meter boundaries and timezone conventions are not confirmed.",
                              "No cleaning, resampling, train/test split or forecasting is performed.",
                              "Data fingerprints detect identical rows, not every type of channel duplication."]}
    with ZipFile(path) as archive:
        for member in archive.infolist():
            name = member.filename
            if member.is_dir():
                continue
            if name.lower().endswith(".xlsx") and "historical data" in name.lower():
                report["workbooks"].extend(inspect_workbook(archive.read(member), name))
            elif name.lower().endswith(".csv"):
                report["weather"].append(inspect_weather(archive.read(member), name))
            elif name.lower().endswith(".zip") and any(token in name for token in ("Household", "Industrial", "Municipality")):
                with ZipFile(io.BytesIO(archive.read(member))) as nested:
                    for child in nested.infolist():
                        if child.filename.lower().endswith(".xlsx"):
                            label = name + "::" + child.filename
                            report["workbooks"].extend(inspect_workbook(nested.read(child), label))
            else:
                report["other_members"].append({"name": name, "bytes": member.file_size})
    groups = defaultdict(list)
    for workbook in report["workbooks"]:
        # Equal column meanings are required as well as equal row values.
        key = (tuple(workbook["columns"]), workbook["records"], workbook["data_rows_sha256"])
        groups[key].append(workbook["source"])
    report["duplicate_data_groups"] = [sources for sources in groups.values() if len(sources) > 1]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.suffix.lower() != ".json":
        parser.error("The output must be a .json inspection report")
    if arguments.archive.resolve() == arguments.output.resolve():
        parser.error("The report cannot overwrite the source archive")
    report = audit_archive(arguments.archive)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Inspected {len(report['workbooks'])} measurement workbooks and {len(report['weather'])} weather files.")
    print(f"Found {len(report['duplicate_data_groups'])} duplicate data groups. Report: {arguments.output}")


if __name__ == "__main__":
    main()
