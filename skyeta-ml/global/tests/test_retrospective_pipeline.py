from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from scipy import sparse

from .. import pipeline
from ..features import schedule_geography_features
from ..pipeline import (
    RetrospectiveMatrixMemoryLimits,
    prepare_retrospective_global_data,
)
from ..schedule_categories import ScheduleCategoricalFeatureConfig
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
            record_id=f"retrospective-pipeline-{index}",
            operating_flight_number=str(500 + index),
            scheduled_departure_utc=departure,
            schedule_observed_at=departure - timedelta(days=8),
            outcome_observed_at=label_first_seen,
        )
        for index, departure in enumerate(departures, start=1)
    )


def test_retrospective_preparation_is_target_free_and_aligned(make_record):
    records = _records(make_record)
    prepared = prepare_retrospective_global_data(records, _boundaries())

    assert prepared.publishable is False
    assert prepared.target_derived_history_features_allowed is False
    assert not hasattr(prepared, "history_snapshot")
    assert prepared.retrospective_audit is prepared.split.audit
    assert prepared.retrospective_audit.point_in_time_backtest is False

    partitions = (
        prepared.train,
        prepared.tune,
        prepared.calibration,
        prepared.test,
    )
    expected_names = (
        tuple(sorted(schedule_geography_features(records[0])))
        + prepared.schedule_categorical_snapshot.feature_names
    )
    for partition in partitions:
        assert partition.matrix.shape == (2, len(expected_names))
        assert sparse.isspmatrix_csr(partition.matrix)
        assert partition.feature_names == expected_names
        assert not any(name.startswith("history_") for name in partition.feature_names)
        assert partition.matrix.dtype == np.float32
        assert len(partition.records) == len(partition.targets["arrival_15"])
        assert len(partition.records) == len(
            partition.target_available["arrival_15"]
        )
        selected_matrix, selected_targets = partition.rows_for_target(
            "cancelled"
        )
        assert selected_matrix is partition.matrix
        assert selected_targets is partition.targets["cancelled"]

    assert prepared.schedule_categorical_snapshot.config.enabled is True
    assert len(prepared.schedule_categorical_snapshot.digest) == 64
    matrix_audit = prepared.matrix_audit.to_dict()
    assert matrix_audit["storage_format"] == "scipy_csr"
    assert matrix_audit["dtype"] == "float32"
    assert matrix_audit["total_nnz"] == sum(
        partition.matrix.nnz for partition in partitions
    )
    assert matrix_audit["total_estimated_csr_bytes"] > 0
    assert (
        matrix_audit["limits"]["max_evaluation_additional_bytes"]
        == 1024 * 1024 * 1024
    )
    assert matrix_audit["total_dense_equivalent_bytes"] == sum(
        partition.matrix.shape[0] * partition.matrix.shape[1] * 4
        for partition in partitions
    )
    for name, partition in zip(
        ("train", "tune", "calibration", "test"),
        partitions,
        strict=True,
    ):
        audit = matrix_audit["partitions"][name]
        assert audit["rows"] == partition.matrix.shape[0]
        assert audit["columns"] == partition.matrix.shape[1]
        assert audit["nnz"] == partition.matrix.nnz
        assert audit["estimated_csr_bytes"] == (
            partition.matrix.data.nbytes
            + partition.matrix.indices.nbytes
            + partition.matrix.indptr.nbytes
        )

    assert prepared.retrospective_audit.window_counts == {
        "train": 2,
        "tune": 2,
        "calibration": 2,
        "test": 2,
        "excluded_after_test": 0,
    }


def test_retrospective_preparation_passes_only_empty_history_mappings(
    make_record,
    monkeypatch,
):
    records = _records(make_record)
    observed_history = []
    real_assemble = pipeline.assemble_feature_row

    def audited_assemble(record, history=None):
        observed_history.append(history)
        assert history == {}
        return real_assemble(record, history)

    monkeypatch.setattr(pipeline, "assemble_feature_row", audited_assemble)
    prepare_retrospective_global_data(records, _boundaries())

    assert len(observed_history) == len(records)
    assert all(value == {} for value in observed_history)


def test_retrospective_preparation_dedupes_at_fixed_t_minus_seven(make_record):
    records = list(_records(make_record))
    selected = records[0]
    post_horizon_revision = replace(
        selected,
        record_id="post-horizon-revision",
        scheduled_departure_utc=selected.scheduled_departure_utc
        + timedelta(minutes=30),
        scheduled_arrival_utc=selected.scheduled_arrival_utc
        + timedelta(minutes=30),
        schedule_observed_at=selected.scheduled_departure_utc
        - timedelta(days=7)
        + timedelta(minutes=31),
        schedule_revision="synthetic-v2",
    )
    records.append(post_horizon_revision)

    prepared = prepare_retrospective_global_data(records, _boundaries())

    assert prepared.dedupe.input_rows == 9
    assert prepared.dedupe.duplicate_rows == 1
    selected_ids = {
        record.record_id
        for partition in (
            prepared.train,
            prepared.tune,
            prepared.calibration,
            prepared.test,
        )
        for record in partition.records
    }
    assert selected.record_id in selected_ids
    assert post_horizon_revision.record_id not in selected_ids


def test_retrospective_preparation_has_no_encoder_entry_point(make_record):
    with pytest.raises(TypeError, match="unexpected keyword argument 'encoder'"):
        prepare_retrospective_global_data(
            _records(make_record),
            _boundaries(),
            encoder=object(),
        )


def test_retrospective_schedule_categories_can_be_explicitly_disabled(make_record):
    records = _records(make_record)
    prepared = prepare_retrospective_global_data(
        records,
        _boundaries(),
        schedule_categorical_config=ScheduleCategoricalFeatureConfig(enabled=False),
    )

    expected_names = tuple(sorted(schedule_geography_features(records[0])))
    assert prepared.schedule_categorical_snapshot.feature_names == ()
    assert prepared.train.feature_names == expected_names
    assert prepared.test.matrix.shape == (2, len(expected_names))


def test_retrospective_matrix_guard_fails_before_partition_allocation(
    make_record,
    monkeypatch,
):
    def unexpected_allocation(*args, **kwargs):
        raise AssertionError("partition allocation started before memory guard")

    monkeypatch.setattr(
        pipeline,
        "_base_feature_partition",
        unexpected_allocation,
    )
    with pytest.raises(MemoryError, match="before allocation"):
        prepare_retrospective_global_data(
            _records(make_record),
            _boundaries(),
            matrix_memory_limits=RetrospectiveMatrixMemoryLimits(
                max_partition_peak_bytes=1,
                max_total_csr_bytes=1,
            ),
        )

    with pytest.raises(MemoryError, match="retained CSR matrices"):
        prepare_retrospective_global_data(
            _records(make_record),
            _boundaries(),
            matrix_memory_limits=RetrospectiveMatrixMemoryLimits(
                max_partition_peak_bytes=1024 * 1024,
                max_total_csr_bytes=1,
            ),
        )
