"""One-shot final test on the reserved month (Azm, September 2026).

This is the only code that reads September. It runs the same daily
rolling-origin procedure used for model selection (models/walk_forward.py),
with the same fixed settings and the same draft generator policy, and scores
only the test month. The 28 days before it are forecast too, only to warm up
the recent-error margin exactly as in operation.

Safeguards:
  - without --open-test-set the script runs a rehearsal on the validation
    month and reads nothing from the test month;
  - with --open-test-set it refuses to run if results/final_test_azm.json
    already exists. The test set is opened once.

Rehearsal:  python scripts/final_test.py --archive <data zip>
Real run:   python scripts/final_test.py --archive <data zip> --open-test-set
"""

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from zipfile import ZipFile

from ..data.calendar_days import load_public_holidays
from ..data.preparation import _site_records, file_sha256, hourly_means
from ..generators.policy import load_policy
from ..models.quantiles import signed_net_series
from ..models.walk_forward import POINT_METHODS, UPPER_METHODS, run, summarize, summary_markdown
from . import run_log

REPOSITORY = Path(__file__).resolve().parents[3]
RECORD = REPOSITORY / "results" / "final_test_azm.json"
WARM_UP_DAYS = 28


def read_net_load(archive_path, sites, protocol, end):
    """Azm hourly net load from the source ZIP, keeping nothing at or after `end`."""
    from collections import Counter

    site = next(item for item in sites if item["site_id"] == "azm")
    profile = {**protocol["azm"], "validation_end_exclusive": end.isoformat()}
    counters = {"timestamp_interpretations": Counter(), "positive_intervals_seconds": Counter(),
                "reserved_or_later_rows_not_used": 0, "workbooks_read": 0, "reserved_workbooks_not_opened": []}
    with ZipFile(archive_path) as archive:
        records = list(_site_records(archive, site, profile, counters))
    hourly, preparation = hourly_means(records, targets=profile["targets"],
                                       sampling_minutes=profile["sampling_minutes"], cutoff=end)
    net = signed_net_series(hourly["load"], hourly["pv"])
    if net and max(net) >= end:
        raise ValueError("Prepared data extends past the requested end")
    return net, {"rows_read": preparation["included_raw_records"],
                 "rows_at_or_after_end_not_used": counters["reserved_or_later_rows_not_used"],
                 "complete_hours": len(net)}


def evaluate(net, start, end, configuration, policy, holidays, progress=None):
    table = run(net, holidays, configuration, start - timedelta(days=WARM_UP_DAYS), end, progress=progress)
    label = f"{start:%B %Y}"
    summary = summarize({stamp: entry for stamp, entry in table.items() if stamp >= start}, policy,
                        configuration["quantile"], {label: (start, end)})
    return table, summary, label


def main():
    from threadpoolctl import threadpool_limits

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--open-test-set", action="store_true",
                        help="Read and score the reserved test month. Allowed once.")
    parser.add_argument("--protocol", type=Path, default=Path("config/baseline.json"))
    parser.add_argument("--sites", type=Path, default=Path("config/sites.json"))
    parser.add_argument("--config", type=Path, default=Path("config/walk_forward.json"))
    parser.add_argument("--policy", type=Path, default=Path("config/azm_generators.json"))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    sites = json.loads(args.sites.read_text(encoding="utf-8"))["sites"]
    configuration = json.loads(args.config.read_text(encoding="utf-8"))
    validation_start = datetime.fromisoformat(protocol["azm"]["validation_start"])
    test_start = datetime.fromisoformat(protocol["azm"]["validation_end_exclusive"])
    test_end = datetime.fromisoformat(protocol["azm"]["reserved_test_end_exclusive"])
    if args.open_test_set:
        if RECORD.exists():
            raise SystemExit(f"Refusing to run: {RECORD} exists, so the test set was already opened. "
                             "The final test is run once.")
        start, end, mode = test_start, test_end, "final_test"
    else:
        start, end, mode = validation_start, test_start, "rehearsal_on_validation_month"
    output_dir = args.output_dir or Path("outputs/final_test" if args.open_test_set else "outputs/final_test_rehearsal")
    source_sha256 = file_sha256(args.archive)
    net, preparation = read_net_load(args.archive, sites, protocol, end)
    policy = load_policy(args.policy)
    with threadpool_limits(limits=1):
        table, summary, label = evaluate(net, start, end, configuration, policy, set(load_public_holidays()),
                                         progress=lambda day: print(f"Forecast {day.date()}", flush=True)
                                         if day.day in (1, 15) else None)
    report = {"run_time_utc": datetime.now(timezone.utc).isoformat(), "mode": mode, "site_id": "azm",
              "target": "signed_net_load_kw = campus_load_kw - solar_pv_kw", "unit": "kW",
              "scored_period": [start.isoformat(), end.isoformat()], "warm_up_days": WARM_UP_DAYS,
              "test_period_scored": bool(args.open_test_set), "configuration": configuration,
              "reserve_margin_fraction": policy[2], "preparation": preparation,
              "source_sha256": source_sha256, "source_unchanged": file_sha256(args.archive) == source_sha256,
              "policy_sha256": file_sha256(args.policy), "config_sha256": file_sha256(args.config),
              "code_sha256": {name: file_sha256(Path(__file__).with_name(name) if name == "final_test.py"
                                                 else REPOSITORY / "src" / "lebanon_energy" / "models" / name)
                              for name in ("final_test.py", "walk_forward.py")},
              "summary": summary}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    (output_dir / "summary.md").write_text(summary_markdown(report), encoding="utf-8")
    columns = ["timestamp_local", "actual", *POINT_METHODS, *UPPER_METHODS]
    with (output_dir / "predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for stamp, entry in sorted(table.items()):
            if stamp >= start:
                writer.writerow({"timestamp_local": stamp.isoformat(), **{name: entry.get(name) for name in columns[1:]}})
    section = summary["periods"].get(label)
    if section is None:
        raise SystemExit("No scored hours in the requested month")
    logged = []
    for kind in ("point", "upper"):
        for method, entry in section[kind].items():
            metrics = {"undersized_hours": entry["generator_choice"]["undersized_hours"],
                       "oversized_hours": entry["generator_choice"]["oversized_hours"]}
            metrics["nmae" if kind == "point" else "coverage"] = (
                entry["nmae"] if kind == "point" else entry["quantile_scores"]["empirical_hourly_coverage"])
            logged += [{"run_time_utc": report["run_time_utc"], "script": mode, "site_id": "azm", "split": label,
                        "method": method, "metric": metric, "value": value, "hours": section["hours"],
                        "identifier_sha256": report["code_sha256"]["final_test.py"][:12]}
                       for metric, value in metrics.items()]
    run_log.append(logged)
    if args.open_test_set:
        RECORD.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        print(f"Final test recorded in {RECORD}. Do not rerun.")
    print(summary_markdown(report))


if __name__ == "__main__":
    main()
