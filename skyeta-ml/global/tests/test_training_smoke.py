from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from ..export import (
    MODEL_HEADS,
    SLICE_DIMENSIONS,
    ArtifactError,
    assert_publishable,
    predict_artifact_probabilities,
    validate_artifact,
    verify_parity_cases,
)
from ..pipeline import prepare_global_data
from ..splits import ChronologicalBoundaries
from ..train import TrainingConfig, fit_candidate_artifact


def test_synthetic_end_to_end_fit_stays_a_candidate(make_record):
    start = datetime(2024, 1, 1, 8, tzinfo=timezone.utc)
    patterns = (
        ("landed", 0),
        ("landed", 20),
        ("landed", 40),
        ("landed", 75),
        ("cancelled", None),
        ("diverted", None),
    )
    records = []
    for index in range(72):
        departure = start + timedelta(days=index)
        status, delay = patterns[index % len(patterns)]
        arrival = departure + timedelta(hours=2)
        records.append(
            make_record(
                record_id=f"fit-{index}",
                service_date=(departure + timedelta(hours=1)).date(),
                operating_flight_number=str(100 + index % len(patterns)),
                scheduled_departure_utc=departure,
                scheduled_arrival_utc=arrival,
                status=status,
                actual_arrival_utc=(
                    arrival + timedelta(minutes=delay)
                    if delay is not None
                    else None
                ),
            )
        )
    boundaries = ChronologicalBoundaries(
        train_end=start + timedelta(days=30),
        tune_end=start + timedelta(days=44),
        calibration_end=start + timedelta(days=58),
        test_end=start + timedelta(days=73),
    )
    prepared = prepare_global_data(records, boundaries)
    artifact = fit_candidate_artifact(
        prepared,
        data_sources=[
            {
                "sourceId": "unit-fixture",
                "name": "synthetic unit-test rows",
                "rightsStatus": "synthetic_test_only",
                "rightsEvidence": {
                    "type": "synthetic_fixture",
                    "reference": "generated unit-test records",
                    "url": "urn:skyeta:unit-fixture",
                    "reviewedAtUtc": "2026-08-09T00:00:00Z",
                    "sha256": sha256(b"generated unit-test records").hexdigest(),
                },
            }
        ],
        coverage_summary={"rows": len(records), "synthetic": True},
        config=TrainingConfig(
            n_estimators=20,
            learning_rate=0.1,
            num_leaves=7,
            min_child_samples=2,
            early_stopping_rounds=4,
        ),
    )
    assert artifact["artifactStatus"] == "candidate"
    assert artifact["paritySource"] == "native_lightgbm"
    assert artifact["coveragePolicy"]["coldStartAction"] == "refuse"
    assert artifact["modelCard"]["dataCoverage"]["globalReleaseGatePassed"] is False
    assert verify_parity_cases(artifact) <= 1e-12
    evaluation = artifact["modelCard"]["evaluation"]
    assert set(evaluation["sliceMetrics"]) == set(SLICE_DIMENSIONS)
    for dimension in SLICE_DIMENSIONS:
        entries = evaluation["sliceMetrics"][dimension]
        assert sum(entry["populationRows"] for entry in entries) == len(
            prepared.test.records
        )
        for head in MODEL_HEADS:
            assert sum(entry["metrics"][head]["rows"] for entry in entries) == (
                evaluation["testMetrics"][head]["rows"]
            )
            assert sum(
                entry["metrics"][head]["positives"] for entry in entries
            ) == evaluation["testMetrics"][head]["positives"]

    incomplete_slices = copy.deepcopy(artifact)
    del incomplete_slices["modelCard"]["evaluation"]["sliceMetrics"]["season"]
    with pytest.raises(ArtifactError, match="season slice evaluation"):
        validate_artifact(incomplete_slices)

    inconsistent_slice = copy.deepcopy(artifact)
    first_region = inconsistent_slice["modelCard"]["evaluation"]["sliceMetrics"][
        "region"
    ][0]
    first_region["populationRows"] += 1
    with pytest.raises(ArtifactError, match="exhaust the untouched test"):
        validate_artifact(inconsistent_slice)

    structurally_validated = copy.deepcopy(artifact)
    structurally_validated["artifactStatus"] = "validated"
    structurally_validated["modelCard"]["evaluation"]["untouchedTest"] = True
    structurally_validated["modelCard"]["dataCoverage"].pop("synthetic")
    structurally_validated["modelCard"]["dataCoverage"][
        "globalReleaseGatePassed"
    ] = True
    with pytest.raises(ArtifactError, match="not approved"):
        assert_publishable(structurally_validated)

    completed_months = [
        f"{year}-{month:02d}"
        for year in (2024, 2025)
        for month in range(1, 13)
    ]
    source = structurally_validated["modelCard"]["dataSources"][0]
    source.update(
        {
            "sourceId": "provider-records",
            "name": "Provider aviation records",
            "rightsStatus": "approved_for_training_and_derived_publication",
            "rightsEvidence": {
                "type": "public_license",
                "reference": "Provider license grant dated 2026-01-01",
                "url": "https://example.invalid/provider-license",
                "reviewedAtUtc": "2026-08-09T00:00:00Z",
                "sha256": sha256(b"provider-license-evidence").hexdigest(),
            },
        }
    )
    structurally_validated["modelCard"]["dataCoverage"].update(
        {
            "rows": 650_000,
            "corpusAudit": {
                "completedMonths": completed_months,
                "scheduledRows": 650_000,
                "identityCompleteRows": 637_000,
                "knownOutcomeRows": 617_500,
                "operatedRows": 600_000,
                "operatedRowsWithArrivalTimes": 540_000,
                "arrival15DelayedRows": 60_000,
                "cancellationRows": 6_000,
            },
        }
    )
    with pytest.raises(ArtifactError, match="bound normalized record count"):
        assert_publishable(structurally_validated)

    scoring_candidate = copy.deepcopy(artifact)
    scoring_candidate["coveragePolicy"]["coldStartAction"] = "global_backoff"
    probabilities = predict_artifact_probabilities(
        scoring_candidate,
        record=records[-1],
        allow_unvalidated=True,
    )
    assert set(probabilities) == set(MODEL_HEADS)
    with pytest.raises(ArtifactError, match="record-derived contract"):
        predict_artifact_probabilities(
            scoring_candidate,
            [0.0] * len(scoring_candidate["featureNames"]),
            record=records[-1],
            allow_unvalidated=True,
        )
