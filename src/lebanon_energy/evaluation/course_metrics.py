"""Score the served model with the metrics of course chapter 6 (model tuning and testing).

1. Regression metrics (MBE, MAE, MSE, RMSE) on training fit, validation and test,
   to read the train/test gap (underfitting vs. overfitting).
2. Fold consistency: the same metrics month by month (rolling origin is the
   time-series form of K-fold cross-validation).
3. Classification metrics for the decision itself: the generator
   configuration picked against the one needed, as a multi-class confusion
   matrix with per-class precision and recall, macro averages and F1.
4. Statistical tests for "is model A really better than B": McNemar on paired
   hourly outcomes and the Z-test for a difference in proportions.

Sign convention follows the notes: MBE = mean(actual - forecast), so a
positive MBE means the model under-predicts.

Everything is computed from saved predictions. Nothing is refitted except
the two in-sample fits used for the training-error column, and nothing here
reads the test month from the source data.
"""

import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from ..data.calendar_days import load_public_holidays
from ..features.holidays import holiday_aware_features
from ..generators.policy import Generator, recommend
from ..models.quantiles import signed_net_series
from ..models.ridge import load_inputs, make_pipeline
from ..models.walk_forward import boosted
from .error_analysis import BASELINE, POINT, UPPER

XGBOOST, XGBOOST_UPPER = "xgboost", "xgboost_p90"


def regression_metrics(actual, forecast):
    errors = [a - f for a, f in zip(actual, forecast)]
    count = len(errors)
    if not count:
        return None
    mse = math.fsum(e * e for e in errors) / count
    mae = math.fsum(abs(e) for e in errors) / count
    return {"n": count, "mbe": math.fsum(errors) / count, "mae": mae, "mse": mse, "rmse": math.sqrt(mse),
            "nmae": mae / (math.fsum(abs(a) for a in actual) / count)}


def read_predictions(path, columns):
    rows = {}
    with Path(path).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            values = {name: float(row[name]) if row.get(name) not in (None, "") else None for name in columns}
            if all(value is not None for value in values.values()):
                rows[datetime.fromisoformat(row["timestamp_local"])] = values
    return rows


def training_fit(net, holidays, end, configuration):
    """In-sample error of Ridge and XGBoost fitted on every hour before `end` and scored on those hours."""
    rows, targets = [], []
    for stamp in sorted(net):
        if stamp >= end:
            continue
        features, _ = holiday_aware_features(net, stamp, holidays)
        if features is not None:
            rows.append(features)
            targets.append(net[stamp])
    ridge = make_pipeline(configuration["ridge_alpha"]).fit(rows, targets)
    trees = boosted(configuration["xgboost"]).fit(rows, targets)
    return {POINT: regression_metrics(targets, [float(v) for v in ridge.predict(rows)]),
            XGBOOST: regression_metrics(targets, [float(v) for v in trees.predict(rows)])}


def confusion(needed, picked, classes):
    """Multi-class confusion matrix (rows = needed, columns = picked) with the notes' per-class metrics."""
    index = {label: position for position, label in enumerate(classes)}
    matrix = [[0] * len(classes) for _ in classes]
    for truth, choice in zip(needed, picked):
        matrix[index[truth]][index[choice]] += 1
    total = sum(map(sum, matrix))
    per_class = {}
    for label, i in index.items():
        column, row = sum(matrix[j][i] for j in range(len(classes))), sum(matrix[i])
        precision = matrix[i][i] / column if column else None
        recall = matrix[i][i] / row if row else None
        f1 = (2 * precision * recall / (precision + recall)
              if precision is not None and recall is not None and precision + recall > 0 else None)
        per_class[label] = {"needed_hours": row, "picked_hours": column, "precision": precision, "recall": recall, "f1": f1}
    present = [values for values in per_class.values() if values["needed_hours"]]

    def macro(key):
        scores = [values[key] if values[key] is not None else 0.0 for values in present]
        return math.fsum(scores) / len(scores) if scores else None

    return {"classes": classes, "matrix": matrix, "accuracy": sum(matrix[i][i] for i in range(len(classes))) / total,
            "per_class": per_class, "macro_precision": macro("precision"), "macro_recall": macro("recall"),
            "macro_f1": macro("f1"),
            "below_needed": sum(matrix[i][j] for i in range(len(classes)) for j in range(i)) / total,
            "above_needed": sum(matrix[i][j] for i in range(len(classes)) for j in range(i + 1, len(classes))) / total}


