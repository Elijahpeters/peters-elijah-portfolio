"""End-to-end preparation of leakage-safe global model matrices."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from scipy import sparse

from .dedupe import DedupeResult, deduplicate_records
from .encodings import EncodingSnapshot, PastOnlyHierarchicalEncoder
from .features import assemble_feature_row
from .labels import TARGET_NAMES, derive_labels
from .schedule_categories import (
    SCHEDULE_CATEGORY_FEATURE_PREFIX,
    ScheduleCategoricalFeatureConfig,
    ScheduleCategoricalSnapshot,
    TrainingOnlyScheduleCategoricalTransformer,
)
from .schema import GlobalFlightRecord
from .splits import (
    RETROSPECTIVE_EVALUATION_HORIZON,
    ChronologicalBoundaries,
    ChronologicalSplit,
    RetrospectiveTemporalEvaluationAudit,
    RetrospectiveTemporalEvaluationSplit,
    chronological_split,
    retrospective_temporal_evaluation_split,
)


@dataclass(frozen=True, slots=True)
class PreparedPartition:
    records: tuple[GlobalFlightRecord, ...]
    feature_names: tuple[str, ...]
    matrix: np.ndarray | sparse.csr_matrix
    targets: dict[str, np.ndarray]
    target_available: dict[str, np.ndarray]

    def rows_for_target(
        self, target: str
    ) -> tuple[np.ndarray | sparse.csr_matrix, np.ndarray]:
        if target not in self.targets:
            raise KeyError(target)
        available = self.target_available[target]
        # SciPy's boolean row indexing always materializes a new CSR matrix.
        # Most cancellation/disruption corpora have labels for every row, so
        # preserve the original matrix and target vector in that common case.
        if bool(np.all(available)):
            return self.matrix, self.targets[target]
        return self.matrix[available], self.targets[target][available]


@dataclass(frozen=True, slots=True)
class RetrospectiveMatrixMemoryLimits:
    """Fail-before-allocation limits for retrospective feature matrices.

    The partition peak estimate includes the temporary base and categorical
    CSR inputs plus their combined CSR output.  The total estimate covers all
    four combined matrices retained by :class:`PreparedRetrospectiveGlobalData`.
    """

    max_partition_peak_bytes: int = 768 * 1024 * 1024
    max_total_csr_bytes: int = 1536 * 1024 * 1024
    max_evaluation_additional_bytes: int = 1024 * 1024 * 1024

    def __post_init__(self) -> None:
        for name, value in (
            ("max_partition_peak_bytes", self.max_partition_peak_bytes),
            ("max_total_csr_bytes", self.max_total_csr_bytes),
            (
                "max_evaluation_additional_bytes",
                self.max_evaluation_additional_bytes,
            ),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_partition_peak_bytes": self.max_partition_peak_bytes,
            "max_total_csr_bytes": self.max_total_csr_bytes,
            "max_evaluation_additional_bytes": (
                self.max_evaluation_additional_bytes
            ),
        }


@dataclass(frozen=True, slots=True)
class MatrixStorageAudit:
    rows: int
    columns: int
    nnz: int
    data_bytes: int
    indices_bytes: int
    indptr_bytes: int
    estimated_csr_bytes: int
    dense_equivalent_bytes: int
    density: float
    guard_estimated_peak_bytes: int

    def to_dict(self) -> dict[str, int | float]:
        return {
            "rows": self.rows,
            "columns": self.columns,
            "nnz": self.nnz,
            "data_bytes": self.data_bytes,
            "indices_bytes": self.indices_bytes,
            "indptr_bytes": self.indptr_bytes,
            "estimated_csr_bytes": self.estimated_csr_bytes,
            "dense_equivalent_bytes": self.dense_equivalent_bytes,
            "density": self.density,
            "guard_estimated_peak_bytes": self.guard_estimated_peak_bytes,
        }


@dataclass(frozen=True, slots=True)
class RetrospectiveMatrixAudit:
    storage_format: str
    dtype: str
    partitions: tuple[tuple[str, MatrixStorageAudit], ...]
    total_nnz: int
    total_estimated_csr_bytes: int
    total_dense_equivalent_bytes: int
    limits: RetrospectiveMatrixMemoryLimits

    def to_dict(self) -> dict[str, object]:
        return {
            "storage_format": self.storage_format,
            "dtype": self.dtype,
            "partitions": {
                name: audit.to_dict() for name, audit in self.partitions
            },
            "total_nnz": self.total_nnz,
            "total_estimated_csr_bytes": self.total_estimated_csr_bytes,
            "total_dense_equivalent_bytes": self.total_dense_equivalent_bytes,
            "limits": self.limits.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class _SparsePartitionPlan:
    rows: int
    columns: int
    base_max_nnz: int
    categorical_max_nnz: int
    combined_max_nnz: int
    estimated_csr_bytes: int
    dense_equivalent_bytes: int
    estimated_peak_bytes: int


@dataclass(frozen=True, slots=True)
class PreparedGlobalData:
    dedupe: DedupeResult
    split: ChronologicalSplit
    history_snapshot: EncodingSnapshot
    train: PreparedPartition
    tune: PreparedPartition
    calibration: PreparedPartition
    test: PreparedPartition


@dataclass(frozen=True, slots=True)
class PreparedRetrospectiveGlobalData:
    """Base-feature matrices for a disclosed retrospective experiment only.

    Unlike :class:`PreparedGlobalData`, this type has no history encoder or
    history snapshot.  Its fixed policy flags prevent callers from mistaking
    recovered-after-the-fact labels for a point-in-time, publishable model
    preparation run.
    """

    dedupe: DedupeResult
    split: RetrospectiveTemporalEvaluationSplit
    retrospective_audit: RetrospectiveTemporalEvaluationAudit
    schedule_categorical_snapshot: ScheduleCategoricalSnapshot
    matrix_audit: RetrospectiveMatrixAudit
    train: PreparedPartition
    tune: PreparedPartition
    calibration: PreparedPartition
    test: PreparedPartition
    target_derived_history_features_allowed: bool = field(
        init=False,
        default=False,
    )
    publishable: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if self.retrospective_audit != self.split.audit:
            raise ValueError("retrospective audit must be the split audit")
        expected = self.train.feature_names
        categorical_names = self.schedule_categorical_snapshot.feature_names
        if (
            categorical_names
            and expected[-len(categorical_names) :] != categorical_names
        ):
            raise ValueError("retrospective schedule categories are misaligned")
        for name, partition, records in (
            ("train", self.train, self.split.train),
            ("tune", self.tune, self.split.tune),
            ("calibration", self.calibration, self.split.calibration),
            ("test", self.test, self.split.test),
        ):
            if partition.records != records:
                raise ValueError(f"retrospective {name} records are misaligned")
            if partition.feature_names != expected:
                raise ValueError(
                    f"retrospective {name} feature contract is misaligned"
                )
            if any(feature.startswith("history_") for feature in expected):
                raise ValueError(
                    "retrospective preparation cannot contain history features"
                )
            if not sparse.isspmatrix_csr(partition.matrix):
                raise ValueError(
                    f"retrospective {name} matrix must use CSR storage"
                )
        if tuple(name for name, _ in self.matrix_audit.partitions) != (
            "train",
            "tune",
            "calibration",
            "test",
        ):
            raise ValueError("retrospective matrix audit partitions are misaligned")


def _partition(
    records: tuple[GlobalFlightRecord, ...],
    history_rows,
    feature_names: tuple[str, ...] | None = None,
) -> PreparedPartition:
    if len(records) != len(history_rows):
        raise ValueError("records and history rows must be aligned")
    assembled = [
        assemble_feature_row(record, history)
        for record, history in zip(records, history_rows, strict=True)
    ]
    if not assembled:
        raise ValueError("prepared partitions must not be empty")
    names = feature_names or tuple(sorted(assembled[0].values))
    if any(set(row.values) != set(names) for row in assembled):
        raise ValueError("feature contract differs between prepared rows")
    matrix = np.asarray(
        [[row.values[name] for name in names] for row in assembled],
        dtype="float32",
    )
    targets, target_available = _target_arrays(records)
    return PreparedPartition(
        records=records,
        feature_names=names,
        matrix=matrix,
        targets=targets,
        target_available=target_available,
    )


def _target_arrays(
    records: tuple[GlobalFlightRecord, ...],
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    target_values: dict[str, list[int]] = {target: [] for target in TARGET_NAMES}
    available_values: dict[str, list[bool]] = {
        target: [] for target in TARGET_NAMES
    }
    for record in records:
        labels = derive_labels(record).targets()
        for target, value in labels.items():
            available_values[target].append(value is not None)
            target_values[target].append(int(value) if value is not None else 0)
    return (
        {
            target: np.asarray(values, dtype="int8")
            for target, values in target_values.items()
        },
        {
            target: np.asarray(values, dtype="bool")
            for target, values in available_values.items()
        },
    )


def _csr_bytes(rows: int, nnz: int) -> int:
    """Conservative float32/int32 CSR byte estimate."""

    return nnz * (np.dtype("float32").itemsize + np.dtype("int32").itemsize) + (
        rows + 1
    ) * np.dtype("int32").itemsize


def _categorical_max_nnz_per_row(
    snapshot: ScheduleCategoricalSnapshot,
) -> int:
    if not snapshot.config.enabled:
        return 0
    values_per_field = (
        3 if snapshot.config.include_fit_frequency_features else 1
    )
    return len(snapshot.vocabularies) * values_per_field


def _sparse_partition_plan(
    rows: int,
    base_columns: int,
    snapshot: ScheduleCategoricalSnapshot,
) -> _SparsePartitionPlan:
    categorical_columns = len(snapshot.feature_names)
    base_max_nnz = rows * base_columns
    categorical_max_nnz = rows * _categorical_max_nnz_per_row(snapshot)
    combined_max_nnz = base_max_nnz + categorical_max_nnz
    base_bytes = _csr_bytes(rows, base_max_nnz)
    categorical_bytes = _csr_bytes(rows, categorical_max_nnz)
    combined_bytes = _csr_bytes(rows, combined_max_nnz)
    columns = base_columns + categorical_columns
    return _SparsePartitionPlan(
        rows=rows,
        columns=columns,
        base_max_nnz=base_max_nnz,
        categorical_max_nnz=categorical_max_nnz,
        combined_max_nnz=combined_max_nnz,
        estimated_csr_bytes=combined_bytes,
        dense_equivalent_bytes=(
            rows * columns * np.dtype("float32").itemsize
        ),
        estimated_peak_bytes=base_bytes + categorical_bytes + combined_bytes,
    )


def _validate_sparse_matrix_plans(
    plans: tuple[tuple[str, _SparsePartitionPlan], ...],
    limits: RetrospectiveMatrixMemoryLimits,
) -> None:
    """Reject unsafe configurations before any partition-sized allocation."""

    for name, plan in plans:
        if plan.combined_max_nnz > np.iinfo(np.int32).max:
            raise MemoryError(
                f"retrospective {name} CSR plan exceeds int32 index capacity"
            )
        if plan.estimated_peak_bytes > limits.max_partition_peak_bytes:
            raise MemoryError(
                f"retrospective {name} matrix estimated peak "
                f"{plan.estimated_peak_bytes} bytes exceeds limit "
                f"{limits.max_partition_peak_bytes} before allocation"
            )
    total = sum(plan.estimated_csr_bytes for _, plan in plans)
    if total > limits.max_total_csr_bytes:
        raise MemoryError(
            "retrospective retained CSR matrices estimate "
            f"{total} bytes exceeds limit {limits.max_total_csr_bytes} "
            "before allocation"
        )


def _base_feature_partition(
    records: tuple[GlobalFlightRecord, ...],
    base_feature_names: tuple[str, ...],
    *,
    categorical_transformer: TrainingOnlyScheduleCategoricalTransformer,
    categorical_snapshot: ScheduleCategoricalSnapshot,
    first_assembled=None,
) -> PreparedPartition:
    """Prepare schedule/geography features as CSR with no target input path."""

    if not records:
        raise ValueError("prepared partitions must not be empty")
    maximum_nnz = len(records) * len(base_feature_names)
    data = np.empty(maximum_nnz, dtype=np.float32)
    indices = np.empty(maximum_nnz, dtype=np.int32)
    indptr = np.empty(len(records) + 1, dtype=np.int32)
    indptr[0] = 0
    cursor = 0
    for row_index, record in enumerate(records):
        assembled = (
            first_assembled
            if row_index == 0 and first_assembled is not None
            else assemble_feature_row(record, {})
        )
        if set(assembled.values) != set(base_feature_names):
            raise ValueError("feature contract differs between prepared rows")
        for column, name in enumerate(base_feature_names):
            value = assembled.values[name]
            if value != 0.0:
                indices[cursor] = column
                data[cursor] = value
                cursor += 1
        indptr[row_index + 1] = cursor
    base_matrix = sparse.csr_matrix(
        (data[:cursor], indices[:cursor], indptr),
        shape=(len(records), len(base_feature_names)),
        dtype=np.float32,
        copy=True,
    )
    # Ensure the retained CSR owns compact arrays instead of keeping a view of
    # the conservative maximum-NNZ preallocation on any supported SciPy build.
    del data, indices, indptr
    categorical_matrix = categorical_transformer.transform(
        records, categorical_snapshot
    )
    feature_names = base_feature_names + categorical_snapshot.feature_names
    if len(set(feature_names)) != len(feature_names):
        raise ValueError("retrospective feature names collide")
    matrix = sparse.hstack(
        (base_matrix, categorical_matrix),
        format="csr",
        dtype=np.float32,
    )
    matrix.sort_indices()
    targets, target_available = _target_arrays(records)
    partition = PreparedPartition(
        records=records,
        feature_names=feature_names,
        matrix=matrix,
        targets=targets,
        target_available=target_available,
    )
    if any(name.startswith("history_") for name in feature_names):
        raise AssertionError("retrospective preparation admitted a history feature")
    if any(
        name.startswith(SCHEDULE_CATEGORY_FEATURE_PREFIX)
        for name in base_feature_names
    ):
        raise AssertionError("schedule categories collided with base features")
    return partition


def _matrix_storage_audit(
    matrix: sparse.csr_matrix,
    plan: _SparsePartitionPlan,
) -> MatrixStorageAudit:
    rows, columns = matrix.shape
    nnz = int(matrix.nnz)
    total_cells = rows * columns
    data_bytes = int(matrix.data.nbytes)
    indices_bytes = int(matrix.indices.nbytes)
    indptr_bytes = int(matrix.indptr.nbytes)
    return MatrixStorageAudit(
        rows=rows,
        columns=columns,
        nnz=nnz,
        data_bytes=data_bytes,
        indices_bytes=indices_bytes,
        indptr_bytes=indptr_bytes,
        estimated_csr_bytes=data_bytes + indices_bytes + indptr_bytes,
        dense_equivalent_bytes=(
            total_cells * np.dtype("float32").itemsize
        ),
        density=nnz / total_cells if total_cells else 0.0,
        guard_estimated_peak_bytes=plan.estimated_peak_bytes,
    )


def _retrospective_matrix_audit(
    partitions: tuple[tuple[str, PreparedPartition], ...],
    plans: tuple[tuple[str, _SparsePartitionPlan], ...],
    limits: RetrospectiveMatrixMemoryLimits,
) -> RetrospectiveMatrixAudit:
    plan_by_name = dict(plans)
    audited: list[tuple[str, MatrixStorageAudit]] = []
    for name, partition in partitions:
        if not sparse.isspmatrix_csr(partition.matrix):
            raise AssertionError("retrospective matrix audit requires CSR matrices")
        audit = _matrix_storage_audit(partition.matrix, plan_by_name[name])
        audited.append((name, audit))
    audits = tuple(audit for _, audit in audited)
    return RetrospectiveMatrixAudit(
        storage_format="scipy_csr",
        dtype="float32",
        partitions=tuple(audited),
        total_nnz=sum(audit.nnz for audit in audits),
        total_estimated_csr_bytes=sum(
            audit.estimated_csr_bytes for audit in audits
        ),
        total_dense_equivalent_bytes=sum(
            audit.dense_equivalent_bytes for audit in audits
        ),
        limits=limits,
    )


def prepare_global_data(
    records: Iterable[GlobalFlightRecord],
    boundaries: ChronologicalBoundaries,
    *,
    encoder: PastOnlyHierarchicalEncoder | None = None,
) -> PreparedGlobalData:
    """Dedupe, split, encode, and build consistent numeric matrices.

    Tune, calibration, and test use the training-boundary snapshot unchanged.
    Their outcomes never update any feature map.
    """

    history_encoder = encoder or PastOnlyHierarchicalEncoder()
    dedupe = deduplicate_records(
        records,
        prediction_horizon=history_encoder.prediction_horizon,
    )
    split = chronological_split(
        dedupe.records,
        boundaries,
        prediction_horizon=history_encoder.prediction_horizon,
    )
    train_history, snapshot = history_encoder.fit_transform(
        split.train, snapshot_as_of=boundaries.train_end
    )
    tune_history = history_encoder.transform(split.tune, snapshot)
    calibration_history = history_encoder.transform(split.calibration, snapshot)
    test_history = history_encoder.transform(split.test, snapshot)
    train = _partition(split.train, train_history)
    tune = _partition(split.tune, tune_history, train.feature_names)
    calibration = _partition(
        split.calibration, calibration_history, train.feature_names
    )
    test = _partition(split.test, test_history, train.feature_names)
    return PreparedGlobalData(
        dedupe=dedupe,
        split=split,
        history_snapshot=snapshot,
        train=train,
        tune=tune,
        calibration=calibration,
        test=test,
    )


def prepare_retrospective_global_data(
    records: Iterable[GlobalFlightRecord],
    boundaries: ChronologicalBoundaries,
    *,
    schedule_categorical_config: ScheduleCategoricalFeatureConfig | None = None,
    matrix_memory_limits: RetrospectiveMatrixMemoryLimits | None = None,
) -> PreparedRetrospectiveGlobalData:
    """Build non-publishable T-7 retrospective evaluation matrices.

    This path is for terminal outcomes whose historical publication time is
    not proven.  It deliberately exposes no encoder argument and no history
    snapshot: all four windows contain schedule/geography features plus a
    bounded schedule-category vocabulary fitted on train only, while recovered
    outcomes remain labels.  The categorical transformer never reads outcomes,
    and tune/calibration/test cannot alter its vocabulary.  The result must
    never be exported as a production artifact or described as a point-in-time
    backtest.
    """

    dedupe = deduplicate_records(
        records,
        prediction_horizon=RETROSPECTIVE_EVALUATION_HORIZON,
    )
    split = retrospective_temporal_evaluation_split(
        dedupe.records,
        boundaries,
        prediction_horizon=RETROSPECTIVE_EVALUATION_HORIZON,
    )
    categorical_transformer = TrainingOnlyScheduleCategoricalTransformer(
        schedule_categorical_config
    )
    categorical_snapshot = categorical_transformer.fit(split.train)
    # Assemble one train row to establish the base feature contract, then
    # retain it for matrix construction so every source row is still assembled
    # exactly once.  All memory plans are validated before a partition-sized
    # NumPy or SciPy array is allocated.
    first_train_row = assemble_feature_row(split.train[0], {})
    base_feature_names = tuple(sorted(first_train_row.values))
    limits = matrix_memory_limits or RetrospectiveMatrixMemoryLimits()
    plans = tuple(
        (
            name,
            _sparse_partition_plan(
                len(partition_records),
                len(base_feature_names),
                categorical_snapshot,
            ),
        )
        for name, partition_records in (
            ("train", split.train),
            ("tune", split.tune),
            ("calibration", split.calibration),
            ("test", split.test),
        )
    )
    _validate_sparse_matrix_plans(plans, limits)
    train = _base_feature_partition(
        split.train,
        base_feature_names,
        categorical_transformer=categorical_transformer,
        categorical_snapshot=categorical_snapshot,
        first_assembled=first_train_row,
    )
    tune = _base_feature_partition(
        split.tune,
        base_feature_names,
        categorical_transformer=categorical_transformer,
        categorical_snapshot=categorical_snapshot,
    )
    calibration = _base_feature_partition(
        split.calibration,
        base_feature_names,
        categorical_transformer=categorical_transformer,
        categorical_snapshot=categorical_snapshot,
    )
    test = _base_feature_partition(
        split.test,
        base_feature_names,
        categorical_transformer=categorical_transformer,
        categorical_snapshot=categorical_snapshot,
    )
    partitions = (
        ("train", train),
        ("tune", tune),
        ("calibration", calibration),
        ("test", test),
    )
    matrix_audit = _retrospective_matrix_audit(partitions, plans, limits)
    return PreparedRetrospectiveGlobalData(
        dedupe=dedupe,
        split=split,
        retrospective_audit=split.audit,
        schedule_categorical_snapshot=categorical_snapshot,
        matrix_audit=matrix_audit,
        train=train,
        tune=tune,
        calibration=calibration,
        test=test,
    )
