"""Schedule-only and geographic features available before departure."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Mapping

from .encodings import EncodedHistoryRow
from .schema import GlobalFlightRecord


EARTH_RADIUS_KM = 6_371.0088
REGION_TOKENS = (
    "africa",
    "asia",
    "europe",
    "middle_east",
    "north_america",
    "oceania",
    "south_america",
    "other",
)


@dataclass(frozen=True, slots=True)
class FeatureRow:
    record_id: str
    values: dict[str, float]


def _region_token(value: str) -> str:
    token = "_".join(value.strip().casefold().replace("-", " ").split())
    return token if token in REGION_TOKENS else "other"


def _cyclic(value: float, period: float) -> tuple[float, float]:
    angle = 2.0 * math.pi * value / period
    return math.sin(angle), math.cos(angle)


def _ecef(latitude: float, longitude: float) -> tuple[float, float, float]:
    latitude_radians = math.radians(latitude)
    longitude_radians = math.radians(longitude)
    cosine_latitude = math.cos(latitude_radians)
    return (
        cosine_latitude * math.cos(longitude_radians),
        cosine_latitude * math.sin(longitude_radians),
        math.sin(latitude_radians),
    )


def great_circle_distance_km(record: GlobalFlightRecord) -> float:
    origin_latitude = math.radians(record.origin_latitude)
    destination_latitude = math.radians(record.destination_latitude)
    latitude_delta = destination_latitude - origin_latitude
    longitude_delta = math.radians(
        record.destination_longitude - record.origin_longitude
    )
    haversine = (
        math.sin(latitude_delta / 2.0) ** 2
        + math.cos(origin_latitude)
        * math.cos(destination_latitude)
        * math.sin(longitude_delta / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(haversine)))


def initial_bearing_radians(record: GlobalFlightRecord) -> float:
    origin_latitude = math.radians(record.origin_latitude)
    destination_latitude = math.radians(record.destination_latitude)
    longitude_delta = math.radians(
        record.destination_longitude - record.origin_longitude
    )
    y = math.sin(longitude_delta) * math.cos(destination_latitude)
    x = math.cos(origin_latitude) * math.sin(destination_latitude) - math.sin(
        origin_latitude
    ) * math.cos(destination_latitude) * math.cos(longitude_delta)
    return math.atan2(y, x)


def schedule_geography_features(record: GlobalFlightRecord) -> dict[str, float]:
    """Build only target-free fields known from a published itinerary."""

    origin_local_departure = record.scheduled_departure_utc + timedelta(
        minutes=record.origin_timezone_offset_minutes
    )
    destination_local_arrival = record.scheduled_arrival_utc + timedelta(
        minutes=record.destination_timezone_offset_minutes
    )
    duration_minutes = (
        record.scheduled_arrival_utc - record.scheduled_departure_utc
    ).total_seconds() / 60.0
    distance_km = great_circle_distance_km(record)
    bearing = initial_bearing_radians(record)
    origin_ecef = _ecef(record.origin_latitude, record.origin_longitude)
    destination_ecef = _ecef(
        record.destination_latitude, record.destination_longitude
    )
    month_sin, month_cos = _cyclic(origin_local_departure.month, 12.0)
    weekday_sin, weekday_cos = _cyclic(origin_local_departure.isoweekday(), 7.0)
    year_days = 366.0 if origin_local_departure.year % 4 == 0 else 365.0
    year_day_sin, year_day_cos = _cyclic(
        origin_local_departure.timetuple().tm_yday, year_days
    )
    origin_hour = origin_local_departure.hour + origin_local_departure.minute / 60.0
    destination_hour = (
        destination_local_arrival.hour + destination_local_arrival.minute / 60.0
    )
    utc_hour = (
        record.scheduled_departure_utc.hour
        + record.scheduled_departure_utc.minute / 60.0
    )
    origin_hour_sin, origin_hour_cos = _cyclic(origin_hour, 24.0)
    destination_hour_sin, destination_hour_cos = _cyclic(
        destination_hour, 24.0
    )
    utc_hour_sin, utc_hour_cos = _cyclic(utc_hour, 24.0)

    values = {
        "month_sin": month_sin,
        "month_cos": month_cos,
        "weekday_sin": weekday_sin,
        "weekday_cos": weekday_cos,
        "year_day_sin": year_day_sin,
        "year_day_cos": year_day_cos,
        "origin_departure_hour_sin": origin_hour_sin,
        "origin_departure_hour_cos": origin_hour_cos,
        "destination_arrival_hour_sin": destination_hour_sin,
        "destination_arrival_hour_cos": destination_hour_cos,
        "utc_departure_hour_sin": utc_hour_sin,
        "utc_departure_hour_cos": utc_hour_cos,
        "is_origin_weekend": float(origin_local_departure.isoweekday() >= 6),
        "scheduled_duration_minutes": duration_minutes,
        "scheduled_duration_log1p": math.log1p(duration_minutes),
        "great_circle_distance_km": distance_km,
        "great_circle_distance_log1p": math.log1p(distance_km),
        "bearing_sin": math.sin(bearing),
        "bearing_cos": math.cos(bearing),
        "timezone_change_hours": (
            record.destination_timezone_offset_minutes
            - record.origin_timezone_offset_minutes
        )
        / 60.0,
        "same_country": float(record.origin_country == record.destination_country),
        "same_region": float(
            record.origin_region.casefold() == record.destination_region.casefold()
        ),
        "is_international": float(
            record.origin_country != record.destination_country
        ),
        "origin_ecef_x": origin_ecef[0],
        "origin_ecef_y": origin_ecef[1],
        "origin_ecef_z": origin_ecef[2],
        "destination_ecef_x": destination_ecef[0],
        "destination_ecef_y": destination_ecef[1],
        "destination_ecef_z": destination_ecef[2],
        "aircraft_family_missing": float(record.aircraft_family is None),
    }
    origin_region = _region_token(record.origin_region)
    destination_region = _region_token(record.destination_region)
    for region in REGION_TOKENS:
        values[f"origin_region_{region}"] = float(origin_region == region)
        values[f"destination_region_{region}"] = float(
            destination_region == region
        )
    return values


def assemble_feature_row(
    record: GlobalFlightRecord,
    history: EncodedHistoryRow | Mapping[str, float] | None = None,
) -> FeatureRow:
    values = schedule_geography_features(record)
    if isinstance(history, EncodedHistoryRow):
        if history.record_id != record.record_id:
            raise ValueError("history row does not match the flight record")
        history_values = history.features
    else:
        history_values = history or {}
    for name, value in history_values.items():
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"feature {name} is not finite")
        if name in values:
            raise ValueError(f"history feature collides with base feature: {name}")
        values[name] = numeric
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("feature row contains a non-finite value")
    return FeatureRow(record.record_id, values)
