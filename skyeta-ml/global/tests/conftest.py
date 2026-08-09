from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from ..schema import GlobalFlightRecord


@pytest.fixture
def make_record():
    sequence = 0

    def factory(**overrides) -> GlobalFlightRecord:
        nonlocal sequence
        sequence += 1
        departure = overrides.pop(
            "scheduled_departure_utc",
            datetime(2025, 1, 1, 8, tzinfo=timezone.utc) + timedelta(days=sequence),
        )
        arrival = overrides.pop("scheduled_arrival_utc", departure + timedelta(hours=2))
        status = overrides.pop("status", "landed")
        actual_arrival = overrides.pop(
            "actual_arrival_utc",
            arrival + timedelta(minutes=20) if status == "landed" else None,
        )
        actual_departure = overrides.pop(
            "actual_departure_utc",
            departure + timedelta(minutes=10) if status in {"landed", "diverted"} else None,
        )
        schedule_observed_at = overrides.pop(
            "schedule_observed_at", departure - timedelta(days=30)
        )
        schedule_revision = overrides.pop("schedule_revision", "synthetic-v1")
        if status == "landed":
            default_outcome_observed_at = actual_arrival
        elif status == "cancelled":
            default_outcome_observed_at = departure - timedelta(hours=1)
        elif status == "diverted":
            default_outcome_observed_at = departure + timedelta(hours=1)
        else:
            default_outcome_observed_at = None
        outcome_observed_at = overrides.pop(
            "outcome_observed_at", default_outcome_observed_at
        )
        origin_offset = overrides.pop("origin_timezone_offset_minutes", 60)
        local_departure = departure + timedelta(minutes=origin_offset)
        row = {
            "record_id": f"row-{sequence}",
            "service_date": local_departure.date(),
            "operating_carrier": "SK",
            "operating_flight_number": "101",
            "marketing_carrier": "XY",
            "marketing_flight_number": "9001",
            "origin": "LOS",
            "destination": "LHR",
            "scheduled_departure_utc": departure,
            "scheduled_arrival_utc": arrival,
            "schedule_observed_at": schedule_observed_at,
            "schedule_revision": schedule_revision,
            "actual_departure_utc": actual_departure,
            "actual_arrival_utc": actual_arrival,
            "outcome_observed_at": outcome_observed_at,
            "status": status,
            "origin_latitude": 6.5774,
            "origin_longitude": 3.3212,
            "destination_latitude": 51.47,
            "destination_longitude": -0.4543,
            "origin_country": "NG",
            "destination_country": "GB",
            "origin_region": "Africa",
            "destination_region": "Europe",
            "origin_timezone_offset_minutes": origin_offset,
            "destination_timezone_offset_minutes": 0,
            "aircraft_family": "Boeing 787",
            "source": "synthetic-test-fixture",
        }
        row.update(overrides)
        return GlobalFlightRecord.from_mapping(row)

    return factory
