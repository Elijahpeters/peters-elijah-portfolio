from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from .. import train
from ..export import MODEL_HEADS
from ..pipeline import (
    RetrospectiveMatrixMemoryLimits,
    prepare_retrospective_global_data,
)
from ..splits import ChronologicalBoundaries
from ..train import (
    TrainingConfig,
    _lightgbm_parameters,
    _project_probability_matrix_in_place,
    evaluate_retrospective_temporal_model,
)


def _prepared_retrospective_data(make_record, *, matrix_memory_limits=None):
    boundaries = ChronologicalBoundaries(
        train_end=datetime(2025, 1, 20, tzinfo=timezone.utc),
        tune_end=datetime(2025, 2, 20, tzinfo=timezone.utc),
        calibration_end=datetime(2025, 3, 20, tzinfo=timezone.utc),
        test_end=datetime(2025, 4, 20, tzinfo=timezone.utc),
    )
    patterns = (
        ("landed", 0, 0),
        ("landed", 20, 4),
        ("landed", 40, 8),
        ("landed", 75, 12),
        ("cancelled", None, 16),
        ("diverted", None, 20),
    )
    label_first_seen = datetime(2025, 7, 1, tzinfo=timezone.utc)
    records = []
    for month in range(1, 5):
        for index in range(12):
            status, delay, hour = patterns[index % len(patterns)]
            prediction_at = datetime(
                2025,
                month,
                2 + index,
                hour,
                tzinfo=timezone.utc,
            )
            departure = prediction_at + timedelta(days=7)
            arrival = departure + timedelta(hours=2)
            records.append(
                make_record(
                    record_id=f"retrospective-fit-{month}-{index}",
                    operating_flight_number=f"{month}{index:02d}",
                    scheduled_departure_utc=departure,
                    scheduled_arrival_utc=arrival,
                    schedule_observed_at=prediction_at - timedelta(hours=1),
                    status=status,
                    actual_arrival_utc=(
                        arrival + timedelta(minutes=delay)
                        if delay is not None
                        else None
                    ),
                    outcome_observed_at=label_first_seen,
                    aircraft_family=(None if month == 4 else "Boeing 787"),
                )
            )
    return prepare_retrospective_global_data(
        records,
        boundaries,
        matrix_memory_limits=matrix_memory_limits,
    )


def test_retrospective_fit_returns_diagnostics_not_a_deployable_artifact(
    make_record,
):
    prepared = _prepared_retrospective_data(make_record)

    config = TrainingConfig(
        n_estimators=24,
        learning_rate=0.1,
        num_leaves=7,
        min_child_samples=2,
        early_stopping_rounds=4,
    )
    result = evaluate_retrospective_temporal_model(prepared, config=config)
    repeated = evaluate_retrospective_temporal_model(prepared, config=config)

    assert repeated == result

    assert result["evaluation_kind"] == "retrospective_temporal_evaluation"
    assert result["point_in_time_backtest"] is False
    assert result["publishable"] is False
    assert result["target_derived_history_features_used"] is False
    assert result["feature_contract"]["precomputed_matrices_only"] is True
    assert result["feature_contract"]["target_derived_history_features"] is False
    assert result["feature_contract"]["matrix_storage"]["storage_format"] == (
        "scipy_csr"
    )
    assert result["training_configuration"]["num_threads"] == 1
    provenance = result["runtime_provenance"]
    assert provenance["deterministic"] is True
    assert all(
        provenance[name]
        for name in ("python", "numpy", "scipy", "scikit_learn", "lightgbm")
    )
    assert provenance["deterministic_parameters"] == {
        "random_state": 42,
        "bagging_seed": 42,
        "feature_fraction_seed": 42,
        "data_random_seed": 42,
        "deterministic": True,
        "force_col_wise": True,
        "device_type": "cpu",
        "n_jobs": 1,
    }
    assert all(
        not name.startswith("history_")
        for name in result["feature_contract"]["feature_names"]
    )
    assert result["temporal_audit"]["window_counts"] == {
        "train": 12,
        "tune": 12,
        "calibration": 12,
        "test": 12,
        "excluded_after_test": 0,
    }
    assert set(result["test_metrics"]) == set(MODEL_HEADS)
    assert set(result["model_diagnostics"]) == set(MODEL_HEADS)
    cold_start = result["cold_start_diagnostics"]
    assert cold_start["membershipBasis"] == "training_schedule_identity_only"
    assert cold_start["targetDerivedHistoryUsed"] is False
    assert set(cold_start["fields"]) == {
        "operatingCarrier",
        "origin",
        "destination",
        "route",
        "aircraftFamily",
    }
    aircraft = cold_start["fields"]["aircraftFamily"]
    assert aircraft["unseenDistinctValues"] == ["__MISSING__"]
    assert aircraft["unseen"]["populationRows"] == 12
    assert cold_start["combined"]["fullySeen"]["populationRows"] == 0
    assert cold_start["combined"]["anyUnseen"]["populationRows"] == 12

    memory = result["evaluation_memory_audit"]
    assert memory["guard_applied_before_model_fit"] is True
    assert memory["head_order"] == list(MODEL_HEADS)
    assert memory["test_rows"] == 12
    assert memory["head_count"] == len(MODEL_HEADS)
    assert memory["probability_storage"] == "numpy_float64_matrix"
    assert memory["probability_matrix_bytes"] == 12 * len(MODEL_HEADS) * 8
    model_reserve = sum(memory["lightgbm_reserves"].values())
    assert memory["stage_estimated_additional_bytes"]["model_fit"] == (
        model_reserve
        + memory["maximum_fit_subset_peak_bytes"]
        + memory["cross_iteration_calibration_overlap_reserve_bytes"]
    )
    assert memory["stage_estimated_additional_bytes"][
        "test_probability_generation"
    ] == (
        model_reserve
        + memory["probability_matrix_bytes"]
        + memory["raw_score_overlap_reserve_bytes"]
        + memory["projection_workspace_bytes"]
    )
    assert memory["raw_score_overlap_reserve_bytes"] == (
        2 * memory["maximum_raw_score_vector_bytes"]
    )
    assert memory["estimated_peak_additional_bytes"] <= memory["limit_bytes"]
    assert set(memory["stage_estimated_additional_bytes"]) == {
        "model_fit",
        "calibration",
        "test_probability_generation",
        "test_metrics",
        "cold_start_diagnostics",
    }
    for partition in ("train", "tune", "calibration", "test"):
        all_labelled = memory["target_selections"][partition]["cancelled"]
        assert all_labelled["csr_copy_required"] is False
        assert all_labelled["csr_copy_bytes"] == 0
        arrival = memory["target_selections"][partition]["arrival_15"]
        assert arrival["csr_copy_required"] is True
        assert arrival["csr_copy_bytes"] > 0

    for head in MODEL_HEADS:
        metrics = result["test_metrics"][head]
        expected_rows = 8 if head.startswith("arrival_") else 12
        assert metrics["rows"] == expected_rows
        assert 0 < metrics["positives"] < metrics["rows"]
        diagnostic = result["model_diagnostics"][head]
        assert diagnostic["bestIteration"] >= 1
        assert diagnostic["treeCount"] >= 1
        assert diagnostic["featureCount"] == len(prepared.train.feature_names)
        assert diagnostic["calibration"]["fittedRows"] == (
            8 if head.startswith("arrival_") else 12
        )
        assert set(diagnostic["partitionPopulations"]) == {
            "train",
            "tune",
            "calibration",
            "test",
        }
        assert len(diagnostic["featureImportanceGain"]) == len(
            prepared.train.feature_names
        )

    serialized = json.dumps(result, allow_nan=False)
    for artifact_field in (
        "artifactStatus",
        "boosters",
        "corpusBinding",
        "parityCases",
    ):
        assert artifact_field not in serialized


