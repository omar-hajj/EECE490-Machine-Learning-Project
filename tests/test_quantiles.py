"""Direct net-target alignment and asymmetric quantile scoring."""
import unittest
from lebanon_energy.quantiles import quantile_scores, signed_net_series


class QuantileTests(unittest.TestCase):
    def test_net_target_uses_only_matching_observed_hours_and_preserves_sign(self):
        self.assertEqual(signed_net_series({1: 100, 2: 20, 3: 10}, {1: 30, 2: 50, 4: 5}), {1: 70, 2: -30})

    def test_p90_penalizes_underestimation_more_than_overestimation(self):
        self.assertAlmostEqual(quantile_scores([10], [0], .9)["pinball_loss"], 9)
        self.assertAlmostEqual(quantile_scores([0], [10], .9)["pinball_loss"], 1)

    def test_coverage_is_measured_instead_of_assumed_to_equal_nominal_quantile(self):
        result = quantile_scores([-1, 1], [0, 0], .9)
        self.assertEqual(result["empirical_hourly_coverage"], .5)
        self.assertEqual(result["underforecast_hours"], 1)

    def test_missing_values_and_invalid_quantiles_are_rejected(self):
        for actual, predicted, q in (([], [], .9), ([1], [], .9), ([1], [float('nan')], .9), ([1], [1], 1)):
            with self.subTest(q=q), self.assertRaises(ValueError):
                quantile_scores(actual, predicted, q)


if __name__ == "__main__":
    unittest.main()
