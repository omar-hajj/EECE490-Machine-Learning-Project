"""Integration checks for the shared comparison with a tree estimator."""

from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lebanon_energy.models.boosting import make_pipeline
from lebanon_energy.models.ridge import train_group


class BoostingComparisonTests(unittest.TestCase):
    def test_factory_uses_repeatable_single_cpu_estimator(self):
        model = make_pipeline(max_depth=2, n_estimators=3, learning_rate=0.1)
        params = model.named_steps["boosting"].get_params()
        self.assertEqual(params["n_jobs"], 1)
        self.assertEqual(params["random_state"], 42)
        self.assertEqual(params["objective"], "reg:squarederror")

    def test_shared_runner_preserves_validation_boundaries_and_candidate_log(self):
        start = datetime(2025, 6, 1)
        first = start - timedelta(days=15)
        series = {first + timedelta(hours=index): float(20 + index % 24) for index in range(16 * 24)}
        group = {"validation_start": start.isoformat(), "validation_end_exclusive": (start + timedelta(days=1)).isoformat()}
        baselines = {start + timedelta(hours=index): {method: float(20 + index) for method in ("yesterday", "last_week", "weekday_average")} for index in range(24)}
        config = {"lag_hours": [24, 168], "candidate_parameters": [
            {"max_depth": 2, "n_estimators": 3, "learning_rate": 0.1},
            {"max_depth": 2, "n_estimators": 5, "learning_rate": 0.1}]}
        result, model, rows = train_group(series, group, baselines, config, pipeline_factory=make_pipeline)
        self.assertEqual(len(result["alpha_search"]), 2)
        self.assertEqual(result["common_comparison_hours"], 24)
        self.assertEqual(len(rows), 24)
        self.assertLess(datetime.fromisoformat(result["training_last_target"]), start)
        self.assertFalse(result["deployment_model_selected"])
        self.assertIn(result["selected_parameters"], config["candidate_parameters"])
        self.assertIsNotNone(model)


if __name__ == "__main__":
    unittest.main()
