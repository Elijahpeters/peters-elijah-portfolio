from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from ..coverage import assess_coverage
from ..encodings import PastOnlyHierarchicalEncoder
from ..features import assemble_feature_row, great_circle_distance_km


def test_schedule_geography_features_are_finite_and_global(make_record):
    record = make_record()
    row = assemble_feature_row(record)
    assert 4_500 < great_circle_distance_km(record) < 5_500
    assert row.values["is_international"] == 1
    assert row.values["origin_region_africa"] == 1
    assert row.values["destination_region_europe"] == 1
    assert all(math.isfinite(value) for value in row.values.values())


def test_cold_start_uses_hierarchical_support_tiers(make_record):
    start = datetime(2024, 1, 1, 8, tzinfo=timezone.utc)
    history = [
        make_record(
            record_id=f"history-{index}",
            service_date=(start + timedelta(days=index)).date(),
            scheduled_departure_utc=start + timedelta(days=index),
            scheduled_arrival_utc=start + timedelta(days=index, hours=2),
            actual_arrival_utc=start + timedelta(days=index, hours=2, minutes=20),
            operating_flight_number="101" if index < 50 else "202",
        )
        for index in range(55)
    ]
    encoder = PastOnlyHierarchicalEncoder()
    _, snapshot = encoder.fit_transform(history)

    established = make_record(
        scheduled_departure_utc=start + timedelta(days=100),
        operating_flight_number="101",
    )
    partial = make_record(
        scheduled_departure_utc=start + timedelta(days=101),
        operating_flight_number="555",
    )
    cold = make_record(
        scheduled_departure_utc=start + timedelta(days=102),
        operating_carrier="ZZ",
        operating_flight_number="9",
        origin="NBO",
        destination="DXB",
        origin_country="KE",
        destination_country="AE",
        origin_region="Africa",
        destination_region="Middle East",
        origin_latitude=-1.3192,
        origin_longitude=36.9278,
        destination_latitude=25.2532,
        destination_longitude=55.3657,
        origin_timezone_offset_minutes=180,
        destination_timezone_offset_minutes=240,
    )
    established_assessment = assess_coverage(established, snapshot)
    assert established_assessment.tier == "established"
    assert established_assessment.strongest_level == "flight_route"
    assert established_assessment.strongest_arrival_sample == 50
    assert assess_coverage(partial, snapshot).tier == "partial"
    cold_assessment = assess_coverage(cold, snapshot)
    assert cold_assessment.tier == "cold_start"
    assert cold_assessment.strongest_arrival_sample == 0
    assert "flight_route" in cold_assessment.fallbacks


def test_coverage_cannot_use_a_snapshot_newer_than_prediction(make_record):
    historical = make_record()
    _, snapshot = PastOnlyHierarchicalEncoder().fit_transform([historical])
    too_early = make_record(
        operating_flight_number="999",
        scheduled_departure_utc=historical.scheduled_departure_utc + timedelta(days=1),
    )
    with pytest.raises(ValueError, match="snapshot is newer"):
        assess_coverage(too_early, snapshot)
