"""Chronological and geographic evaluation splits for global flight models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from .encodings import (
    prediction_timestamp,
    validate_outcome_after_prediction,
    validate_schedule_at_prediction,
)
from .schema import GlobalFlightRecord


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
