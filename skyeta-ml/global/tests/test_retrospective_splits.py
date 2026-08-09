from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ..splits import (
    ChronologicalBoundaries,
    RETROSPECTIVE_EVALUATION_HORIZON,
    chronological_split,
    retrospective_temporal_evaluation_split,
)


def _boundaries() -> ChronologicalBoundaries:
    return ChronologicalBoundaries(
        train_end=datetime(2025, 2, 1, tzinfo=timezone.utc),
        tune_end=datetime(2025, 3, 1, tzinfo=timezone.utc),
        calibration_end=datetime(2025, 4, 1, tzinfo=timezone.utc),
        test_end=datetime(2025, 5, 1, tzinfo=timezone.utc),
    )


def test_retrospective_split_keeps_late_labels_in_prediction_time_windows(
    make_record,
):
    label_first_seen = datetime(2025, 8, 1, tzinfo=timezone.utc)
    departures = (
        datetime(2025, 1, 15, 8, tzinfo=timezone.utc),
        # The remaining prediction timestamps fall exactly on exclusive
        # boundaries and therefore enter the following window.
        datetime(2025, 2, 8, 8, tzinfo=timezone.utc),
        datetime(2025, 3, 8, 8, tzinfo=timezone.utc),
        datetime(2025, 4, 8, 8, tzinfo=timezone.utc),
        datetime(2025, 5, 8, 8, tzinfo=timezone.utc),
    )
    records = tuple(
        make_record(
            record_id=f"retrospective-{index}",
            operating_flight_number=str(100 + index),
            scheduled_departure_utc=departure,
            schedule_observed_at=departure - timedelta(days=8),
            outcome_observed_at=label_first_seen,
        )
        for index, departure in enumerate(departures, start=1)
    )

    split = retrospective_temporal_evaluation_split(records, _boundaries())

    assert [row.record_id for row in split.train] == ["retrospective-1"]
    assert [row.record_id for row in split.tune] == ["retrospective-2"]
    assert [row.record_id for row in split.calibration] == ["retrospective-3"]
    assert [row.record_id for row in split.test] == ["retrospective-4"]
    assert [row.record_id for row in split.excluded_after_test] == [
        "retrospective-5"
    ]

    # The ordinary split remains a point-in-time backtest and therefore purges
    # the same four pre-test-end labels as unavailable at their window cutoffs.
    point_in_time = chronological_split(
        records,
        _boundaries(),
        require_non_empty=False,
    )
    assert not point_in_time.train
    assert not point_in_time.tune
    assert not point_in_time.calibration
    assert not point_in_time.test
    assert len(point_in_time.purged_immature) == 4


def test_retrospective_audit_discloses_counts_and_feature_policy(make_record):
    label_first_seen = datetime(2025, 8, 1, tzinfo=timezone.utc)
    records = tuple(
        make_record(
            operating_flight_number=str(200 + index),
            scheduled_departure_utc=departure,
            outcome_observed_at=label_first_seen,
        )
        for index, departure in enumerate(
            (
                datetime(2025, 1, 15, tzinfo=timezone.utc),
                datetime(2025, 2, 15, tzinfo=timezone.utc),
                datetime(2025, 3, 15, tzinfo=timezone.utc),
                datetime(2025, 4, 15, tzinfo=timezone.utc),
            )
        )
    )

    audit = retrospective_temporal_evaluation_split(
        records, _boundaries()
    ).audit

    assert audit.evaluation_kind == "retrospective_temporal_evaluation"
    assert audit.point_in_time_backtest is False
    assert audit.target_derived_history_features_allowed is False
    assert audit.prediction_horizon_seconds == 7 * 24 * 60 * 60
    assert audit.input_count == 4
    assert audit.window_counts == {
        "train": 1,
        "tune": 1,
        "calibration": 1,
        "test": 1,
        "excluded_after_test": 0,
    }
    assert audit.earliest_label_first_seen_at == label_first_seen
    assert audit.latest_label_first_seen_at == label_first_seen
    serialized = audit.to_dict()
    assert serialized["point_in_time_backtest"] is False
    assert serialized["target_derived_history_features_allowed"] is False
    assert serialized["window_counts"] == audit.window_counts


def test_retrospective_split_requires_schedule_evidence_by_t_minus_seven(
    make_record,
):
    departure = datetime(2025, 1, 15, tzinfo=timezone.utc)
    visible_at_boundary = make_record(
        record_id="visible-at-t-minus-seven",
        operating_flight_number="401",
        scheduled_departure_utc=departure,
        schedule_observed_at=departure - timedelta(days=7),
        outcome_observed_at=datetime(2025, 8, 1, tzinfo=timezone.utc),
    )
    accepted = retrospective_temporal_evaluation_split(
        [visible_at_boundary], _boundaries(), require_non_empty=False
    )
    assert accepted.train == (visible_at_boundary,)

    record = make_record(
        operating_flight_number="402",
        scheduled_departure_utc=departure,
        schedule_observed_at=departure - timedelta(days=7) + timedelta(seconds=1),
        outcome_observed_at=datetime(2025, 8, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError, match="schedule was first observed after"):
        retrospective_temporal_evaluation_split(
            [record], _boundaries(), require_non_empty=False
        )


def test_retrospective_split_requires_terminal_outcomes(make_record):
    record = make_record(
        status="scheduled",
        scheduled_departure_utc=datetime(2025, 1, 15, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError, match="requires terminal outcomes"):
        retrospective_temporal_evaluation_split(
            [record], _boundaries(), require_non_empty=False
        )


def test_retrospective_split_requires_labels_first_seen_after_entire_corpus(
    make_record,
):
    earlier = make_record(
        record_id="earlier-label",
        operating_flight_number="301",
        scheduled_departure_utc=datetime(2025, 1, 15, tzinfo=timezone.utc),
        outcome_observed_at=datetime(2025, 1, 20, tzinfo=timezone.utc),
    )
    later = make_record(
        record_id="later-service",
        operating_flight_number="302",
        scheduled_departure_utc=datetime(2025, 4, 15, tzinfo=timezone.utc),
        outcome_observed_at=datetime(2025, 8, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError, match="after the complete service corpus"):
        retrospective_temporal_evaluation_split(
            [earlier, later], _boundaries(), require_non_empty=False
        )


def test_retrospective_split_is_fixed_to_t_minus_seven(make_record):
    with pytest.raises(ValueError, match="fixed at T-7"):
        retrospective_temporal_evaluation_split(
            [],
            _boundaries(),
            prediction_horizon=timedelta(days=1),
            require_non_empty=False,
        )

    empty = retrospective_temporal_evaluation_split(
        [],
        _boundaries(),
        prediction_horizon=RETROSPECTIVE_EVALUATION_HORIZON,
        require_non_empty=False,
    )
    assert empty.audit.input_count == 0
    assert empty.audit.window_counts == {
        "train": 0,
        "tune": 0,
        "calibration": 0,
        "test": 0,
        "excluded_after_test": 0,
    }