def chi_square_1df_p(statistic):
    """p-value of a chi-squared statistic with 1 degree of freedom."""
    return math.erfc(math.sqrt(statistic / 2))


def mcnemar(correct_1, correct_2):
    """McNemar test on paired outcomes, as in the notes: chi2 = (B - C)^2 / (B + C)."""
    b = sum(first and not second for first, second in zip(correct_1, correct_2))
    c = sum(second and not first for first, second in zip(correct_1, correct_2))
    statistic = (b - c) ** 2 / (b + c) if b + c else 0.0
    return {"n": len(correct_1), "only_first_correct_B": b, "only_second_correct_C": c,
            "accuracy_first": sum(correct_1) / len(correct_1), "accuracy_second": sum(correct_2) / len(correct_2),
            "chi_square": statistic, "p_value": chi_square_1df_p(statistic) if b + c else 1.0}


def proportion_z_test(accuracy_1, accuracy_2, n):
    """Z-test for a difference in proportions with the notes' variance: acc(1 - acc) / n each."""
    variance = accuracy_1 * (1 - accuracy_1) / n + accuracy_2 * (1 - accuracy_2) / n
    z = (accuracy_1 - accuracy_2) / math.sqrt(variance) if variance > 0 else 0.0
    return {"z": z, "p_value_two_sided": math.erfc(abs(z) / math.sqrt(2))}


def paired_error_z_test(actual, forecast_1, forecast_2):
    """Z-test on the mean hourly difference in absolute error (first minus second).

    Hourly errors are correlated in time, so the true uncertainty is larger
    than this test assumes. Treat a borderline result as not significant.
    """
    differences = [abs(a - f1) - abs(a - f2) for a, f1, f2 in zip(actual, forecast_1, forecast_2)]
    n = len(differences)
    mean = math.fsum(differences) / n
    deviation = math.sqrt(math.fsum((d - mean) ** 2 for d in differences) / (n - 1))
    z = mean / (deviation / math.sqrt(n)) if deviation > 0 else 0.0
    return {"n": n, "mean_difference_kw": mean, "z": z, "p_value_two_sided": math.erfc(abs(z) / math.sqrt(2))}


def decision_scores(rows, policy):
    """Generator-choice outcomes for the served rule and the alternatives, on the same hours."""
    generators = [Generator(item["generator_id"], float(item["usable_capacity_kw"])) for item in policy["generators"]]
    allowed, reserve = policy["allowed_configurations"], float(policy["reserve_margin_fraction"])
    names = {}
    for configuration in allowed:
        capacity = math.fsum(g.usable_capacity_kw for g in generators if g.generator_id in configuration)
        names.setdefault(capacity, []).append("+".join(sorted(configuration)))
    classes = [" or ".join(names[capacity]) for capacity in sorted(names)]
    label = {capacity: " or ".join(names[capacity]) for capacity in names}
    order = {name: position for position, name in enumerate(classes)}

    def pick(value, margin):
        return recommend(max(value, 0.0), generators, allowed_configurations=allowed,
                         reserve_margin_fraction=margin)["selected_capacity_kw"]

    stamps = sorted(rows)
    needed = [pick(rows[s]["actual"], 0.0) for s in stamps]
    picks = {method: [pick(rows[s][method], reserve) for s in stamps] for method in (UPPER, XGBOOST_UPPER, BASELINE, POINT)}
    usable = [i for i in range(len(stamps)) if needed[i] is not None and all(p[i] is not None for p in picks.values())]
    result = {"hours": len(usable), "methods": {}}
    outcomes = {}
    for method, chosen in picks.items():
        truth = [label[needed[i]] for i in usable]
        choice = [label[chosen[i]] for i in usable]
        matrix = confusion(truth, choice, classes)
        outcomes[method] = {"right": [t == c for t, c in zip(truth, choice)],
                            "safe": [order[c] >= order[t] for t, c in zip(truth, choice)]}
        result["methods"][method] = matrix
    comparisons = {}
    for other in (XGBOOST_UPPER, BASELINE, POINT):
        for outcome in ("safe", "right"):
            test = mcnemar(outcomes[UPPER][outcome], outcomes[other][outcome])
            test["z_test"] = proportion_z_test(test["accuracy_first"], test["accuracy_second"], test["n"])
            comparisons[f"{UPPER} vs {other} ({outcome})"] = test
    result["comparisons"] = comparisons
    return result


