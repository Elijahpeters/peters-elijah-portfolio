"""Target-free schedule and calendar context features for SkyETA.

Fit the maps on January-September only, then reuse them unchanged for later
splits.  These are counts of scheduled service, never outcomes or realized
delays, so they are available before departure.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd


CONTEXT_FEATURE_NAMES = [
    "route_frequency_log1p",
    "carrier_route_frequency_log1p",
    "origin_bank_frequency_log1p",
    "is_major_holiday_window",
]


@dataclass
class ScheduleContextMaps:
    route: dict[str, int]
    carrier_route: dict[str, int]
    origin_bank: dict[str, int]


@dataclass
class ScheduleContextAccumulator:
    """Small streaming accumulator suitable for ``train.py`` chunk scans."""

    route: Counter[str] = field(default_factory=Counter)
    carrier_route: Counter[str] = field(default_factory=Counter)
    origin_bank: Counter[str] = field(default_factory=Counter)

    def update(self, frame: pd.DataFrame) -> None:
        routes = frame["Origin"].astype(str) + "_" + frame["Dest"].astype(str)
        carrier_routes = frame["Reporting_Airline"].astype(str) + "|" + routes
        self.route.update(routes)
        self.carrier_route.update(carrier_routes)
        self.origin_bank.update(_scheduled_bank(frame))

    def finalize(self) -> ScheduleContextMaps:
        return ScheduleContextMaps(
            route=dict(self.route),
            carrier_route=dict(self.carrier_route),
            origin_bank=dict(self.origin_bank),
        )


def _scheduled_bank(frame: pd.DataFrame) -> pd.Series:
    scheduled = pd.to_numeric(frame["CRSDepTime"], errors="coerce").fillna(0).astype(int) % 2400
    minute_of_day = (scheduled // 100) * 60 + scheduled % 100
    half_hour = (minute_of_day // 30).clip(0, 47)
    return (
        frame["Origin"].astype(str)
        + "|"
        + frame["DayOfWeek"].astype(str)
        + "|"
        + half_hour.astype(str)
    )


def fit_schedule_context(training: pd.DataFrame) -> ScheduleContextMaps:
    accumulator = ScheduleContextAccumulator()
    accumulator.update(training)
    return accumulator.finalize()


def _thanksgiving(year: int) -> date:
    first = date(year, 11, 1)
    return first + timedelta(days=(3 - first.weekday()) % 7 + 21)


def _major_holiday_dates(year: int) -> set[date]:
    # Travel-sensitive fixed dates plus Thanksgiving.  The window below is
    # deliberately symmetric and known from the calendar before departure.
    return {
        date(year, 1, 1),
        date(year, 7, 4),
        _thanksgiving(year),
        date(year, 12, 25),
    }


def transform_schedule_context(
    frame: pd.DataFrame, maps: ScheduleContextMaps, default_year: int = 2025
) -> pd.DataFrame:
    route = frame["Origin"].astype(str) + "_" + frame["Dest"].astype(str)
    carrier_route = frame["Reporting_Airline"].astype(str) + "|" + route
    years = frame["Year"] if "Year" in frame else pd.Series(default_year, index=frame.index)
    dates = pd.to_datetime(
        {
            "year": pd.to_numeric(years, errors="coerce"),
            "month": pd.to_numeric(frame["Month"], errors="coerce"),
            "day": pd.to_numeric(frame["DayofMonth"], errors="coerce"),
        },
        errors="coerce",
    )

    holiday = np.zeros(len(frame), dtype="float32")
    for position, timestamp in enumerate(dates):
        if pd.isna(timestamp):
            continue
        day = timestamp.date()
        candidates = _major_holiday_dates(day.year)
        holiday[position] = any(abs((day - item).days) <= 2 for item in candidates)

    return pd.DataFrame(
        {
            "route_frequency_log1p": np.log1p(route.map(maps.route).fillna(0)).astype("float32"),
            "carrier_route_frequency_log1p": np.log1p(
                carrier_route.map(maps.carrier_route).fillna(0)
            ).astype("float32"),
            "origin_bank_frequency_log1p": np.log1p(
                _scheduled_bank(frame).map(maps.origin_bank).fillna(0)
            ).astype("float32"),
            "is_major_holiday_window": holiday,
        },
        index=frame.index,
    )
