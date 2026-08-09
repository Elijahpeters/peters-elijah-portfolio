"""Provider-neutral LightGBM candidate fitting for SkyETA global schedules.

This module never downloads data and never marks an artifact as validated.  A
caller must first normalize a licensed provider export, then independently
review geographic coverage and untouched-test results before publication.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict
from typing import Mapping, Sequence

import lightgbm as lgb
import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)

from .calibration import (
    PlattCalibrator,
    calibrate_head_scores,
    fit_platt_calibrator,
)
from .export import MODEL_HEADS, SLICE_DIMENSIONS, build_artifact, build_corpus_binding
from .pipeline import (
    PreparedGlobalData,
    PreparedPartition,
    PreparedRetrospectiveGlobalData,
)


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    seed: int = 42
    n_estimators: int = 700
    learning_rate: float = 0.035
    num_leaves: int = 31
    min_child_samples: int = 150
    early_stopping_rounds: int = 50


def _head_rows(partition: PreparedPartition, head: str):
    features, labels = partition.rows_for_target(head)
    if len(features) < 2 or len(np.unique(labels)) != 2:
        raise ValueError(f"{head} requires at least two rows and both classes")
    return features, labels


def _fit_head(
    train: PreparedPartition,
    tune: PreparedPartition,
    head: str,
    config: TrainingConfig,
) -> lgb.LGBMClassifier:
    x_train, y_train = _head_rows(train, head)
    x_tune, y_tune = _head_rows(tune, head)
    model = lgb.LGBMClassifier(
        objective="binary",
        n_estimators=config.n_estimators,
        learning_rate=config.learning_rate,
        num_leaves=config.num_leaves,
        min_child_samples=config.min_child_samples,
        subsample=0.9,
        subsample_freq=1,
        colsample_bytree=0.9,
        reg_alpha=0.1,
        reg_lambda=1.0,
        random_state=config.seed,
        n_jobs=-1,
        verbosity=-1,
    )
    model.fit(
        x_train,
        y_train,
        eval_set=[(x_tune, y_tune)],
        eval_metric="binary_logloss",
        callbacks=[lgb.early_stopping(config.early_stopping_rounds, verbose=False)],
    )
    return model


def _metrics(
    labels: np.ndarray, probabilities: np.ndarray
) -> dict[str, float | int | None]:
    rows = int(len(labels))
    positives = int(np.sum(labels))
    if rows == 0:
        return {
            "rocAuc": None,
            "averagePrecision": None,
            "brierScore": None,
            "logLoss": None,
            "rows": 0,
            "positives": 0,
            "positiveShare": None,
        }
    has_both_classes = 0 < positives < rows
    return {
        "rocAuc": (
            float(roc_auc_score(labels, probabilities))
            if has_both_classes
            else None
        ),
        "averagePrecision": (
            float(average_precision_score(labels, probabilities))
            if has_both_classes
            else None
        ),
        "brierScore": float(brier_score_loss(labels, probabilities)),
        "logLoss": float(log_loss(labels, probabilities, labels=[0, 1])),
        "rows": rows,
        "positives": positives,
        "positiveShare": positives / rows,
    }


def _support_bucket(count: int) -> str:
    if count == 0:
        return "no_prior_history"
    if count < 100:
        return "1_to_99_prior_legs"
    if count < 1_000:
        return "100_to_999_prior_legs"
    return "1000_plus_prior_legs"


def _season(record) -> str:
    month = record.service_date.month
    if month in {12, 1, 2}:
        northern = "winter"
    elif month in {3, 4, 5}:
        northern = "spring"
    elif month in {6, 7, 8}:
        northern = "summer"
    else:
        northern = "autumn"
    if record.origin_latitude >= 0:
        return northern
    return {
        "winter": "summer",
        "spring": "autumn",
        "summer": "winter",
        "autumn": "spring",
    }[northern]


def _slice_keys(prepared: PreparedGlobalData, index: int) -> dict[str, str]:
    record = prepared.test.records[index]
    snapshot = prepared.history_snapshot
    airport_support = max(
        snapshot.schedule_support("origin", record.origin),
        snapshot.schedule_support("destination", record.destination),
    )
    route_support = snapshot.schedule_support("route", record.route_key)
    return {
        "region": record.origin_region,
        "country": record.origin_country,
        "carrier": record.operating_carrier,
        "airportSize": _support_bucket(airport_support),
        "routeFrequency": _support_bucket(route_support),
        "season": _season(record),
    }


def _slice_evaluation(
    prepared: PreparedGlobalData,
    probabilities: Sequence[Mapping[str, float]],
) -> dict[str, list[dict[str, object]]]:
    if len(probabilities) != len(prepared.test.records):
        raise ValueError("test probabilities must align with untouched-test records")
    grouped: dict[str, dict[str, list[int]]] = {
        dimension: defaultdict(list) for dimension in SLICE_DIMENSIONS
    }
    for index in range(len(prepared.test.records)):
        for dimension, value in _slice_keys(prepared, index).items():
            grouped[dimension][value].append(index)

    result: dict[str, list[dict[str, object]]] = {}
    for dimension in SLICE_DIMENSIONS:
        entries: list[dict[str, object]] = []
        for value, indices in sorted(grouped[dimension].items()):
            head_metrics: dict[str, dict[str, float | int | None]] = {}
            for head in MODEL_HEADS:
                selected = np.asarray(indices, dtype="int64")
                available = prepared.test.target_available[head][selected]
                labels = prepared.test.targets[head][selected][available]
                predicted = np.asarray(
                    [probabilities[index][head] for index in indices],
                    dtype="float64",
                )[available]
                head_metrics[head] = _metrics(labels, predicted)
            entries.append(
                {
                    "value": value,
                    "populationRows": len(indices),
                    "metrics": head_metrics,
                }
            )
        result[dimension] = entries
    return result


def _retrospective_schedule_category(record, field: str) -> str:
    """Return one target-free schedule identity for cold-start auditing."""

    values = {
        "operatingCarrier": record.operating_carrier,
        "origin": record.origin,
        "destination": record.destination,
        "route": record.route_key,
    }
    try:
        return " ".join(str(values[field]).strip().upper().split())
    except KeyError as error:
        raise ValueError(
            f"unsupported retrospective cold-start field: {field}"
        ) from error


def _retrospective_cold_start_evaluation(
    prepared: PreparedRetrospectiveGlobalData,
    probabilities: Sequence[Mapping[str, float]],
) -> dict[str, object]:
    """Measure untouched-test behavior for identities absent from train.

    Membership is derived only from published schedule fields.  In particular,
    neither labels nor the capped one-hot vocabulary decide whether an identity
    is genuinely new: all distinct training identities participate in the
    comparison, even when a low-frequency value was mapped to an unknown model
    column.
    """

    if len(probabilities) != len(prepared.test.records):
        raise ValueError(
            "retrospective probabilities must align with untouched-test records"
        )

    fields = ("operatingCarrier", "origin", "destination", "route")
    training_values = {
        field: {
            _retrospective_schedule_category(record, field)
            for record in prepared.train.records
        }
        for field in fields
    }
    test_values = {
        field: tuple(
            _retrospective_schedule_category(record, field)
            for record in prepared.test.records
        )
        for field in fields
    }

    def metrics_for(indices: list[int]) -> dict[str, dict[str, float | int | None]]:
        selected = np.asarray(indices, dtype="int64")
        result: dict[str, dict[str, float | int | None]] = {}
        for head in MODEL_HEADS:
            if len(selected):
                available = prepared.test.target_available[head][selected]
                labels = prepared.test.targets[head][selected][available]
                predicted = np.asarray(
                    [probabilities[index][head] for index in indices],
                    dtype="float64",
                )[available]
            else:
                labels = np.asarray([], dtype="int8")
                predicted = np.asarray([], dtype="float64")
            result[head] = _metrics(labels, predicted)
        return result

    field_results: dict[str, object] = {}
    unseen_masks: list[list[bool]] = []
    for field in fields:
        train = training_values[field]
        values = test_values[field]
        unseen = [value not in train for value in values]
        unseen_masks.append(unseen)
        seen_indices = [
            index for index, is_unseen in enumerate(unseen) if not is_unseen
        ]
        unseen_indices = [
            index for index, is_unseen in enumerate(unseen) if is_unseen
        ]
        unseen_distinct = sorted(set(values) - train)
        field_results[field] = {
            "trainingDistinctValues": len(train),
            "testDistinctValues": len(set(values)),
            "unseenDistinctValues": unseen_distinct,
            "unseenDistinctValueCount": len(unseen_distinct),
            "seen": {
                "populationRows": len(seen_indices),
                "metrics": metrics_for(seen_indices),
            },
            "unseen": {
                "populationRows": len(unseen_indices),
                "populationShare": (
                    len(unseen_indices) / len(values) if values else 0.0
                ),
                "metrics": metrics_for(unseen_indices),
            },
        }

    unseen_field_counts = [
        sum(mask[index] for mask in unseen_masks)
        for index in range(len(prepared.test.records))
    ]
    any_unseen = [
        index for index, count in enumerate(unseen_field_counts) if count > 0
    ]
    fully_seen = [
        index for index, count in enumerate(unseen_field_counts) if count == 0
    ]
    count_distribution = {
        str(count): unseen_field_counts.count(count)
        for count in range(len(fields) + 1)
    }
    return {
        "membershipBasis": "training_schedule_identity_only",
        "targetDerivedHistoryUsed": False,
        "fields": field_results,
        "combined": {
            "unseenFieldCountDistribution": count_distribution,
            "fullySeen": {
                "populationRows": len(fully_seen),
                "metrics": metrics_for(fully_seen),
            },
            "anyUnseen": {
                "populationRows": len(any_unseen),
                "populationShare": (
                    len(any_unseen) / len(prepared.test.records)
                    if prepared.test.records
                    else 0.0
                ),
                "metrics": metrics_for(any_unseen),
            },
        },
    }


def _partition_population(
    partition: PreparedPartition,
    head: str,
) -> dict[str, int | float]:
    """Return JSON-safe label counts without consulting flight records."""

    available = partition.target_available[head]
    labels = partition.targets[head][available]
    rows = int(len(labels))
    positives = int(np.sum(labels))
    return {
        "rows": rows,
        "positives": positives,
        "positiveShare": positives / rows if rows else 0.0,
    }


def _validate_retrospective_training_input(
    prepared: PreparedRetrospectiveGlobalData,
) -> None:
    """Fail closed unless the dedicated target-history-free contract is intact."""

    if prepared.publishable is not False:
        raise ValueError("retrospective prepared data must be non-publishable")
    if prepared.target_derived_history_features_allowed is not False:
        raise ValueError(
            "retrospective prepared data must prohibit target-derived history"
        )
    audit = prepared.retrospective_audit
    if audit.evaluation_kind != "retrospective_temporal_evaluation":
        raise ValueError("retrospective evaluation kind is invalid")
    if audit.point_in_time_backtest is not False:
        raise ValueError(
            "retrospective evaluation cannot claim a point-in-time backtest"
        )
    if audit.target_derived_history_features_allowed is not False:
        raise ValueError("retrospective audit must prohibit target-derived history")

    feature_names = prepared.train.feature_names
    if not feature_names:
        raise ValueError("retrospective evaluation requires prepared features")
    if any(name.startswith("history_") for name in feature_names):
        raise ValueError("retrospective evaluation cannot use history features")
    for name, partition in (
        ("train", prepared.train),
        ("tune", prepared.tune),
        ("calibration", prepared.calibration),
        ("test", prepared.test),
    ):
        if partition.feature_names != feature_names:
            raise ValueError(f"retrospective {name} feature contract is misaligned")
        if partition.matrix.ndim != 2:
            raise ValueError(f"retrospective {name} matrix must be two-dimensional")
        if partition.matrix.shape[1] != len(feature_names):
            raise ValueError(f"retrospective {name} matrix shape is misaligned")
        if not np.isfinite(partition.matrix).all():
            raise ValueError(f"retrospective {name} matrix contains non-finite values")
        if set(partition.targets) != set(MODEL_HEADS) or set(
            partition.target_available
        ) != set(MODEL_HEADS):
            raise ValueError(
                f"retrospective {name} must define every model head exactly once"
            )
        rows = partition.matrix.shape[0]
        for head in MODEL_HEADS:
            target = partition.targets[head]
            available = partition.target_available[head]
            if target.shape != (rows,) or available.shape != (rows,):
                raise ValueError(
                    f"retrospective {name} {head} targets are misaligned"
                )


def evaluate_retrospective_temporal_model(
    prepared: PreparedRetrospectiveGlobalData,
    *,
    config: TrainingConfig = TrainingConfig(),
) -> dict[str, object]:
    """Run a disclosed retrospective LightGBM experiment without an artifact.

    The function consumes the four matrices produced by
    :func:`prepare_retrospective_global_data` as-is.  It has no history encoder,
    corpus binding, export, or publication path: train labels fit each head,
    tune labels are used only for early stopping, calibration labels fit the
    Platt sigmoid, and the final metrics use only the temporal test window.
    """

    _validate_retrospective_training_input(prepared)

    models: dict[str, lgb.LGBMClassifier] = {}
    calibrators: dict[str, PlattCalibrator] = {}
    for head in MODEL_HEADS:
        model = _fit_head(prepared.train, prepared.tune, head, config)
        x_calibration, y_calibration = _head_rows(prepared.calibration, head)
        calibrator = fit_platt_calibrator(
            model.booster_.predict(x_calibration, raw_score=True),
            y_calibration,
        )
        models[head] = model
        calibrators[head] = calibrator

    raw_test_scores = {
        head: models[head].booster_.predict(
            prepared.test.matrix,
            raw_score=True,
        )
        for head in MODEL_HEADS
    }
    test_probabilities = [
        calibrate_head_scores(
            {head: float(raw_test_scores[head][index]) for head in MODEL_HEADS},
            calibrators,
        )
        for index in range(len(prepared.test.matrix))
    ]

    test_metrics: dict[str, dict[str, float | int | None]] = {}
    model_diagnostics: dict[str, dict[str, object]] = {}
    for head in MODEL_HEADS:
        mask = prepared.test.target_available[head]
        labels = prepared.test.targets[head][mask]
        probability = np.asarray(
            [
                value[head]
                for value, keep in zip(test_probabilities, mask, strict=True)
                if keep
            ],
            dtype="float64",
        )
        test_metrics[head] = _metrics(labels, probability)

        model = models[head]
        booster = model.booster_
        feature_gain = booster.feature_importance(importance_type="gain")
        ranked_gain = sorted(
            (
                {"feature": feature, "gain": float(gain)}
                for feature, gain in zip(
                    prepared.train.feature_names,
                    feature_gain,
                    strict=True,
                )
            ),
            key=lambda entry: (-entry["gain"], entry["feature"]),
        )
        best_score = getattr(model, "best_score_", {})
        tune_score = best_score.get("valid_0", {}).get("binary_logloss")
        model_diagnostics[head] = {
            "bestIteration": int(model.best_iteration_ or booster.current_iteration()),
            "treeCount": int(booster.num_trees()),
            "featureCount": len(prepared.train.feature_names),
            "tuneBinaryLogLossAtBestIteration": (
                float(tune_score) if tune_score is not None else None
            ),
            "calibration": calibrators[head].as_dict(),
            "partitionPopulations": {
                name: _partition_population(partition, head)
                for name, partition in (
                    ("train", prepared.train),
                    ("tune", prepared.tune),
                    ("calibration", prepared.calibration),
                    ("test", prepared.test),
                )
            },
            "featureImportanceGain": ranked_gain,
        }

    return {
        "evaluation_kind": "retrospective_temporal_evaluation",
        "point_in_time_backtest": False,
        "publishable": False,
        "target_derived_history_features_used": False,
        "temporal_audit": prepared.retrospective_audit.to_dict(),
        "training_configuration": {
            "seed": config.seed,
            "n_estimators": config.n_estimators,
            "learning_rate": config.learning_rate,
            "num_leaves": config.num_leaves,
            "min_child_samples": config.min_child_samples,
            "early_stopping_rounds": config.early_stopping_rounds,
        },
        "feature_contract": {
            "feature_count": len(prepared.train.feature_names),
            "feature_names": list(prepared.train.feature_names),
            "precomputed_matrices_only": True,
            "target_derived_history_features": False,
        },
        "test_metrics": test_metrics,
        "cold_start_diagnostics": _retrospective_cold_start_evaluation(
            prepared,
            test_probabilities,
        ),
        "model_diagnostics": model_diagnostics,
    }


def fit_candidate_artifact(
    prepared: PreparedGlobalData,
    *,
    data_sources: Sequence[Mapping[str, object]],
    coverage_summary: Mapping,
    config: TrainingConfig = TrainingConfig(),
) -> dict:
    """Fit all heads and return a non-publishable candidate artifact."""

    if not data_sources:
        raise ValueError("at least one licensed data source must be documented")
    models: dict[str, lgb.LGBMClassifier] = {}
    calibrators: dict[str, PlattCalibrator] = {}
    for head in MODEL_HEADS:
        model = _fit_head(prepared.train, prepared.tune, head, config)
        x_calibration, y_calibration = _head_rows(prepared.calibration, head)
        calibrator = fit_platt_calibrator(
            model.booster_.predict(x_calibration, raw_score=True), y_calibration
        )
        models[head] = model
        calibrators[head] = calibrator

    boosters = {head: models[head].booster_.dump_model() for head in MODEL_HEADS}
    raw_test_scores = {
        head: models[head].booster_.predict(
            prepared.test.matrix, raw_score=True
        )
        for head in MODEL_HEADS
    }
    test_probabilities = [
        calibrate_head_scores(
            {head: float(raw_test_scores[head][index]) for head in MODEL_HEADS},
            calibrators,
        )
        for index in range(len(prepared.test.matrix))
    ]

    metrics: dict[str, dict[str, float | int]] = {}
    for head in MODEL_HEADS:
        mask = prepared.test.target_available[head]
        labels = prepared.test.targets[head][mask]
        probability = np.asarray(
            [
                value[head]
                for value, keep in zip(test_probabilities, mask, strict=True)
                if keep
            ],
            dtype="float64",
        )
        metrics[head] = _metrics(labels, probability)

    model_card = {
        "modelName": "SkyETA global schedule candidate",
        "dataSources": [dict(source) for source in data_sources],
        "dataCoverage": {
            **dict(coverage_summary),
            # A separate release review must change this after inspecting
            # geography and cold-start slices; fitting alone never passes it.
            "globalReleaseGatePassed": False,
        },
        "evaluation": {
            "untouchedTest": True,
            "testMetrics": metrics,
            "testPopulationRows": len(prepared.test.records),
            "sliceMetrics": _slice_evaluation(prepared, test_probabilities),
            "tuneUsedFor": "LightGBM early stopping only",
            "calibrationUsedFor": "Platt calibration only",
        },
        "limitations": [
            "Schedule-only probabilities are estimates, not live flight status.",
            (
                "A candidate must pass geographic and cold-start release review "
                "before publication."
            ),
        ],
    }
    parity_rows = prepared.test.matrix[: min(64, len(prepared.test.matrix))]
    return build_artifact(
        feature_names=prepared.train.feature_names,
        boosters=boosters,
        calibrators=calibrators,
        history_snapshot=prepared.history_snapshot,
        model_card=model_card,
        parity_feature_rows=parity_rows,
        native_parity_probabilities=test_probabilities[: len(parity_rows)],
        artifact_status="candidate",
        corpus_binding=build_corpus_binding(prepared.dedupe.records),
    )
