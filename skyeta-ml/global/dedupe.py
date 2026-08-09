"""Operating-leg deduplication for codeshare-heavy global provider data."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from .schema import GlobalFlightRecord, TERMINAL_STATUSES


class DedupeConflict(ValueError):
    """Raised when rows for one claimed physical leg contradict each other."""


@dataclass(frozen=True, slots=True)
class DedupeResult:
    records: tuple[GlobalFlightRecord, ...]
    input_rows: int
    duplicate_rows: int


def _quality(
    record: GlobalFlightRecord,
) -> tuple[int, int, int, int, int, int, str]:
    return (
        int(record.status in TERMINAL_STATUSES),
        int(record.outcome_observed_at is not None),
        int(record.actual_arrival_utc is not None),
        int(record.actual_departure_utc is not None),
        int(record.schedule_revision is not None),
        int(record.schedule_observed_at is not None),
        record.record_id,
    )


def _schedule_signature(record: GlobalFlightRecord) -> tuple[datetime, datetime]:
    return record.scheduled_departure_utc, record.scheduled_arrival_utc


def _raise_conflict(record: GlobalFlightRecord, field: str) -> None:
    raise DedupeConflict(
        f"conflicting {field} values for {record.physical_leg_key}"
    )


def _validate_pair(current: GlobalFlightRecord, incoming: GlobalFlightRecord) -> None:
    """Reject contradictions without treating a documented revision as one."""

    if (
        current.status in TERMINAL_STATUSES
        and incoming.status in TERMINAL_STATUSES
        and current.status != incoming.status
    ):
        raise DedupeConflict(
            "conflicting terminal outcomes for "
            f"{incoming.physical_leg_key}: {current.status} vs {incoming.status}"
        )

    # These are facts about the eventual physical operation, not schedule
    # revisions.  Two non-null source claims must agree.
    for field in (
        "actual_departure_utc",
        "actual_arrival_utc",
        "outcome_observed_at",
    ):
        current_value = getattr(current, field)
        incoming_value = getattr(incoming, field)
        if (
            current_value is not None
            and incoming_value is not None
            and current_value != incoming_value
        ):
            _raise_conflict(incoming, field)

    current_schedule = _schedule_signature(current)
    incoming_schedule = _schedule_signature(incoming)
    current_revision = current.schedule_revision
    incoming_revision = incoming.schedule_revision

    if current_revision == incoming_revision:
        # The same named revision (including two legacy rows with no revision
        # identifier) cannot describe two different schedules.
        if current.scheduled_departure_utc != incoming.scheduled_departure_utc:
            _raise_conflict(incoming, "scheduled_departure_utc")
        if current.scheduled_arrival_utc != incoming.scheduled_arrival_utc:
            _raise_conflict(incoming, "scheduled_arrival_utc")
        if (
            current.schedule_observed_at is not None
            and incoming.schedule_observed_at is not None
            and current.schedule_observed_at != incoming.schedule_observed_at
        ):
            _raise_conflict(incoming, "schedule_observed_at")
        return

    if current_schedule == incoming_schedule:
        # Providers can assign a new revision identifier without changing the
        # model-visible schedule.  Selection below still uses its observation
        # time, while preserving one complete source row.
        return

    # A changed schedule is a defensible revision sequence only when both rows
    # identify their revisions and say when those exact revisions were seen.
    if (
        current_revision is None
        or incoming_revision is None
        or current.schedule_observed_at is None
        or incoming.schedule_observed_at is None
    ):
        _raise_conflict(incoming, "schedule revision metadata")
    if current.schedule_observed_at == incoming.schedule_observed_at:
        _raise_conflict(incoming, "simultaneous schedule revisions")


def _observable_at_horizon(
    record: GlobalFlightRecord,
    prediction_horizon: timedelta,
) -> bool:
    observed_at = record.schedule_observed_at
    return (
        observed_at is not None
        and observed_at <= record.scheduled_departure_utc - prediction_horizon
    )


def _select_revision(
    records: list[GlobalFlightRecord],
    prediction_horizon: timedelta,
) -> GlobalFlightRecord:
    eligible = [
        record
        for record in records
        if _observable_at_horizon(record, prediction_horizon)
    ]
    if eligible:
        # Revision identifiers are opaque.  Observation time is the only
        # provider-neutral ordering evidence, and only horizon-eligible rows
        # participate so a richer post-horizon row cannot hide an older one.
        return max(
            eligible,
            key=lambda record: (
                record.schedule_observed_at,
                _quality(record),
            ),
        )

    observed = [
        record for record in records if record.schedule_observed_at is not None
    ]
    if observed:
        # Preserve the best complete source row for the downstream point-in-time
        # validator to reject with its precise horizon error.
        return max(
            observed,
            key=lambda record: (
                record.schedule_observed_at,
                _quality(record),
            ),
        )
    return max(records, key=_quality)


def deduplicate_records(
    records: Iterable[GlobalFlightRecord],
    *,
    prediction_horizon: timedelta = timedelta(days=7),
) -> DedupeResult:
    """Keep the horizon-visible revision of each physical operating leg.

    Terminal disagreements are rejected rather than hidden by an arbitrary
    provider-row ordering.  Schedule changes are ordered by their observation
    metadata, never by a mutable departure time or opaque revision string.
    """

    if prediction_horizon < timedelta(0):
        raise ValueError("prediction horizon must not be negative")
    horizon_seconds = prediction_horizon.total_seconds()
    if not math.isfinite(horizon_seconds) or not horizon_seconds.is_integer():
        raise ValueError(
            "prediction horizon must use a finite whole number of seconds"
        )

    grouped: dict[str, list[GlobalFlightRecord]] = {}
    input_rows = 0
    for record in records:
        input_rows += 1
        grouped.setdefault(record.physical_leg_key, []).append(record)

    chosen: list[GlobalFlightRecord] = []
    for key, candidates in grouped.items():
        for index, current in enumerate(candidates):
            if current.physical_leg_key != key:
                raise RuntimeError(
                    "physical-leg grouping key changed during deduplication"
                )
            for incoming in candidates[index + 1 :]:
                _validate_pair(current, incoming)
        chosen.append(_select_revision(candidates, prediction_horizon))

    ordered = tuple(
        sorted(
            chosen,
            key=lambda row: (
                row.scheduled_departure_utc,
                row.physical_leg_key,
                row.record_id,
            ),
        )
    )
    return DedupeResult(
        records=ordered,
        input_rows=input_rows,
        duplicate_rows=input_rows - len(ordered),
    )
