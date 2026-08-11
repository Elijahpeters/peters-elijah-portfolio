from __future__ import annotations

from copy import deepcopy

import pytest

from ..anac_annual_gate_review import (
    ANAC_ANNUAL_GATE_REVIEW_SCHEMA,
    AnacAnnualGateReviewError,
    render_gate_review_markdown,
    review_annual_evaluation,
)
from ..anac_annual_retrospective import ANAC_ANNUAL_RETROSPECTIVE_OUTPUT_SCHEMA
from ..export import MODEL_HEADS
from ..retrospective_audit_contract import canonical_sha256


def _metric(rate: float, *, auc: float, ap: float, brier: float, loss: float):
    rows = 1_000
    return {
        "rocAuc": auc,
        "averagePrecision": ap,
        "brierScore": brier,
        "logLoss": loss,
        "rows": rows,
        "positives": int(rate * rows),
        "positiveShare": rate,
    }


def _evaluation() -> dict[str, object]:
    metrics = {
        "arrival_15": _metric(
            0.2, auc=0.64, ap=0.28, brier=0.15, loss=0.47
        ),
        "arrival_30": _metric(
            0.1, auc=0.62, ap=0.14, brier=0.095, loss=0.34
        ),
        "arrival_60": _metric(
            0.04, auc=0.58, ap=0.05, brier=0.038, loss=0.165
        ),
        "cancelled": _metric(
            0.03, auc=0.77, ap=0.14, brier=0.026, loss=0.12
        ),
    }
    metrics["disrupted"] = dict(metrics["cancelled"])
    value: dict[str, object] = {
        "schema_version": ANAC_ANNUAL_RETROSPECTIVE_OUTPUT_SCHEMA,
        "publishable": False,
        "production_artifact_created": False,
        "deployment_performed": False,
        "exact_join_cohort": {
            "metric_population_rows": 900,
            "t7_schedule_rows": 1_000,
            "exact_match_rate_over_t7_schedules": 0.9,
        },
        "model_evaluation": {
            "test_metrics": metrics,
        },
    }
    value["audit_sha256"] = canonical_sha256(value)
    return value


def test_gate_review_blocks_release_and_exposes_reference_regressions():
    review = review_annual_evaluation(_evaluation())

    assert review["schema_version"] == ANAC_ANNUAL_GATE_REVIEW_SCHEMA
    assert review["release_decision"] == "blocked"
    assert review["target_aliases"] == {"disrupted": "cancelled"}
    assert set(review["head_reviews"]) == set(MODEL_HEADS)
    assert review["head_reviews"]["arrival_30"]["constantReference"][
        "modelImprovement"
    ]["brierScore"] < 0
    assert review["head_reviews"]["cancelled"]["constantReference"][
        "modelImprovement"
    ]["brierScore"] > 0
    assert len(review["review_sha256"]) == 64

    markdown = render_gate_review_markdown(review)
    assert "Blocked from production" in markdown
    assert "Same target as cancelled" in markdown
    assert "90.00%" in markdown


def test_gate_review_rejects_tampered_evidence():
    evaluation = _evaluation()
    tampered = deepcopy(evaluation)
    tampered["model_evaluation"]["test_metrics"]["arrival_15"]["rocAuc"] = 0.99

    with pytest.raises(AnacAnnualGateReviewError, match="digest"):
        review_annual_evaluation(tampered)


def test_gate_review_requires_every_model_head():
    evaluation = _evaluation()
    del evaluation["model_evaluation"]["test_metrics"]["arrival_60"]
    evaluation["audit_sha256"] = canonical_sha256(
        {key: value for key, value in evaluation.items() if key != "audit_sha256"}
    )

    with pytest.raises(AnacAnnualGateReviewError, match="all model heads"):
        review_annual_evaluation(evaluation)
