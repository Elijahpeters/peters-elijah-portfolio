"""Outcome labels derived from normalized terminal flight records."""

from __future__ import annotations

from dataclasses import dataclass

from .schema import GlobalFlightRecord, TERMINAL_STATUSES


TARGET_NAMES = (
    "arrival_15",
    "arrival_30",
    "arrival_60",
    "cancelled",
    "disrupted",
)


@dataclass(frozen=True, slots=True)
class FlightLabels:
    arrival_delay_minutes: float | None
    arrival_15: bool | None
    arrival_30: bool | None
    arrival_60: bool | None
    cancelled: bool
    disrupted: bool

    def targets(self) -> dict[str, bool | None]:
        return {
            "arrival_15": self.arrival_15,
            "arrival_30": self.arrival_30,
            "arrival_60": self.arrival_60,
            "cancelled": self.cancelled,
            "disrupted": self.disrupted,
        }


def derive_labels(record: GlobalFlightRecord) -> FlightLabels:
    """Derive labels without turning cancellation or diversion into a delay."""

    if record.status not in TERMINAL_STATUSES:
        raise ValueError("training labels require a terminal flight outcome")

    arrival_delay: float | None = None
    if record.status == "landed" and record.actual_arrival_utc is not None:
        arrival_delay = (
            record.actual_arrival_utc - record.scheduled_arrival_utc
        ).total_seconds() / 60.0

    return FlightLabels(
        arrival_delay_minutes=arrival_delay,
        arrival_15=None if arrival_delay is None else arrival_delay >= 15,
        arrival_30=None if arrival_delay is None else arrival_delay >= 30,
        arrival_60=None if arrival_delay is None else arrival_delay >= 60,
        cancelled=record.status == "cancelled",
        disrupted=record.status in {"cancelled", "diverted"},
    )
