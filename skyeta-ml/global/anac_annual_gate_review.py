"""Deterministic release-gate review for one signed ANAC annual evaluation.

The annual retrospective runner intentionally cannot publish or deploy a
model.  This module verifies that signed output, compares every reported head
with the honest constant-prevalence reference, exposes source-equivalent
targets, and writes a concise review without changing the original evidence.
"""

from __future__ import annotations

import argparse
import math
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from .anac_annual_retrospective import ANAC_ANNUAL_RETROSPECTIVE_OUTPUT_SCHEMA
from .export import MODEL_HEADS
from .retrospective_audit_contract import canonical_json, canonical_sha256


ANAC_ANNUAL_GATE_REVIEW_SCHEMA = "skyeta-anac-annual-gate-review-v1"


class AnacAnnualGateReviewError(ValueError):
    """The signed annual evaluation cannot support a deterministic review."""


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnacAnnualGateReviewError(f"{name} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise AnacAnnualGateReviewError(f"{name} must be finite")
    return number


def _constant_reference(metrics: Mapping[str, object], head: str) -> dict[str, object]:
    rows = metrics.get("rows")
    positives = metrics.get("positives")
    if (
        isinstance(rows, bool)
        or not isinstance(rows, int)
        or rows <= 0
        or isinstance(positives, bool)
        or not isinstance(positives, int)
        or not 0 < positives < rows
    ):
        raise AnacAnnualGateReviewError(
            f"{head} requires a positive test population with both classes"
        )
    prevalence = positives / rows
    reported_share = _finite_number(metrics.get("positiveShare"), f"{head}.positiveShare")
    if not math.isclose(prevalence, reported_share, rel_tol=0.0, abs_tol=1e-15):
        raise AnacAnnualGateReviewError(
            f"{head} positiveShare does not equal positives / rows"
        )

    baseline_brier = prevalence * (1.0 - prevalence)
    baseline_log_loss = -(
        prevalence * math.log(prevalence)
        + (1.0 - prevalence) * math.log(1.0 - prevalence)
    )
    roc_auc = _finite_number(metrics.get("rocAuc"), f"{head}.rocAuc")
    average_precision = _finite_number(
        metrics.get("averagePrecision"), f"{head}.averagePrecision"
    )
    brier = _finite_number(metrics.get("brierScore"), f"{head}.brierScore")
    log_loss = _finite_number(metrics.get("logLoss"), f"{head}.logLoss")
    return {
        "constantProbability": prevalence,
        "constantMetrics": {
            "rocAuc": 0.5,
            "averagePrecision": prevalence,
            "brierScore": baseline_brier,
            "logLoss": baseline_log_loss,
        },
        "modelImprovement": {
            "rocAucAboveChance": roc_auc - 0.5,
            "averagePrecision": average_precision - prevalence,
            "brierScore": baseline_brier - brier,
            "logLoss": baseline_log_loss - log_loss,
        },
        "referenceChecks": {
            "ranksAboveChance": roc_auc > 0.5,
            "averagePrecisionBeatsPrevalence": average_precision > prevalence,
            "brierBeatsConstant": brier < baseline_brier,
            "logLossBeatsConstant": log_loss < baseline_log_loss,
        },
    }


def _same_reported_metrics(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    fields = (
        "rocAuc",
        "averagePrecision",
        "brierScore",
        "logLoss",
        "rows",
        "positives",
        "positiveShare",
    )
    return all(left.get(field) == right.get(field) for field in fields)


def review_annual_evaluation(evaluation: Mapping[str, object]) -> dict[str, object]:
    """Verify and review one immutable annual retrospective output."""

    if evaluation.get("schema_version") != ANAC_ANNUAL_RETROSPECTIVE_OUTPUT_SCHEMA:
        raise AnacAnnualGateReviewError("unsupported annual evaluation schema")
    signed_digest = evaluation.get("audit_sha256")
    without_digest = dict(evaluation)
    without_digest.pop("audit_sha256", None)
    if not isinstance(signed_digest, str) or signed_digest != canonical_sha256(
        without_digest
    ):
        raise AnacAnnualGateReviewError("annual evaluation digest is inconsistent")

    model_evaluation = evaluation.get("model_evaluation")
    test_metrics = (
        model_evaluation.get("test_metrics")
        if isinstance(model_evaluation, Mapping)
        else None
    )
    if not isinstance(test_metrics, Mapping) or set(test_metrics) != set(MODEL_HEADS):
        raise AnacAnnualGateReviewError("annual evaluation lacks all model heads")

    aliases = dict(model_evaluation.get("target_aliases", {}))
    if not aliases and _same_reported_metrics(
        test_metrics["cancelled"], test_metrics["disrupted"]
    ):
        aliases["disrupted"] = "cancelled"

    head_reviews: dict[str, dict[str, object]] = {}
    for head in MODEL_HEADS:
        metrics = dict(test_metrics[head])
        head_reviews[head] = {
            "metrics": metrics,
            "constantReference": _constant_reference(metrics, head),
            "aliasOf": aliases.get(head),
        }

    cohort = evaluation.get("exact_join_cohort")
    if not isinstance(cohort, Mapping):
        raise AnacAnnualGateReviewError("annual evaluation lacks cohort qualification")
    exact_match_rate = _finite_number(
        cohort.get("exact_match_rate_over_t7_schedules"),
        "exact_join_cohort.exact_match_rate_over_t7_schedules",
    )

    blockers = []
    for field in (
        "publishable",
        "production_artifact_created",
        "deployment_performed",
    ):
        if evaluation.get(field) is not False:
            raise AnacAnnualGateReviewError(
                f"retrospective evaluation must keep {field}=false"
            )
    blockers.extend(
        [
            "The evaluation is retrospective, not a historical point-in-time backtest.",
            "Metrics are conditioned on final schedules remaining exactly joinable after T-7.",
            "The signed output intentionally contains no production model artifact.",
            "ANAC VRA exposes cancellation but no distinct diversion outcome.",
        ]
    )

    result: dict[str, object] = {
        "schema_version": ANAC_ANNUAL_GATE_REVIEW_SCHEMA,
        "source_evaluation_audit_sha256": signed_digest,
        "release_decision": "blocked",
        "release_blockers": blockers,
        "cohort": {
            "metricPopulationRows": cohort.get("metric_population_rows"),
            "t7ScheduleRows": cohort.get("t7_schedule_rows"),
            "exactMatchRate": exact_match_rate,
            "annualPopulationPerformanceClaimAllowed": False,
        },
        "target_aliases": aliases,
        "head_reviews": head_reviews,
        "next_actions": [
            "Keep this signed output as retrospective research evidence only.",
            "Use a future time period for development after this test-period review.",
            "Improve and recalibrate the 30- and 60-minute arrival heads before another gate review.",
            "Acquire immutable point-in-time outcome evidence and archive ANAC publication rights evidence.",
            "Run a new chronological regional evaluation before creating any Brazil production artifact.",
        ],
    }
    result["review_sha256"] = canonical_sha256(result)
    return result


def render_gate_review_markdown(review: Mapping[str, object]) -> str:
    """Render a concise human-readable companion to the canonical JSON review."""

    cohort = review["cohort"]
    lines = [
        "# SkyETA ANAC 2023 annual model gate review",
        "",
        "## Decision",
        "",
        "**Blocked from production.** The annual run completed successfully, but it is retrospective research evidence rather than a deployable model.",
        "",
        "## Evaluated cohort",
        "",
        f"- Exactly joined model rows: **{cohort['metricPopulationRows']:,}**",
        f"- T-7 schedule rows: **{cohort['t7ScheduleRows']:,}**",
        f"- Exact schedule-to-outcome match rate: **{cohort['exactMatchRate']:.2%}**",
        "- Annual-population performance claim: **not allowed**",
        "",
        "## Untouched chronological test results",
        "",
        "| Head | Rows | Event rate | ROC AUC | Average precision | Brier vs constant | Log loss vs constant | Interpretation |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for head in MODEL_HEADS:
        item = review["head_reviews"][head]
        metrics = item["metrics"]
        reference = item["constantReference"]
        improvements = reference["modelImprovement"]
        interpretation = (
            f"Same target as {item['aliasOf']} for this source"
            if item["aliasOf"]
            else "Distinct evaluated target"
        )
        lines.append(
            "| {head} | {rows:,} | {rate:.2%} | {auc:.3f} | {ap:.3f} | {brier:+.4f} | {logloss:+.4f} | {interpretation} |".format(
                head=head,
                rows=metrics["rows"],
                rate=metrics["positiveShare"],
                auc=metrics["rocAuc"],
                ap=metrics["averagePrecision"],
                brier=improvements["brierScore"],
                logloss=improvements["logLoss"],
                interpretation=interpretation,
            )
        )
    lines.extend(
        [
            "",
            "Positive Brier/log-loss differences mean the model beat the constant-rate reference; negative values mean it did worse.",
            "",
            "## Release blockers",
            "",
            *[f"- {item}" for item in review["release_blockers"]],
            "",
            "## Next engineering actions",
            "",
            *[f"{index}. {item}" for index, item in enumerate(review["next_actions"], 1)],
            "",
            f"Source evaluation digest: `{review['source_evaluation_audit_sha256']}`",
            "",
            f"Gate-review digest: `{review['review_sha256']}`",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, text: str) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", required=True, type=Path)
    parser.add_argument("--json-output", required=True, type=Path)
    parser.add_argument("--markdown-output", required=True, type=Path)
    args = parser.parse_args(argv)
    import json

    evaluation = json.loads(args.evaluation.read_text(encoding="utf-8"))
    review = review_annual_evaluation(evaluation)
    _atomic_write(args.json_output, canonical_json(review, indent=2) + "\n")
    _atomic_write(args.markdown_output, render_gate_review_markdown(review))
    print(canonical_json({"review_sha256": review["review_sha256"]}))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())


__all__ = [
    "ANAC_ANNUAL_GATE_REVIEW_SCHEMA",
    "AnacAnnualGateReviewError",
    "render_gate_review_markdown",
    "review_annual_evaluation",
]
