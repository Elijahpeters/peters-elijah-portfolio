"""Train and export the documented SkyETA portfolio model."""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROCESS_STARTED = time.perf_counter()
if __name__ == "__main__":
    print("[SkyETA] Loading Python ML dependencies...", flush=True)

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from predeparture_context import (
    CONTEXT_FEATURE_NAMES,
    ScheduleContextAccumulator,
    ScheduleContextMaps,
    transform_schedule_context,
)
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_curve
from weather_config import (
    DEFAULT_CUTOFF_HOURS,
    DEFAULT_MAX_OBSERVATION_AGE_HOURS,
    DEFAULT_WEATHER_YEAR,
    GHCNH_DOCUMENTATION_URL,
    WEATHER_FEATURE_NAMES,
)
from weather_features import attach_predeparture_weather


SOURCE_BASE = "https://transtats.bts.gov/PREZIP"
SOURCE_PATTERN = (
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_2025_{month}.zip"
)
USE_COLUMNS = [
    "Month",
    "DayofMonth",
    "DayOfWeek",
    "Reporting_Airline",
    "Origin",
    "Dest",
    "CRSDepTime",
    "CRSElapsedTime",
    "Distance",
    "ArrDel15",
    "Cancelled",
    "Diverted",
]
SAMPLE_COLUMNS = [
    "Month",
    "DayofMonth",
    "DayOfWeek",
    "Reporting_Airline",
    "Origin",
    "Dest",
    "CRSDepTime",
    "CRSElapsedTime",
    "Distance",
    "ArrDel15",
    "route",
]
CORE_FEATURE_NAMES = [
    "month_sin",
    "month_cos",
    "weekday_sin",
    "weekday_cos",
    "day_of_month_sin",
    "day_of_month_cos",
    "departure_hour_sin",
    "departure_hour_cos",
    "departure_minute_fraction",
    "is_weekend",
    "scheduled_duration_minutes",
    "distance_miles",
    "carrier_delay_rate",
    "origin_delay_rate",
    "destination_delay_rate",
    "route_delay_rate",
]
FEATURE_SET_CHOICES = ("core", "context", "weather", "full")
RATE_PRIORS = {
    "carrier": 500.0,
    "origin": 500.0,
    "destination": 500.0,
    "route": 150.0,
}
RATE_FEATURE_NAMES = [
    "carrier_delay_rate",
    "origin_delay_rate",
    "destination_delay_rate",
    "route_delay_rate",
]
MIN_EXPORT_ROC_AUC = 0.52
MIN_ABLATION_VALIDATION_ROC_AUC_GAIN = 0.005
CALIBRATION_BIN_COUNT = 10


def uses_context(feature_set: str) -> bool:
    return feature_set in {"context", "full"}


def uses_weather(feature_set: str) -> bool:
    return feature_set in {"weather", "full"}


def feature_names_for(feature_set: str) -> list[str]:
    if feature_set not in FEATURE_SET_CHOICES:
        raise ValueError(f"Unknown feature set: {feature_set}")
    names = list(CORE_FEATURE_NAMES)
    if uses_context(feature_set):
        names.extend(CONTEXT_FEATURE_NAMES)
    if uses_weather(feature_set):
        names.extend(WEATHER_FEATURE_NAMES)
    return names


