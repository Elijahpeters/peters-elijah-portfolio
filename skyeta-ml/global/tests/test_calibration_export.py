from __future__ import annotations

import copy
from datetime import timedelta
from hashlib import sha256

import pytest

from ..calibration import (
    PlattCalibrator,
    calibrate_head_scores,
    fit_platt_calibrator,
    project_cumulative_probabilities,
    project_nonincreasing,
)
from ..encodings import PastOnlyHierarchicalEncoder
from ..export import (
    MODEL_HEADS,
    ArtifactError,
    assert_publishable,
    build_artifact,
    predict_artifact_probabilities,
    validate_artifact,
    verify_parity_cases,
)


def leaf_booster(value: float):
    return {
        "objective": "binary sigmoid:1",
        "average_output": False,
        "tree_info": [{"tree_structure": {"leaf_value": value}}],
    }


def synthetic_source():
    return {
        "sourceId": "unit-fixture",
        "name": "synthetic unit-test fixture",
        "rightsStatus": "synthetic_test_only",
        "rightsEvidence": {
            "type": "synthetic_fixture",
            "reference": "generated unit-test records",
            "url": "urn:skyeta:unit-fixture",
            "reviewedAtUtc": "2026-08-09T00:00:00Z",
            "sha256": sha256(b"generated unit-test records").hexdigest(),
        },
    }


def test_platt_fit_and_monotonic_projection():
    calibrator = fit_platt_calibrator([-2, -1, 1, 2], [0, 0, 1, 1])
    assert calibrator.slope > 0
    assert calibrator.apply(-1) < calibrator.apply(1)
    assert project_nonincreasing([0.2, 0.5, 0.1]) == pytest.approx(
        (0.35, 0.35, 0.1)
    )
    projected = project_cumulative_probabilities(
        {"arrival_15": 0.2, "arrival_30": 0.4, "arrival_60": 0.6}
    )
    assert projected["arrival_15"] >= projected["arrival_30"]
    assert projected["arrival_30"] >= projected["arrival_60"]


def test_all_head_calibration_enforces_every_logical_subset():
    calibrators = {
        head: PlattCalibrator(1, 0, 10) for head in MODEL_HEADS
    }
    scores = {
        "arrival_15": -2,
        "arrival_30": -1,
        "arrival_60": 0,
        "cancelled": 2,
        "disrupted": -2,
    }
    result = calibrate_head_scores(scores, calibrators)
    assert result["arrival_15"] >= result["arrival_30"] >= result["arrival_60"]
    assert result["cancelled"] <= result["disrupted"]


