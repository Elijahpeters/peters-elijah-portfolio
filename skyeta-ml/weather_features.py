"""Leakage-safe NOAA weather features for SkyETA flight rows.

The prediction moment is defined as three hours before the scheduled departure.
For both endpoints, every value is selected from an observation timestamped at
or before that moment.  Values older than three hours are treated as missing.
This is intentionally a day-of-flight model contract, not an arrival-weather or
perfect-forecast model.
"""

from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

from weather_config import (
    AIRPORTS,
    DEFAULT_CUTOFF_HOURS,
    DEFAULT_MAX_OBSERVATION_AGE_HOURS,
    DEFAULT_WEATHER_YEAR,
    RAW_WEATHER_VARIABLES,
    WEATHER_FEATURE_NAMES,
)


# These codes are suspect, erroneous, removed, or missing in the NOAA source
# families documented by GHCNh.  Other accepted/edited/calculated codes remain.
REJECTED_QUALITY_CODES = {"2", "3", "5", "6", "7", "9", "F", "X", "N", "Y", "K", "G", "O", "Z"}
VARIABLE_OUTPUT_NAMES = {
    "temperature": "temperature_c",
    "dew_point_temperature": "dew_point_c",
    "relative_humidity": "relative_humidity_pct",
    "sea_level_pressure": "sea_level_pressure_hpa",
    "wind_speed": "wind_speed_mps",
    "wind_gust": "wind_gust_mps",
    "precipitation": "precipitation_mm",
    "visibility": "visibility_km",
    "ceiling_height": "ceiling_m",
}


