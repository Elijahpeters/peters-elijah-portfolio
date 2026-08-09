"""Chronological and geographic evaluation splits for global flight models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .encodings import (
    prediction_timestamp,
    validate_outcome_after_prediction,
    validate_schedule_at_prediction,
)
from .schema import GlobalFlightRecord, TERMINAL_STATUSES


RETROSPECTIVE_EVALUATION_HORIZON = timedelta(days=7)
"""The fixed T-7 decision horizon for retrospective temporal evaluation."""


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ChronologicalBoundaries:
    """Exclusive prediction-time boundaries for model-development windows."""

    train_end: datetime
    tune_end: datetime
    calibration_end: datetime
    test_end: datetime

    def __post_init__(self) -> None:
        values = tuple(
            _utc(value, name)
            for name, value in (
                ("train_end", self.train_end),
                ("tune_end", self.tune_end),
                ("calibration_end", self.calibration_end),
                ("test_end", self.test_end),
            )
        )
        if not all(left < right for left, right in zip(values, values[1:])):
            raise ValueError("chronological boundaries must be strictly increasing")
        for name, value in zip(
            ("train_end", "tune_end", "calibration_end", "test_end"),
            values,
            strict=True,
        ):
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class ChronologicalSplit:
    train: tuple[GlobalFlightRecord, ...]
    tune: tuple[GlobalFlightRecord, ...]
    calibration: tuple[GlobalFlightRecord, ...]
    test: tuple[GlobalFlightRecord, ...]
    purged_immature: tuple[GlobalFlightRecord, ...]
    excluded_after_test: tuple[GlobalFlightRecord, ...]


def chronological_split(
    records: Iterable[GlobalFlightRecord],
    boundaries: ChronologicalBoundaries,
    *,
    prediction_horizon: timedelta = timedelta(days=7),
    require_non_empty: bool = True,
) -> ChronologicalSplit:
    """Split by prediction time and purge labels unavailable by each cutoff."""

    if prediction_horizon < timedelta(0):
        raise ValueError("prediction horizon must not be negative")

    groups: dict[str, list[GlobalFlightRecord]] = {
        "train": [],
        "tune": [],
        "calibration": [],
        "test": [],
        "purged_immature": [],
        "excluded_after_test": [],
    }
    for record in sorted(
        records,
        key=lambda item: (
            prediction_timestamp(item, prediction_horizon),
            item.canonical_key,
        ),
    ):
        timestamp = validate_schedule_at_prediction(record, prediction_horizon)
        if timestamp < boundaries.train_end:
            group = "train"
            maturity_cutoff = boundaries.train_end
        elif timestamp < boundaries.tune_end:
            group = "tune"
            maturity_cutoff = boundaries.tune_end
        elif timestamp < boundaries.calibration_end:
            group = "calibration"
            maturity_cutoff = boundaries.calibration_end
        elif timestamp < boundaries.test_end:
            group = "test"
            maturity_cutoff = boundaries.test_end
        else:
            group = "excluded_after_test"
            maturity_cutoff = None
        outcome_at = validate_outcome_after_prediction(record, prediction_horizon)
        if (
            maturity_cutoff is not None
            and outcome_at >= maturity_cutoff
        ):
            groups["purged_immature"].append(record)
        else:
            groups[group].append(record)

    if require_non_empty:
        empty = [name for name in ("train", "tune", "calibration", "test") if not groups[name]]
        if empty:
            raise ValueError(f"chronological split has empty windows: {', '.join(empty)}")

    return ChronologicalSplit(
        **{name: tuple(rows) for name, rows in groups.items()}
    )


@dataclass(frozen=True, slots=True)
class RetrospectiveTemporalEvaluationAudit:
    """Reconciled disclosure for a non-point-in-time temporal experiment.

    The labels in this evaluation were first observed only after the complete
    service corpus had finished.  They may be used as supervised outcomes, but
    never as historical rate/count features that claim to have existed at T-7.
    """

    prediction_horizon_seconds: int
    input_count: int
    train_count: int
    tune_count: int
    calibration_count: int
    test_count: int
    excluded_after_test_count: int
    earliest_prediction_at: datetime | None
    latest_prediction_at: datetime | None
    latest_service_at: datetime | None
    earliest_label_first_seen_at: datetime | None
    latest_label_first_seen_at: datetime | None
    evaluation_kind: str = field(
        init=False,
        default="retrospective_temporal_evaluation",
    )
    point_in_time_backtest: bool = field(init=False, default=False)
    target_derived_history_features_allowed: bool = field(
        init=False,
        default=False,
    )

    def __post_init__(self) -> None:
        if self.prediction_horizon_seconds != int(
            RETROSPECTIVE_EVALUATION_HORIZON.total_seconds()
        ):
            raise ValueError("retrospective evaluation audit must describe T-7")
        counts = (
            self.input_count,
            self.train_count,
            self.tune_count,
            self.calibration_count,
            self.test_count,
            self.excluded_after_test_count,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts
        ):
            raise ValueError(
                "retrospective evaluation counts must be non-negative integers"
            )
        if sum(counts[1:]) != self.input_count:
            raise ValueError("retrospective evaluation window counts do not reconcile")

        temporal_values = (
            self.earliest_prediction_at,
            self.latest_prediction_at,
            self.latest_service_at,
            self.earliest_label_first_seen_at,
            self.latest_label_first_seen_at,
        )
        if self.input_count == 0:
            if any(value is not None for value in temporal_values):
                raise ValueError("an empty retrospective audit cannot have timestamps")
            return
        if any(value is None for value in temporal_values):
            raise ValueError("a non-empty retrospective audit requires all timestamps")

        normalized = tuple(
            _utc(value, name)
            for name, value in zip(
                (
                    "earliest_prediction_at",
                    "latest_prediction_at",
                    "latest_service_at",
                    "earliest_label_first_seen_at",
                    "latest_label_first_seen_at",
                ),
                temporal_values,
                strict=True,
            )
            if value is not None
        )
        for name, value in zip(
            (
                "earliest_prediction_at",
                "latest_prediction_at",
                "latest_service_at",
                "earliest_label_first_seen_at",
                "latest_label_first_seen_at",
            ),
            normalized,
            strict=True,
        ):
            object.__setattr__(self, name, value)

        if normalized[0] > normalized[1]:
            raise ValueError("retrospective prediction timestamps are inverted")
        if normalized[3] > normalized[4]:
            raise ValueError("retrospective label timestamps are inverted")
        if normalized[3] <= normalized[2]:
            raise ValueError(
                "retrospective labels must first be seen after the complete "
                "service corpus"
            )

    @property
    def window_counts(self) -> dict[str, int]:
        """Return a fresh, JSON-friendly count map for audit artifacts."""

        return {
            "train": self.train_count,
            "tune": self.tune_count,
            "calibration": self.calibration_count,
            "test": self.test_count,
            "excluded_after_test": self.excluded_after_test_count,
        }

    def to_dict(self) -> dict[str, object]:
        def instant(value: datetime | None) -> str | None:
            return value.isoformat().replace("+00:00", "Z") if value else None

        return {
            "evaluation_kind": self.evaluation_kind,
            "point_in_time_backtest": self.point_in_time_backtest,
            "target_derived_history_features_allowed": (
                self.target_derived_history_features_allowed
            ),
            "prediction_horizon_seconds": self.prediction_horizon_seconds,
            "input_count": self.input_count,
            "window_counts": self.window_counts,
            "earliest_prediction_at": instant(self.earliest_prediction_at),
            "latest_prediction_at": instant(self.latest_prediction_at),
            "latest_service_at": instant(self.latest_service_at),
            "earliest_label_first_seen_at": instant(
                self.earliest_label_first_seen_at
            ),
            "latest_label_first_seen_at": instant(self.latest_label_first_seen_at),
        }


@dataclass(frozen=True, slots=True)
class RetrospectiveTemporalEvaluationSplit:
    """Temporal windows for evaluation with labels recovered after the fact.

    This type is deliberately distinct from :class:`ChronologicalSplit`.
    There is no ``purged_immature`` window because label publication time does
    not simulate historical model availability.  Feature preparation for this
    split must use schedule/geography inputs only; target-derived hierarchical
    history is explicitly prohibited by the attached audit policy.
    """

    train: tuple[GlobalFlightRecord, ...]
    tune: tuple[GlobalFlightRecord, ...]
    calibration: tuple[GlobalFlightRecord, ...]
    test: tuple[GlobalFlightRecord, ...]
    excluded_after_test: tuple[GlobalFlightRecord, ...]
    audit: RetrospectiveTemporalEvaluationAudit


def retrospective_temporal_evaluation_split(
    records: Iterable[GlobalFlightRecord],
    boundaries: ChronologicalBoundaries,
    *,
    prediction_horizon: timedelta = RETROSPECTIVE_EVALUATION_HORIZON,
    require_non_empty: bool = True,
) -> RetrospectiveTemporalEvaluationSplit:
    """Build a clearly labelled retrospective T-7 temporal evaluation.

    This is appropriate for hash-pinned terminal outcome files that are
    observable today but lack evidence of historical publication by the model
    development cutoffs.  Rows are assigned solely by their nominal T-7
    prediction timestamp.  Every schedule must have been observable by T-7,
    every row must be terminal, and the earliest label observation must follow
    the latest scheduled arrival in the supplied corpus.

    The result is *not* a point-in-time backtest.  In particular, callers must
    not pass it through ``PastOnlyHierarchicalEncoder`` or any other feature
    builder that derives historical rates/counts from these targets.
    """

    if prediction_horizon != RETROSPECTIVE_EVALUATION_HORIZON:
        raise ValueError("retrospective temporal evaluation is fixed at T-7")

    materialized = tuple(records)
    groups: dict[str, list[GlobalFlightRecord]] = {
        "train": [],
        "tune": [],
        "calibration": [],
        "test": [],
        "excluded_after_test": [],
    }
    prediction_times: list[datetime] = []
    label_times: list[datetime] = []

    ordered = sorted(
        materialized,
        key=lambda item: (
            prediction_timestamp(item, prediction_horizon),
            item.canonical_key,
        ),
    )
    for record in ordered:
        if record.status not in TERMINAL_STATUSES:
            raise ValueError(
                "retrospective temporal evaluation requires terminal outcomes; "
                f"row {record.record_id!r} has status {record.status!r}"
            )
        prediction_at = validate_schedule_at_prediction(record, prediction_horizon)
        label_first_seen_at = validate_outcome_after_prediction(
            record, prediction_horizon
        )
        prediction_times.append(prediction_at)
        label_times.append(label_first_seen_at)

        if prediction_at < boundaries.train_end:
            group = "train"
        elif prediction_at < boundaries.tune_end:
            group = "tune"
        elif prediction_at < boundaries.calibration_end:
            group = "calibration"
        elif prediction_at < boundaries.test_end:
            group = "test"
        else:
            group = "excluded_after_test"
        groups[group].append(record)

    if materialized:
        latest_service_at = max(row.scheduled_arrival_utc for row in materialized)
        if min(label_times) <= latest_service_at:
            raise ValueError(
                "retrospective temporal evaluation requires every label to be "
                "first seen after the complete service corpus; use "
                "chronological_split when historical availability is proven"
            )
    else:
        latest_service_at = None

    if require_non_empty:
        empty = [
            name
            for name in ("train", "tune", "calibration", "test")
            if not groups[name]
        ]
        if empty:
            raise ValueError(
                "retrospective temporal evaluation has empty windows: "
                + ", ".join(empty)
            )

    audit = RetrospectiveTemporalEvaluationAudit(
        prediction_horizon_seconds=int(prediction_horizon.total_seconds()),
        input_count=len(materialized),
        train_count=len(groups["train"]),
        tune_count=len(groups["tune"]),
        calibration_count=len(groups["calibration"]),
        test_count=len(groups["test"]),
        excluded_after_test_count=len(groups["excluded_after_test"]),
        earliest_prediction_at=min(prediction_times) if prediction_times else None,
        latest_prediction_at=max(prediction_times) if prediction_times else None,
        latest_service_at=latest_service_at,
        earliest_label_first_seen_at=min(label_times) if label_times else None,
        latest_label_first_seen_at=max(label_times) if label_times else None,
    )
    return RetrospectiveTemporalEvaluationSplit(
        train=tuple(groups["train"]),
        tune=tuple(groups["tune"]),
        calibration=tuple(groups["calibration"]),
        test=tuple(groups["test"]),
        excluded_after_test=tuple(groups["excluded_after_test"]),
        audit=audit,
    )


@dataclass(frozen=True, slots=True)
class RegionHoldoutSplit:
    training: tuple[GlobalFlightRecord, ...]
    holdout_test: tuple[GlobalFlightRecord, ...]
    purged_immature: tuple[GlobalFlightRecord, ...]
    excluded: tuple[GlobalFlightRecord, ...]
    held_out_regions: tuple[str, ...]


def _record_regions(record: GlobalFlightRecord) -> frozenset[str]:
    return frozenset({record.origin_region.casefold(), record.destination_region.casefold()})


def region_holdout_split(
    records: Iterable[GlobalFlightRecord],
    held_out_regions: Iterable[str],
    test_start: datetime,
    *,
    prediction_horizon: timedelta = timedelta(days=7),
) -> RegionHoldoutSplit:
    """Build a diagnostic split whose regions are unseen during fitting.

    Pre-cutoff rows touching a held-out region are excluded from training.  Only
    future rows touching that region enter the holdout test.  Future non-holdout
    rows are excluded, which prevents the diagnostic from becoming an ordinary
    temporal mixture.
    """

    regions = tuple(sorted({value.strip().casefold() for value in held_out_regions if value.strip()}))
    if not regions:
        raise ValueError("at least one held-out region is required")
    region_set = frozenset(regions)
    cutoff = _utc(test_start, "test_start")
    training: list[GlobalFlightRecord] = []
    holdout: list[GlobalFlightRecord] = []
    purged_immature: list[GlobalFlightRecord] = []
    excluded: list[GlobalFlightRecord] = []

    for record in sorted(
        records,
        key=lambda item: (
            prediction_timestamp(item, prediction_horizon),
            item.canonical_key,
        ),
    ):
        touches_holdout = bool(_record_regions(record) & region_set)
        prediction_at = validate_schedule_at_prediction(record, prediction_horizon)
        outcome_at = validate_outcome_after_prediction(record, prediction_horizon)
        if prediction_at < cutoff and not touches_holdout:
            if outcome_at >= cutoff:
                purged_immature.append(record)
            else:
                training.append(record)
        elif prediction_at >= cutoff and touches_holdout:
            holdout.append(record)
        else:
            excluded.append(record)

    if not training or not holdout:
        raise ValueError("region holdout requires non-empty training and future holdout rows")
    if any(_record_regions(row) & region_set for row in training):
        raise AssertionError("held-out geography leaked into training")

    return RegionHoldoutSplit(
        training=tuple(training),
        holdout_test=tuple(holdout),
        purged_immature=tuple(purged_immature),
        excluded=tuple(excluded),
        held_out_regions=regions,
    )
