from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ..export import MODEL_HEADS
from ..pipeline import prepare_retrospective_global_data
from ..splits import ChronologicalBoundaries
from ..train import TrainingConfig, evaluate_retrospective_temporal_model


def _prepared_retrospective_data(make_record):
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
                )
            )
    return prepare_retrospective_global_data(records, boundaries)


def test_retrospective_fit_returns_diagnostics_not_a_deployable_artifact(
    make_record,
):
    prepared = _prepared_retrospective_data(make_record)

    result = evaluate_retrospective_temporal_model(
        prepared,
        config=TrainingConfig(
            n_estimators=24,
            learning_rate=0.1,
            num_leaves=7,
            min_child_samples=2,
            early_stopping_rounds=4,
        ),
    )

    assert result["evaluation_kind"] == "retrospective_temporal_evaluation"
    assert result["point_in_time_backtest"] is False
    assert result["publishable"] is False
    assert result["target_derived_history_features_used"] is False
    assert result["feature_contract"]["precomputed_matrices_only"] is True
    assert result["feature_contract"]["target_derived_history_features"] is False
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
    }
    assert cold_start["combined"]["fullySeen"]["populationRows"] == 12
    assert cold_start["combined"]["anyUnseen"]["populationRows"] == 0

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
