"""Focused regression checks for SkyETA's pre-departure weather join."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parent))
from weather_config import RAW_WEATHER_VARIABLES  # noqa: E402
from weather_features import attach_predeparture_weather  # noqa: E402


class WeatherFeatureTests(unittest.TestCase):
    def test_noaa_string_timestamp_joins_to_nanosecond_flight_cutoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            weather_dir = Path(temporary_directory)
            station_path = weather_dir / "2025" / "ATL_test.parquet"
            station_path.parent.mkdir()

            station = pd.DataFrame(
                {
                    # Pandas 3 parses these NOAA-style strings as datetime64[us,
                    # UTC]. The production join must still align them with its
                    # datetime64[ns, UTC] flight cutoffs.
                    "DATE": ["2025-01-02T10:52:00"],
                    "temperature": [12.0],
                    "dew_point_temperature": [5.0],
                    "relative_humidity": [62.0],
                    "sea_level_pressure": [1014.0],
                    "wind_speed": [4.0],
                    "wind_gust": [7.0],
                    "precipitation": [0.0],
                    "visibility": [16.0],
                    "ceiling_height": [2500.0],
                }
            )
            for variable in RAW_WEATHER_VARIABLES:
                station[f"{variable}_Quality_Code"] = "1"
            station.to_parquet(station_path, index=False)

            manifest = {
                "year": 2025,
                "airports": [
                    {
                        "iata": "ATL",
                        "path": str(station_path),
                        "downloaded": True,
                    }
                ],
            }
            (weather_dir / "manifest-2025.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            flights = pd.DataFrame(
                {
                    "Year": [2025],
                    "Month": [1],
                    "DayofMonth": [2],
                    "Origin": ["ATL"],
                    "Dest": ["ATL"],
                    # 09:00 America/New_York is 14:00 UTC; the three-hour
                    # prediction cutoff is 11:00 UTC, eight minutes after NOAA.
                    "CRSDepTime": [900],
                }
            )

            result = attach_predeparture_weather(
                flights,
                weather_dir=weather_dir,
                cutoff_hours=3.0,
                max_observation_age_hours=3.0,
            )

            self.assertAlmostEqual(float(result.loc[0, "origin_temperature_c"]), 12.0)
            self.assertAlmostEqual(
                float(result.loc[0, "destination_temperature_c"]), 12.0
            )
            self.assertAlmostEqual(
                float(result.loc[0, "origin_weather_max_age_hours"]), 8.0 / 60.0
            )
            self.assertEqual(float(result.loc[0, "origin_weather_missing_fraction"]), 0.0)
            self.assertEqual(
                float(result.loc[0, "destination_weather_missing_fraction"]), 0.0
            )

    def test_missing_station_returns_nan_without_all_nan_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            weather_dir = Path(temporary_directory)
            (weather_dir / "manifest-2025.json").write_text(
                json.dumps({"year": 2025, "airports": []}), encoding="utf-8"
            )
            flights = pd.DataFrame(
                {
                    "Year": [2025],
                    "Month": [1],
                    "DayofMonth": [2],
                    "Origin": ["ATL"],
                    "Dest": ["ATL"],
                    "CRSDepTime": [900],
                }
            )

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = attach_predeparture_weather(flights, weather_dir=weather_dir)

            runtime_warnings = [
                warning for warning in caught if warning.category is RuntimeWarning
            ]
            self.assertEqual(runtime_warnings, [])
            self.assertTrue(pd.isna(result.loc[0, "origin_weather_max_age_hours"]))
            self.assertTrue(
                pd.isna(result.loc[0, "destination_weather_max_age_hours"])
            )
            self.assertEqual(float(result.loc[0, "origin_weather_missing_fraction"]), 1.0)
            self.assertEqual(
                float(result.loc[0, "destination_weather_missing_fraction"]), 1.0
            )


if __name__ == "__main__":
    unittest.main()
