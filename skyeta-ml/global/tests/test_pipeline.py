from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from ..encodings import PastOnlyHierarchicalEncoder
from ..pipeline import prepare_global_data
from ..splits import ChronologicalBoundaries


def test_preparation_freezes_later_windows_to_training_history(make_record):
    start = datetime(2025, 1, 1, 8, tzinfo=timezone.utc)
    records = []
    for index, day in enumerate((7, 8, 19, 20, 39, 40, 59, 60)):
        departure = start + timedelta(days=day)
        records.append(
            make_record(
                record_id=f"pipeline-{index}",
                service_date=(departure + timedelta(hours=1)).date(),
                scheduled_departure_utc=departure,
                scheduled_arrival_utc=departure + timedelta(hours=2),
                actual_arrival_utc=departure + timedelta(hours=2, minutes=20),
            )
        )
    boundaries = ChronologicalBoundaries(
        train_end=start + timedelta(days=10),
        tune_end=start + timedelta(days=30),
        calibration_end=start + timedelta(days=50),
        test_end=start + timedelta(days=70),
    )
    prepared = prepare_global_data(records, boundaries)
    assert prepared.train.matrix.shape[0] == 2
    assert prepared.tune.matrix.shape[0] == 2
    assert prepared.calibration.matrix.shape[0] == 2
    assert prepared.test.matrix.shape[0] == 2
    assert prepared.train.feature_names == prepared.test.feature_names

    feature = "history_route_arrival_15_log_count"
    index = prepared.train.feature_names.index(feature)
    # The training snapshot contains the two resolved training outcomes. Tune,
    # calibration and test all reuse it; later outcomes never update the map.
    expected = prepared.tune.matrix[0, index]
    assert expected > 0
    assert all(value == expected for value in prepared.calibration.matrix[:, index])
    assert all(value == expected for value in prepared.test.matrix[:, index])


def test_preparation_purges_labels_not_observed_before_partition_cutoff(make_record):
    start = datetime(2025, 1, 1, 8, tzinfo=timezone.utc)
    departure_days = (7, 8, 16, 19, 39, 59)
    records = []
    for index, day in enumerate(departure_days):
        departure = start + timedelta(days=day)
        records.append(
            make_record(
                record_id=f"maturity-{index}",
                service_date=(departure + timedelta(hours=1)).date(),
                scheduled_departure_utc=departure,
                scheduled_arrival_utc=departure + timedelta(hours=2),
                actual_arrival_utc=departure + timedelta(hours=2, minutes=20),
            )
        )
    prepared = prepare_global_data(
        records,
        ChronologicalBoundaries(
            train_end=start + timedelta(days=10),
            tune_end=start + timedelta(days=30),
            calibration_end=start + timedelta(days=50),
            test_end=start + timedelta(days=70),
        ),
    )
    assert [row.record_id for row in prepared.split.purged_immature] == [
        "maturity-2"
    ]
    assert "maturity-2" not in {
        row.record_id
        for partition in (
            prepared.split.train,
            prepared.split.tune,
            prepared.split.calibration,
            prepared.split.test,
        )
        for row in partition
    }


def test_preparation_uses_encoder_horizon_for_revision_selection(make_record):
    start = datetime(2025, 1, 1, 8, tzinfo=timezone.utc)
    records = []
    for index, day in enumerate((3, 4, 13, 14, 33, 34, 53, 54)):
        departure = start + timedelta(days=day)
        records.append(
            make_record(
                record_id=f"custom-horizon-{index}",
                service_date=(departure + timedelta(hours=1)).date(),
                scheduled_departure_utc=departure,
                scheduled_arrival_utc=departure + timedelta(hours=2),
                actual_arrival_utc=departure + timedelta(hours=2, minutes=20),
                schedule_revision="synthetic-v1",
            )
        )

    initial = records[0]
    three_day_revision = replace(
        initial,
        record_id="custom-horizon-revision",
        scheduled_departure_utc=initial.scheduled_departure_utc
        + timedelta(minutes=30),
        scheduled_arrival_utc=initial.scheduled_arrival_utc
        + timedelta(minutes=30),
        schedule_revision="synthetic-v2",
        schedule_observed_at=initial.scheduled_departure_utc - timedelta(days=5),
    )
    records.append(three_day_revision)

    prepared = prepare_global_data(
        records,
        ChronologicalBoundaries(
            train_end=start + timedelta(days=10),
            tune_end=start + timedelta(days=30),
            calibration_end=start + timedelta(days=50),
            test_end=start + timedelta(days=70),
        ),
        encoder=PastOnlyHierarchicalEncoder(
            prediction_horizon=timedelta(days=3)
        ),
    )

    selected_ids = {
        row.record_id
        for partition in (
            prepared.split.train,
            prepared.split.tune,
            prepared.split.calibration,
            prepared.split.test,
        )
        for row in partition
    }
    assert "custom-horizon-revision" in selected_ids
    assert initial.record_id not in selected_ids
