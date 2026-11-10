"""Observed Azm generator output and operating pattern (roadmap Week 1, Product).

The export has no nameplate ratings, so the roadmap's fallback is used: each
unit's highest observed five-minute output before the reserved September test
month. An observed maximum is a lower bound on a unit's rating, not a verified
usable capacity. The draft policy below is labelled as such until the school
confirms ratings, permitted combinations and a reserve margin.

The status columns also describe the current practice: which unit, or which
parallel combination, actually ran for whole hours, and at what net load.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import math
from pathlib import Path
from zipfile import ZipFile

from .baselines import _site_records, file_sha256

GENERATOR_IDS = ("G1", "G2", "G3", "G4")
SAMPLING_MINUTES = 5


def _profile(cutoff):
    targets = {"load": "Load Power", "pv": "Production", "utility_kw": "Utility Power",
               "utility_status": "Utility Status"}
    for index, generator_id in enumerate(GENERATOR_IDS, start=1):
        targets[f"{generator_id}_kw"] = f"Generator {index} Power"
        targets[f"{generator_id}_status"] = f"Generator {index} Status"
    return {"validation_end_exclusive": cutoff.isoformat(), "targets": targets}


def _number(value):
    if value is None or value == "":
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def read_records(archive_path, site, cutoff):
    """Yield (timestamp, numeric values) for Azm rows strictly before cutoff."""
    counters = {"timestamp_interpretations": Counter(), "positive_intervals_seconds": Counter(),
                "reserved_or_later_rows_not_used": 0, "workbooks_read": 0,
                "reserved_workbooks_not_opened": []}
    with ZipFile(archive_path) as archive:
        for timestamp, values in _site_records(archive, site, _profile(cutoff), counters):
            yield timestamp, {key: _number(value) for key, value in values.items()}


def _quantile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def configuration_label(running):
    return "+".join(running) if running else "none"


def summarize(records, generator_ids=GENERATOR_IDS, samples_per_hour=60 // SAMPLING_MINUTES):
    """Per-unit output statistics and whole-hour configuration usage.

    records: iterable of (timestamp, values) with keys load, pv, utility_kw,
    utility_status and <id>_kw / <id>_status for every generator id.
    A configuration counts as deliberately operated in an hour only when all
    samples_per_hour readings of that hour exist and share one configuration;
    brief overlaps during handover therefore do not count.
    """
    outputs = {g: [] for g in generator_ids}
    running_outputs = {g: [] for g in generator_ids}
    status_samples = Counter()
    mismatches = Counter()
    hours = defaultdict(list)
    balance_checked = balance_within = utility_on = samples = 0
    for timestamp, values in records:
        samples += 1
        running = []
        for g in generator_ids:
            power, status = values.get(f"{g}_kw"), values.get(f"{g}_status")
            if power is not None:
                outputs[g].append(power)
            if status == 1:
                running.append(g)
                status_samples[g] += 1
                if power is not None:
                    running_outputs[g].append(power)
            if power is not None and status is not None and (power > 1) != (status == 1):
                mismatches[g] += 1
        if values.get("utility_status") == 1:
            utility_on += 1
        load, pv = values.get("load"), values.get("pv")
        generated = [values.get(f"{g}_kw") for g in generator_ids]
        if load and pv is not None and all(v is not None for v in generated):
            supplied = math.fsum(generated) + pv + (values.get("utility_kw") or 0.0)
            balance_checked += 1
            balance_within += abs(supplied - load) <= 0.1 * load
        net = load - pv if load is not None and pv is not None else None
        hours[timestamp.replace(minute=0, second=0, microsecond=0)].append((tuple(running), net))
    if not samples:
        raise ValueError("No generator records were read")

    units = []
    for g in generator_ids:
        units.append({
            "generator_id": g,
            "observed_max_kw": max(outputs[g]) if outputs[g] else None,
            "p99_kw_while_running": _quantile(running_outputs[g], 0.99),
            "median_kw_while_running": _quantile(running_outputs[g], 0.5),
            "share_of_samples_running": status_samples[g] / samples,
            "power_status_disagreements": mismatches[g],
        })

    usage = defaultdict(list)
    complete_hours = 0
    for hour_samples in hours.values():
        configurations = {running for running, _ in hour_samples}
        nets = [net for _, net in hour_samples if net is not None]
        if len(hour_samples) == samples_per_hour and len(configurations) == 1 and len(nets) == samples_per_hour:
            complete_hours += 1
            usage[configuration_label(next(iter(configurations)))].append(math.fsum(nets) / len(nets))
    configurations = []
    for label, nets in sorted(usage.items(), key=lambda item: -len(item[1])):
        configurations.append({"configuration": label, "whole_hours": len(nets),
                               "net_load_kw_median": _quantile(nets, 0.5),
                               "net_load_kw_p95": _quantile(nets, 0.95),
                               "net_load_kw_max": max(nets)})
    return {"samples": samples, "hours_seen": len(hours), "whole_single_configuration_hours": complete_hours,
            "utility_on_share": utility_on / samples,
            "power_balance_rows_checked": balance_checked,
            "power_balance_within_10pct_share": balance_within / balance_checked if balance_checked else None,
            "units": units, "configurations": configurations}


def draft_policy(summary, *, minimum_whole_hours=3, reserve_margin_fraction=0.10):
    """Draft selection inputs: observed-maximum capacities and sustained configurations.

    Every single unit is allowed. A parallel combination is allowed only when
    the data show it running unchanged for at least minimum_whole_hours whole
    hours. No all-off configuration is included because the school never ran
    without a generator in the inspected period.
    """
    generators = []
    for unit in summary["units"]:
        if not unit["observed_max_kw"] or unit["observed_max_kw"] <= 0:
            raise ValueError(f"No positive observed output for {unit['generator_id']}")
        generators.append({"generator_id": unit["generator_id"],
                           "usable_capacity_kw": round(unit["observed_max_kw"], 1),
                           "capacity_basis": "highest observed 5-minute output (lower bound on rating)"})
    allowed = [[unit["generator_id"]] for unit in summary["units"]]
    for entry in summary["configurations"]:
        members = entry["configuration"].split("+")
        if len(members) > 1 and entry["whole_hours"] >= minimum_whole_hours:
            allowed.append(members)
    return {"status": "draft_from_observed_data_pending_school_confirmation",
            "generators": generators, "allowed_configurations": allowed,
            "reserve_margin_fraction": reserve_margin_fraction,
            "parallel_rule": f"parallel combinations observed for at least {minimum_whole_hours} whole hours",
            "selection_rule": "Run the smallest allowed configuration whose capacity covers the forecast net load (load minus PV) times (1 + reserve margin); ties go to the operator."}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sites", type=Path, default=Path("config/sites.json"))
    parser.add_argument("--cutoff", default="2026-09-01", help="Exclusive end; September stays reserved")
    parser.add_argument("--policy-output", type=Path, default=Path("config/azm_generators.json"))
    parser.add_argument("--summary-output", type=Path, default=Path("outputs/generators/azm_generator_summary.json"))
    args = parser.parse_args()
    cutoff = datetime.fromisoformat(args.cutoff)
    if cutoff > datetime(2026, 9, 1):
        raise ValueError("The September 2026 test month must stay unread")
    site = next(s for s in json.loads(args.sites.read_text(encoding="utf-8"))["sites"] if s["site_id"] == "azm")
    summary = summarize(read_records(args.archive, site, cutoff))
    summary.update({"source_sha256": file_sha256(args.archive), "data_end_exclusive": cutoff.isoformat()})
    policy = draft_policy(summary)
    policy.update({"site_id": "azm", "unit": "kW", "derived_from": "scripts/extract_generators.py",
                   "data_end_exclusive": cutoff.isoformat(), "source_sha256": summary["source_sha256"]})
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    args.policy_output.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
    for unit in summary["units"]:
        print(f"{unit['generator_id']}: observed max {unit['observed_max_kw']:.1f} kW, "
              f"running {100 * unit['share_of_samples_running']:.1f}% of samples")
    print("Allowed configurations:", [configuration_label(c) for c in policy["allowed_configurations"]])
    print(f"Wrote {args.policy_output} and {args.summary_output}")
