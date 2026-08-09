"""Provider-neutral LightGBM candidate fitting for SkyETA global schedules.

This module never downloads data and never marks an artifact as validated.  A
caller must first normalize a licensed provider export, then independently
review geographic coverage and untouched-test results before publication.
"""

from __future__ import annotations

import platform
from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

import lightgbm as lgb
import numpy as np
import scipy
from scipy import sparse
from scipy.special import expit
import sklearn
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


_RETROSPECTIVE_WORK_CHUNK_ROWS = 65_536
_MISSING_SCHEDULE_CATEGORY = "__MISSING__"
_RETROSPECTIVE_COLD_START_FIELDS = (
    "operatingCarrier",
    "origin",
    "destination",
    "route",
    "aircraftFamily",
)


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    seed: int = 42
    n_estimators: int = 700
    learning_rate: float = 0.035
    num_leaves: int = 31
    min_child_samples: int = 150
    early_stopping_rounds: int = 50
    num_threads: int = 1

    def __post_init__(self) -> None:
        if (
            isinstance(self.num_threads, bool)
            or not isinstance(self.num_threads, int)
            or self.num_threads <= 0
        ):
            raise ValueError("num_threads must be a positive integer")


def _lightgbm_parameters(config: TrainingConfig) -> dict[str, object]:
    """Return the exact deterministic sklearn-wrapper parameter contract."""

    return {
        "objective": "binary",
        "n_estimators": config.n_estimators,
        "learning_rate": config.learning_rate,
        "num_leaves": config.num_leaves,
        "min_child_samples": config.min_child_samples,
        "subsample": 0.9,
        "subsample_freq": 1,
        "colsample_bytree": 0.9,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "random_state": config.seed,
        "bagging_seed": config.seed,
        "feature_fraction_seed": config.seed,
        "data_random_seed": config.seed,
        "deterministic": True,
        "force_col_wise": True,
        "device_type": "cpu",
        "n_jobs": config.num_threads,
        "verbosity": -1,
    }


def _runtime_provenance(config: TrainingConfig) -> dict[str, object]:
    return {
        "deterministic": True,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine() or "unknown",
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "scikit_learn": sklearn.__version__,
        "lightgbm": lgb.__version__,
        "deterministic_parameters": {
            key: value
            for key, value in _lightgbm_parameters(config).items()
            if key
            in {
                "random_state",
                "bagging_seed",
                "feature_fraction_seed",
                "data_random_seed",
                "deterministic",
                "force_col_wise",
                "device_type",
                "n_jobs",
            }
        },
    }


def _head_rows(partition: PreparedPartition, head: str):
    features, labels = partition.rows_for_target(head)
    if features.shape[0] < 2 or len(np.unique(labels)) != 2:
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
    model = lgb.LGBMClassifier(**_lightgbm_parameters(config))
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
        "aircraftFamily": record.aircraft_family,
    }
    try:
        value = values[field]
    except KeyError as error:
        raise ValueError(
            f"unsupported retrospective cold-start field: {field}"
        ) from error
    if value is None:
        return _MISSING_SCHEDULE_CATEGORY
    normalized = " ".join(str(value).strip().upper().split())
    return normalized or _MISSING_SCHEDULE_CATEGORY


def _validate_retrospective_probability_matrix(
    prepared: PreparedRetrospectiveGlobalData,
    probabilities: np.ndarray,
) -> None:
    expected_shape = (prepared.test.matrix.shape[0], len(MODEL_HEADS))
    if (
        not isinstance(probabilities, np.ndarray)
        or probabilities.shape != expected_shape
    ):
        raise ValueError(
            "retrospective probabilities must be a numeric matrix aligned "
            "with untouched-test records and MODEL_HEADS"
        )
    if probabilities.dtype.kind not in {"f", "i", "u"}:
        raise ValueError("retrospective probabilities must be numeric")
    if not np.isfinite(probabilities).all() or np.any(
        (probabilities < 0.0) | (probabilities > 1.0)
    ):
        raise ValueError("retrospective probabilities must lie between zero and one")


