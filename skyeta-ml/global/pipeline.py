"""End-to-end preparation of leakage-safe global model matrices."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

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
    matrix: np.ndarray
    targets: dict[str, np.ndarray]
    target_available: dict[str, np.ndarray]

    def rows_for_target(self, target: str) -> tuple[np.ndarray, np.ndarray]:
        if target not in self.targets:
            raise KeyError(target)
        available = self.target_available[target]
        return self.matrix[available], self.targets[target][available]


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
    target_values: dict[str, list[int]] = {target: [] for target in TARGET_NAMES}
    target_available: dict[str, list[bool]] = {target: [] for target in TARGET_NAMES}
    for record in records:
        labels = derive_labels(record).targets()
        for target, value in labels.items():
            target_available[target].append(value is not None)
            target_values[target].append(int(value) if value is not None else 0)
    return PreparedPartition(
        records=records,
        feature_names=names,
        matrix=matrix,
        targets={
            target: np.asarray(values, dtype="int8")
            for target, values in target_values.items()
        },
        target_available={
            target: np.asarray(values, dtype="bool")
            for target, values in target_available.items()
        },
    )


def _base_feature_partition(
    records: tuple[GlobalFlightRecord, ...],
    base_feature_names: tuple[str, ...] | None = None,
    *,
    categorical_transformer: TrainingOnlyScheduleCategoricalTransformer,
    categorical_snapshot: ScheduleCategoricalSnapshot,
) -> PreparedPartition:
    """Prepare schedule/geography features with no target-derived input path."""

    empty_history = tuple({} for _ in records)
    base = _partition(records, empty_history, base_feature_names)
    categorical_matrix = categorical_transformer.transform(
        records, categorical_snapshot
    )
    feature_names = base.feature_names + categorical_snapshot.feature_names
    if len(set(feature_names)) != len(feature_names):
        raise ValueError("retrospective feature names collide")
    partition = PreparedPartition(
        records=base.records,
        feature_names=feature_names,
        matrix=np.concatenate((base.matrix, categorical_matrix), axis=1),
        targets=base.targets,
        target_available=base.target_available,
    )
    if any(name.startswith("history_") for name in feature_names):
        raise AssertionError("retrospective preparation admitted a history feature")
    if any(
        name.startswith(SCHEDULE_CATEGORY_FEATURE_PREFIX)
        for name in base.feature_names
    ):
        raise AssertionError("schedule categories collided with base features")
    return partition


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
    train = _base_feature_partition(
        split.train,
        categorical_transformer=categorical_transformer,
        categorical_snapshot=categorical_snapshot,
    )
    base_feature_count = len(train.feature_names) - len(
        categorical_snapshot.feature_names
    )
    base_feature_names = train.feature_names[:base_feature_count]
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
    return PreparedRetrospectiveGlobalData(
        dedupe=dedupe,
        split=split,
        retrospective_audit=split.audit,
        schedule_categorical_snapshot=categorical_snapshot,
        train=train,
        tune=tune,
        calibration=calibration,
        test=test,
    )
