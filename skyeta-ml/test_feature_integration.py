"""Small synthetic checks for SkyETA feature-set integration (no downloads/training)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parent))
import train  # noqa: E402


class FeatureIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.flights = pd.DataFrame(
            {
                "Month": [1, 1, 2, 2],
                "DayofMonth": [1, 2, 3, 4],
                "DayOfWeek": [3, 4, 1, 2],
                "Reporting_Airline": ["AA", "AA", "DL", "DL"],
                "Origin": ["PHX", "PHX", "ATL", "ATL"],
                "Dest": ["LAX", "LAX", "JFK", "JFK"],
                "CRSDepTime": [900, 930, 1400, 1430],
                "CRSElapsedTime": [90, 90, 150, 150],
                "Distance": [370, 370, 760, 760],
                "ArrDel15": [0, 1, 0, 1],
                "route": ["PHX_LAX", "PHX_LAX", "ATL_JFK", "ATL_JFK"],
            }
        )
        self.rates = {
            "global": 0.5,
            "carrier": {"AA": 0.4, "DL": 0.6},
            "origin": {"PHX": 0.4, "ATL": 0.6},
            "destination": {"LAX": 0.4, "JFK": 0.6},
            "route": {"PHX_LAX": 0.4, "ATL_JFK": 0.6},
        }
        accumulator = train.ScheduleContextAccumulator()
        accumulator.update(self.flights)
        self.context = accumulator.finalize()

    def test_full_contract_order_missingness_and_target_independence(self) -> None:
        weather = pd.DataFrame(
            np.arange(len(self.flights) * len(train.WEATHER_FEATURE_NAMES)).reshape(
                len(self.flights), -1
            ),
            columns=train.WEATHER_FEATURE_NAMES,
            dtype="float32",
        )
        weather.iloc[0, 0] = np.nan
        with patch.object(train, "attach_predeparture_weather", return_value=weather):
            features, target = train.engineer(
                self.flights,
                self.rates,
                feature_set="full",
                schedule_context_maps=self.context,
            )
            changed_target = self.flights.copy()
            changed_target["ArrDel15"] = 1 - changed_target["ArrDel15"]
            changed_features, _ = train.engineer(
                changed_target,
                self.rates,
                feature_set="full",
                schedule_context_maps=self.context,
            )

        self.assertEqual(list(features), train.feature_names_for("full"))
        self.assertEqual(len(features.columns), 44)
        self.assertTrue(np.isnan(features.iloc[0][train.WEATHER_FEATURE_NAMES[0]]))
        np.testing.assert_allclose(features, changed_features, equal_nan=True)
        np.testing.assert_array_equal(target, np.array([0, 1, 0, 1], dtype="int8"))

    def test_core_never_touches_weather_and_json_missing_is_null(self) -> None:
        with patch.object(
            train,
            "attach_predeparture_weather",
            side_effect=AssertionError("weather should not be called"),
        ):
            features, _ = train.engineer(
                self.flights,
                self.rates,
                feature_set="core",
            )
        self.assertEqual(list(features), train.CORE_FEATURE_NAMES)
        self.assertEqual(train.browser_feature_values(np.array([1.0, np.nan])), [1.0, None])

    def test_calibration_threshold_and_ablation_policy_are_explicit(self) -> None:
        raw_score = np.array([-3.0, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0])
        target = np.array([0, 0, 0, 0, 0, 1, 1, 1], dtype="int8")
        calibration = train.fit_sigmoid_calibration(raw_score, target)
        probability = train.apply_sigmoid_calibration(raw_score, calibration)
        threshold = train.select_f1_threshold(target, probability)
        metrics = train.evaluate(target, probability, threshold)

        self.assertGreater(float(calibration["slope"]), 0)
        self.assertTrue(np.all(np.diff(probability) > 0))
        self.assertGreater(threshold, 0)
        self.assertLess(threshold, 1)
        self.assertEqual(metrics["atDecisionThreshold"]["threshold"], threshold)

        selected = {
            "validation": {"rocAuc": 0.61, "averagePrecision": 0.3, "brierScore": 0.1, "logLoss": 0.4},
            "test": {"rocAuc": 0.60, "averagePrecision": 0.3, "brierScore": 0.1, "logLoss": 0.4},
        }
        core = {
            "validation": {"rocAuc": 0.60, "averagePrecision": 0.3, "brierScore": 0.1, "logLoss": 0.4},
            "test": {"rocAuc": 0.62, "averagePrecision": 0.3, "brierScore": 0.1, "logLoss": 0.4},
        }
        comparison = train.ablation_comparison("context", selected, core)
        self.assertTrue(comparison["acceptance"]["accepted"])
        self.assertEqual(comparison["acceptance"]["decisionSplit"], "validation")
        self.assertFalse(comparison["acceptance"]["testUsedForSelection"])


if __name__ == "__main__":
    unittest.main()