def analyse(validation_csv, test_csv, policy, net, holidays, validation_start, configuration):
    columns = ("actual", POINT, UPPER, BASELINE, XGBOOST, XGBOOST_UPPER)
    validation = read_predictions(validation_csv, columns)
    test = read_predictions(test_csv, columns) if test_csv and Path(test_csv).is_file() else {}
    splits = {"rolling origin before validation": {s: v for s, v in validation.items() if s < validation_start},
              "validation month": {s: v for s, v in validation.items() if s >= validation_start}}
    if test:
        splits["test month"] = test
    report = {"regression": {"training fit (in-sample)": training_fit(net, holidays, validation_start, configuration)},
              "folds": {}, "error_tests": {}, "decision": {}}
    for name, rows in splits.items():
        stamps = sorted(rows)
        actual = [rows[s]["actual"] for s in stamps]
        report["regression"][name] = {method: regression_metrics(actual, [rows[s][method] for s in stamps])
                                      for method in (POINT, XGBOOST, BASELINE)}
        report["error_tests"][name] = {
            f"{POINT} vs {other}": paired_error_z_test(actual, [rows[s][POINT] for s in stamps],
                                                       [rows[s][other] for s in stamps])
            for other in (BASELINE, XGBOOST)}
        report["decision"][name] = decision_scores(rows, policy)
    everything = {**validation, **test}
    for month in dict.fromkeys(stamp.strftime("%B") for stamp in sorted(everything)):
        rows = {s: v for s, v in everything.items() if s.strftime("%B") == month}
        stamps = sorted(rows)
        actual = [rows[s]["actual"] for s in stamps]
        report["folds"][month] = {method: regression_metrics(actual, [rows[s][method] for s in stamps])
                                  for method in (POINT, XGBOOST, BASELINE)}
    return report


