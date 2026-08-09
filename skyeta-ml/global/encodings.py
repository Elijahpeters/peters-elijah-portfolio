"""Strictly past-only hierarchical history features.

The encoder treats outcomes as events that become available only after a flight
has finished.  Rows at the same prediction timestamp are encoded together, then
their schedule counts are added; their outcomes are added later.  Consequently
no row can observe its own target, another simultaneous target, or an outcome
that had not happened yet.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import count, groupby
from typing import Iterable, Mapping

from .labels import TARGET_NAMES, FlightLabels, derive_labels
from .schema import GlobalFlightRecord, TERMINAL_STATUSES


HIERARCHY_LEVELS = (
    "flight_route",
    "carrier_route",
    "route",
    "carrier",
    "origin",
    "destination",
    "region_pair",
)
DEFAULT_PRIORS = {
    "arrival_15": 0.20,
    "arrival_30": 0.12,
    "arrival_60": 0.06,
    "cancelled": 0.025,
    "disrupted": 0.04,
}
DEFAULT_PRIOR_STRENGTH = {
    "flight_route": 30.0,
    "carrier_route": 60.0,
    "route": 90.0,
    "carrier": 180.0,
    "origin": 180.0,
    "destination": 180.0,
    "region_pair": 400.0,
}
PARENT_LEVEL = {
    "flight_route": "carrier_route",
    "carrier_route": "route",
    "route": "region_pair",
    "carrier": None,
    "origin": None,
    "destination": None,
    "region_pair": None,
}


@dataclass(frozen=True, slots=True)
class Aggregate:
    count: int = 0
    positives: int = 0

    def add(self, positive: bool) -> "Aggregate":
        return Aggregate(self.count + 1, self.positives + int(positive))


@dataclass(frozen=True, slots=True)
class EncodingSnapshot:
    schedule_counts: dict[str, dict[str, int]]
    target_aggregates: dict[str, dict[str, dict[str, Aggregate]]]
    global_aggregates: dict[str, Aggregate]
    as_of: datetime | None
    priors: dict[str, float]
    prior_strength: dict[str, float]
    prediction_horizon_seconds: int

    def support(self, level: str, key: str, target: str = "arrival_15") -> int:
        return self.target_aggregates.get(target, {}).get(level, {}).get(
            key, Aggregate()
        ).count

    def schedule_support(self, level: str, key: str) -> int:
        return self.schedule_counts.get(level, {}).get(key, 0)

    def to_serializable(self) -> dict:
        return {
            "asOf": self.as_of.isoformat().replace("+00:00", "Z")
            if self.as_of
            else None,
            "priors": dict(self.priors),
            "priorStrength": dict(self.prior_strength),
            "predictionHorizonSeconds": self.prediction_horizon_seconds,
            "scheduleCounts": self.schedule_counts,
            "targets": {
                target: {
                    level: {
                        key: [aggregate.count, aggregate.positives]
                        for key, aggregate in values.items()
                    }
                    for level, values in levels.items()
                }
                for target, levels in self.target_aggregates.items()
            },
            "globalTargets": {
                target: [aggregate.count, aggregate.positives]
                for target, aggregate in self.global_aggregates.items()
            },
        }


@dataclass(frozen=True, slots=True)
class EncodedHistoryRow:
    record_id: str
    features: dict[str, float]


def hierarchy_keys(record: GlobalFlightRecord) -> dict[str, str]:
    return {
        "flight_route": record.flight_route_key,
        "carrier_route": record.carrier_route_key,
        "route": record.route_key,
        "carrier": record.operating_carrier,
        "origin": record.origin,
        "destination": record.destination,
        "region_pair": f"{record.origin_region.casefold()}>{record.destination_region.casefold()}",
    }


def outcome_available_at(record: GlobalFlightRecord) -> datetime:
    """Point-in-time instant after which the row's outcome may enter history."""

    if record.outcome_observed_at is not None:
        return record.outcome_observed_at
    raise ValueError(
        f"terminal {record.status} row {record.record_id!r} requires "
        "outcome_observed_at"
    )


def prediction_timestamp(
    record: GlobalFlightRecord, prediction_horizon: timedelta
) -> datetime:
    return record.scheduled_departure_utc - prediction_horizon


def validate_schedule_at_prediction(
    record: GlobalFlightRecord, prediction_horizon: timedelta
) -> datetime:
    """Require evidence that the schedule existed at the nominal prediction."""

    prediction_at = prediction_timestamp(record, prediction_horizon)
    if record.schedule_observed_at is None:
        raise ValueError(
            f"row {record.record_id!r} requires schedule_observed_at for a "
            "point-in-time prediction cohort"
        )
    if record.schedule_observed_at > prediction_at:
        raise ValueError(
            f"row {record.record_id!r} schedule was first observed after its "
            "prediction timestamp"
        )
    return prediction_at


