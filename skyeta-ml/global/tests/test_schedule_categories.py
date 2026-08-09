from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np

from ..pipeline import prepare_retrospective_global_data
from ..schedule_categories import (
    ScheduleCategoricalFeatureConfig,
    TrainingOnlyScheduleCategoricalTransformer,
)
from ..splits import ChronologicalBoundaries


def _boundaries() -> ChronologicalBoundaries:
    return ChronologicalBoundaries(
        train_end=datetime(2025, 2, 1, tzinfo=timezone.utc),
        tune_end=datetime(2025, 3, 1, tzinfo=timezone.utc),
        calibration_end=datetime(2025, 4, 1, tzinfo=timezone.utc),
        test_end=datetime(2025, 5, 1, tzinfo=timezone.utc),
    )


def _records(make_record):
    label_first_seen = datetime(2025, 8, 1, tzinfo=timezone.utc)
    departures = (
        datetime(2025, 1, 15, 8, tzinfo=timezone.utc),
        datetime(2025, 1, 16, 8, tzinfo=timezone.utc),
        datetime(2025, 2, 15, 8, tzinfo=timezone.utc),
        datetime(2025, 2, 16, 8, tzinfo=timezone.utc),
        datetime(2025, 3, 15, 8, tzinfo=timezone.utc),
        datetime(2025, 3, 16, 8, tzinfo=timezone.utc),
        datetime(2025, 4, 15, 8, tzinfo=timezone.utc),
        datetime(2025, 4, 16, 8, tzinfo=timezone.utc),
    )
    return tuple(
        make_record(
            record_id=f"schedule-categorical-{index}",
            operating_flight_number=str(800 + index),
            scheduled_departure_utc=departure,
            schedule_observed_at=departure - timedelta(days=8),
            outcome_observed_at=label_first_seen,
        )
        for index, departure in enumerate(departures, start=1)
    )


def _held_out_only_categories(records, suffix: str):
    changed = list(records)
    for index in range(2, len(changed)):
        changed[index] = replace(
            changed[index],
            operating_carrier=f"Z{suffix}",
            origin=f"A{suffix}A",
            destination=f"B{suffix}B",
            aircraft_family=f"Evaluation only {suffix}",
        )
    return tuple(changed)


def test_evaluation_only_categories_cannot_change_fitted_vocabulary(make_record):
    records = _records(make_record)
    first = prepare_retrospective_global_data(
        _held_out_only_categories(records, "X"), _boundaries()
    )
    second = prepare_retrospective_global_data(
        _held_out_only_categories(records, "Y"), _boundaries()
    )

    assert first.schedule_categorical_snapshot == second.schedule_categorical_snapshot
    assert first.train.feature_names == second.train.feature_names
    np.testing.assert_array_equal(first.train.matrix, second.train.matrix)

    test = first.test
    unknown_columns = [
        index
        for index, name in enumerate(test.feature_names)
        if name.startswith("schedule_category_") and name.endswith("__unknown")
    ]
    assert len(unknown_columns) == 5
    np.testing.assert_array_equal(
        test.matrix[:, unknown_columns],
        np.ones((len(test.records), 5), dtype="float32"),
    )


def test_transformer_digest_and_tie_order_are_input_order_independent(make_record):
    first = make_record(
        operating_carrier="ZZ",
        origin="ABV",
        destination="ACC",
        aircraft_family="A320",
    )
    second = make_record(
        operating_carrier="AA",
        origin="LOS",
        destination="LHR",
        aircraft_family="B787",
    )
    transformer = TrainingOnlyScheduleCategoricalTransformer(
        ScheduleCategoricalFeatureConfig(max_routes=1)
    )

    forward = transformer.fit((first, second))
    reverse = transformer.fit((second, first))

    assert forward == reverse
    assert len(forward.digest) == 64
    carrier_vocabulary = next(
        vocabulary
        for vocabulary in forward.vocabularies
        if vocabulary.field == "operating_carrier"
    )
    assert carrier_vocabulary.categories == ("AA", "ZZ")
    route_vocabulary = next(
        vocabulary for vocabulary in forward.vocabularies if vocabulary.field == "route"
    )
    assert route_vocabulary.categories == ("ABV>ACC",)


def test_transformer_never_uses_outcomes_or_creates_history_features(make_record):
    record = make_record()
    changed_outcome = replace(
        record,
        status="cancelled",
        actual_departure_utc=None,
        actual_arrival_utc=None,
        outcome_observed_at=record.scheduled_departure_utc - timedelta(hours=1),
    )
    transformer = TrainingOnlyScheduleCategoricalTransformer()

    original = transformer.fit((record,))
    changed = transformer.fit((changed_outcome,))

    assert original == changed
    assert all(not name.startswith("history_") for name in original.feature_names)
    matrix = transformer.transform((record, changed_outcome), original)
    assert matrix.shape == (2, len(original.feature_names))
    np.testing.assert_array_equal(matrix[0], matrix[1])