def summary_markdown(report):
    names = {POINT: "Ridge, holiday-aware (served)", XGBOOST: "XGBoost", BASELINE: "Same hour last week",
             UPPER: "Served rule", XGBOOST_UPPER: "XGBoost P90 rule"}
    lines = ["# Model scored with the chapter 6 metrics", "",
             "MBE = mean(actual - forecast): positive means the model under-predicts. Units are kW (MSE in kW^2).", "",
             "## Regression metrics by split", "",
             "| Split | Method | n | MBE | MAE | MSE | RMSE | MAE / mean load |", "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for split, methods in report["regression"].items():
        for method, m in methods.items():
            lines.append(f"| {split} | {names[method]} | {m['n']} | {m['mbe']:+.1f} | {m['mae']:.1f} | {m['mse']:.0f} | "
                         f"{m['rmse']:.1f} | {m['nmae']:.1%} |")
    lines += ["", "## Consistency across folds (months)", "", "| Month | n | Served MAE | Served RMSE | XGBoost MAE | Last-week MAE |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for month, methods in report["folds"].items():
        lines.append(f"| {month} | {methods[POINT]['n']} | {methods[POINT]['mae']:.1f} | {methods[POINT]['rmse']:.1f} | "
                     f"{methods[XGBOOST]['mae']:.1f} | {methods[BASELINE]['mae']:.1f} |")
    lines += ["", "## Is the forecast really more accurate? (Z-test on hourly absolute-error differences)", "",
              "| Split | Comparison | Mean difference (kW) | z | p |", "| --- | --- | ---: | ---: | ---: |"]
    for split, tests in report["error_tests"].items():
        for name, test in tests.items():
            lines.append(f"| {split} | {name} | {test['mean_difference_kw']:+.2f} | {test['z']:+.2f} | {test['p_value_two_sided']:.3f} |")
    lines += ["", "Negative difference = the served forecast has the smaller error. Hourly errors are correlated, "
              "so these p-values are optimistic.", ""]
    for split, decision in report["decision"].items():
        served = decision["methods"][UPPER]
        lines += [f"## Generator choice as classification: {split} ({decision['hours']} hours)", "",
                  "| Rule | Accuracy (right unit) | Picked too small | Picked too large | Macro precision | Macro recall | Macro F1 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for method, m in decision["methods"].items():
            lines.append(f"| {names[method]}{' (forecast alone)' if method in (BASELINE, POINT) else ''} | {m['accuracy']:.1%} | "
                         f"{m['below_needed']:.1%} | {m['above_needed']:.1%} | {m['macro_precision']:.2f} | "
                         f"{m['macro_recall']:.2f} | {m['macro_f1']:.2f} |")
        lines += ["", "Confusion matrix of the served rule (rows = needed, columns = picked):", "",
                  "| Needed \\\\ picked | " + " | ".join(served["classes"]) + " | Recall |",
                  "| --- |" + " ---: |" * (len(served["classes"]) + 1)]
        for label, row in zip(served["classes"], served["matrix"]):
            recall = served["per_class"][label]["recall"]
            lines.append(f"| {label} | " + " | ".join(str(v) for v in row) + f" | {'' if recall is None else f'{recall:.0%}'} |")
        lines.append("| Precision | " + " | ".join(
            "" if served["per_class"][c]["precision"] is None else f"{served['per_class'][c]['precision']:.0%}"
            for c in served["classes"]) + " | |")
        lines += ["", "| McNemar comparison | B (only served right) | C (only other right) | chi2 | p |",
                  "| --- | ---: | ---: | ---: | ---: |"]
        for name, test in decision["comparisons"].items():
            readable = name.replace(UPPER, "served rule").replace(XGBOOST_UPPER, "XGBoost P90 rule").replace(
                BASELINE, "last week alone").replace(POINT, "Ridge alone")
            lines.append(f"| {readable} | {test['only_first_correct_B']} | {test['only_second_correct_C']} | "
                         f"{test['chi_square']:.1f} | {test['p_value']:.4f} |")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline-dir", type=Path, default=Path("outputs/baselines_confirmed_azm"))
    parser.add_argument("--validation-predictions", type=Path, default=Path("outputs/walk_forward/predictions.csv"))
    parser.add_argument("--test-predictions", type=Path, default=Path("outputs/final_test/predictions.csv"))
    parser.add_argument("--policy", type=Path, default=Path("config/azm_generators.json"))
    parser.add_argument("--config", type=Path, default=Path("config/walk_forward.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/course_metrics"))
    args = parser.parse_args()
    _, groups, series, _ = load_inputs(args.baseline_dir)
    net = signed_net_series(series[("azm", "load")], series[("azm", "pv")])
    report = analyse(args.validation_predictions, args.test_predictions,
                     json.loads(args.policy.read_text(encoding="utf-8")), net, set(load_public_holidays()),
                     datetime.fromisoformat(groups[("azm", "load")]["validation_start"]),
                     json.loads(args.config.read_text(encoding="utf-8")))
    report["run_time_utc"] = datetime.now(timezone.utc).isoformat()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (args.output_dir / "summary.md").write_text(summary_markdown(report), encoding="utf-8")
    print(summary_markdown(report))


if __name__ == "__main__":
    main()
