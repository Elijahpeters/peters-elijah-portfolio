from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from ..splits import (
    ChronologicalBoundaries,
    chronological_split,
    region_holdout_split,
)


def test_four_way_chronological_split_has_exclusive_boundaries(make_record):
    records = [
        make_record(scheduled_departure_utc=datetime(2025, month, 15, tzinfo=timezone.utc))
        for month in range(1, 6)
    ]
    boundaries = ChronologicalBoundaries(
        train_end=datetime(2025, 2, 1, tzinfo=timezone.utc),
        tune_end=datetime(2025, 3, 1, tzinfo=timezone.utc),
        calibration_end=datetime(2025, 4, 1, tzinfo=timezone.utc),
        test_end=datetime(2025, 5, 1, tzinfo=timezone.utc),
    )
    split = chronological_split(records, boundaries)
    assert [row.scheduled_departure_utc.month for row in split.train] == [1]
    assert [row.scheduled_departure_utc.month for row in split.tune] == [2]
    assert [row.scheduled_departure_utc.month for row in split.calibration] == [3]
    assert [row.scheduled_departure_utc.month for row in split.test] == [4]
    assert [row.scheduled_departure_utc.month for row in split.excluded_after_test] == [5]


def test_split_uses_prediction_horizon_and_purges_at_observation_cutoff(make_record):
    departure = datetime(2025, 1, 10, 8, tzinfo=timezone.utc)
    observed_before_cutoff = make_record(
        record_id="horizon-train",
        status="cancelled",
        scheduled_departure_utc=departure,
        outcome_observed_at=datetime(2025, 1, 4, tzinfo=timezone.utc),
    )
    observed_at_cutoff = make_record(
        record_id="horizon-purged",
        status="cancelled",
        operating_flight_number="102",
        scheduled_departure_utc=departure + timedelta(hours=1),
        outcome_observed_at=datetime(2025, 1, 5, tzinfo=timezone.utc),
    )
    boundaries = ChronologicalBoundaries(
        train_end=datetime(2025, 1, 5, tzinfo=timezone.utc),
        tune_end=datetime(2025, 1, 15, tzinfo=timezone.utc),
        calibration_end=datetime(2025, 1, 25, tzinfo=timezone.utc),
        test_end=datetime(2025, 2, 5, tzinfo=timezone.utc),
    )
    split = chronological_split(
        [observed_at_cutoff, observed_before_cutoff],
        boundaries,
        prediction_horizon=timedelta(days=7),
        require_non_empty=False,
    )
    # Both departures occur after train_end, but their prediction timestamps
    # are in the train window. The outcome observed exactly at the exclusive
    # cutoff is unavailable to fitting and is purged.
    assert [row.record_id for row in split.train] == ["horizon-train"]
    assert [row.record_id for row in split.purged_immature] == ["horizon-purged"]

    with pytest.raises(ValueError, match="requires outcome_observed_at"):
        chronological_split(
            [replace(observed_before_cutoff, outcome_observed_at=None)],
            boundaries,
            require_non_empty=False,
        )


def test_region_holdout_removes_geography_from_training(make_record):
    records = [
        make_record(
            scheduled_departure_utc=datetime(2025, 1, 1, tzinfo=timezone.utc),
            origin_region="Africa",
            destination_region="Europe",
        ),
        make_record(
            scheduled_departure_utc=datetime(2025, 1, 2, tzinfo=timezone.utc),
            origin_region="North America",
            destination_region="Europe",
        ),
        make_record(
            scheduled_departure_utc=datetime(2025, 2, 10, tzinfo=timezone.utc),
            origin_region="Africa",
            destination_region="Asia",
        ),
    ]
    split = region_holdout_split(
        records,
        ["Africa"],
        datetime(2025, 2, 1, tzinfo=timezone.utc),
    )
    assert len(split.training) == 1
    assert split.training[0].origin_region == "North America"
    assert len(split.holdout_test) == 1
    assert split.holdout_test[0].origin_region == "Africa"
    assert len(split.excluded) == 1