def progress(message: str) -> None:
    elapsed = time.perf_counter() - PROCESS_STARTED
    print(f"[SkyETA +{elapsed:7.1f}s] {message}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("skyeta-ml/data/raw"))
    parser.add_argument(
        "--public-dir", type=Path, default=Path("public/assets")
    )
    parser.add_argument(
        "--artifact-dir", type=Path, default=Path("skyeta-ml/artifacts")
    )
    parser.add_argument("--max-train-rows", type=int, default=750_000)
    parser.add_argument("--max-validation-rows", type=int, default=150_000)
    parser.add_argument("--max-test-rows", type=int, default=150_000)
    parser.add_argument("--chunksize", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--feature-set",
        choices=FEATURE_SET_CHOICES,
        default="core",
        help=(
            "Feature contract to train: core BTS fields; core plus target-free "
            "schedule context; core plus leakage-safe pre-departure NOAA weather; "
            "or all three groups"
        ),
    )
    parser.add_argument(
        "--ablation",
        action="store_true",
        help=(
            "Fit a core-only baseline on the identical sampled rows and report "
            "metric deltas against the selected non-core feature set"
        ),
    )
    parser.add_argument(
        "--weather-dir",
        type=Path,
        default=Path("skyeta-ml/data/weather"),
    )
    parser.add_argument("--weather-year", type=int, default=DEFAULT_WEATHER_YEAR)
    parser.add_argument(
        "--weather-cutoff-hours",
        type=float,
        default=DEFAULT_CUTOFF_HOURS,
        help="Prediction horizon before scheduled departure; must be positive",
    )
    parser.add_argument(
        "--weather-max-observation-age-hours",
        type=float,
        default=DEFAULT_MAX_OBSERVATION_AGE_HOURS,
        help="Reject NOAA observations older than this many hours",
    )
    parser.add_argument(
        "--allow-partial-weather",
        action="store_true",
        help=(
            "Allow a weather feature run with only some manifest stations cached; "
            "intended for smoke diagnostics, not the public artifact"
        ),
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help=(
            "Use Jan-Mar for training, April for validation, and May for testing "
            "with small caps; verify metrics/parity without writing artifacts"
        ),
    )
    return parser.parse_args()


def validate_weather_cache(
    weather_dir: Path,
    year: int,
    allow_partial: bool,
) -> dict:
    """Validate local NOAA inputs without downloading or modifying anything."""
    manifest_path = weather_dir / f"manifest-{year}.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Missing weather manifest: {manifest_path}. "
            "Run download_weather.py separately after reviewing WEATHER.md."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("year") != year or not isinstance(manifest.get("airports"), list):
        raise RuntimeError(f"Invalid weather manifest contract: {manifest_path}")

    entries = manifest["airports"]
    downloaded = [entry for entry in entries if entry.get("downloaded")]
    missing_files = [
        str(entry.get("path"))
        for entry in downloaded
        if not entry.get("path") or not Path(entry["path"]).is_file()
    ]
    if missing_files:
        raise FileNotFoundError(
            "Weather manifest marks missing files as downloaded:\n"
            + "\n".join(missing_files)
        )
    if not downloaded:
        raise RuntimeError(
            f"{manifest_path} has no cached station-year weather files"
        )
    if len(downloaded) != len(entries) and not allow_partial:
        raise RuntimeError(
            "Weather cache is incomplete: "
            f"{len(downloaded)}/{len(entries)} station files are available. "
            "Complete the separate weather download, or use "
            "--allow-partial-weather for a non-public diagnostic run."
        )
    return manifest


def archive_path(data_dir: Path, month: int) -> Path:
    return data_dir / SOURCE_PATTERN.format(month=month)


def csv_member(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        candidates = [
            item.filename
            for item in archive.infolist()
            if item.filename.lower().endswith(".csv")
            and "readme" not in item.filename.lower()
        ]
    if not candidates:
        raise RuntimeError(f"No flight CSV found inside {path}")
    return max(candidates, key=len)


def validate_archive(path: Path) -> None:
    """Check the ZIP directory, selected CSV member, and required schema.

    ``download_bts.py`` already performs the expensive full CRC pass. Avoiding
    a second ``testzip()`` here saves a complete decompression of all 12 CSVs;
    any later stream/CRC failure still surfaces while pandas reads the member.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            member = next(
                (
                    item.filename
                    for item in archive.infolist()
                    if item.filename.lower().endswith(".csv")
                    and "readme" not in item.filename.lower()
                ),
                None,
            )
            if member is None:
                raise RuntimeError(f"No flight CSV found inside {path}")
            with archive.open(member) as source:
                header = next(csv.reader([source.readline().decode("utf-8-sig")]))
            missing_columns = sorted(set(USE_COLUMNS) - set(header))
            if missing_columns:
                raise RuntimeError(
                    f"{path} is missing required columns: {', '.join(missing_columns)}"
                )
    except zipfile.BadZipFile as error:
        raise RuntimeError(f"Invalid ZIP archive: {path}") from error


def iter_clean_chunks(path: Path, chunksize: int):
    member = csv_member(path)
    with zipfile.ZipFile(path) as archive, archive.open(member) as source:
        for chunk in pd.read_csv(
            source,
            usecols=USE_COLUMNS,
            chunksize=chunksize,
            low_memory=False,
        ):
            scheduled = pd.to_numeric(chunk["CRSDepTime"], errors="coerce")
            duration = pd.to_numeric(chunk["CRSElapsedTime"], errors="coerce")
            distance = pd.to_numeric(chunk["Distance"], errors="coerce")
            target = pd.to_numeric(chunk["ArrDel15"], errors="coerce")
            valid_scheduled = scheduled.between(0, 2400) & (
                (scheduled % 100) < 60
            )
            chunk = chunk[
                target.isin([0, 1])
                & valid_scheduled
                & duration.gt(0)
                & distance.gt(0)
                & chunk["Month"].between(1, 12)
                & chunk["DayofMonth"].between(1, 31)
                & chunk["DayOfWeek"].between(1, 7)
                & chunk["Reporting_Airline"].notna()
                & chunk["Origin"].notna()
                & chunk["Dest"].notna()
                & (chunk["Cancelled"].fillna(0) == 0)
                & (chunk["Diverted"].fillna(0) == 0)
            ].copy()
            if chunk.empty:
                continue
            chunk["Reporting_Airline"] = chunk["Reporting_Airline"].astype(str)
            chunk["Origin"] = chunk["Origin"].astype(str)
            chunk["Dest"] = chunk["Dest"].astype(str)
            chunk = chunk[
                chunk["Reporting_Airline"].str.strip().ne("")
                & chunk["Origin"].str.strip().ne("")
                & chunk["Dest"].str.strip().ne("")
            ].copy()
            if chunk.empty:
                continue
            chunk["CRSDepTime"] = scheduled.loc[chunk.index]
            chunk["CRSElapsedTime"] = duration.loc[chunk.index]
            chunk["Distance"] = distance.loc[chunk.index]
            chunk["ArrDel15"] = target.loc[chunk.index]
            chunk["route"] = chunk["Origin"] + "_" + chunk["Dest"]
            chunk["ArrDel15"] = chunk["ArrDel15"].astype("int8")
            yield chunk[SAMPLE_COLUMNS]


def merge_group_totals(
    counts: dict[str, int],
    positives: dict[str, float],
    grouped: pd.DataFrame,
) -> None:
    for key, row in grouped.iterrows():
        key_text = str(key)
        counts[key_text] += int(row["count"])
        positives[key_text] += float(row["sum"])


def sample_limits(max_rows: int, month_count: int) -> list[int]:
    """Allocate an exact, nearly equal sample budget across months."""
    if month_count < 1:
        raise ValueError("At least one month is required")
    if max_rows < month_count:
        raise ValueError(
            f"Sample cap {max_rows} must be at least the {month_count} selected months"
        )
    base, remainder = divmod(max_rows, month_count)
    return [base + (index < remainder) for index in range(month_count)]


def update_priority_sample(
    candidates: pd.DataFrame,
    rows: pd.DataFrame,
    limit: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Keep a uniform bounded sample by retaining the smallest random keys."""
    incoming = rows[SAMPLE_COLUMNS].copy()
    incoming["_sample_priority"] = rng.random(len(incoming))
    combined = (
        incoming
        if candidates.empty
        else pd.concat([candidates, incoming], ignore_index=True)
    )
    if len(combined) > limit:
        combined = combined.nsmallest(limit, "_sample_priority")
    return combined.reset_index(drop=True)


def finish_priority_sample(candidates: pd.DataFrame, month: int) -> pd.DataFrame:
    if candidates.empty:
        raise RuntimeError(f"No valid flight rows found for month {month}")
    return candidates.drop(columns="_sample_priority").reset_index(drop=True)


def collect_training_data(
    data_dir: Path,
    months: list[int],
    chunksize: int,
    max_rows: int,
    seed: int,
) -> tuple[dict, dict, pd.DataFrame, ScheduleContextMaps]:
    """Collect full training statistics and a bounded raw sample in one pass."""
    count_maps = {
        "carrier": defaultdict(int),
        "origin": defaultdict(int),
        "destination": defaultdict(int),
        "route": defaultdict(int),
    }
    positive_maps = {
        "carrier": defaultdict(float),
        "origin": defaultdict(float),
        "destination": defaultdict(float),
        "route": defaultdict(float),
    }
    route_profiles: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "duration_sum": 0.0, "distance_sum": 0.0}
    )
    total_rows = 0
    total_positive = 0.0
    rng = np.random.default_rng(seed)
    limits = sample_limits(max_rows, len(months))
    sampled_months: list[pd.DataFrame] = []
    fold_statistics: dict[int, dict] = {}
    schedule_context_accumulator = ScheduleContextAccumulator()

    for month, month_limit in zip(months, limits, strict=True):
        path = archive_path(data_dir, month)
        month_candidates = pd.DataFrame()
        month_rows = 0
        month_positive = 0.0
        month_count_maps = {
            label: defaultdict(int) for label in count_maps
        }
        month_positive_maps = {
            label: defaultdict(float) for label in positive_maps
        }
        progress(
            f"Training scan month {month:02d}/{months[-1]:02d} started "
            f"(sample cap {month_limit:,})"
        )
        for chunk_number, chunk in enumerate(
            iter_clean_chunks(path, chunksize), start=1
        ):
            chunk_positive = float(chunk["ArrDel15"].sum())
            month_rows += len(chunk)
            month_positive += chunk_positive
            total_rows += len(chunk)
            total_positive += chunk_positive
            schedule_context_accumulator.update(chunk)
            for label, column in (
                ("carrier", "Reporting_Airline"),
                ("origin", "Origin"),
                ("destination", "Dest"),
                ("route", "route"),
            ):
                grouped = chunk.groupby(column, observed=True)["ArrDel15"].agg(
                    ["count", "sum"]
                )
                merge_group_totals(count_maps[label], positive_maps[label], grouped)
                merge_group_totals(
                    month_count_maps[label], month_positive_maps[label], grouped
                )

            profiles = chunk.groupby(
                ["Reporting_Airline", "Origin", "Dest"], observed=True
            ).agg(
                count=("ArrDel15", "size"),
                duration_sum=("CRSElapsedTime", "sum"),
                distance_sum=("Distance", "sum"),
            )
            for key, row in profiles.iterrows():
                profile_key = "|".join(map(str, key))
                profile = route_profiles[profile_key]
                profile["count"] += float(row["count"])
                profile["duration_sum"] += float(row["duration_sum"])
                profile["distance_sum"] += float(row["distance_sum"])

            month_candidates = update_priority_sample(
                month_candidates, chunk, month_limit, rng
            )
            progress(
                f"Training month {month:02d}: chunk {chunk_number}, "
                f"{month_rows:,} clean rows, {len(month_candidates):,} retained"
            )

        sampled_month = finish_priority_sample(month_candidates, month)
        sampled_months.append(sampled_month)
        fold_statistics[month] = {
            "summary": {
                "rows": month_rows,
                "positiveRows": int(month_positive),
            },
            "counts": {
                label: dict(values) for label, values in month_count_maps.items()
            },
            "positives": {
                label: dict(values)
                for label, values in month_positive_maps.items()
            },
        }
        progress(
            f"Training month {month:02d} complete: {month_rows:,} clean rows, "
            f"{len(sampled_month):,} sampled"
        )

    if total_rows == 0:
        raise RuntimeError("No valid training rows were found")

    global_rate = total_positive / total_rows

    def smooth_map(label: str, prior_weight: float) -> dict[str, float]:
        result = {}
        for key, count in count_maps[label].items():
            positives = positive_maps[label][key]
            result[key] = (positives + prior_weight * global_rate) / (
                count + prior_weight
            )
        return result

    rate_maps = {
        "global": global_rate,
        "carrier": smooth_map("carrier", RATE_PRIORS["carrier"]),
        "origin": smooth_map("origin", RATE_PRIORS["origin"]),
        "destination": smooth_map("destination", RATE_PRIORS["destination"]),
        "route": smooth_map("route", RATE_PRIORS["route"]),
    }
    statistics = {
        "rows": total_rows,
        "positiveRows": int(total_positive),
        "globalDelayRate": global_rate,
    }
    aggregate_info = {
        "profiles": route_profiles,
        "summary": statistics,
        "counts": {label: dict(values) for label, values in count_maps.items()},
        "positives": {
            label: dict(values) for label, values in positive_maps.items()
        },
        "folds": fold_statistics,
    }
    training_sample = pd.concat(sampled_months, ignore_index=True)
    progress(
        f"Training scan complete: {total_rows:,} clean historical rows, "
        f"{len(training_sample):,} retained for fitting"
    )
    return (
        rate_maps,
        aggregate_info,
        training_sample,
        schedule_context_accumulator.finalize(),
    )


