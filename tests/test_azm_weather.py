"""Azm weather download script, tested offline with fake responses."""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lebanon_energy.data.azm_weather import compare, request_parameters, run

HEADER = ("latitude,longitude,elevation,utc_offset_seconds,timezone,timezone_abbreviation\n"
          "34.411247,35.88679,10.0,7200,Asia/Beirut,GMT+2\n\n"
          "time,temperature_2m (°C),relative_humidity_2m (%)\n")


def observed(*rows):
    return HEADER + "".join(f"{row}\n" for row in rows)


class AzmWeatherTests(unittest.TestCase):
    def test_request_matches_the_supplied_files(self):
        forecast = request_parameters("forecast", 34.4453066, 35.8440889)
        self.assertTrue(forecast["hourly"].startswith("temperature_2m_previous_day1,"))
        self.assertEqual((forecast["timezone"], forecast["format"]), ("Asia/Beirut", "csv"))
        self.assertEqual((forecast["start_date"], forecast["end_date"]), ("2026-04-16", "2026-09-30"))
        self.assertNotIn("previous_day1", request_parameters("observed", 34.4, 35.8)["hourly"])

    def test_compare_counts_identical_and_differing_hours(self):
        old = observed("2026-04-16T00:00,20.3,38", "2026-04-16T01:00,20.0,40")
        new = observed("2026-04-16T00:00,20.3,38", "2026-04-16T01:00,20.0,41")
        result = compare(new, old)
        self.assertEqual((result["identical_hours"], result["differing_hours_total"]), (1, 1))
        self.assertTrue(result["same_grid_point"] and result["same_columns"])

    def test_blocked_service_is_reported_not_hidden(self):
        folder = Path(tempfile.mkdtemp())
        archive = folder / "data.zip"
        with ZipFile(archive, "w") as zipped:
            zipped.writestr("Data/azm_weather_observed.csv.csv", observed("2026-04-16T00:00,20.3,38"))
            zipped.writestr("Data/azm_weather_forecast_day1.csv.csv", observed("2026-04-16T00:00,20.2,54"))

        def fake_fetch(url, parameters):
            if "previous-runs" in url:
                raise OSError("handshake failed")
            return observed("2026-04-16T00:00,20.3,38")

        manifest = run(["observed", "forecast"], 34.4453066, 35.8440889, folder / "out", archive, fetch=fake_fetch)
        self.assertEqual(manifest["files"]["observed"]["comparison_with_supplied_file"]["identical_hours"], 1)
        self.assertEqual(manifest["files"]["forecast"]["status"], "failed")
        self.assertIn("--only forecast", manifest["files"]["forecast"]["advice"])
        saved = json.loads((folder / "out" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["files"]["observed"]["status"], "downloaded")


if __name__ == "__main__":
    unittest.main()
