"""Shared fail-closed contracts for offline retrospective model audits.

The ANAC annual and January diagnostics deliberately produce evidence, not a
deployable model.  This module keeps their evaluator validation, source-code
binding, canonical digesting, and atomic output semantics identical without
opening an arbitrary evaluator seam in either public runner.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .export import MODEL_HEADS


def canonical_json(value: object, *, indent: int | None = None) -> str:
    """Render strict deterministic JSON suitable for a signed audit fact."""

    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        indent=indent,
        separators=(",", ":") if indent is None else None,
    )


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def source_code_provenance(
    *,
    base: Path,
    relative_files: Sequence[str],
    contract: str,
    error_type: type[Exception],
) -> dict[str, object]:
    """Bind an audit to an ordered, explicit set of evaluator source bytes."""

    files: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw_name in relative_files:
        relative_name = str(raw_name)
        if (
            not relative_name
            or relative_name in seen
            or "\\" in relative_name
            or Path(relative_name).is_absolute()
            or any(part in {"", ".", ".."} for part in relative_name.split("/"))
        ):
            raise error_type(
                f"invalid reviewed source-contract path: {relative_name!r}"
            )
        seen.add(relative_name)
        path = base.joinpath(*relative_name.split("/")).resolve()
        try:
            path.relative_to(base.resolve())
        except ValueError as error:
            raise error_type(
                f"reviewed source-contract path escapes its base: {relative_name}"
            ) from error
        if not path.is_file():
            raise error_type(
                f"reviewed source-contract file is missing: {relative_name}"
            )
        raw = path.read_bytes()
        files.append(
            {
                "path": relative_name,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return {
        "contract": contract,
        "files": files,
        "aggregate_sha256": canonical_sha256(files),
    }


def exact_join_cohort_qualification(
    *,
    matched_count: int,
    eligible_schedule_count: int,
    outcome_count: int,
    schedule_dispositions: Mapping[str, int],
    outcome_dispositions: Mapping[str, int],
    interpretation: str,
    population_claim_field: str,
) -> dict[str, object]:
    """Build the common, selection-bias-qualified exact-join denominator."""

    counts = (matched_count, eligible_schedule_count, outcome_count)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
        raise ValueError("exact-join population counts must be non-negative integers")
    if eligible_schedule_count <= 0:
        raise ValueError("eligible schedule denominator must be positive")
    if matched_count > eligible_schedule_count or matched_count > outcome_count:
        raise ValueError("matched rows exceed an exact-join input population")
    required_dispositions = {"matched", "unmatched", "ambiguous", "rejected"}
    schedule_counts = dict(schedule_dispositions)
    outcome_counts = dict(outcome_dispositions)
    if set(schedule_counts) != required_dispositions or set(outcome_counts) != required_dispositions:
        raise ValueError("exact-join dispositions are incomplete")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (*schedule_counts.values(), *outcome_counts.values())
    ):
        raise ValueError("exact-join dispositions must be non-negative integers")
    if schedule_counts["matched"] != matched_count or outcome_counts["matched"] != matched_count:
        raise ValueError("exact-join matched dispositions do not reconcile")
    if sum(schedule_counts.values()) != eligible_schedule_count:
        raise ValueError("eligible schedule dispositions do not reconcile")
    if sum(outcome_counts.values()) != outcome_count:
        raise ValueError("outcome dispositions do not reconcile")
    claim_field = str(population_claim_field).strip()
    if not claim_field:
        raise ValueError("population claim field is required")
    return {
        "join_conditioned_cohort": True,
        "conditioning_uses_post_prediction_schedule_stability": True,
        "metric_population_rows": matched_count,
        "eligible_schedule_rows": eligible_schedule_count,
        "final_vra_candidate_rows": outcome_count,
        "exact_match_rate_over_eligible_schedules": (
            matched_count / eligible_schedule_count
        ),
        "schedule_dispositions": schedule_counts,
        "outcome_dispositions": outcome_counts,
        "required_exact_identity": (
            "carrier, flight number, ICAO route, scheduled departure UTC, "
            "and scheduled arrival UTC"
        ),
        "interpretation": str(interpretation),
        claim_field: False,
    }


def validate_retrospective_evaluator_contract(
    *,
    prepared: Any,
    evaluation: object,
    training_config: Any,
    matrix_memory_limits: Any,
    source_contract_sha256: str,
    cohort_qualification: Mapping[str, object],
    error_type: type[Exception],
) -> dict[str, object]:
    """Validate and qualify one fixed retrospective evaluator result."""

    if not isinstance(evaluation, Mapping):
        raise error_type("retrospective evaluator must return an object")
    if (
        evaluation.get("evaluation_kind")
        != "retrospective_temporal_evaluation"
        or evaluation.get("publishable") is not False
        or evaluation.get("point_in_time_backtest") is not False
        or evaluation.get("target_derived_history_features_used") is not False
    ):
        raise error_type(
            "evaluator violated the retrospective non-publication contract"
        )
    if evaluation.get("training_configuration") != asdict(training_config):
        raise error_type("evaluator training configuration is inconsistent")
    if evaluation.get("temporal_audit") != prepared.retrospective_audit.to_dict():
        raise error_type("evaluator temporal audit is inconsistent")

    runtime_provenance = evaluation.get("runtime_provenance")
    if not isinstance(runtime_provenance, Mapping):
        raise error_type("evaluator must disclose its runtime provenance")
    deterministic_parameters = runtime_provenance.get("deterministic_parameters")
    if not isinstance(deterministic_parameters, Mapping):
        raise error_type("evaluator must disclose its deterministic parameters")
    expected_deterministic_parameters = {
        "random_state": training_config.seed,
        "bagging_seed": training_config.seed,
        "feature_fraction_seed": training_config.seed,
        "data_random_seed": training_config.seed,
        "deterministic": True,
        "force_col_wise": True,
        "device_type": "cpu",
        "n_jobs": training_config.num_threads,
    }
    if (
        runtime_provenance.get("deterministic") is not True
        or dict(deterministic_parameters) != expected_deterministic_parameters
    ):
        raise error_type(
            "evaluator must disclose the exact deterministic runtime contract"
        )
    for field_name in (
        "python",
        "platform",
        "machine",
        "numpy",
        "scipy",
        "scikit_learn",
        "lightgbm",
    ):
        value = runtime_provenance.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise error_type(
                f"evaluator runtime provenance lacks {field_name}"
            )

    feature_contract = evaluation.get("feature_contract")
    matrix_storage_audit = prepared.matrix_audit.to_dict()
    if not isinstance(feature_contract, Mapping):
        raise error_type("evaluator must disclose its feature contract")
    if (
        feature_contract.get("feature_count") != len(prepared.train.feature_names)
        or feature_contract.get("feature_names")
        != list(prepared.train.feature_names)
        or feature_contract.get("precomputed_matrices_only") is not True
        or feature_contract.get("target_derived_history_features") is not False
        or feature_contract.get("matrix_storage") != matrix_storage_audit
    ):
        raise error_type("evaluator feature contract is inconsistent")

    memory_audit = evaluation.get("evaluation_memory_audit")
    if not isinstance(memory_audit, Mapping):
        raise error_type("evaluator must disclose its evaluation memory audit")
    stage_estimates = memory_audit.get("stage_estimated_additional_bytes")
    target_selections = memory_audit.get("target_selections")
    required_stages = {
        "model_fit",
        "calibration",
        "test_probability_generation",
        "test_metrics",
        "cold_start_diagnostics",
    }
    if not isinstance(stage_estimates, Mapping) or set(stage_estimates) != required_stages:
        raise error_type("evaluator memory stages are inconsistent")
    if not isinstance(target_selections, Mapping) or set(target_selections) != {
        "train",
        "tune",
        "calibration",
        "test",
    } or any(
        not isinstance(selection, Mapping)
        or set(selection) != set(MODEL_HEADS)
        for selection in target_selections.values()
    ):
        raise error_type("evaluator target-selection memory audit is inconsistent")

    lightgbm_reserves = memory_audit.get("lightgbm_reserves")
    if not isinstance(lightgbm_reserves, Mapping) or set(lightgbm_reserves) != {
        "dataset_bytes",
        "histogram_bytes",
        "tree_structure_bytes",
    } or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in lightgbm_reserves.values()
    ):
        raise error_type("evaluator LightGBM memory reserves are inconsistent")
    model_reserve = sum(lightgbm_reserves.values())
    raw_score_bytes = memory_audit.get("maximum_raw_score_vector_bytes")
    raw_overlap_reserve = memory_audit.get("raw_score_overlap_reserve_bytes")
    fit_subset_peak = memory_audit.get("maximum_fit_subset_peak_bytes")
    calibration_overlap_reserve = memory_audit.get(
        "cross_iteration_calibration_overlap_reserve_bytes"
    )
    projection_workspace = memory_audit.get("projection_workspace_bytes")
    probability_bytes = memory_audit.get("probability_matrix_bytes")
    estimated_peak = memory_audit.get("estimated_peak_additional_bytes")
    stage_values = tuple(stage_estimates.values())
    memory_limit = matrix_memory_limits.max_evaluation_additional_bytes
    if (
        memory_audit.get("guard_applied_before_model_fit") is not True
        or memory_audit.get("scope")
        != "additional_retrospective_evaluator_working_memory"
        or memory_audit.get("estimate_kind")
        != "conservative_preflight_estimate_not_native_allocator_hard_cap"
        or memory_audit.get("lightgbm_native_allocator_hard_cap") is not False
        or memory_audit.get("head_order") != list(MODEL_HEADS)
        or memory_audit.get("test_rows") != prepared.test.matrix.shape[0]
        or memory_audit.get("head_count") != len(MODEL_HEADS)
        or memory_audit.get("probability_storage") != "numpy_float64_matrix"
        or probability_bytes
        != prepared.test.matrix.shape[0] * len(MODEL_HEADS) * 8
        or isinstance(raw_score_bytes, bool)
        or not isinstance(raw_score_bytes, int)
        or raw_overlap_reserve != 2 * raw_score_bytes
        or isinstance(fit_subset_peak, bool)
        or not isinstance(fit_subset_peak, int)
        or isinstance(calibration_overlap_reserve, bool)
        or not isinstance(calibration_overlap_reserve, int)
        or stage_estimates["model_fit"]
        != model_reserve + fit_subset_peak + calibration_overlap_reserve
        or isinstance(projection_workspace, bool)
        or not isinstance(projection_workspace, int)
        or stage_estimates["test_probability_generation"]
        != (
            model_reserve
            + probability_bytes
            + raw_overlap_reserve
            + projection_workspace
        )
        or memory_audit.get("limit_bytes") != memory_limit
        or isinstance(estimated_peak, bool)
        or not isinstance(estimated_peak, int)
        or not stage_values
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in stage_values
        )
        or estimated_peak != max(stage_values)
        or estimated_peak > memory_limit
    ):
        raise error_type("evaluator memory contract is inconsistent")

    test_metrics = evaluation.get("test_metrics")
    model_diagnostics = evaluation.get("model_diagnostics")
    if (
        not isinstance(test_metrics, Mapping)
        or set(test_metrics) != set(MODEL_HEADS)
        or not isinstance(model_diagnostics, Mapping)
        or set(model_diagnostics) != set(MODEL_HEADS)
    ):
        raise error_type("evaluator must report every reviewed model head")
    reference_baselines = evaluation.get("reference_baselines")
    if not isinstance(reference_baselines, Mapping) or set(
        reference_baselines
    ) != set(MODEL_HEADS):
        raise error_type(
            "evaluator must report a constant-rate reference for every model head"
        )
    target_aliases = evaluation.get("target_aliases")
    if not isinstance(target_aliases, Mapping) or any(
        alias not in MODEL_HEADS
        or canonical not in MODEL_HEADS
        or alias == canonical
        or MODEL_HEADS.index(canonical) >= MODEL_HEADS.index(alias)
        for alias, canonical in target_aliases.items()
    ):
        raise error_type("evaluator target aliases are inconsistent")
    for head in MODEL_HEADS:
        diagnostic = model_diagnostics[head]
        if not isinstance(diagnostic, Mapping) or diagnostic.get(
            "trainedAsAliasOf"
        ) != target_aliases.get(head):
            raise error_type("evaluator target alias diagnostics are inconsistent")
    projection = evaluation.get("probability_ordering_projection")
    required_projection_fields = {
        "arrival15BelowArrival30Rows",
        "arrival30BelowArrival60Rows",
        "allArrivalHeadsPooledRows",
        "arrivalPairPooledRows",
        "disruptedBelowCancelledRows",
    }
    if (
        not isinstance(projection, Mapping)
        or set(projection) != required_projection_fields
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in projection.values()
        )
    ):
        raise error_type("evaluator probability-ordering audit is inconsistent")
    cold_start = evaluation.get("cold_start_diagnostics")
    cold_fields = cold_start.get("fields") if isinstance(cold_start, Mapping) else None
    if not isinstance(cold_fields, Mapping) or set(cold_fields) != {
        "operatingCarrier",
        "origin",
        "destination",
        "aircraftFamily",
        "route",
    }:
        raise error_type("evaluator must report all required cold-start fields")

    result = dict(evaluation)
    result["cohort_qualification"] = dict(cohort_qualification)
    result["source_contract_sha256"] = str(source_contract_sha256)
    return result


def write_canonical_audit(
    result: Mapping[str, object],
    output_path: str | Path,
    *,
    expected_schema: str,
    error_type: type[Exception],
) -> Path:
    """Validate the embedded digest and atomically write canonical JSON."""

    if result.get("schema_version") != expected_schema:
        raise error_type("result schema does not match the requested audit writer")
    expected = result.get("audit_sha256")
    without_digest = dict(result)
    without_digest.pop("audit_sha256", None)
    if expected != canonical_sha256(without_digest):
        raise error_type("audit digest is inconsistent")
    target = Path(output_path).expanduser().resolve()
    if target.exists() and target.is_dir():
        raise IsADirectoryError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(dict(result), indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


__all__ = [
    "canonical_json",
    "canonical_sha256",
    "exact_join_cohort_qualification",
    "source_code_provenance",
    "validate_retrospective_evaluator_contract",
    "write_canonical_audit",
]