def rate_lookup(series: pd.Series, mapping: dict[str, float], fallback: float) -> np.ndarray:
    return series.astype(str).map(mapping).fillna(fallback).to_numpy(dtype="float32")


def out_of_fold_rate(
    series: pd.Series,
    total_counts: dict[str, int],
    total_positives: dict[str, float],
    fold_counts: dict[str, int],
    fold_positives: dict[str, float],
    prior_weight: float,
    prior_rate: float,
) -> np.ndarray:
    """Encode a held-out month using target totals from every other month.

    Do not replace this with per-row leave-one-out encoding. For otherwise
    identical group members, subtracting each positive row's own target makes
    its encoded rate exactly ``1 / (count - 1 + prior)`` lower than a negative
    row's rate. Tree models can learn that artificial inverse-label signal.
    """
    keys = series.astype(str)
    count = (
        keys.map(total_counts).fillna(0).to_numpy(dtype="float64")
        - keys.map(fold_counts).fillna(0).to_numpy(dtype="float64")
    )
    positive = (
        keys.map(total_positives).fillna(0).to_numpy(dtype="float64")
        - keys.map(fold_positives).fillna(0).to_numpy(dtype="float64")
    )
    encoded = (positive + prior_weight * prior_rate) / (
        np.maximum(count, 0.0) + prior_weight
    )
    return encoded.astype("float32")


