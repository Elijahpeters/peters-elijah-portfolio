from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from ..encodings import PastOnlyHierarchicalEncoder


def test_history_waits_until_outcome_is_available(make_record):
    first_departure = datetime(2025, 1, 1, 8, tzinfo=timezone.utc)
    first = make_record(
        scheduled_departure_utc=first_departure,
        scheduled_arrival_utc=first_departure + timedelta(hours=2),
        actual_arrival_utc=first_departure + timedelta(hours=4),
    )
    second_departure = first_departure + timedelta(hours=2)
    second = make_record(
        scheduled_departure_utc=second_departure,
        scheduled_arrival_utc=second_departure + timedelta(hours=2),
        actual_arrival_utc=second_departure + timedelta(hours=4),
    )
    third_departure = first_departure + timedelta(hours=5)
    third = make_record(
        scheduled_departure_utc=third_departure,
        scheduled_arrival_utc=third_departure + timedelta(hours=2),
        actual_arrival_utc=third_departure + timedelta(hours=3),
    )

    encoded, _ = PastOnlyHierarchicalEncoder(
        prediction_horizon=timedelta(0)
    ).fit_transform([third, second, first])
    by_id = {row.record_id: row.features for row in encoded}
    count_name = "history_route_arrival_15_log_count"
    assert by_id[first.record_id][count_name] == 0
    # The first flight has not arrived when the second is scored.
    assert by_id[second.record_id][count_name] == 0
    # Only the first outcome is available before the third departure.
    assert by_id[third.record_id][count_name] == math.log1p(1)


def test_simultaneous_rows_cannot_observe_each_other(make_record):
    departure = datetime(2025, 1, 1, 8, tzinfo=timezone.utc)
    left = make_record(scheduled_departure_utc=departure)
    right = make_record(
        scheduled_departure_utc=departure,
        operating_flight_number="102",
    )
    encoded, _ = PastOnlyHierarchicalEncoder(
        prediction_horizon=timedelta(0)
    ).fit_transform([left, right])
    assert all(
        row.features["history_route_arrival_15_log_count"] == 0
        for row in encoded
    )
    assert all(
        row.features["history_route_schedule_log_count"] == 0
        for row in encoded
    )


def test_schedule_counts_include_cancelled_rows_but_arrival_counts_do_not(make_record):
    first_departure = datetime(2025, 1, 1, 8, tzinfo=timezone.utc)
    cancelled = make_record(
        status="cancelled",
        scheduled_departure_utc=first_departure,
        outcome_observed_at=first_departure + timedelta(hours=1),
    )
    later = make_record(
        scheduled_departure_utc=first_departure + timedelta(days=1),
    )
    encoded, snapshot = PastOnlyHierarchicalEncoder(
        prediction_horizon=timedelta(0)
    ).fit_transform(
        [cancelled, later]
    )
    later_features = {row.record_id: row.features for row in encoded}[later.record_id]
    assert later_features["history_route_schedule_log_count"] == math.log1p(1)
    assert later_features["history_route_arrival_15_log_count"] == 0
    assert later_features["history_route_cancelled_log_count"] == math.log1p(1)
    assert snapshot.support("route", cancelled.route_key, "arrival_15") == 1
    # Only the landed `later` row contributes to the final arrival population.
    assert snapshot.support("route", cancelled.route_key, "cancelled") == 2


def test_frozen_transform_does_not_learn_validation_outcomes(make_record):
    training = make_record()
    encoder = PastOnlyHierarchicalEncoder()
    _, snapshot = encoder.fit_transform([training])
    before = snapshot.to_serializable()
    future = make_record(
        operating_flight_number="999",
        scheduled_departure_utc=training.actual_arrival_utc + timedelta(days=8),
    )
    first = encoder.transform([future], snapshot)
    second = encoder.transform([future], snapshot)
    assert first == second
    assert snapshot.to_serializable() == before


def test_fixed_horizon_requires_point_in_time_schedule_evidence(make_record):
    record = make_record()
    encoder = PastOnlyHierarchicalEncoder()
    with pytest.raises(ValueError, match="requires schedule_observed_at"):
        encoder.fit_transform([replace(record, schedule_observed_at=None)])

    prediction_at = record.scheduled_departure_utc - timedelta(days=7)
    with pytest.raises(ValueError, match="first observed after"):
        encoder.fit_transform(
            [replace(record, schedule_observed_at=prediction_at + timedelta(seconds=1))]
        )


def test_every_terminal_history_requires_observation_time(make_record):
    for status in ("landed", "cancelled", "diverted"):
        record = replace(
            make_record(status=status),
            outcome_observed_at=None,
        )
        with pytest.raises(ValueError, match="requires outcome_observed_at"):
            PastOnlyHierarchicalEncoder().fit_transform([record])


def test_implicit_final_snapshot_is_stamped_with_its_latest_information(make_record):
    training = make_record()
    encoder = PastOnlyHierarchicalEncoder()
    _, snapshot = encoder.fit_transform([training])
    assert snapshot.as_of is not None
    assert snapshot.as_of > training.outcome_observed_at

    too_early = make_record(
        operating_flight_number="999",
        scheduled_departure_utc=training.scheduled_departure_utc + timedelta(days=1),
    )
    with pytest.raises(ValueError, match="snapshot is newer"):
        encoder.transform([too_early], snapshot)


def test_cohort_rejects_an_outcome_known_by_prediction_time(make_record):
    record = make_record(status="cancelled")
    prediction_at = record.scheduled_departure_utc - timedelta(days=7)
    with pytest.raises(ValueError, match="already observed"):
        PastOnlyHierarchicalEncoder().fit_transform(
            [replace(record, outcome_observed_at=prediction_at)]
        )


def test_frozen_snapshot_cannot_be_newer_than_prediction(make_record):
    encoder = PastOnlyHierarchicalEncoder()
    departure = datetime(2025, 1, 20, 8, tzinfo=timezone.utc)
    training = make_record(scheduled_departure_utc=departure)
    _, snapshot = encoder.fit_transform(
        [training], snapshot_as_of=datetime(2025, 1, 15, tzinfo=timezone.utc)
    )
    too_early = make_record(
        operating_flight_number="999",
        scheduled_departure_utc=datetime(2025, 1, 21, 8, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="snapshot is newer"):
        encoder.transform([too_early], snapshot)