def _retrospective_metric_vectors(
    prepared: PreparedRetrospectiveGlobalData,
    probabilities: np.ndarray,
    head_index: int,
    population_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    head = MODEL_HEADS[head_index]
    available = prepared.test.target_available[head]
    if population_mask is None:
        selected = available
    else:
        if (
            population_mask.shape != available.shape
            or population_mask.dtype.kind != "b"
        ):
            raise ValueError("retrospective population mask is misaligned")
        selected = np.logical_and(population_mask, available)
    if bool(np.all(selected)):
        return prepared.test.targets[head], probabilities[:, head_index]
    if not bool(np.any(selected)):
        return (
            np.asarray([], dtype="int8"),
            np.asarray([], dtype="float64"),
        )
    return (
        prepared.test.targets[head][selected],
        probabilities[selected, head_index],
    )


def _retrospective_cold_start_evaluation(
    prepared: PreparedRetrospectiveGlobalData,
    probabilities: np.ndarray,
) -> dict[str, object]:
    """Measure untouched-test behavior for identities absent from train.

    Membership is derived only from published schedule fields.  In particular,
    neither labels nor the capped one-hot vocabulary decide whether an identity
    is genuinely new: all distinct training identities participate in the
    comparison, even when a low-frequency value was mapped to an unknown model
    column.
    """

    _validate_retrospective_probability_matrix(prepared, probabilities)

    fields = _RETROSPECTIVE_COLD_START_FIELDS
    row_count = prepared.test.matrix.shape[0]

    def metrics_for(
        population_mask: np.ndarray,
    ) -> dict[str, dict[str, float | int | None]]:
        result: dict[str, dict[str, float | int | None]] = {}
        for head_index, head in enumerate(MODEL_HEADS):
            labels, predicted = _retrospective_metric_vectors(
                prepared,
                probabilities,
                head_index,
                population_mask,
            )
            result[head] = _metrics(labels, predicted)
        return result

    field_results: dict[str, object] = {}
    unseen_field_counts = np.zeros(row_count, dtype=np.uint8)
    for field in fields:
        train = {
            _retrospective_schedule_category(record, field)
            for record in prepared.train.records
        }
        unseen = np.empty(row_count, dtype=np.bool_)
        test_distinct: set[str] = set()
        unseen_distinct_values: set[str] = set()
        for index, record in enumerate(prepared.test.records):
            value = _retrospective_schedule_category(record, field)
            test_distinct.add(value)
            is_unseen = value not in train
            unseen[index] = is_unseen
            if is_unseen:
                unseen_distinct_values.add(value)
        unseen_field_counts += unseen
        seen = np.logical_not(unseen)
        unseen_rows = int(np.count_nonzero(unseen))
        seen_rows = row_count - unseen_rows
        unseen_distinct = sorted(unseen_distinct_values)
        field_results[field] = {
            "trainingDistinctValues": len(train),
            "testDistinctValues": len(test_distinct),
            "unseenDistinctValues": unseen_distinct,
            "unseenDistinctValueCount": len(unseen_distinct),
            "seen": {
                "populationRows": seen_rows,
                "metrics": metrics_for(seen),
            },
            "unseen": {
                "populationRows": unseen_rows,
                "populationShare": (
                    unseen_rows / row_count if row_count else 0.0
                ),
                "metrics": metrics_for(unseen),
            },
        }

    any_unseen = unseen_field_counts > 0
    fully_seen = np.logical_not(any_unseen)
    any_unseen_rows = int(np.count_nonzero(any_unseen))
    fully_seen_rows = row_count - any_unseen_rows
    distribution = np.bincount(
        unseen_field_counts,
        minlength=len(fields) + 1,
    )
    count_distribution = {
        str(count): int(distribution[count])
        for count in range(len(fields) + 1)
    }
    return {
        "membershipBasis": "training_schedule_identity_only",
        "targetDerivedHistoryUsed": False,
        "fields": field_results,
        "combined": {
            "unseenFieldCountDistribution": count_distribution,
            "fullySeen": {
                "populationRows": fully_seen_rows,
                "metrics": metrics_for(fully_seen),
            },
            "anyUnseen": {
                "populationRows": any_unseen_rows,
                "populationShare": (
                    any_unseen_rows / row_count if row_count else 0.0
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


def _matrix_is_finite(matrix: np.ndarray | sparse.spmatrix) -> bool:
    values = matrix.data if sparse.issparse(matrix) else matrix
    return bool(np.isfinite(values).all())


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
        if not sparse.isspmatrix_csr(partition.matrix):
            raise ValueError(f"retrospective {name} matrix must use CSR storage")
        if partition.matrix.ndim != 2:
            raise ValueError(f"retrospective {name} matrix must be two-dimensional")
        if partition.matrix.shape[1] != len(feature_names):
            raise ValueError(f"retrospective {name} matrix shape is misaligned")
        if not _matrix_is_finite(partition.matrix):
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


def _masked_csr_allocation_audit(
    partition: PreparedPartition,
    head: str,
) -> dict[str, int | bool]:
    """Estimate one target selection without materializing its CSR subset."""

    matrix = partition.matrix
    if not sparse.isspmatrix_csr(matrix):
        raise ValueError("retrospective evaluation memory audit requires CSR matrices")
    available = partition.target_available[head]
    selected_rows = int(np.count_nonzero(available))
    all_rows = selected_rows == matrix.shape[0]
    if all_rows:
        return {
            "selected_rows": selected_rows,
            "csr_copy_required": False,
            "csr_copy_bytes": 0,
            "label_copy_bytes": 0,
            "selection_workspace_bytes": 0,
        }

    selected_nnz = 0
    for start in range(0, matrix.shape[0], _RETROSPECTIVE_WORK_CHUNK_ROWS):
        end = min(start + _RETROSPECTIVE_WORK_CHUNK_ROWS, matrix.shape[0])
        row_nnz = np.subtract(
            matrix.indptr[start + 1 : end + 1],
            matrix.indptr[start:end],
        )
        selected_nnz += int(np.sum(row_nnz, where=available[start:end]))
    csr_copy_bytes = (
        selected_nnz * (matrix.data.dtype.itemsize + matrix.indices.dtype.itemsize)
        + (selected_rows + 1) * matrix.indptr.dtype.itemsize
    )
    return {
        "selected_rows": selected_rows,
        "csr_copy_required": True,
        "csr_copy_bytes": int(csr_copy_bytes),
        "label_copy_bytes": int(
            selected_rows * partition.targets[head].dtype.itemsize
        ),
        # SciPy may normalize a boolean selector to platform-sized row indices
        # while creating the subset.  Reserve that transient explicitly.
        "selection_workspace_bytes": int(
            selected_rows * np.dtype(np.intp).itemsize
        ),
    }


def _retrospective_evaluation_memory_audit(
    prepared: PreparedRetrospectiveGlobalData,
    config: TrainingConfig,
) -> dict[str, object]:
    """Bound evaluator-owned allocations before fitting the first model.

    The retained feature matrices have their own preparation-time guard.  This
    audit covers target-specific CSR copies, calibrated test probabilities,
    numeric metrics/cold-start work arrays, and conservative LightGBM dataset,
    histogram, and tree-structure reserves.  Its scan uses a fixed-size chunk
    and does not construct a target subset.
    """

    partitions = {
        "train": prepared.train,
        "tune": prepared.tune,
        "calibration": prepared.calibration,
        "test": prepared.test,
    }
    selections = {
        name: {
            head: _masked_csr_allocation_audit(partition, head)
            for head in MODEL_HEADS
        }
        for name, partition in partitions.items()
    }

    def retained_selection_bytes(name: str, head: str) -> int:
        entry = selections[name][head]
        return int(entry["csr_copy_bytes"]) + int(entry["label_copy_bytes"])

    def selection_creation_peak(name: str, head: str) -> int:
        entry = selections[name][head]
        return retained_selection_bytes(name, head) + int(
            entry["selection_workspace_bytes"]
        )

    fit_subset_peak = 0
    calibration_subset_peak = 0
    for head in MODEL_HEADS:
        train_retained = retained_selection_bytes("train", head)
        fit_subset_peak = max(
            fit_subset_peak,
            selection_creation_peak("train", head),
            train_retained + selection_creation_peak("tune", head),
        )
        calibration_retained = retained_selection_bytes("calibration", head)
        calibration_rows = int(selections["calibration"][head]["selected_rows"])
        calibration_subset_peak = max(
            calibration_subset_peak,
            selection_creation_peak("calibration", head),
            calibration_retained + calibration_rows * np.dtype("float64").itemsize,
        )

    test_rows = prepared.test.matrix.shape[0]
    head_count = len(MODEL_HEADS)
    float64_bytes = np.dtype("float64").itemsize
    probability_matrix_bytes = test_rows * head_count * float64_bytes
    raw_score_vector_bytes = test_rows * float64_bytes
    projection_rows = min(test_rows, _RETROSPECTIVE_WORK_CHUNK_ROWS)
    # Boolean advanced indexing can briefly retain several selected float
    # vectors in addition to masks.  Reserve 48 bytes per bounded chunk row;
    # the calibrated matrix itself is accounted separately.
    projection_workspace_bytes = projection_rows * 48

    # Metrics may retain probability/label copies, ordering vectors, threshold
    # arrays, cumulative counts, and sklearn working arrays.  Reserve 128
    # bytes per row rather than relying on one library version's observed peak.
    metric_workspace_bytes = test_rows * 128
    cold_start_workspace_bytes = test_rows * (
        np.dtype(np.uint8).itemsize
        + 2 * np.dtype(np.bool_).itemsize
    ) + metric_workspace_bytes
    train_rows = prepared.train.matrix.shape[0]
    # Each cold-start field is processed sequentially, so current-field sets
    # scale with train + test.  The returned unseen-identity lists accumulate
    # across fields.  These per-row reserves cover Python strings, set/list
    # slots, and allocator overhead without constructing identities here.
    cold_start_identity_set_reserve_bytes = (
        train_rows * 192 + test_rows * 256
    )
    cold_start_retained_identity_reserve_bytes = (
        len(_RETROSPECTIVE_COLD_START_FIELDS) * test_rows * 128
    )

    feature_count = prepared.train.matrix.shape[1]
    train_tune_nnz = prepared.train.matrix.nnz + prepared.tune.matrix.nnz
    lightgbm_dataset_reserve_bytes = int(train_tune_nnz * 12)
    lightgbm_histogram_reserve_bytes = int(
        feature_count * 255 * 2 * float64_bytes * config.num_threads
    )
    lightgbm_tree_structure_reserve_bytes = int(
        head_count
        * config.n_estimators
        * max(1, 2 * config.num_leaves - 1)
        * 128
    )
    feature_diagnostics_reserve_bytes = int(head_count * feature_count * 256)
    model_reserve_bytes = (
        lightgbm_dataset_reserve_bytes
        + lightgbm_histogram_reserve_bytes
        + lightgbm_tree_structure_reserve_bytes
    )

    # The implementation explicitly releases loop temporaries, while these
    # cross-iteration reserves keep the guard safe even if a future refactor
    # extends their lifetime by one iteration.
    calibration_overlap_reserve_bytes = calibration_subset_peak
    raw_score_overlap_reserve_bytes = 2 * raw_score_vector_bytes
    stage_estimates = {
        "model_fit": fit_subset_peak
        + calibration_overlap_reserve_bytes
        + model_reserve_bytes,
        "calibration": calibration_subset_peak + model_reserve_bytes,
        "test_probability_generation": model_reserve_bytes
        + probability_matrix_bytes
        + raw_score_overlap_reserve_bytes
        + projection_workspace_bytes,
        "test_metrics": model_reserve_bytes
        + probability_matrix_bytes
        + metric_workspace_bytes,
        "cold_start_diagnostics": model_reserve_bytes
        + probability_matrix_bytes
        + cold_start_workspace_bytes
        + cold_start_identity_set_reserve_bytes
        + cold_start_retained_identity_reserve_bytes
        + feature_diagnostics_reserve_bytes,
    }
    estimated_peak = max(stage_estimates.values(), default=0)
    limit = prepared.matrix_audit.limits.max_evaluation_additional_bytes
    audit: dict[str, object] = {
        "guard_applied_before_model_fit": True,
        "scope": "additional_retrospective_evaluator_working_memory",
        "estimate_kind": (
            "conservative_preflight_estimate_not_native_allocator_hard_cap"
        ),
        "lightgbm_native_allocator_hard_cap": False,
        "head_order": list(MODEL_HEADS),
        "test_rows": test_rows,
        "head_count": head_count,
        "probability_storage": "numpy_float64_matrix",
        "probability_matrix_bytes": probability_matrix_bytes,
        "maximum_raw_score_vector_bytes": raw_score_vector_bytes,
        "maximum_fit_subset_peak_bytes": fit_subset_peak,
        "maximum_calibration_subset_peak_bytes": calibration_subset_peak,
        "cross_iteration_calibration_overlap_reserve_bytes": (
            calibration_overlap_reserve_bytes
        ),
        "raw_score_overlap_reserve_bytes": raw_score_overlap_reserve_bytes,
        "projection_chunk_rows": _RETROSPECTIVE_WORK_CHUNK_ROWS,
        "projection_workspace_bytes": projection_workspace_bytes,
        "metric_workspace_reserve_bytes": metric_workspace_bytes,
        "cold_start_workspace_reserve_bytes": cold_start_workspace_bytes,
        "cold_start_identity_set_reserve_bytes": (
            cold_start_identity_set_reserve_bytes
        ),
        "cold_start_retained_identity_reserve_bytes": (
            cold_start_retained_identity_reserve_bytes
        ),
        "lightgbm_reserves": {
            "dataset_bytes": lightgbm_dataset_reserve_bytes,
            "histogram_bytes": lightgbm_histogram_reserve_bytes,
            "tree_structure_bytes": lightgbm_tree_structure_reserve_bytes,
        },
        "feature_diagnostics_reserve_bytes": feature_diagnostics_reserve_bytes,
        "target_selections": selections,
        "stage_estimated_additional_bytes": stage_estimates,
        "estimated_peak_additional_bytes": estimated_peak,
        "limit_bytes": limit,
    }
    if estimated_peak > limit:
        raise MemoryError(
            "retrospective evaluation estimated additional peak "
            f"{estimated_peak} bytes exceeds limit {limit} before model fitting"
        )
    return audit


def _project_probability_matrix_in_place(probabilities: np.ndarray) -> None:
    """Apply the two ordering projections without per-row Python objects."""

    arrival_columns = tuple(MODEL_HEADS.index(head) for head in MODEL_HEADS[:3])
    disrupted_column = MODEL_HEADS.index("disrupted")
    cancelled_column = MODEL_HEADS.index("cancelled")
    for start in range(0, probabilities.shape[0], _RETROSPECTIVE_WORK_CHUNK_ROWS):
        end = min(start + _RETROSPECTIVE_WORK_CHUNK_ROWS, probabilities.shape[0])
        a = probabilities[start:end, arrival_columns[0]]
        b = probabilities[start:end, arrival_columns[1]]
        c = probabilities[start:end, arrival_columns[2]]

        left = a < b
        mean = (a + b) * 0.5
        pool_all = np.logical_and(left, mean < c)
        if bool(np.any(pool_all)):
            all_mean = (a[pool_all] + b[pool_all] + c[pool_all]) / 3.0
            a[pool_all] = all_mean
            b[pool_all] = all_mean
            c[pool_all] = all_mean
        pair = np.logical_and(left, np.logical_not(pool_all))
        if bool(np.any(pair)):
            a[pair] = mean[pair]
            b[pair] = mean[pair]

        right = np.logical_and(np.logical_not(left), b < c)
        mean = (b + c) * 0.5
        pool_all = np.logical_and(right, a < mean)
        if bool(np.any(pool_all)):
            all_mean = (a[pool_all] + b[pool_all] + c[pool_all]) / 3.0
            a[pool_all] = all_mean
            b[pool_all] = all_mean
            c[pool_all] = all_mean
        pair = np.logical_and(right, np.logical_not(pool_all))
        if bool(np.any(pair)):
            b[pair] = mean[pair]
            c[pair] = mean[pair]

        disrupted = probabilities[start:end, disrupted_column]
        cancelled = probabilities[start:end, cancelled_column]
        violation = disrupted < cancelled
        if bool(np.any(violation)):
            mean = (disrupted[violation] + cancelled[violation]) * 0.5
            disrupted[violation] = mean
            cancelled[violation] = mean


def _retrospective_probability_matrix(
    test_matrix: sparse.csr_matrix,
    models: Mapping[str, lgb.LGBMClassifier],
    calibrators: Mapping[str, PlattCalibrator],
) -> np.ndarray:
    """Predict one head at a time into a compact numeric test matrix."""

    probabilities = np.empty(
        (test_matrix.shape[0], len(MODEL_HEADS)),
        dtype=np.float64,
    )
    for head_index, head in enumerate(MODEL_HEADS):
        raw_scores = np.asarray(
            models[head].booster_.predict(test_matrix, raw_score=True),
            dtype=np.float64,
        )
        if raw_scores.shape != (test_matrix.shape[0],):
            raise ValueError(f"{head} returned a misaligned test score vector")
        column = probabilities[:, head_index]
        np.multiply(raw_scores, calibrators[head].slope, out=column)
        np.add(column, calibrators[head].intercept, out=column)
        expit(column, out=column)
        # Keep the preflight lifetime model exact: no prior raw-score vector
        # or column view may overlap the next head or the projection stage.
        del raw_scores, column
    _project_probability_matrix_in_place(probabilities)
    if not np.isfinite(probabilities).all():
        raise ValueError("retrospective calibrated probabilities are non-finite")
    return probabilities


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
    evaluation_memory_audit = _retrospective_evaluation_memory_audit(
        prepared,
        config,
    )

    models: dict[str, lgb.LGBMClassifier] = {}
    calibrators: dict[str, PlattCalibrator] = {}
    for head in MODEL_HEADS:
        model = _fit_head(prepared.train, prepared.tune, head, config)
        x_calibration, y_calibration = _head_rows(prepared.calibration, head)
        calibrator = fit_platt_calibrator(
            model.booster_.predict(x_calibration, raw_score=True),
            y_calibration,
        )
        # Partial-label calibration creates a CSR/label subset.  Release it
        # before fitting the next head, as assumed by the memory-stage audit.
        del x_calibration, y_calibration
        models[head] = model
        calibrators[head] = calibrator

    test_probabilities = _retrospective_probability_matrix(
        prepared.test.matrix,
        models,
        calibrators,
    )

    test_metrics: dict[str, dict[str, float | int | None]] = {}
    model_diagnostics: dict[str, dict[str, object]] = {}
    for head_index, head in enumerate(MODEL_HEADS):
        labels, probability = _retrospective_metric_vectors(
            prepared,
            test_probabilities,
            head_index,
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
            "num_threads": config.num_threads,
        },
        "runtime_provenance": _runtime_provenance(config),
        "evaluation_memory_audit": evaluation_memory_audit,
        "feature_contract": {
            "feature_count": len(prepared.train.feature_names),
            "feature_names": list(prepared.train.feature_names),
            "precomputed_matrices_only": True,
            "target_derived_history_features": False,
            "matrix_storage": prepared.matrix_audit.to_dict(),
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
        for index in range(prepared.test.matrix.shape[0])
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
    parity_rows = prepared.test.matrix[: min(64, prepared.test.matrix.shape[0])]
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