def test_retrospective_fit_rejects_a_history_feature_contract(make_record):
    prepared = _prepared_retrospective_data(make_record)
    feature_name = "history_route_arrival_15_rate"

    def history_partition(partition):
        return replace(
            partition,
            feature_names=(feature_name,),
            matrix=partition.matrix[:, :1],
        )

    unsafe = SimpleNamespace(
        publishable=False,
        target_derived_history_features_allowed=False,
        retrospective_audit=prepared.retrospective_audit,
        train=history_partition(prepared.train),
        tune=history_partition(prepared.tune),
        calibration=history_partition(prepared.calibration),
        test=history_partition(prepared.test),
    )

    with pytest.raises(ValueError, match="cannot use history features"):
        evaluate_retrospective_temporal_model(unsafe)


def test_retrospective_fit_rejects_a_publishable_claim(make_record):
    prepared = _prepared_retrospective_data(make_record)
    unsafe = SimpleNamespace(
        publishable=True,
        target_derived_history_features_allowed=False,
        retrospective_audit=prepared.retrospective_audit,
        train=prepared.train,
        tune=prepared.tune,
        calibration=prepared.calibration,
        test=prepared.test,
    )

    with pytest.raises(ValueError, match="must be non-publishable"):
        evaluate_retrospective_temporal_model(unsafe)


def test_lightgbm_configuration_is_fixed_and_deterministic():
    config = TrainingConfig(seed=17, num_threads=2)
    parameters = _lightgbm_parameters(config)

    assert parameters["deterministic"] is True
    assert parameters["force_col_wise"] is True
    assert parameters["device_type"] == "cpu"
    assert parameters["n_jobs"] == 2
    assert parameters["random_state"] == 17
    assert parameters["bagging_seed"] == 17
    assert parameters["feature_fraction_seed"] == 17
    assert parameters["data_random_seed"] == 17

    with pytest.raises(ValueError, match="num_threads"):
        TrainingConfig(num_threads=0)


def test_retrospective_memory_guard_fails_before_first_model_fit(
    make_record,
    monkeypatch,
):
    prepared = _prepared_retrospective_data(
        make_record,
        matrix_memory_limits=RetrospectiveMatrixMemoryLimits(
            max_evaluation_additional_bytes=1,
        ),
    )

    def unexpected_fit(*args, **kwargs):
        raise AssertionError("model fitting began before evaluation memory guard")

    monkeypatch.setattr(train, "_fit_head", unexpected_fit)
    with pytest.raises(MemoryError, match="before model fitting"):
        evaluate_retrospective_temporal_model(
            prepared,
            config=TrainingConfig(
                n_estimators=2,
                num_leaves=2,
                min_child_samples=2,
            ),
        )


def test_numeric_probability_projection_matches_ordering_contract():
    probabilities = np.asarray(
        [
            [0.10, 0.40, 0.90, 0.80, 0.20],
            [0.90, 0.10, 0.40, 0.20, 0.80],
            [0.90, 0.60, 0.20, 0.20, 0.10],
        ],
        dtype=np.float64,
    )

    _project_probability_matrix_in_place(probabilities)

    np.testing.assert_allclose(
        probabilities,
        np.asarray(
            [
                [
                    0.4666666666666667,
                    0.4666666666666667,
                    0.4666666666666667,
                    0.50,
                    0.50,
                ],
                [0.90, 0.25, 0.25, 0.20, 0.80],
                [0.90, 0.60, 0.20, 0.15, 0.15],
            ]
        ),
    )