def test_synthetic_artifact_has_parity_but_cannot_be_published(make_record):
    encoder = PastOnlyHierarchicalEncoder()
    historical = make_record()
    _, snapshot = encoder.fit_transform([historical])
    boosters = {
        "arrival_15": leaf_booster(-2),
        "arrival_30": leaf_booster(-1),
        "arrival_60": leaf_booster(0),
        "cancelled": leaf_booster(-3),
        "disrupted": leaf_booster(-2.5),
    }
    calibrators = {
        head: PlattCalibrator(1, 0, 10) for head in MODEL_HEADS
    }
    model_card = {
        "dataSources": [synthetic_source()],
        "evaluation": {"untouchedTest": False},
        "dataCoverage": {"globalReleaseGatePassed": False},
    }
    artifact = build_artifact(
        feature_names=["x", "y"],
        boosters=boosters,
        calibrators=calibrators,
        history_snapshot=snapshot,
        model_card=model_card,
        parity_feature_rows=[[0, 0], [1, -1]],
        artifact_status="synthetic_test_only",
    )
    assert artifact["formatVersion"] == 4
    assert verify_parity_cases(artifact) == 0
    probabilities = artifact["parityCases"][0]["probabilities"]
    assert probabilities["arrival_15"] >= probabilities["arrival_30"]
    assert probabilities["arrival_30"] >= probabilities["arrival_60"]
    assert probabilities["cancelled"] <= probabilities["disrupted"]
    with pytest.raises(ArtifactError, match="cold-start policy refuses"):
        predict_artifact_probabilities(
            artifact,
            [0, 0],
            coverage_tier="cold_start",
            allow_unvalidated=True,
        )
    assert set(
        predict_artifact_probabilities(
            artifact,
            [0, 0],
            coverage_tier="established",
            allow_unvalidated=True,
        )
    ) == set(MODEL_HEADS)
    scoring_record = make_record(
        operating_flight_number="999",
        scheduled_departure_utc=historical.outcome_observed_at + timedelta(days=8),
    )
    with pytest.raises(ArtifactError, match="caller coverage tier disagrees"):
        predict_artifact_probabilities(
            artifact,
            [0, 0],
            record=scoring_record,
            coverage_tier="established",
            allow_unvalidated=True,
        )
    with pytest.raises(ArtifactError, match="cold-start policy refuses"):
        predict_artifact_probabilities(
            artifact,
            [0, 0],
            record=scoring_record,
            allow_unvalidated=True,
        )
    with pytest.raises(ArtifactError, match="cannot be published"):
        predict_artifact_probabilities(
            artifact, [0, 0], coverage_tier="established"
        )
    with pytest.raises(ArtifactError, match="cannot be published"):
        assert_publishable(artifact)

    validated = copy.deepcopy(artifact)
    validated["artifactStatus"] = "validated"
    validated["modelCard"]["evaluation"]["untouchedTest"] = True
    validated["modelCard"]["dataCoverage"]["globalReleaseGatePassed"] = True
    with pytest.raises(ArtifactError, match="native parity"):
        assert_publishable(validated)

    malformed = copy.deepcopy(artifact)
    del malformed["boosters"]
    with pytest.raises(ArtifactError, match="boosters"):
        validate_artifact(malformed)

    invalid_hidden_branch = copy.deepcopy(artifact)
    invalid_hidden_branch["boosters"]["arrival_15"]["tree_info"][0][
        "tree_structure"
    ] = {
        "split_feature": 0,
        "threshold": 0.5,
        "left_child": {"leaf_value": 0},
        "right_child": {
            "split_feature": 99,
            "threshold": 0.5,
            "left_child": {"leaf_value": 0},
            "right_child": {"leaf_value": 1},
        },
    }
    with pytest.raises(ArtifactError, match="invalid feature or threshold"):
        validate_artifact(invalid_hidden_branch)

    unsupported_zero_missing = copy.deepcopy(artifact)
    unsupported_zero_missing["boosters"]["arrival_15"]["tree_info"][0][
        "tree_structure"
    ] = {
        "split_feature": 0,
        "threshold": 0.5,
        "decision_type": "<=",
        "default_left": True,
        "missing_type": "Zero",
        "left_child": {"leaf_value": 0},
        "right_child": {"leaf_value": 1},
    }
    with pytest.raises(ArtifactError, match="missing_type"):
        validate_artifact(unsupported_zero_missing)

    impossible_history = copy.deepcopy(artifact)
    impossible_history["history"]["globalTargets"]["cancelled"] = [10, 10]
    with pytest.raises(ArtifactError, match="schedule|hierarchy|cancellation"):
        validate_artifact(impossible_history)

    unsupported_policy_field = copy.deepcopy(artifact)
    unsupported_policy_field["coveragePolicy"]["callerMayOverrideTier"] = True
    with pytest.raises(ArtifactError, match="coverage policy fields"):
        validate_artifact(unsupported_policy_field)


def test_publication_rejects_boolean_only_gate_and_candidate_needs_native_parity(
    make_record,
):
    minimal = {
        "formatVersion": 4,
        "artifactStatus": "validated",
        "modelCard": {
            "evaluation": {"untouchedTest": True},
            "dataCoverage": {"globalReleaseGatePassed": True},
        },
    }
    with pytest.raises(ArtifactError, match="scope and population"):
        assert_publishable(minimal)

    encoder = PastOnlyHierarchicalEncoder()
    _, snapshot = encoder.fit_transform(
        [make_record()],
        snapshot_as_of=make_record().scheduled_departure_utc,
    )
    boosters = {head: leaf_booster(-1) for head in MODEL_HEADS}
    calibrators = {head: PlattCalibrator(1, 0, 10) for head in MODEL_HEADS}
    with pytest.raises(ArtifactError, match="native LightGBM parity"):
        build_artifact(
            feature_names=["x"],
            boosters=boosters,
            calibrators=calibrators,
            history_snapshot=snapshot,
            model_card={
                "dataSources": [synthetic_source()],
                "evaluation": {"untouchedTest": False},
                "dataCoverage": {"globalReleaseGatePassed": False},
            },
            parity_feature_rows=[[0]],
            artifact_status="candidate",
        )
