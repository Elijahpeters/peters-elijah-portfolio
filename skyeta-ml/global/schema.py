"""Canonical, provider-neutral flight outcome schema.

Provider adapters must normalize into this schema before deduplication,
feature engineering, splitting, or training.  Datetimes are UTC instants; the
local service date and timezone offsets remain explicit schedule attributes.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, fields
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping


IATA_AIRPORT_CODE = re.compile(r"^[A-Z]{3}$")
ICAO_AIRPORT_CODE = re.compile(r"^[A-Z0-9]{4}$")
CARRIER_CODE = re.compile(r"^[A-Z0-9]{2,3}$")
FLIGHT_NUMBER = re.compile(r"^[A-Z0-9]{1,6}$")
COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")
TERMINAL_STATUSES = frozenset({"landed", "cancelled", "diverted"})
ALLOWED_STATUSES = TERMINAL_STATUSES | {"scheduled"}
STATUS_ALIASES = {
    "arrived": "landed",
    "completed": "landed",
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "diverted": "diverted",
    "landed": "landed",
    "scheduled": "scheduled",
}


class SchemaError(ValueError):
    """Raised when a provider row cannot satisfy the normalized contract."""


def _text(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{field} must be a non-empty string")
    return value.strip()


def _code(
    value: Any,
    field: str,
    pattern: re.Pattern[str],
    *,
    optional: bool = False,
) -> str | None:
    text = _text(value, field, optional=optional)
    if text is None:
        return None
    normalized = text.upper().replace(" ", "")
    if not pattern.fullmatch(normalized):
        raise SchemaError(f"{field} has an invalid code: {text!r}")
    return normalized


def _airport_code(value: Any, field: str) -> str:
    """Accept an explicit IATA or ICAO airport identity without guessing.

    Three-character values are IATA identities. Four-character values are
    ICAO identities. Keeping both schemes in the canonical token lets regional
    sources retain valid ICAO-only aerodromes instead of inventing an IATA code.
    """

    text = _text(value, field)
    assert text is not None
    normalized = text.upper().replace(" ", "")
    if not (
        IATA_AIRPORT_CODE.fullmatch(normalized)
        or ICAO_AIRPORT_CODE.fullmatch(normalized)
    ):
        raise SchemaError(f"{field} has an invalid IATA/ICAO code: {text!r}")
    return normalized


def _date(value: Any, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise SchemaError(f"{field} must use YYYY-MM-DD") from error
    raise SchemaError(f"{field} must be a date or ISO date string")


def _datetime(value: Any, field: str, *, optional: bool = False) -> datetime | None:
    if value is None and optional:
        return None
    parsed: datetime
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        candidate = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as error:
            raise SchemaError(f"{field} must be an ISO datetime") from error
    else:
        raise SchemaError(f"{field} must be an aware datetime or ISO string")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SchemaError(f"{field} must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def _coordinate(value: Any, field: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise SchemaError(f"{field} must be numeric") from error
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise SchemaError(f"{field} must be between {minimum} and {maximum}")
    return parsed


def _offset(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise SchemaError(f"{field} must be an integer number of minutes")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise SchemaError(f"{field} must be an integer number of minutes") from error
    if parsed != value and not (isinstance(value, str) and str(parsed) == value.strip()):
        raise SchemaError(f"{field} must be an integer number of minutes")
    if not -14 * 60 <= parsed <= 14 * 60:
        raise SchemaError(f"{field} is outside the supported UTC offset range")
    return parsed


@dataclass(frozen=True, slots=True)
class GlobalFlightRecord:
    """One scheduled operating leg and its eventual outcome.

    Marketing flight identifiers are provenance only.  Identity, deduplication,
    and model history always use the operating carrier and flight number.
    """

    record_id: str
    service_date: date
    operating_carrier: str
    operating_flight_number: str
    marketing_carrier: str | None
    marketing_flight_number: str | None
    origin: str
    destination: str
    scheduled_departure_utc: datetime
    scheduled_arrival_utc: datetime
    schedule_observed_at: datetime | None
    schedule_revision: str | None
    actual_departure_utc: datetime | None
    actual_arrival_utc: datetime | None
    outcome_observed_at: datetime | None
    status: str
    origin_latitude: float
    origin_longitude: float
    destination_latitude: float
    destination_longitude: float
    origin_country: str
    destination_country: str
    origin_region: str
    destination_region: str
    origin_timezone_offset_minutes: int
    destination_timezone_offset_minutes: int
    aircraft_family: str | None
    source: str

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "GlobalFlightRecord":
        """Normalize and validate one provider mapping without mutating it."""

        raw_status = _text(row.get("status"), "status")
        assert raw_status is not None
        status = STATUS_ALIASES.get(raw_status.lower())
        if status not in ALLOWED_STATUSES:
            raise SchemaError(f"status is not recognized: {raw_status!r}")

        scheduled_departure = _datetime(
            row.get("scheduled_departure_utc"), "scheduled_departure_utc"
        )
        scheduled_arrival = _datetime(
            row.get("scheduled_arrival_utc"), "scheduled_arrival_utc"
        )
        assert scheduled_departure is not None and scheduled_arrival is not None
        scheduled_minutes = (scheduled_arrival - scheduled_departure).total_seconds() / 60
        if not 0 < scheduled_minutes <= 36 * 60:
            raise SchemaError("scheduled duration must be greater than 0 and at most 36 hours")

        origin = _airport_code(row.get("origin"), "origin")
        destination = _airport_code(row.get("destination"), "destination")
        if origin == destination:
            raise SchemaError("origin and destination must differ")

        actual_departure = _datetime(
            row.get("actual_departure_utc"), "actual_departure_utc", optional=True
        )
        actual_arrival = _datetime(
            row.get("actual_arrival_utc"), "actual_arrival_utc", optional=True
        )
        schedule_observed_at = _datetime(
            row.get("schedule_observed_at"), "schedule_observed_at", optional=True
        )
        outcome_observed_at = _datetime(
            row.get("outcome_observed_at"), "outcome_observed_at", optional=True
        )
        if actual_departure and actual_arrival and actual_arrival < actual_departure:
            raise SchemaError("actual arrival cannot precede actual departure")
        if status == "landed" and actual_arrival is None:
            # Providers may legitimately have incomplete landed rows.  Keep them
            # for cancellation/disruption labels but not arrival-delay labels.
            pass
        if status in {"cancelled", "scheduled"} and actual_arrival is not None:
            raise SchemaError(f"{status} rows cannot contain an actual arrival")
        if status == "scheduled" and outcome_observed_at is not None:
            raise SchemaError("scheduled rows cannot contain an observed terminal outcome")
        if (
            status == "landed"
            and actual_arrival is not None
            and outcome_observed_at is not None
            and outcome_observed_at < actual_arrival
        ):
            raise SchemaError("landed outcome cannot be observed before actual arrival")
        if (
            status == "diverted"
            and actual_departure is not None
            and outcome_observed_at is not None
            and outcome_observed_at < actual_departure
        ):
            raise SchemaError("diversion outcome cannot be observed before actual departure")

        service_date = _date(row.get("service_date"), "service_date")
        origin_offset = _offset(
            row.get("origin_timezone_offset_minutes"),
            "origin_timezone_offset_minutes",
        )
        destination_offset = _offset(
            row.get("destination_timezone_offset_minutes"),
            "destination_timezone_offset_minutes",
        )
        origin_local_date = (
            scheduled_departure + timedelta(minutes=origin_offset)
        ).date()
        if service_date != origin_local_date:
            raise SchemaError(
                "service_date must equal the origin-local scheduled departure date"
            )

        return cls(
            record_id=_text(row.get("record_id"), "record_id") or "",
            service_date=service_date,
            operating_carrier=_code(
                row.get("operating_carrier"), "operating_carrier", CARRIER_CODE
            )
            or "",
            operating_flight_number=_code(
                row.get("operating_flight_number"),
                "operating_flight_number",
                FLIGHT_NUMBER,
            )
            or "",
            marketing_carrier=_code(
                row.get("marketing_carrier"),
                "marketing_carrier",
                CARRIER_CODE,
                optional=True,
            ),
            marketing_flight_number=_code(
                row.get("marketing_flight_number"),
                "marketing_flight_number",
                FLIGHT_NUMBER,
                optional=True,
            ),
            origin=origin or "",
            destination=destination or "",
            scheduled_departure_utc=scheduled_departure,
            scheduled_arrival_utc=scheduled_arrival,
            schedule_observed_at=schedule_observed_at,
            schedule_revision=_text(
                row.get("schedule_revision"), "schedule_revision", optional=True
            ),
            actual_departure_utc=actual_departure,
            actual_arrival_utc=actual_arrival,
            outcome_observed_at=outcome_observed_at,
            status=status,
            origin_latitude=_coordinate(
                row.get("origin_latitude"), "origin_latitude", -90, 90
            ),
            origin_longitude=_coordinate(
                row.get("origin_longitude"), "origin_longitude", -180, 180
            ),
            destination_latitude=_coordinate(
                row.get("destination_latitude"), "destination_latitude", -90, 90
            ),
            destination_longitude=_coordinate(
                row.get("destination_longitude"), "destination_longitude", -180, 180
            ),
            origin_country=_code(
                row.get("origin_country"), "origin_country", COUNTRY_CODE
            )
            or "",
            destination_country=_code(
                row.get("destination_country"), "destination_country", COUNTRY_CODE
            )
            or "",
            origin_region=_text(row.get("origin_region"), "origin_region") or "",
            destination_region=_text(
                row.get("destination_region"), "destination_region"
            )
            or "",
            origin_timezone_offset_minutes=origin_offset,
            destination_timezone_offset_minutes=destination_offset,
            aircraft_family=_text(
                row.get("aircraft_family"), "aircraft_family", optional=True
            ),
            source=_text(row.get("source"), "source") or "",
        )

    @property
    def canonical_key(self) -> str:
        """Schedule-specific key used for deterministic row ordering."""

        departure = self.scheduled_departure_utc.isoformat().replace("+00:00", "Z")
        return "|".join(
            (
                self.service_date.isoformat(),
                self.operating_carrier,
                self.operating_flight_number,
                self.origin,
                self.destination,
                departure,
            )
        )

    @property
    def origin_code_scheme(self) -> str:
        """The namespace carried by ``origin`` (``iata`` or ``icao``)."""

        return "iata" if len(self.origin) == 3 else "icao"

    @property
    def destination_code_scheme(self) -> str:
        """The namespace carried by ``destination`` (``iata`` or ``icao``)."""

        return "iata" if len(self.destination) == 3 else "icao"

    @property
    def physical_leg_key(self) -> str:
        """Schedule-revision-independent operating-leg identity.

        A published departure time is mutable and therefore cannot identify a
        physical operation across schedule snapshots.  The service date,
        operating identity, and route are the strongest provider-neutral key
        available in this schema.  Deduplication treats schedule disagreements
        within this key as revisions only when their revision metadata makes
        that interpretation defensible; otherwise it fails closed.
        """

        return "|".join(
            (
                self.service_date.isoformat(),
                self.operating_carrier,
                self.operating_flight_number,
                self.origin,
                self.destination,
            )
        )

    @property
    def route_key(self) -> str:
        return f"{self.origin}>{self.destination}"

    @property
    def carrier_route_key(self) -> str:
        return f"{self.operating_carrier}|{self.route_key}"

    @property
    def flight_route_key(self) -> str:
        return (
            f"{self.operating_carrier}{self.operating_flight_number}|{self.route_key}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}


def normalize_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[GlobalFlightRecord, ...]:
    """Normalize an iterable eagerly so a bad provider row fails before training."""

    return tuple(GlobalFlightRecord.from_mapping(row) for row in rows)