def _manifest(weather_dir: Path, year: int) -> dict:
    path = weather_dir / f"manifest-{year}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run skyeta-ml/download_weather.py first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _scheduled_cutoff_utc(
    flights: pd.DataFrame, cutoff_hours: float, default_year: int
) -> pd.Series:
    required = {"Month", "DayofMonth", "Origin", "CRSDepTime"}
    missing = sorted(required - set(flights.columns))
    if missing:
        raise ValueError(f"Flight rows are missing: {', '.join(missing)}")

    frame = flights.reset_index(drop=True)
    scheduled = pd.to_numeric(frame["CRSDepTime"], errors="coerce")
    valid = scheduled.between(0, 2400) & ((scheduled % 100) < 60)
    scheduled = scheduled.where(valid)
    day_offset = scheduled.eq(2400).fillna(False).astype("int8")
    scheduled_mod = scheduled.fillna(0).astype("int32") % 2400
    year = (
        pd.to_numeric(frame["Year"], errors="coerce")
        if "Year" in frame
        else pd.Series(default_year, index=frame.index)
    )
    local_date = pd.to_datetime(
        {
            "year": year,
            "month": pd.to_numeric(frame["Month"], errors="coerce"),
            "day": pd.to_numeric(frame["DayofMonth"], errors="coerce"),
        },
        errors="coerce",
    ) + pd.to_timedelta(day_offset, unit="D")
    local_clock = local_date + pd.to_timedelta(
        (scheduled_mod // 100) * 60 + (scheduled_mod % 100), unit="m"
    )
    local_clock = local_clock.where(valid)

    result = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    for origin, positions in frame.groupby("Origin", sort=False).groups.items():
        configured = AIRPORTS.get(str(origin))
        if configured is None:
            continue
        try:
            localized = pd.DatetimeIndex(local_clock.iloc[positions]).tz_localize(
                ZoneInfo(configured.timezone),
                ambiguous="NaT",
                nonexistent="shift_forward",
            )
        except ZoneInfoNotFoundError as error:
            raise RuntimeError(
                "IANA timezone data is unavailable. Install the 'tzdata' requirement."
            ) from error
        result.iloc[positions] = localized.tz_convert("UTC") - pd.Timedelta(
            hours=cutoff_hours
        )
    return result


def _clean_station(path: Path) -> pd.DataFrame:
    columns = ["DATE"]
    for variable in RAW_WEATHER_VARIABLES:
        columns.extend([variable, f"{variable}_Quality_Code"])
    try:
        raw = pd.read_parquet(path, columns=columns)
    except ImportError as error:
        raise RuntimeError(
            "Reading NOAA's compact Parquet files requires the 'pyarrow' requirement."
        ) from error

    # Pandas 3 preserves the source string precision here and therefore parses
    # NOAA's second-resolution timestamps as datetime64[us, UTC].  The flight
    # cutoffs are datetime64[ns, UTC]; converting both to int64 without first
    # aligning units makes every weather observation appear roughly 1,000x
    # older than the query.  Keep one canonical nanosecond unit for the as-of
    # join regardless of the pandas/Arrow version used to read the Parquet.
    timestamps = pd.to_datetime(raw["DATE"], errors="coerce", utc=True).astype(
        "datetime64[ns, UTC]"
    )
    result = pd.DataFrame({"timestamp": timestamps})
    for variable, (minimum, maximum) in RAW_WEATHER_VARIABLES.items():
        values = pd.to_numeric(raw[variable], errors="coerce")
        quality_column = f"{variable}_Quality_Code"
        quality = raw[quality_column].fillna("").astype(str).str.strip().str.upper()
        values = values.mask(quality.isin(REJECTED_QUALITY_CODES))
        result[variable] = values.where(values.between(minimum, maximum))
    result = result.dropna(subset=["timestamp"]).sort_values("timestamp")
    return result.drop_duplicates("timestamp", keep="last").reset_index(drop=True)


def _asof_values(
    observation_time: np.ndarray,
    observation_values: np.ndarray,
    query_time: np.ndarray,
    max_age_ns: int,
) -> tuple[np.ndarray, np.ndarray]:
    present = np.isfinite(observation_values)
    times = observation_time[present]
    values = observation_values[present]
    output = np.full(len(query_time), np.nan, dtype="float32")
    ages = np.full(len(query_time), np.nan, dtype="float32")
    if not len(times):
        return output, ages
    positions = np.searchsorted(times, query_time, side="right") - 1
    valid = positions >= 0
    clipped = np.maximum(positions, 0)
    age = query_time - times[clipped]
    valid &= (age >= 0) & (age <= max_age_ns)
    output[valid] = values[clipped[valid]].astype("float32")
    ages[valid] = (age[valid] / 3_600_000_000_000).astype("float32")
    return output, ages


def attach_predeparture_weather(
    flights: pd.DataFrame,
    weather_dir: Path = Path("skyeta-ml/data/weather"),
    year: int = DEFAULT_WEATHER_YEAR,
    cutoff_hours: float = DEFAULT_CUTOFF_HOURS,
    max_observation_age_hours: float = DEFAULT_MAX_OBSERVATION_AGE_HOURS,
) -> pd.DataFrame:
    """Return same-row weather features for a BTS-shaped flight frame.

    The output is independent of the target column.  Missing airports,
    ambiguous fall-DST clock times, stale reports, and rejected NOAA values are
    represented by NaN plus an explicit missing fraction.
    """
    if cutoff_hours <= 0:
        raise ValueError("cutoff_hours must be positive")
    if max_observation_age_hours <= 0:
        raise ValueError("max_observation_age_hours must be positive")

    frame = flights.reset_index(drop=True)
    cutoff = _scheduled_cutoff_utc(frame, cutoff_hours, year)
    cutoff_ns = cutoff.astype("int64").to_numpy()
    nat_value = np.iinfo("int64").min
    manifest = _manifest(weather_dir, year)
    station_entries = {
        entry["iata"]: entry
        for entry in manifest["airports"]
        if entry.get("downloaded")
    }
    station_cache: dict[str, pd.DataFrame] = {}
    output = pd.DataFrame(np.nan, index=frame.index, columns=WEATHER_FEATURE_NAMES, dtype="float32")
    max_age_ns = int(max_observation_age_hours * 3_600_000_000_000)

    for endpoint, airport_column in (("origin", "Origin"), ("destination", "Dest")):
        if airport_column not in frame:
            raise ValueError(f"Flight rows are missing: {airport_column}")
        base_feature_columns = [
            f"{endpoint}_{VARIABLE_OUTPUT_NAMES[name]}" for name in RAW_WEATHER_VARIABLES
        ]
        endpoint_ages = np.full((len(frame), len(RAW_WEATHER_VARIABLES)), np.nan, dtype="float32")
        for airport, positions in frame.groupby(airport_column, sort=False).groups.items():
            airport = str(airport)
            entry = station_entries.get(airport)
            if entry is None:
                continue
            station = station_cache.get(airport)
            if station is None:
                station = _clean_station(Path(entry["path"]))
                station_cache[airport] = station
            query_positions = np.asarray(positions, dtype="int64")
            query = cutoff_ns[query_positions]
            valid_query = query != nat_value
            observation_time = station["timestamp"].astype("int64").to_numpy()
            for feature_index, variable in enumerate(RAW_WEATHER_VARIABLES):
                values = np.full(len(query), np.nan, dtype="float32")
                ages = np.full(len(query), np.nan, dtype="float32")
                if valid_query.any():
                    selected, selected_ages = _asof_values(
                        observation_time,
                        station[variable].to_numpy(dtype="float64"),
                        query[valid_query],
                        max_age_ns,
                    )
                    values[valid_query] = selected
                    ages[valid_query] = selected_ages
                output.loc[query_positions, base_feature_columns[feature_index]] = values
                endpoint_ages[query_positions, feature_index] = ages

        values = output[base_feature_columns]
        ingredients_present = values[
            [
                f"{endpoint}_temperature_c",
                f"{endpoint}_wind_speed_mps",
                f"{endpoint}_wind_gust_mps",
                f"{endpoint}_precipitation_mm",
                f"{endpoint}_visibility_km",
                f"{endpoint}_ceiling_m",
            ]
        ].notna()
        adverse = (
            values[f"{endpoint}_wind_speed_mps"].ge(15.0)
            | values[f"{endpoint}_wind_gust_mps"].ge(20.0)
            | values[f"{endpoint}_precipitation_mm"].gt(0.0)
            | values[f"{endpoint}_visibility_km"].lt(5.0)
            | values[f"{endpoint}_ceiling_m"].lt(305.0)
            | (
                values[f"{endpoint}_temperature_c"].le(0.0)
                & values[f"{endpoint}_precipitation_mm"].gt(0.0)
            )
        ).astype("float32")
        adverse = adverse.mask(~ingredients_present.any(axis=1))
        output[f"{endpoint}_adverse_weather"] = adverse
        all_ages_missing = np.all(np.isnan(endpoint_ages), axis=1)
        # ``np.nanmax`` warns for every all-NaN row, even though an endpoint
        # without a usable report is an expected state.  Reduce over a safe
        # sentinel and restore those rows to NaN so values remain unchanged.
        max_ages = np.max(
            np.where(np.isnan(endpoint_ages), -np.inf, endpoint_ages), axis=1
        )
        max_ages[all_ages_missing] = np.nan
        output[f"{endpoint}_weather_max_age_hours"] = max_ages.astype("float32")
        output[f"{endpoint}_weather_missing_fraction"] = values.isna().mean(axis=1).astype("float32")

    output.index = flights.index
    return output.astype("float32")
