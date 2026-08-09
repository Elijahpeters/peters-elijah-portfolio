"""End-to-end preparation of leakage-safe global model matrices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from .dedupe import DedupeResult, deduplicate_records
from .encodings import EncodingSnapshot, PastOnlyHierarchicalEncoder
from .features import assemble_feature_row
from .labels import TARGET_NAMES, derive_labels
from .schema import GlobalFlightRecord
from .splits import ChronologicalBoundaries, ChronologicalSplit, chronological_split


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
