"""Integration checks for paired prediction input and report grouping."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.compare_modes import compare_csv


class PairedPredictionTests(unittest.TestCase):
    header = "site_id,timestamp,target,actual,history_prediction,location_prediction\n"

    def evaluate(self, records):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "predictions.csv"
            path.write_text(self.header + records, encoding="utf-8")
            return compare_csv(path)

    def test_different_sites_and_targets_are_not_pooled(self):
        result = self.evaluate(
            "a,2026-07-01T00:00:00+03:00,load,100,100,110\n"
            "b,2026-07-01T00:00:00+03:00,load,1,1,2\n"
            "a,2026-07-01T00:00:00+03:00,pv,0,0,0\n"
        )
        comparisons = {(row["site_id"], row["target"]): row for row in result["comparisons"]}
        self.assertAlmostEqual(comparisons[("a", "load")]["location_only"]["nmae"], 0.10)
        self.assertAlmostEqual(comparisons[("b", "load")]["location_only"]["nmae"], 1.0)
        self.assertIsNone(comparisons[("a", "pv")]["location_only"]["nmae"])
        self.assertFalse(result["deployment_approved"])

    def test_duplicate_instants_with_different_offsets_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "repeated"):
            self.evaluate(
                "a,2026-07-01T03:00:00+03:00,load,100,100,110\n"
                "a,2026-07-01T00:00:00+00:00,load,100,100,110\n"
            )

    def test_missing_predictions_are_not_dropped(self):
        with self.assertRaises(ValueError):
            self.evaluate("a,2026-07-01T00:00:00+03:00,load,100,100,\n")

    def test_unzoned_dates_and_nonfinite_predictions_are_rejected(self):
        for row in (
            "a,2026-07-01T00:00:00,load,100,100,110\n",
            "a,2026-07-01T00:00:00+03:00,load,100,100,nan\n",
        ):
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.evaluate(row)


if __name__ == "__main__":
    unittest.main()