def validate_outcome_after_prediction(
    record: GlobalFlightRecord, prediction_horizon: timedelta
) -> datetime:
    """Reject examples whose terminal outcome was already known when scored."""

    prediction_at = prediction_timestamp(record, prediction_horizon)
    available_at = outcome_available_at(record)
    if available_at <= prediction_at:
        raise ValueError(
            f"row {record.record_id!r} outcome was already observed by its "
            "prediction timestamp"
        )
    return available_at


class PastOnlyHierarchicalEncoder:
    """Build empirical-Bayes history rates without future target leakage."""

    def __init__(
        self,
        *,
        priors: Mapping[str, float] = DEFAULT_PRIORS,
        prior_strength: Mapping[str, float] = DEFAULT_PRIOR_STRENGTH,
        prediction_horizon: timedelta = timedelta(days=7),
    ) -> None:
        if set(priors) != set(TARGET_NAMES):
            raise ValueError("priors must define every target exactly once")
        if set(prior_strength) != set(HIERARCHY_LEVELS):
            raise ValueError("prior strength must define every hierarchy level")
        if any(not 0 < value < 1 for value in priors.values()):
            raise ValueError("all target priors must lie strictly between 0 and 1")
        if any(value <= 0 or not math.isfinite(value) for value in prior_strength.values()):
            raise ValueError("all prior strengths must be finite and positive")
        if prediction_horizon < timedelta(0):
            raise ValueError("prediction horizon must not be negative")
        horizon_seconds = prediction_horizon.total_seconds()
        if not math.isfinite(horizon_seconds) or not horizon_seconds.is_integer():
            raise ValueError("prediction horizon must use whole seconds")
        self.priors = {name: float(value) for name, value in priors.items()}
        self.prior_strength = {
            name: float(value) for name, value in prior_strength.items()
        }
        self.prediction_horizon = prediction_horizon

    def fit_transform(
        self,
        records: Iterable[GlobalFlightRecord],
        *,
        snapshot_as_of: datetime | None = None,
    ) -> tuple[tuple[EncodedHistoryRow, ...], EncodingSnapshot]:
        """Encode training rows and return a frozen post-training snapshot."""

        ordered = sorted(
            records,
            key=lambda row: (
                prediction_timestamp(row, self.prediction_horizon),
                row.canonical_key,
            ),
        )
        if any(row.status not in TERMINAL_STATUSES for row in ordered):
            raise ValueError("fit_transform requires terminal historical outcomes")
        for row in ordered:
            validate_schedule_at_prediction(row, self.prediction_horizon)
            validate_outcome_after_prediction(row, self.prediction_horizon)
        normalized_snapshot_as_of: datetime | None = None
        if snapshot_as_of is not None:
            if snapshot_as_of.tzinfo is None or snapshot_as_of.utcoffset() is None:
                raise ValueError("snapshot_as_of must be timezone-aware")
            normalized_snapshot_as_of = snapshot_as_of.astimezone(timezone.utc)
            if (
                ordered
                and normalized_snapshot_as_of
                <= prediction_timestamp(ordered[-1], self.prediction_horizon)
            ):
                raise ValueError(
                    "snapshot_as_of must be later than every training prediction"
                )

        schedule_counts = {
            level: defaultdict(int) for level in HIERARCHY_LEVELS
        }
        target_aggregates = {
            target: {level: {} for level in HIERARCHY_LEVELS}
            for target in TARGET_NAMES
        }
        global_aggregates = {target: Aggregate() for target in TARGET_NAMES}
        pending: list[
            tuple[datetime, int, GlobalFlightRecord, FlightLabels]
        ] = []
        pending_sequence = count()
        output: list[EncodedHistoryRow] = []

        def add_outcome(record: GlobalFlightRecord, labels: FlightLabels) -> None:
            keys = hierarchy_keys(record)
            for target, value in labels.targets().items():
                if value is None:
                    continue
                global_aggregates[target] = global_aggregates[target].add(value)
                for level, key in keys.items():
                    current = target_aggregates[target][level].get(key, Aggregate())
                    target_aggregates[target][level][key] = current.add(value)

        def flush_before(cutoff: datetime, *, inclusive: bool = False) -> None:
            while pending and (
                pending[0][0] < cutoff
                or (inclusive and pending[0][0] == cutoff)
            ):
                _, _, record, labels = heapq.heappop(pending)
                add_outcome(record, labels)

        for timestamp, grouped in groupby(
            ordered,
            key=lambda row: prediction_timestamp(row, self.prediction_horizon),
        ):
            batch = tuple(grouped)
            flush_before(timestamp)
            snapshot = self._snapshot(
                schedule_counts,
                target_aggregates,
                global_aggregates,
                as_of=timestamp,
            )
            output.extend(self.transform(batch, snapshot))
            for record in batch:
                for level, key in hierarchy_keys(record).items():
                    schedule_counts[level][key] += 1
                labels = derive_labels(record)
                heapq.heappush(
                    pending,
                    (
                        outcome_available_at(record),
                        next(pending_sequence),
                        record,
                        labels,
                    ),
                )

        if normalized_snapshot_as_of is not None:
            final_as_of = normalized_snapshot_as_of
            flush_before(final_as_of)
        else:
            while pending:
                _, _, record, labels = heapq.heappop(pending)
                add_outcome(record, labels)
            if ordered:
                latest_outcome = max(outcome_available_at(row) for row in ordered)
                try:
                    final_as_of = latest_outcome + timedelta(microseconds=1)
                except OverflowError as error:
                    raise ValueError(
                        "cannot represent a safe history snapshot cutoff"
                    ) from error
            else:
                final_as_of = None

        return tuple(output), self._snapshot(
            schedule_counts,
            target_aggregates,
            global_aggregates,
            as_of=final_as_of,
        )

    def transform(
        self,
        records: Iterable[GlobalFlightRecord],
        snapshot: EncodingSnapshot,
    ) -> tuple[EncodedHistoryRow, ...]:
        """Apply a frozen snapshot without learning from the transformed rows."""

        expected_horizon_seconds = int(self.prediction_horizon.total_seconds())
        if snapshot.prediction_horizon_seconds != expected_horizon_seconds:
            raise ValueError("history snapshot prediction horizon does not match encoder")
        rows: list[EncodedHistoryRow] = []
        for record in records:
            prediction_at = validate_schedule_at_prediction(
                record, self.prediction_horizon
            )
            if snapshot.as_of is not None and prediction_at < snapshot.as_of:
                raise ValueError(
                    f"history snapshot is newer than row {record.record_id!r} "
                    "prediction timestamp"
                )
            keys = hierarchy_keys(record)
            features: dict[str, float] = {}
            for level, key in keys.items():
                features[f"history_{level}_schedule_log_count"] = math.log1p(
                    snapshot.schedule_support(level, key)
                )
                for target in TARGET_NAMES:
                    aggregate = (
                        snapshot.target_aggregates.get(target, {})
                        .get(level, {})
                        .get(key, Aggregate())
                    )
                    rate = self._smoothed_rate(
                        record, level, target, snapshot
                    )
                    prefix = f"history_{level}_{target}"
                    features[f"{prefix}_rate"] = rate
                    features[f"{prefix}_log_count"] = math.log1p(aggregate.count)
            rows.append(EncodedHistoryRow(record.record_id, features))
        return tuple(rows)

    def _smoothed_rate(
        self,
        record: GlobalFlightRecord,
        level: str,
        target: str,
        snapshot: EncodingSnapshot,
        trail: frozenset[str] = frozenset(),
    ) -> float:
        if level in trail:
            raise RuntimeError("history hierarchy contains a cycle")
        keys = hierarchy_keys(record)
        parent = PARENT_LEVEL[level]
        if parent is None:
            global_aggregate = snapshot.global_aggregates.get(target, Aggregate())
            global_strength = 500.0
            prior = snapshot.priors[target]
            parent_rate = (
                global_aggregate.positives + global_strength * prior
            ) / (global_aggregate.count + global_strength)
        else:
            parent_rate = self._smoothed_rate(
                record, parent, target, snapshot, trail | {level}
            )
        aggregate = (
            snapshot.target_aggregates.get(target, {})
            .get(level, {})
            .get(keys[level], Aggregate())
        )
        strength = snapshot.prior_strength[level]
        return (aggregate.positives + strength * parent_rate) / (
            aggregate.count + strength
        )

    def _snapshot(
        self,
        schedule_counts: Mapping[str, Mapping[str, int]],
        target_aggregates: Mapping[
            str, Mapping[str, Mapping[str, Aggregate]]
        ],
        global_aggregates: Mapping[str, Aggregate],
        *,
        as_of: datetime | None,
    ) -> EncodingSnapshot:
        return EncodingSnapshot(
            schedule_counts={
                level: dict(values) for level, values in schedule_counts.items()
            },
            target_aggregates={
                target: {
                    level: dict(values) for level, values in levels.items()
                }
                for target, levels in target_aggregates.items()
            },
            global_aggregates=dict(global_aggregates),
            as_of=as_of,
            priors=dict(self.priors),
            prior_strength=dict(self.prior_strength),
            prediction_horizon_seconds=int(self.prediction_horizon.total_seconds()),
        )