def engineer(
    chunk: pd.DataFrame,
    rate_maps: dict,
    out_of_fold_statistics: dict | None = None,
    feature_set: str = "core",
    schedule_context_maps: ScheduleContextMaps | None = None,
    weather_dir: Path = Path("skyeta-ml/data/weather"),
    weather_year: int = DEFAULT_WEATHER_YEAR,
    weather_cutoff_hours: float = DEFAULT_CUTOFF_HOURS,
    weather_max_observation_age_hours: float = DEFAULT_MAX_OBSERVATION_AGE_HOURS,
) -> tuple[pd.DataFrame, np.ndarray]:
    chunk = chunk.reset_index(drop=True)
    month = chunk["Month"].to_numpy(dtype="float32")
    weekday = chunk["DayOfWeek"].to_numpy(dtype="float32")
    day_of_month = chunk["DayofMonth"].to_numpy(dtype="float32")
    scheduled = chunk["CRSDepTime"].fillna(0).to_numpy(dtype="int32") % 2400
    hour = np.clip(scheduled // 100, 0, 23).astype("float32")
    minute = np.clip(scheduled % 100, 0, 59).astype("float32")
    global_rate = float(rate_maps["global"])
    target = chunk["ArrDel15"].to_numpy(dtype="float32")
    month_values = chunk["Month"].to_numpy(dtype="int16")

    def encoded_rate(label: str, series: pd.Series) -> np.ndarray:
        if out_of_fold_statistics is None:
            return rate_lookup(series, rate_maps[label], global_rate)
        encoded = np.empty(len(series), dtype="float32")
        overall_summary = out_of_fold_statistics["summary"]
        for month in np.unique(month_values):
            fold = out_of_fold_statistics["folds"].get(int(month))
            if fold is None:
                raise RuntimeError(f"No out-of-fold statistics for month {month}")
            fold_summary = fold["summary"]
            excluded_rows = (
                float(overall_summary["rows"]) - float(fold_summary["rows"])
            )
            if excluded_rows <= 0:
                raise RuntimeError("Out-of-fold encoding requires at least two months")
            excluded_global_rate = (
                float(overall_summary["positiveRows"])
                - float(fold_summary["positiveRows"])
            ) / excluded_rows
            positions = np.flatnonzero(month_values == month)
            encoded[positions] = out_of_fold_rate(
                series.iloc[positions],
                out_of_fold_statistics["counts"][label],
                out_of_fold_statistics["positives"][label],
                fold["counts"][label],
                fold["positives"][label],
                RATE_PRIORS[label],
                excluded_global_rate,
            )
        return encoded

    core_frame = pd.DataFrame(
        {
            "month_sin": np.sin(2 * np.pi * month / 12.0),
            "month_cos": np.cos(2 * np.pi * month / 12.0),
            "weekday_sin": np.sin(2 * np.pi * weekday / 7.0),
            "weekday_cos": np.cos(2 * np.pi * weekday / 7.0),
            "day_of_month_sin": np.sin(2 * np.pi * day_of_month / 31.0),
            "day_of_month_cos": np.cos(2 * np.pi * day_of_month / 31.0),
            "departure_hour_sin": np.sin(2 * np.pi * hour / 24.0),
            "departure_hour_cos": np.cos(2 * np.pi * hour / 24.0),
            "departure_minute_fraction": minute / 60.0,
            "is_weekend": np.isin(weekday, [6, 7]).astype("float32"),
            "scheduled_duration_minutes": chunk["CRSElapsedTime"].to_numpy(
                dtype="float32"
            ),
            "distance_miles": chunk["Distance"].to_numpy(dtype="float32"),
            "carrier_delay_rate": encoded_rate(
                "carrier", chunk["Reporting_Airline"]
            ),
            "origin_delay_rate": encoded_rate("origin", chunk["Origin"]),
            "destination_delay_rate": encoded_rate(
                "destination", chunk["Dest"]
            ),
            "route_delay_rate": encoded_rate("route", chunk["route"]),
        },
        columns=CORE_FEATURE_NAMES,
    )
    feature_parts = [core_frame]
    if uses_context(feature_set):
        if schedule_context_maps is None:
            raise ValueError(
                f"Feature set '{feature_set}' requires training-only schedule context maps"
            )
        feature_parts.append(
            transform_schedule_context(
                chunk,
                schedule_context_maps,
                default_year=weather_year,
            )
        )
    if uses_weather(feature_set):
        feature_parts.append(
            attach_predeparture_weather(
                chunk,
                weather_dir=weather_dir,
                year=weather_year,
                cutoff_hours=weather_cutoff_hours,
                max_observation_age_hours=weather_max_observation_age_hours,
            )
        )

    feature_names = feature_names_for(feature_set)
    frame = pd.concat(feature_parts, axis=1)
    return frame[feature_names].astype("float32"), target.astype("int8")


def load_split_sample(
    data_dir: Path,
    months: list[int],
    chunksize: int,
    max_rows: int,
    seed: int,
    split_name: str,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    limits = sample_limits(max_rows, len(months))
    raw_parts: list[pd.DataFrame] = []

    for month, month_limit in zip(months, limits, strict=True):
        month_candidates = pd.DataFrame()
        month_rows = 0
        progress(
            f"{split_name} scan month {month:02d} started "
            f"(sample cap {month_limit:,})"
        )
        for chunk_number, chunk in enumerate(
            iter_clean_chunks(archive_path(data_dir, month), chunksize), start=1
        ):
            month_rows += len(chunk)
            month_candidates = update_priority_sample(
                month_candidates, chunk, month_limit, rng
            )
            progress(
                f"{split_name} month {month:02d}: chunk {chunk_number}, "
                f"{month_rows:,} clean rows, {len(month_candidates):,} retained"
            )
        sampled_month = finish_priority_sample(month_candidates, month)
        raw_parts.append(sampled_month)
        progress(
            f"{split_name} month {month:02d} complete: {month_rows:,} clean rows, "
            f"{len(sampled_month):,} sampled"
        )

    raw_sample = pd.concat(raw_parts, ignore_index=True)
    progress(f"{split_name} sample ready: {len(raw_sample):,} retained rows")
    return raw_sample


def load_split(
    data_dir: Path,
    months: list[int],
    rate_maps: dict,
    chunksize: int,
    max_rows: int,
    seed: int,
    split_name: str,
    *,
    feature_set: str = "core",
    schedule_context_maps: ScheduleContextMaps | None = None,
    weather_dir: Path = Path("skyeta-ml/data/weather"),
    weather_year: int = DEFAULT_WEATHER_YEAR,
    weather_cutoff_hours: float = DEFAULT_CUTOFF_HOURS,
    weather_max_observation_age_hours: float = DEFAULT_MAX_OBSERVATION_AGE_HOURS,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Load and engineer one split; retained as a small public helper.

    The main ablation path uses :func:`load_split_sample` so the selected and
    core models are evaluated on exactly the same sampled rows.
    """
    raw_sample = load_split_sample(
        data_dir,
        months,
        chunksize,
        max_rows,
        seed,
        split_name,
    )
    features, target = engineer(
        raw_sample,
        rate_maps,
        feature_set=feature_set,
        schedule_context_maps=schedule_context_maps,
        weather_dir=weather_dir,
        weather_year=weather_year,
        weather_cutoff_hours=weather_cutoff_hours,
        weather_max_observation_age_hours=weather_max_observation_age_hours,
    )
    progress(f"{split_name} sample engineered: {len(target):,} rows")
    return features, target


def stable_sigmoid(raw_score: np.ndarray) -> np.ndarray:
    raw_score = np.asarray(raw_score, dtype="float64")
    probability = np.empty_like(raw_score)
    positive = raw_score >= 0
    probability[positive] = 1.0 / (1.0 + np.exp(-raw_score[positive]))
    exponential = np.exp(raw_score[~positive])
    probability[~positive] = exponential / (1.0 + exponential)
    return probability


def fit_sigmoid_calibration(
    raw_score: np.ndarray,
    y_true: np.ndarray,
) -> dict[str, float | int | str]:
    """Fit a compact Platt calibrator on the chronological validation split.

    The browser evaluates LightGBM's raw margin first and then applies this
    affine sigmoid.  The untouched December test split is used only to report
    whether calibration generalises; it is never used to fit this transform.
    """
    raw_score = np.asarray(raw_score, dtype="float64")
    y_true = np.asarray(y_true, dtype="int8")
    if raw_score.ndim != 1 or len(raw_score) != len(y_true):
        raise ValueError("Calibration scores and labels must be aligned vectors")
    if len(np.unique(y_true)) != 2:
        raise ValueError("Calibration requires both target classes")
    calibrator = LogisticRegression(
        C=1_000_000.0,
        solver="lbfgs",
        max_iter=1_000,
    )
    calibrator.fit(raw_score.reshape(-1, 1), y_true)
    slope = float(calibrator.coef_[0, 0])
    intercept = float(calibrator.intercept_[0])
    if not math.isfinite(slope) or slope <= 0 or not math.isfinite(intercept):
        raise RuntimeError(
            "Validation calibration produced a non-monotonic or invalid transform"
        )
    return {
        "method": "platt_sigmoid",
        "input": "lightgbm_raw_score",
        "slope": slope,
        "intercept": intercept,
        "fittedOn": "validation",
        "rows": int(len(y_true)),
    }


def apply_sigmoid_calibration(
    raw_score: np.ndarray,
    calibration: dict[str, float | int | str],
) -> np.ndarray:
    return stable_sigmoid(
        float(calibration["slope"]) * np.asarray(raw_score, dtype="float64")
        + float(calibration["intercept"])
    )


def expected_calibration_error(
    y_true: np.ndarray,
    probability: np.ndarray,
    bin_count: int = CALIBRATION_BIN_COUNT,
) -> float:
    """Return an equal-width ECE diagnostic, weighted by bin population."""
    y_true = np.asarray(y_true, dtype="float64")
    probability = np.asarray(probability, dtype="float64")
    edges = np.linspace(0.0, 1.0, bin_count + 1)
    bin_index = np.minimum(
        np.searchsorted(edges, probability, side="right") - 1,
        bin_count - 1,
    )
    total = len(y_true)
    error = 0.0
    for index in range(bin_count):
        members = bin_index == index
        count = int(members.sum())
        if count:
            error += (count / total) * abs(
                float(probability[members].mean())
                - float(y_true[members].mean())
            )
    return float(error)


def select_f1_threshold(
    y_true: np.ndarray,
    probability: np.ndarray,
) -> float:
    """Select a validation-only diagnostic threshold that maximises F1."""
    precision, recall, thresholds = precision_recall_curve(y_true, probability)
    if not len(thresholds):
        raise RuntimeError("No finite validation thresholds were available")
    denominator = precision[:-1] + recall[:-1]
    f1 = np.divide(
        2.0 * precision[:-1] * recall[:-1],
        denominator,
        out=np.zeros_like(denominator),
        where=denominator > 0,
    )
    best = int(np.argmax(f1))
    threshold = float(thresholds[best])
    if not 0.0 < threshold < 1.0:
        raise RuntimeError(f"Invalid validation decision threshold: {threshold}")
    return threshold


def classification_at_threshold(
    y_true: np.ndarray,
    probability: np.ndarray,
    threshold: float,
) -> dict[str, float]:
    predicted = (probability >= threshold).astype("int8")
    return {
        "threshold": float(threshold),
        "accuracy": float(accuracy_score(y_true, predicted)),
        "precision": float(precision_score(y_true, predicted, zero_division=0)),
        "recall": float(recall_score(y_true, predicted, zero_division=0)),
        "f1": float(f1_score(y_true, predicted, zero_division=0)),
        "predictedPositiveShare": float(np.mean(predicted)),
    }


def evaluate(
    y_true: np.ndarray,
    probability: np.ndarray,
    decision_threshold: float = 0.5,
) -> dict:
    probability = np.asarray(probability, dtype="float64")
    at_50 = classification_at_threshold(y_true, probability, 0.5)
    return {
        "rocAuc": float(roc_auc_score(y_true, probability)),
        "averagePrecision": float(average_precision_score(y_true, probability)),
        "brierScore": float(brier_score_loss(y_true, probability)),
        "logLoss": float(log_loss(y_true, probability)),
        # Retained for transparent comparison with the conventional cutoff.
        # A zero recall here is not hidden when every estimate is below 0.5.
        "accuracyAt50": at_50["accuracy"],
        "precisionAt50": at_50["precision"],
        "recallAt50": at_50["recall"],
        "f1At50": at_50["f1"],
        "atDecisionThreshold": classification_at_threshold(
            y_true, probability, decision_threshold
        ),
        "probabilityRange": {
            "minimum": float(np.min(probability)),
            "maximum": float(np.max(probability)),
        },
        "meanPredictedProbability": float(np.mean(probability)),
        "expectedCalibrationError10Bins": expected_calibration_error(
            y_true, probability
        ),
        "rows": int(len(y_true)),
        "delayRate": float(np.mean(y_true)),
    }


def evaluate_dump_tree(node: dict, row: np.ndarray) -> float:
    current = node
    for _ in range(512):
        if "leaf_value" in current:
            return float(current["leaf_value"])
        feature_index = int(current["split_feature"])
        value = float(row[feature_index])
        threshold = float(current["threshold"])
        decision_type = current.get("decision_type", "<=")
        if not math.isfinite(value):
            go_left = bool(current.get("default_left", False))
        elif decision_type == "<=":
            go_left = value <= threshold
        elif decision_type == "<":
            go_left = value < threshold
        elif decision_type == ">":
            go_left = value > threshold
        elif decision_type == ">=":
            go_left = value >= threshold
        else:
            raise RuntimeError(f"Unsupported LightGBM decision type: {decision_type}")
        current = current["left_child"] if go_left else current["right_child"]
    raise RuntimeError("LightGBM tree exceeded the traversal depth limit")


def evaluate_dump_raw_score(model_dump: dict, row: np.ndarray) -> float:
    return sum(
        evaluate_dump_tree(tree["tree_structure"], row)
        for tree in model_dump["tree_info"]
    )


def evaluate_dump_probability(
    model_dump: dict,
    row: np.ndarray,
    calibration: dict[str, float | int | str] | None = None,
) -> float:
    raw_score = evaluate_dump_raw_score(model_dump, row)
    if calibration is not None:
        raw_score = (
            float(calibration["slope"]) * raw_score
            + float(calibration["intercept"])
        )
    return float(stable_sigmoid(np.array([raw_score]))[0])


def route_presets(profiles: dict[str, dict[str, float]], limit: int = 18) -> list[dict]:
    ranked = sorted(profiles.items(), key=lambda item: item[1]["count"], reverse=True)
    presets = []
    seen_routes: set[str] = set()
    for key, values in ranked:
        carrier, origin, destination = key.split("|")
        route_key = f"{origin}_{destination}"
        if route_key in seen_routes:
            continue
        seen_routes.add(route_key)
        count = values["count"]
        presets.append(
            {
                "carrier": carrier,
                "origin": origin,
                "destination": destination,
                "scheduledDurationMinutes": round(values["duration_sum"] / count),
                "distanceMiles": round(values["distance_sum"] / count),
                "trainingFlights": int(count),
            }
        )
        if len(presets) >= limit:
            break
    return presets


def fit_classifier(
    x_train: pd.DataFrame,
    y_train: np.ndarray,
    x_validation: pd.DataFrame,
    y_validation: np.ndarray,
    *,
    seed: int,
    estimator_count: int,
    early_stopping_rounds: int,
    log_period: int,
    label: str,
) -> lgb.LGBMClassifier:
    progress(
        f"Fitting {label} LightGBM on {len(y_train):,} rows; "
        f"validation has {len(y_validation):,} rows"
    )
    model = lgb.LGBMClassifier(
        objective="binary",
        n_estimators=estimator_count,
        learning_rate=0.04,
        num_leaves=31,
        max_depth=-1,
        min_child_samples=150,
        subsample=0.9,
        subsample_freq=1,
        colsample_bytree=0.9,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=seed,
        n_jobs=-1,
        verbosity=-1,
    )
    model.fit(
        x_train,
        y_train,
        eval_set=[(x_validation, y_validation)],
        eval_metric="auc",
        callbacks=[
            lgb.early_stopping(early_stopping_rounds, verbose=True),
            lgb.log_evaluation(period=log_period),
        ],
    )
    progress(f"{label} fit complete at iteration {model.best_iteration_}")
    return model


def weather_coverage(frame: pd.DataFrame) -> dict[str, float | int]:
    origin = frame["origin_weather_missing_fraction"].lt(1.0)
    destination = frame["destination_weather_missing_fraction"].lt(1.0)
    return {
        "rows": int(len(frame)),
        "originAvailableShare": float(origin.mean()),
        "destinationAvailableShare": float(destination.mean()),
        "atLeastOneEndpointShare": float((origin | destination).mean()),
        "bothEndpointsShare": float((origin & destination).mean()),
    }


def ablation_comparison(
    selected_feature_set: str,
    selected_metrics: dict[str, dict[str, float]],
    core_metrics: dict[str, dict[str, float]],
) -> dict:
    validation_auc_gain = (
        selected_metrics["validation"]["rocAuc"]
        - core_metrics["validation"]["rocAuc"]
    )
    accepted = validation_auc_gain >= MIN_ABLATION_VALIDATION_ROC_AUC_GAIN
    return {
        "baselineFeatureSet": "core",
        "selectedFeatureSet": selected_feature_set,
        "sameSampleRows": True,
        "acceptance": {
            "accepted": accepted,
            "decisionSplit": "validation",
            "primaryMetric": "rocAuc",
            "minimumSelectedMinusCore": (
                MIN_ABLATION_VALIDATION_ROC_AUC_GAIN
            ),
            "observedSelectedMinusCore": validation_auc_gain,
            "testUsedForSelection": False,
        },
        "core": core_metrics,
        "selected": selected_metrics,
        "deltaSelectedMinusCore": {
            split: {
                "rocAuc": selected_metrics[split]["rocAuc"]
                - core_metrics[split]["rocAuc"],
                "averagePrecision": selected_metrics[split]["averagePrecision"]
                - core_metrics[split]["averagePrecision"],
                "brierScore": selected_metrics[split]["brierScore"]
                - core_metrics[split]["brierScore"],
                "logLoss": selected_metrics[split]["logLoss"]
                - core_metrics[split]["logLoss"],
            }
            for split in ("validation", "test")
        },
    }


def browser_feature_values(row: np.ndarray) -> list[float | None]:
    """Encode LightGBM missing values as JSON null, never non-standard NaN."""
    return [float(value) if math.isfinite(float(value)) else None for value in row]


def schedule_context_export(maps: ScheduleContextMaps) -> dict:
    return {
        "featureNames": CONTEXT_FEATURE_NAMES,
        "maps": {
            "route": maps.route,
            "carrierRoute": maps.carrier_route,
            "originBank": maps.origin_bank,
        },
    }


def main() -> None:
    args = parse_args()
    progress("ML dependencies loaded; validating arguments")
    for name in (
        "max_train_rows",
        "max_validation_rows",
        "max_test_rows",
        "chunksize",
    ):
        if getattr(args, name) < 1:
            raise ValueError(f"--{name.replace('_', '-')} must be at least 1")
    if args.ablation and args.feature_set == "core":
        raise ValueError("--ablation requires a non-core --feature-set")
    if (
        not args.smoke_test
        and args.feature_set != "core"
        and not args.ablation
    ):
        raise ValueError(
            "A public non-core export requires --ablation so its validation "
            "gain over the core contract is recorded and checked"
        )
    if args.weather_cutoff_hours <= 0:
        raise ValueError("--weather-cutoff-hours must be positive")
    if args.weather_max_observation_age_hours <= 0:
        raise ValueError("--weather-max-observation-age-hours must be positive")
    if args.weather_year != 2025:
        raise ValueError("The current BTS archive contract requires --weather-year 2025")
    if args.allow_partial_weather and not args.smoke_test:
        raise ValueError(
            "--allow-partial-weather is restricted to --smoke-test so an incomplete "
            "weather cache cannot be exported publicly"
        )

    weather_manifest = None
    if uses_weather(args.feature_set):
        weather_manifest = validate_weather_cache(
            args.weather_dir,
            args.weather_year,
            args.allow_partial_weather,
        )
        cached_count = sum(
            bool(entry.get("downloaded"))
            for entry in weather_manifest["airports"]
        )
        progress(
            f"Weather contract enabled: {cached_count}/"
            f"{len(weather_manifest['airports'])} station files cached"
        )

    if args.smoke_test:
        train_months = [1, 2, 3]
        validation_months = [4]
        test_months = [5]
        max_train_rows = min(args.max_train_rows, 60_000)
        max_validation_rows = min(args.max_validation_rows, 20_000)
        max_test_rows = min(args.max_test_rows, 20_000)
        estimator_count = 120
        early_stopping_rounds = 15
        log_period = 10
        progress(
            "Smoke mode: Jan-Mar train, April validation, May test; "
            "artifacts will not be written"
        )
    else:
        train_months = list(range(1, 10))
        validation_months = [10, 11]
        test_months = [12]
        max_train_rows = args.max_train_rows
        max_validation_rows = args.max_validation_rows
        max_test_rows = args.max_test_rows
        estimator_count = 600
        early_stopping_rounds = 40
        log_period = 25

    selected_months = sorted(set(train_months + validation_months + test_months))
    expected = [
        (month, archive_path(args.data_dir, month)) for month in selected_months
    ]
    missing = [str(path) for _, path in expected if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing BTS archives:\n" + "\n".join(missing))
    progress("Stage 1/5: checking ZIP directories and BTS CSV schemas")
    for index, (month, path) in enumerate(expected, start=1):
        validate_archive(path)
        progress(
            f"Archive month {month:02d} header verified "
            f"({index}/{len(expected)})"
        )

    progress(
        "Stage 2/5: one-pass training statistics and bounded sampling"
    )
    rate_maps, aggregate_info, training_sample, schedule_context_maps = (
        collect_training_data(
        args.data_dir,
        train_months,
        args.chunksize,
        max_train_rows,
        args.seed,
        )
    )
    engineering_options = {
        "schedule_context_maps": schedule_context_maps,
        "weather_dir": args.weather_dir,
        "weather_year": args.weather_year,
        "weather_cutoff_hours": args.weather_cutoff_hours,
        "weather_max_observation_age_hours": (
            args.weather_max_observation_age_hours
        ),
    }
    progress(
        "Engineering selected training rows with month-held-out target rates "
        f"and the '{args.feature_set}' contract"
    )
    x_train, y_train = engineer(
        training_sample,
        rate_maps,
        out_of_fold_statistics=aggregate_info,
        feature_set=args.feature_set,
        **engineering_options,
    )
    x_train_core = None
    if args.ablation:
        progress("Engineering identical training rows for the core ablation baseline")
        x_train_core, core_target = engineer(
            training_sample,
            rate_maps,
            out_of_fold_statistics=aggregate_info,
            feature_set="core",
        )
        if not np.array_equal(y_train, core_target):
            raise RuntimeError("Ablation training targets are not row-identical")
    del training_sample
    train_row_count = int(len(y_train))
    progress(f"Training matrix ready: {train_row_count:,} rows")

    progress(
        "Stage 3/5: streaming validation month(s) "
        + ", ".join(f"{month:02d}" for month in validation_months)
    )
    validation_sample = load_split_sample(
        args.data_dir,
        validation_months,
        args.chunksize,
        max_validation_rows,
        args.seed + 1,
        "Validation",
    )
    x_validation, y_validation = engineer(
        validation_sample,
        rate_maps,
        feature_set=args.feature_set,
        **engineering_options,
    )
    x_validation_core = None
    if args.ablation:
        x_validation_core, core_target = engineer(
            validation_sample,
            rate_maps,
            feature_set="core",
        )
        if not np.array_equal(y_validation, core_target):
            raise RuntimeError("Ablation validation targets are not row-identical")
    del validation_sample
    validation_row_count = int(len(y_validation))
    rate_baseline = x_validation[RATE_FEATURE_NAMES].mean(axis=1).to_numpy()
    rate_baseline_auc = float(roc_auc_score(y_validation, rate_baseline))
    progress(f"Historical-rate validation baseline AUC: {rate_baseline_auc:.6f}")
    if rate_baseline_auc <= 0.5:
        raise RuntimeError(
            "Historical rate features are at or below random direction "
            f"(validation AUC {rate_baseline_auc:.6f}); refusing to fit"
        )

    progress("Stage 4/5: fitting and validating selected feature contract")
    model = fit_classifier(
        x_train,
        y_train,
        x_validation,
        y_validation,
        seed=args.seed,
        estimator_count=estimator_count,
        early_stopping_rounds=early_stopping_rounds,
        log_period=log_period,
        label=args.feature_set,
    )
    validation_raw_score = model.predict(x_validation, raw_score=True)
    validation_uncalibrated_probability = model.predict_proba(x_validation)[:, 1]
    calibration = fit_sigmoid_calibration(validation_raw_score, y_validation)
    validation_probability = apply_sigmoid_calibration(
        validation_raw_score, calibration
    )
    decision_threshold = select_f1_threshold(
        y_validation, validation_probability
    )
    validation_metrics = evaluate(
        y_validation, validation_probability, decision_threshold
    )
    validation_uncalibrated_metrics = evaluate(
        y_validation, validation_uncalibrated_probability
    )
    if validation_metrics["rocAuc"] <= MIN_EXPORT_ROC_AUC:
        raise RuntimeError(
            "Validation AUC failed the export safety floor: "
            f"{validation_metrics['rocAuc']:.6f} <= {MIN_EXPORT_ROC_AUC:.2f}"
        )
    progress(
        f"Validation AUC passed safety floor: {validation_metrics['rocAuc']:.6f}"
    )
    progress(
        "Validation Platt calibration fitted: Brier "
        f"{validation_uncalibrated_metrics['brierScore']:.6f} -> "
        f"{validation_metrics['brierScore']:.6f}; diagnostic F1 threshold "
        f"{decision_threshold:.6f}"
    )

    core_model = None
    core_validation_metrics = None
    core_calibration = None
    core_decision_threshold = None
    if args.ablation:
        if x_train_core is None or x_validation_core is None:
            raise RuntimeError("Core ablation matrices were not prepared")
        core_model = fit_classifier(
            x_train_core,
            y_train,
            x_validation_core,
            y_validation,
            seed=args.seed,
            estimator_count=estimator_count,
            early_stopping_rounds=early_stopping_rounds,
            log_period=log_period,
            label="core ablation baseline",
        )
        core_validation_raw_score = core_model.predict(
            x_validation_core, raw_score=True
        )
        core_calibration = fit_sigmoid_calibration(
            core_validation_raw_score, y_validation
        )
        core_validation_probability = apply_sigmoid_calibration(
            core_validation_raw_score, core_calibration
        )
        core_decision_threshold = select_f1_threshold(
            y_validation, core_validation_probability
        )
        core_validation_metrics = evaluate(
            y_validation,
            core_validation_probability,
            core_decision_threshold,
        )
        progress(
            "Validation ablation delta (selected - core) AUC: "
            f"{validation_metrics['rocAuc'] - core_validation_metrics['rocAuc']:+.6f}"
        )
        validation_auc_gain = (
            validation_metrics["rocAuc"]
            - core_validation_metrics["rocAuc"]
        )
        if (
            not args.smoke_test
            and validation_auc_gain
            < MIN_ABLATION_VALIDATION_ROC_AUC_GAIN
        ):
            raise RuntimeError(
                "Selected feature contract failed the predeclared validation "
                "ablation floor: selected - core AUC "
                f"{validation_auc_gain:+.6f} < "
                f"{MIN_ABLATION_VALIDATION_ROC_AUC_GAIN:+.3f}"
            )
    del x_train, x_train_core, y_train

    progress(
        "Stage 5/5: streaming test month(s) "
        + ", ".join(f"{month:02d}" for month in test_months)
    )
    test_sample = load_split_sample(
        args.data_dir,
        test_months,
        args.chunksize,
        max_test_rows,
        args.seed + 2,
        "Test",
    )
    x_test, y_test = engineer(
        test_sample,
        rate_maps,
        feature_set=args.feature_set,
        **engineering_options,
    )
    x_test_core = None
    if args.ablation:
        x_test_core, core_target = engineer(
            test_sample,
            rate_maps,
            feature_set="core",
        )
        if not np.array_equal(y_test, core_target):
            raise RuntimeError("Ablation test targets are not row-identical")
    del test_sample
    progress("Evaluating held-out metrics and browser export parity")
    test_raw_score = model.predict(x_test, raw_score=True)
    test_uncalibrated_probability = model.predict_proba(x_test)[:, 1]
    test_probability = apply_sigmoid_calibration(test_raw_score, calibration)
    test_metrics = evaluate(y_test, test_probability, decision_threshold)
    test_uncalibrated_metrics = evaluate(
        y_test, test_uncalibrated_probability
    )
    if test_metrics["rocAuc"] <= MIN_EXPORT_ROC_AUC:
        raise RuntimeError(
            "Test AUC failed the export safety floor: "
            f"{test_metrics['rocAuc']:.6f} <= {MIN_EXPORT_ROC_AUC:.2f}"
        )
    metrics = {
        "validation": validation_metrics,
        "test": test_metrics,
    }
    ablation = None
    if args.ablation:
        if (
            core_model is None
            or core_validation_metrics is None
            or core_calibration is None
            or core_decision_threshold is None
            or x_test_core is None
        ):
            raise RuntimeError("Core ablation model or test matrix is unavailable")
        core_test_raw_score = core_model.predict(x_test_core, raw_score=True)
        core_test_metrics = evaluate(
            y_test,
            apply_sigmoid_calibration(core_test_raw_score, core_calibration),
            core_decision_threshold,
        )
        ablation = ablation_comparison(
            args.feature_set,
            metrics,
            {
                "validation": core_validation_metrics,
                "test": core_test_metrics,
            },
        )
        progress(
            "Test ablation delta (selected - core) AUC: "
            f"{ablation['deltaSelectedMinusCore']['test']['rocAuc']:+.6f}"
        )
    test_row_count = int(len(y_test))
    progress(f"Test AUC passed safety floor: {test_metrics['rocAuc']:.6f}")

    calibration_report = {
        **calibration,
        "validation": {
            "brierScoreBefore": validation_uncalibrated_metrics["brierScore"],
            "brierScoreAfter": validation_metrics["brierScore"],
            "logLossBefore": validation_uncalibrated_metrics["logLoss"],
            "logLossAfter": validation_metrics["logLoss"],
            "ece10BinsBefore": validation_uncalibrated_metrics[
                "expectedCalibrationError10Bins"
            ],
            "ece10BinsAfter": validation_metrics[
                "expectedCalibrationError10Bins"
            ],
        },
        "test": {
            "brierScoreBefore": test_uncalibrated_metrics["brierScore"],
            "brierScoreAfter": test_metrics["brierScore"],
            "logLossBefore": test_uncalibrated_metrics["logLoss"],
            "logLossAfter": test_metrics["logLoss"],
            "ece10BinsBefore": test_uncalibrated_metrics[
                "expectedCalibrationError10Bins"
            ],
            "ece10BinsAfter": test_metrics[
                "expectedCalibrationError10Bins"
            ],
        },
    }
    decision_policy = {
        "purpose": "diagnostic classification only",
        "method": "maximum F1 on chronological validation split",
        "threshold": decision_threshold,
        "selectedOn": "validation",
        "testUsedForSelection": False,
        "usedForProbabilityDisplay": False,
        "usedForTravelRecommendation": False,
        "validation": validation_metrics["atDecisionThreshold"],
        "test": test_metrics["atDecisionThreshold"],
    }

    generated_at = datetime.now(timezone.utc).isoformat()
    source_files = [
        f"{SOURCE_BASE}/{SOURCE_PATTERN.format(month=month)}"
        for month in range(1, 13)
    ]
    booster_dump = model.booster_.dump_model()
    parity_frame = x_test.iloc[:64].astype("float32")
    parity_python = apply_sigmoid_calibration(
        model.predict(parity_frame, raw_score=True), calibration
    )
    parity_dump = np.array(
        [
            evaluate_dump_probability(booster_dump, row, calibration)
            for row in parity_frame.to_numpy(dtype="float32")
        ]
    )
    parity_error = float(np.max(np.abs(parity_python - parity_dump)))
    if parity_error > 1e-10:
        raise RuntimeError(
            f"Browser model export parity failed: max abs error {parity_error:.12g}"
        )
    progress(
        f"Browser dump parity verified (max absolute error {parity_error:.3g})"
    )
    parity_cases = [
        {
            "features": browser_feature_values(row),
            "probability": float(probability),
        }
        for row, probability in zip(
            parity_frame.to_numpy(dtype="float32"), parity_python, strict=True
        )
    ]

    if args.smoke_test:
        smoke_result = {
            "mode": "smoke-test",
            "featureSet": args.feature_set,
            "featureNames": feature_names_for(args.feature_set),
            "trainMonths": train_months,
            "validationMonths": validation_months,
            "testMonths": test_months,
            "sampleRows": {
                "train": train_row_count,
                "validation": validation_row_count,
                "test": test_row_count,
            },
            "historicalRateBaselineAuc": rate_baseline_auc,
            "metrics": metrics,
            "uncalibratedMetrics": {
                "validation": validation_uncalibrated_metrics,
                "test": test_uncalibrated_metrics,
            },
            "calibration": calibration_report,
            "decisionPolicy": decision_policy,
            "ablation": ablation,
            "browserExportMaxAbsoluteError": parity_error,
        }
        if uses_weather(args.feature_set):
            smoke_result["weatherCoverage"] = {
                "validation": weather_coverage(x_validation),
                "test": weather_coverage(x_test),
            }
        progress("Smoke test passed; no model artifacts were written")
        print(json.dumps(smoke_result, indent=2), flush=True)
        return

    args.public_dir.mkdir(parents=True, exist_ok=True)
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.artifact_dir / "skyeta-lightgbm.joblib"
    joblib.dump(
        {
            "model": model,
            "calibration": calibration,
            "decisionPolicy": decision_policy,
            "featureSet": args.feature_set,
            "featureNames": feature_names_for(args.feature_set),
        },
        model_path,
    )

    model_card = {
        "modelName": "SkyETA LightGBM 2025",
        "generatedAt": generated_at,
        "source": {
            "publisher": "U.S. Bureau of Transportation Statistics",
            "dataset": "Reporting Carrier On-Time Performance (1987-present)",
            "files": source_files,
        },
        "target": "ArrDel15 (arrival delay of at least 15 minutes)",
        "population": "Completed, non-diverted U.S. domestic flights",
        "split": {
            "train": "2025-01 through 2025-09",
            "validation": "2025-10 through 2025-11",
            "test": "2025-12",
        },
        "evaluationPolicy": {
            "validationUsedFor": [
                "early stopping",
                "probability calibration",
                "diagnostic threshold selection",
                "feature-set ablation acceptance",
            ],
            "testUsedFor": "final untouched reporting only",
            "reportedMetricProbabilities": "validation-fitted Platt calibrated",
        },
        "training": aggregate_info["summary"],
        "sampleRows": {
            "train": train_row_count,
            "validation": validation_row_count,
            "test": test_row_count,
        },
        "featureSet": args.feature_set,
        "features": feature_names_for(args.feature_set),
        "metrics": metrics,
        "uncalibratedMetrics": {
            "validation": validation_uncalibrated_metrics,
            "test": test_uncalibrated_metrics,
        },
        "calibration": calibration_report,
        "decisionPolicy": decision_policy,
        "ablation": ablation,
        "historicalRateValidationAuc": rate_baseline_auc,
        "baselines": {
            "networkHistoricalDelayRate": rate_maps["global"],
            "networkHistoricalDelayRateFitPeriod": (
                "2025-01 through 2025-09 training rows"
            ),
            "uiComparison": (
                "calibrated estimate minus training-period network delay rate"
            ),
            "historicalRateRanker": {
                "definition": (
                    "mean of the four smoothed carrier, origin, destination, "
                    "and route delay-rate features"
                ),
                "validationRocAuc": rate_baseline_auc,
            },
        },
        "minimumExportRocAuc": MIN_EXPORT_ROC_AUC,
        "browserExportMaxAbsoluteError": parity_error,
        "limitations": [
            "SkyETA is not live flight status or operational travel advice.",
            "The model is trained on 2025 U.S. domestic carrier records only.",
            "Predictions are estimates for route conditions, not guarantees for a specific flight.",
            "The validation-tuned classification threshold is a diagnostic only; it is not a travel recommendation or live operational alert.",
        ],
    }
    if uses_weather(args.feature_set):
        model_card["weather"] = {
            "publisher": weather_manifest["publisher"],
            "dataset": weather_manifest["dataset"],
            "documentation": GHCNH_DOCUMENTATION_URL,
            "year": args.weather_year,
            "cutoffHoursBeforeScheduledDeparture": args.weather_cutoff_hours,
            "maxObservationAgeHours": args.weather_max_observation_age_hours,
            "cachedStationCount": sum(
                bool(entry.get("downloaded"))
                for entry in weather_manifest["airports"]
            ),
            "coverage": {
                "validation": weather_coverage(x_validation),
                "test": weather_coverage(x_test),
            },
        }
        model_card["limitations"].append(
            "Weather uses backward-only NOAA observations available at the fixed "
            "pre-departure cutoff; missing airports and stale reports remain missing."
        )
    else:
        model_card["limitations"].append(
            "Weather, aircraft rotations, crew constraints, and live disruption "
            "data are not included."
        )
    if uses_context(args.feature_set):
        model_card["scheduleContext"] = {
            "fitPeriod": "2025-01 through 2025-09 only",
            "targetFree": True,
            "features": CONTEXT_FEATURE_NAMES,
        }
    browser_model = {
        "formatVersion": 2,
        "modelCard": model_card,
        "featureSet": args.feature_set,
        "featureNames": feature_names_for(args.feature_set),
        "booster": booster_dump,
        "calibration": {
            "method": calibration["method"],
            "input": calibration["input"],
            "slope": calibration["slope"],
            "intercept": calibration["intercept"],
        },
        "rates": rate_maps,
        "presets": route_presets(aggregate_info["profiles"]),
        "parityCases": parity_cases,
    }
    if uses_context(args.feature_set):
        browser_model["scheduleContext"] = schedule_context_export(
            schedule_context_maps
        )
    if uses_weather(args.feature_set):
        browser_model["weather"] = {
            "status": "included",
            "source": weather_manifest["dataset"],
            "year": args.weather_year,
            "cutoffHours": args.weather_cutoff_hours,
            "maxObservationAgeHours": args.weather_max_observation_age_hours,
            "featureNames": WEATHER_FEATURE_NAMES,
            "missingValue": None,
        }

    with (args.public_dir / "skyeta-model.json").open("w", encoding="utf-8") as handle:
        json.dump(browser_model, handle, separators=(",", ":"), allow_nan=False)
    with (args.public_dir / "skyeta-model-card.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(model_card, handle, indent=2, allow_nan=False)

    progress(
        "Training complete; wrote skyeta-model.json, skyeta-model-card.json, "
        "and the local joblib artifact"
    )
    print(json.dumps(model_card, indent=2), flush=True)


if __name__ == "__main__":
    main()
