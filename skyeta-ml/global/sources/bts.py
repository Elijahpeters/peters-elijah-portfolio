"""U.S. BTS On-Time Performance adapter for the global flight schema.

The BTS monthly files store gate times as airport-local ``HHMM`` clocks.  A
clock alone does not identify an instant, so this adapter requires the caller
to supply an IANA timezone for every airport.  Scheduled elapsed time and the
published delay/elapsed fields are used as consistency constraints when
resolving midnight and daylight-saving transitions; an offset is never guessed.

The module has no download side effects.  Archive provenance includes the
official URL, a caller-supplied retrieval timestamp, and locally computed file
hash/size/member metadata.  Non-strict ingestion requires an audit object so no
rejected row can disappear silently.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Iterator, Mapping, TextIO, TypedDict
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


BTS_SOURCE_ID = "us_bts_otp"
BTS_PUBLISHER = "U.S. Bureau of Transportation Statistics"
BTS_DATASET_NAME = "Reporting Carrier On-Time Performance (1987-present)"
BTS_BASE_URL = "https://transtats.bts.gov/PREZIP"
BTS_DOCUMENTATION_URL = "https://www.transtats.bts.gov/"
BTS_ARCHIVE_PATTERN = (
    "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip"
)
BTS_ENCODING = "utf-8-sig"

_IATA = re.compile(r"^[A-Z]{3}$")
_CARRIER = re.compile(r"^[A-Z0-9]{2,3}$")
_FLIGHT_NUMBER = re.compile(r"^[A-Z0-9]{1,6}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_ARCHIVE_FILENAME = re.compile(
    r"^On_Time_Reporting_Carrier_On_Time_Performance_1987_present_"
    r"(\d{4})_(0?[1-9]|1[0-2])\.zip$"
)
_CSV_FILENAME = re.compile(
    r"^On_Time_Reporting_Carrier_On_Time_Performance_\(1987_present\)_"
    r"(\d{4})_(0?[1-9]|1[0-2])\.csv$"
)
_OFFICIAL_PATH = re.compile(
    r"^/PREZIP/On_Time_Reporting_Carrier_On_Time_Performance_1987_present_"
    r"(\d{4})_(0?[1-9]|1[0-2])\.zip$"
)

_REQUIRED_FIELDS = frozenset(
    {
        "Year",
        "Month",
        "DayofMonth",
        "FlightDate",
        "Reporting_Airline",
        "Flight_Number_Reporting_Airline",
        "Origin",
        "Dest",
        "CRSDepTime",
        "CRSArrTime",
        "CRSElapsedTime",
        "DepTime",
        "DepDelay",
        "ArrTime",
        "ArrDelay",
        "Cancelled",
        "Diverted",
        "ActualElapsedTime",
        "DivReachedDest",
        "DivActualElapsedTime",
        "DivArrDelay",
    }
)

if TYPE_CHECKING:
    from ..schema import GlobalFlightRecord


class BtsRowError(ValueError):
    """A BTS row cannot be normalized without guessing or contradiction."""


@dataclass(frozen=True, slots=True)
class AirportMetadata:
    """Caller-supplied airport facts needed by ``GlobalFlightRecord``.

    ``timezone_name`` is deliberately mandatory.  Coordinates cannot be used to
    safely infer a civil timezone, particularly near borders or for historical
    daylight-saving rules.
    """

    iata: str
    latitude: float
    longitude: float
    country_code: str
    region_code: str
    timezone_name: str

    def __post_init__(self) -> None:
        iata = _clean_text(self.iata, "airport iata").upper()
        country = _clean_text(self.country_code, "airport country_code").upper()
        region = _clean_text(self.region_code, "airport region_code")
        timezone_name = _clean_text(self.timezone_name, "airport timezone_name")
        if not _IATA.fullmatch(iata):
            raise ValueError(f"Invalid airport IATA code: {self.iata!r}")
        if not _COUNTRY.fullmatch(country):
            raise ValueError(f"Invalid airport country code: {self.country_code!r}")
        latitude = _coordinate(self.latitude, "airport latitude", -90, 90)
        longitude = _coordinate(self.longitude, "airport longitude", -180, 180)
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"Unknown airport timezone: {timezone_name!r}") from error
        object.__setattr__(self, "iata", iata)
        object.__setattr__(self, "latitude", latitude)
        object.__setattr__(self, "longitude", longitude)
        object.__setattr__(self, "country_code", country)
        object.__setattr__(self, "region_code", region)
        object.__setattr__(self, "timezone_name", timezone_name)


BtsAirportMetadata = AirportMetadata


class NormalizedFlightMapping(TypedDict):
    record_id: str
    service_date: date
    operating_carrier: str
    operating_flight_number: str
    marketing_carrier: None
    marketing_flight_number: None
    origin: str
    destination: str
    scheduled_departure_utc: datetime
    scheduled_arrival_utc: datetime
    schedule_observed_at: None
    schedule_revision: None
    actual_departure_utc: datetime | None
    actual_arrival_utc: datetime | None
    outcome_observed_at: None
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
    aircraft_family: None
    source: str


@dataclass(frozen=True, slots=True)
class BtsRejectedRow:
    row_number: int
    reason: str
    record_hint: str


@dataclass(frozen=True, slots=True)
class BtsArchiveProvenance:
    """Reproducibility facts that can be known from a cached monthly archive."""

    source_id: str
    source_provider: str
    product_name: str
    source_url: str
    documentation_url: str
    year: int
    month: int
    archive_path: str
    archive_filename: str
    csv_member: str
    retrieved_at_utc: datetime
    raw_file_sha256: str
    raw_bytes: int

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["retrieved_at_utc"] = self.retrieved_at_utc.isoformat().replace(
            "+00:00", "Z"
        )
        return result


@dataclass(slots=True)
class BtsIngestionAudit:
    """Mutable accounting record populated while a CSV/archive is consumed."""

    source_url: str | None = None
    provenance: BtsArchiveProvenance | None = None
    raw_row_count: int = 0
    accepted_row_count: int = 0
    rejected_rows: list[BtsRejectedRow] = field(default_factory=list)
    completed: bool = False

    @property
    def rejected_row_count(self) -> int:
        return len(self.rejected_rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "provenance": (
                self.provenance.to_dict() if self.provenance is not None else None
            ),
            "raw_row_count": self.raw_row_count,
            "accepted_row_count": self.accepted_row_count,
            "rejected_row_count": self.rejected_row_count,
            "completed": self.completed,
            "rejected_rows": [asdict(rejected) for rejected in self.rejected_rows],
        }


@dataclass(frozen=True, slots=True)
class _Clock:
    hour: int
    minute: int
    next_day: bool = False


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return isinstance(value, float) and math.isnan(value)


def _clean_text(value: object, field_name: str) -> str:
    if _is_blank(value):
        raise ValueError(f"{field_name} is required")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _required(row: Mapping[str, object], field_name: str) -> object:
    if field_name not in row or _is_blank(row[field_name]):
        raise BtsRowError(f"Missing required BTS field: {field_name}")
    return row[field_name]


def _coordinate(
    value: object, field_name: str, minimum: float, maximum: float
) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be numeric") from error
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise ValueError(f"{field_name} must be within [{minimum}, {maximum}]")
    return parsed


def _decimal(value: object, field_name: str, *, required: bool) -> Decimal | None:
    if _is_blank(value):
        if required:
            raise BtsRowError(f"Missing required BTS field: {field_name}")
        return None
    if isinstance(value, bool):
        raise BtsRowError(f"{field_name} must be numeric")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as error:
        raise BtsRowError(
            f"Invalid numeric value in {field_name}: {value!r}"
        ) from error
    if not parsed.is_finite():
        raise BtsRowError(f"Invalid numeric value in {field_name}: {value!r}")
    return parsed


def _integer(value: object, field_name: str, *, required: bool = True) -> int | None:
    parsed = _decimal(value, field_name, required=required)
    if parsed is None:
        return None
    integral = parsed.to_integral_value()
    if parsed != integral:
        raise BtsRowError(f"{field_name} must be a whole number")
    return int(integral)


def _minutes(
    value: object,
    field_name: str,
    *,
    required: bool,
    positive: bool = False,
) -> int | None:
    parsed = _integer(value, field_name, required=required)
    if parsed is None:
        return None
    if positive and parsed <= 0:
        raise BtsRowError(f"{field_name} must be greater than zero")
    return parsed


def _flag(value: object, field_name: str, *, required: bool = True) -> bool | None:
    parsed = _integer(value, field_name, required=required)
    if parsed is None:
        return None
    if parsed not in {0, 1}:
        raise BtsRowError(f"{field_name} must be 0 or 1")
    return bool(parsed)


def _clock(value: object, field_name: str, *, required: bool) -> _Clock | None:
    parsed = _integer(value, field_name, required=required)
    if parsed is None:
        return None
    if parsed == 2400:
        return _Clock(0, 0, next_day=True)
    if not 0 <= parsed <= 2359 or parsed % 100 >= 60:
        raise BtsRowError(f"Invalid HHMM value in {field_name}: {value!r}")
    return _Clock(parsed // 100, parsed % 100)


def _flight_date(row: Mapping[str, object]) -> date:
    raw_date = str(_required(row, "FlightDate")).strip()
    try:
        parsed = date.fromisoformat(raw_date)
    except ValueError as error:
        raise BtsRowError(f"FlightDate must use YYYY-MM-DD: {raw_date!r}") from error
    year = _integer(_required(row, "Year"), "Year")
    month = _integer(_required(row, "Month"), "Month")
    day = _integer(_required(row, "DayofMonth"), "DayofMonth")
    if (year, month, day) != (parsed.year, parsed.month, parsed.day):
        raise BtsRowError("Year/Month/DayofMonth do not match FlightDate")
    return parsed


def _wall_candidates(
    local_date: date,
    clock: _Clock,
    zone: ZoneInfo,
) -> tuple[datetime, ...]:
    if clock.next_day:
        local_date += timedelta(days=1)
    wall = datetime.combine(local_date, time(clock.hour, clock.minute))
    candidates: set[datetime] = set()
    for fold in (0, 1):
        aware = wall.replace(tzinfo=zone, fold=fold)
        utc_value = aware.astimezone(timezone.utc)
        if utc_value.astimezone(zone).replace(tzinfo=None) == wall:
            candidates.add(utc_value)
    return tuple(sorted(candidates))


def _clock_matches(instant: datetime, clock: _Clock, zone: ZoneInfo) -> bool:
    local = instant.astimezone(zone)
    return (local.hour, local.minute) == (clock.hour, clock.minute)


def _scheduled_instants(
    flight_date: date,
    departure_clock: _Clock,
    arrival_clock: _Clock,
    elapsed_minutes: int,
    origin_zone: ZoneInfo,
    destination_zone: ZoneInfo,
) -> tuple[datetime, datetime]:
    if not 0 < elapsed_minutes <= 36 * 60:
        raise BtsRowError("CRSElapsedTime must be greater than 0 and at most 2160")
    matches: set[tuple[datetime, datetime]] = set()
    for departure in _wall_candidates(flight_date, departure_clock, origin_zone):
        arrival = departure + timedelta(minutes=elapsed_minutes)
        if _clock_matches(arrival, arrival_clock, destination_zone):
            matches.add((departure, arrival))
    if not matches:
        raise BtsRowError(
            "Scheduled local clocks, airport timezones, and CRSElapsedTime disagree"
        )
    if len(matches) != 1:
        raise BtsRowError(
            "Scheduled timestamps are ambiguous at a timezone transition"
        )
    return matches.pop()


def _actual_from_delay(
    row: Mapping[str, object],
    *,
    clock_field: str,
    delay_field: str,
    scheduled: datetime,
    zone: ZoneInfo,
    required: bool,
) -> datetime | None:
    clock = _clock(row.get(clock_field), clock_field, required=required)
    delay = _minutes(row.get(delay_field), delay_field, required=required)
    if clock is None and delay is None:
        return None
    if clock is None or delay is None:
        raise BtsRowError(
            f"{clock_field} and {delay_field} must either both be present "
            "or both be blank"
        )
    actual = scheduled + timedelta(minutes=delay)
    if not _clock_matches(actual, clock, zone):
        raise BtsRowError(
            f"{clock_field} disagrees with {delay_field} after timezone normalization"
        )
    return actual


def _elapsed_between(
    departure: datetime,
    arrival: datetime,
    published_minutes: int,
    field_name: str,
) -> None:
    actual_seconds = (arrival - departure).total_seconds()
    if actual_seconds <= 0:
        raise BtsRowError("Actual arrival must be after actual departure")
    if actual_seconds != published_minutes * 60:
        raise BtsRowError(
            f"{field_name} disagrees with normalized actual departure/arrival"
        )


def _airport_metadata(
    airports: Mapping[str, AirportMetadata], raw_code: object, field_name: str
) -> AirportMetadata:
    code = str(_required({field_name: raw_code}, field_name)).strip().upper()
    if not _IATA.fullmatch(code):
        raise BtsRowError(f"Invalid IATA airport code in {field_name}: {raw_code!r}")
    airport = airports.get(code)
    if airport is None:
        raise BtsRowError(f"No airport metadata for {code}; timezone was not inferred")
    if not isinstance(airport, AirportMetadata):
        raise BtsRowError(f"Airport metadata for {code} must be AirportMetadata")
    if airport.iata != code:
        raise BtsRowError(f"Airport metadata key/code mismatch for {code}")
    return airport


def _offset_minutes(airport: AirportMetadata, instant: datetime) -> int:
    offset = instant.astimezone(ZoneInfo(airport.timezone_name)).utcoffset()
    if offset is None:
        raise BtsRowError(f"Timezone offset unavailable for {airport.iata}")
    return int(offset.total_seconds() // 60)


def _carrier_and_flight(row: Mapping[str, object]) -> tuple[str, str]:
    carrier = str(_required(row, "Reporting_Airline")).strip().upper().replace(" ", "")
    if not _CARRIER.fullmatch(carrier):
        raise BtsRowError(f"Invalid BTS reporting carrier: {carrier!r}")
    supplied_iata = row.get("IATA_CODE_Reporting_Airline")
    if not _is_blank(supplied_iata):
        iata = str(supplied_iata).strip().upper().replace(" ", "")
        if iata != carrier:
            raise BtsRowError(
                "IATA_CODE_Reporting_Airline disagrees with Reporting_Airline"
            )

    raw_flight = _required(row, "Flight_Number_Reporting_Airline")
    if isinstance(raw_flight, str) and re.fullmatch(
        r"\s*[A-Za-z0-9]{1,6}\s*", raw_flight
    ):
        flight_number = raw_flight.strip().upper()
    else:
        parsed = _integer(raw_flight, "Flight_Number_Reporting_Airline")
        assert parsed is not None
        flight_number = str(parsed)
    if not _FLIGHT_NUMBER.fullmatch(flight_number):
        raise BtsRowError(f"Invalid BTS flight number: {flight_number!r}")
    return carrier, flight_number


def _record_id(
    row: Mapping[str, object],
    *,
    carrier: str,
    flight_number: str,
    origin: str,
    destination: str,
    scheduled_departure: datetime,
) -> str:
    identity = "|".join(
        (
            str(row.get("DOT_ID_Reporting_Airline", "")).strip(),
            carrier,
            flight_number,
            origin,
            destination,
            scheduled_departure.isoformat(),
            str(row.get("OriginAirportID", "")).strip(),
            str(row.get("DestAirportID", "")).strip(),
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"bts-otp-{digest}"


def _validate_year_month(year: int, month: int) -> None:
    if isinstance(year, bool) or not isinstance(year, int) or not 1987 <= year <= 9999:
        raise ValueError("year must be an integer from 1987 through 9999")
    if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
        raise ValueError("month must be an integer from 1 through 12")


def build_ontime_url(year: int, month: int) -> str:
    """Return the official PREZIP URL for one BTS monthly archive."""

    _validate_year_month(year, month)
    filename = BTS_ARCHIVE_PATTERN.format(year=year, month=month)
    return f"{BTS_BASE_URL}/{filename}"


def _validate_source_url(source_url: str) -> tuple[str, int, int]:
    parsed = urlparse(source_url)
    match = _OFFICIAL_PATH.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "transtats.bts.gov"
        or parsed.port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        raise ValueError("source_url must be an official monthly BTS PREZIP HTTPS URL")
    year, month = int(match.group(1)), int(match.group(2))
    _validate_year_month(year, month)
    return source_url, year, month


def parse_bts_row(
    raw_row: Mapping[str, object],
    airports: Mapping[str, AirportMetadata],
    *,
    source_url: str,
) -> NormalizedFlightMapping:
    """Normalize one BTS row into the shared schema's snake-case mapping."""

    source, source_year, source_month = _validate_source_url(source_url)
    missing_columns = sorted(_REQUIRED_FIELDS - raw_row.keys())
    if missing_columns:
        raise BtsRowError(
            "BTS row is missing required columns: " + ", ".join(missing_columns)
        )
    if None in raw_row:
        raise BtsRowError("BTS row contains more values than its CSV header")

    service_partition_date = _flight_date(raw_row)
    if (service_partition_date.year, service_partition_date.month) != (
        source_year,
        source_month,
    ):
        raise BtsRowError("FlightDate does not belong to the source archive month")

    carrier, flight_number = _carrier_and_flight(raw_row)
    origin = _airport_metadata(airports, raw_row["Origin"], "Origin")
    destination = _airport_metadata(airports, raw_row["Dest"], "Dest")
    if origin.iata == destination.iata:
        raise BtsRowError("Origin and destination airports must differ")
    origin_zone = ZoneInfo(origin.timezone_name)
    destination_zone = ZoneInfo(destination.timezone_name)

    departure_clock = _clock(raw_row["CRSDepTime"], "CRSDepTime", required=True)
    arrival_clock = _clock(raw_row["CRSArrTime"], "CRSArrTime", required=True)
    scheduled_elapsed = _minutes(
        raw_row["CRSElapsedTime"], "CRSElapsedTime", required=True, positive=True
    )
    assert departure_clock is not None
    assert arrival_clock is not None
    assert scheduled_elapsed is not None
    scheduled_departure, scheduled_arrival = _scheduled_instants(
        service_partition_date,
        departure_clock,
        arrival_clock,
        scheduled_elapsed,
        origin_zone,
        destination_zone,
    )

    cancelled = _flag(raw_row["Cancelled"], "Cancelled")
    diverted = _flag(raw_row["Diverted"], "Diverted")
    assert cancelled is not None and diverted is not None
    if cancelled and diverted:
        raise BtsRowError("A BTS row cannot be both cancelled and diverted")

    actual_departure = _actual_from_delay(
        raw_row,
        clock_field="DepTime",
        delay_field="DepDelay",
        scheduled=scheduled_departure,
        zone=origin_zone,
        required=not cancelled,
    )
    actual_arrival: datetime | None = None
    if cancelled:
        status = "cancelled"
        for field_name in ("ArrTime", "ArrDelay", "ActualElapsedTime"):
            if not _is_blank(raw_row[field_name]):
                raise BtsRowError(f"Cancelled row must not contain {field_name}")
    elif diverted:
        status = "diverted"
        if not _is_blank(raw_row["ArrDelay"]):
            raise BtsRowError("Diverted row must use DivArrDelay, not ArrDelay")
        if not _is_blank(raw_row["ActualElapsedTime"]):
            raise BtsRowError(
                "Diverted row must use DivActualElapsedTime, not ActualElapsedTime"
            )
        reached_destination = _flag(
            raw_row["DivReachedDest"], "DivReachedDest", required=True
        )
        assert reached_destination is not None
        if reached_destination:
            arrival_clock_actual = _clock(
                raw_row["ArrTime"], "ArrTime", required=True
            )
            diversion_delay = _minutes(
                raw_row["DivArrDelay"], "DivArrDelay", required=True
            )
            diversion_elapsed = _minutes(
                raw_row["DivActualElapsedTime"],
                "DivActualElapsedTime",
                required=True,
                positive=True,
            )
            assert arrival_clock_actual is not None
            assert diversion_delay is not None
            assert diversion_elapsed is not None
            actual_arrival = scheduled_arrival + timedelta(minutes=diversion_delay)
            if not _clock_matches(
                actual_arrival, arrival_clock_actual, destination_zone
            ):
                raise BtsRowError(
                    "ArrTime disagrees with DivArrDelay after timezone normalization"
                )
            assert actual_departure is not None
            _elapsed_between(
                actual_departure,
                actual_arrival,
                diversion_elapsed,
                "DivActualElapsedTime",
            )
        else:
            for field_name in ("ArrTime", "DivArrDelay", "DivActualElapsedTime"):
                if not _is_blank(raw_row[field_name]):
                    raise BtsRowError(
                        "Diversion that did not reach Dest must not contain "
                        f"{field_name}"
                    )
    else:
        status = "landed"
        actual_arrival = _actual_from_delay(
            raw_row,
            clock_field="ArrTime",
            delay_field="ArrDelay",
            scheduled=scheduled_arrival,
            zone=destination_zone,
            required=True,
        )
        actual_elapsed = _minutes(
            raw_row["ActualElapsedTime"],
            "ActualElapsedTime",
            required=True,
            positive=True,
        )
        assert actual_departure is not None
        assert actual_arrival is not None
        assert actual_elapsed is not None
        _elapsed_between(
            actual_departure, actual_arrival, actual_elapsed, "ActualElapsedTime"
        )

    return {
        "record_id": _record_id(
            raw_row,
            carrier=carrier,
            flight_number=flight_number,
            origin=origin.iata,
            destination=destination.iata,
            scheduled_departure=scheduled_departure,
        ),
        "service_date": scheduled_departure.astimezone(origin_zone).date(),
        "operating_carrier": carrier,
        "operating_flight_number": flight_number,
        # This BTS product has one reporting/operating identity and does not
        # provide a trustworthy marketing-flight mapping for each physical leg.
        "marketing_carrier": None,
        "marketing_flight_number": None,
        "origin": origin.iata,
        "destination": destination.iata,
        "scheduled_departure_utc": scheduled_departure,
        "scheduled_arrival_utc": scheduled_arrival,
        # Retrospective monthly BTS files do not state when this schedule was
        # first visible (or which revision it represents).  In particular, the
        # archive cannot prove availability at a fixed T-7-day prediction
        # horizon, so downstream fixed-horizon training must fail closed.
        "schedule_observed_at": None,
        "schedule_revision": None,
        "actual_departure_utc": actual_departure,
        "actual_arrival_utc": actual_arrival,
        # The final row gives an outcome but no notification/publication time;
        # neither arrival time nor archive retrieval time is a valid substitute.
        "outcome_observed_at": None,
        "status": status,
        "origin_latitude": origin.latitude,
        "origin_longitude": origin.longitude,
        "destination_latitude": destination.latitude,
        "destination_longitude": destination.longitude,
        "origin_country": origin.country_code,
        "destination_country": destination.country_code,
        "origin_region": origin.region_code,
        "destination_region": destination.region_code,
        "origin_timezone_offset_minutes": _offset_minutes(
            origin, scheduled_departure
        ),
        "destination_timezone_offset_minutes": _offset_minutes(
            destination, scheduled_arrival
        ),
        # Tail_Number identifies one airframe, not an aircraft family.
        "aircraft_family": None,
        "source": source,
    }


def parse_bts_record(
    raw_row: Mapping[str, object],
    airports: Mapping[str, AirportMetadata],
    *,
    source_url: str,
) -> "GlobalFlightRecord":
    """Construct a fully validated ``GlobalFlightRecord`` from one BTS row."""

    from ..schema import GlobalFlightRecord

    return GlobalFlightRecord.from_mapping(
        parse_bts_row(raw_row, airports, source_url=source_url)
    )


def _record_hint(row: Mapping[str | None, object]) -> str:
    values = (
        str(row.get("FlightDate") or "?").strip(),
        str(row.get("Reporting_Airline") or "?").strip(),
        str(row.get("Flight_Number_Reporting_Airline") or "?").strip(),
        str(row.get("Origin") or "?").strip(),
        str(row.get("Dest") or "?").strip(),
    )
    return "|".join(values)


def _start_audit(
    audit: BtsIngestionAudit,
    source_url: str,
    provenance: BtsArchiveProvenance | None,
) -> None:
    if (
        audit.source_url is not None
        or audit.provenance is not None
        or audit.raw_row_count
        or audit.accepted_row_count
        or audit.rejected_rows
        or audit.completed
    ):
        raise ValueError("BtsIngestionAudit instances cannot be reused")
    audit.source_url = source_url
    audit.provenance = provenance


def _iter_csv(
    stream: TextIO,
    airports: Mapping[str, AirportMetadata],
    *,
    source_url: str,
    strict: bool,
    audit: BtsIngestionAudit,
) -> Iterator[NormalizedFlightMapping]:
    reader = csv.DictReader(stream)
    if reader.fieldnames is None:
        raise BtsRowError("BTS CSV has no header row")
    duplicate_headers = sorted(
        {
            name
            for name in reader.fieldnames
            if name and reader.fieldnames.count(name) > 1
        }
    )
    if duplicate_headers:
        raise BtsRowError(
            "BTS CSV has duplicate columns: " + ", ".join(duplicate_headers)
        )
    missing = sorted(_REQUIRED_FIELDS - set(reader.fieldnames))
    if missing:
        raise BtsRowError("BTS CSV is missing required columns: " + ", ".join(missing))

    for row_number, raw_row in enumerate(reader, start=2):
        audit.raw_row_count += 1
        try:
            normalized = parse_bts_row(raw_row, airports, source_url=source_url)
        except BtsRowError as error:
            rejection = BtsRejectedRow(row_number, str(error), _record_hint(raw_row))
            audit.rejected_rows.append(rejection)
            if strict:
                raise BtsRowError(f"BTS CSV row {row_number}: {error}") from error
            continue
        audit.accepted_row_count += 1
        yield normalized
    audit.completed = True


def iter_bts_csv(
    stream: TextIO,
    airports: Mapping[str, AirportMetadata],
    *,
    source_url: str,
    strict: bool = True,
    audit: BtsIngestionAudit | None = None,
) -> Iterator[NormalizedFlightMapping]:
    """Stream a BTS CSV, requiring durable rejection accounting if non-strict."""

    source, _, _ = _validate_source_url(source_url)
    if not strict and audit is None:
        raise ValueError("non-strict BTS parsing requires a BtsIngestionAudit")
    active_audit = audit if audit is not None else BtsIngestionAudit()
    _start_audit(active_audit, source, None)
    yield from _iter_csv(
        stream,
        airports,
        source_url=source,
        strict=strict,
        audit=active_audit,
    )


def _retrieval_time(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("retrieved_at_utc must be an aware datetime")
    return value.astimezone(timezone.utc)


def _archive_member(archive: zipfile.ZipFile, year: int, month: int) -> str:
    candidates = []
    for info in archive.infolist():
        member_path = PurePosixPath(info.filename)
        if (
            info.is_dir()
            or member_path.is_absolute()
            or ".." in member_path.parts
            or member_path.suffix.lower() != ".csv"
            or "readme" in member_path.name.lower()
        ):
            continue
        candidates.append(info)
    if len(candidates) != 1:
        raise BtsRowError(
            f"BTS archive must contain exactly one flight CSV; found {len(candidates)}"
        )
    info = candidates[0]
    match = _CSV_FILENAME.fullmatch(PurePosixPath(info.filename).name)
    if match is None or (int(match.group(1)), int(match.group(2))) != (year, month):
        raise BtsRowError("BTS CSV member does not match the archive year/month")
    if info.flag_bits & 0x1:
        raise BtsRowError("Encrypted BTS CSV members are not supported")
    return info.filename


def _validate_header(fieldnames: list[str] | None) -> None:
    if fieldnames is None:
        raise BtsRowError("BTS CSV has no header row")
    missing = sorted(_REQUIRED_FIELDS - set(fieldnames))
    if missing:
        raise BtsRowError("BTS CSV is missing required columns: " + ", ".join(missing))


def inspect_bts_archive(
    archive_path: Path,
    *,
    retrieved_at_utc: datetime,
) -> BtsArchiveProvenance:
    """Validate one cached archive and compute reproducible static provenance."""

    path = archive_path.resolve()
    match = _ARCHIVE_FILENAME.fullmatch(path.name)
    if match is None:
        raise ValueError("archive filename is not an official BTS monthly filename")
    year, month = int(match.group(1)), int(match.group(2))
    _validate_year_month(year, month)
    retrieved = _retrieval_time(retrieved_at_utc)
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        with zipfile.ZipFile(path) as archive:
            member = _archive_member(archive, year, month)
            with archive.open(member) as source:
                header_line = source.readline().decode(BTS_ENCODING)
            _validate_header(next(csv.reader([header_line]), None))
    except zipfile.BadZipFile as error:
        raise BtsRowError(f"Invalid BTS ZIP archive: {path}") from error
    except UnicodeDecodeError as error:
        raise BtsRowError("BTS CSV header is not valid UTF-8") from error

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    source_url = build_ontime_url(year, month)
    return BtsArchiveProvenance(
        source_id=BTS_SOURCE_ID,
        source_provider=BTS_PUBLISHER,
        product_name=BTS_DATASET_NAME,
        source_url=source_url,
        documentation_url=BTS_DOCUMENTATION_URL,
        year=year,
        month=month,
        archive_path=str(path),
        archive_filename=path.name,
        csv_member=member,
        retrieved_at_utc=retrieved,
        raw_file_sha256=digest.hexdigest(),
        raw_bytes=path.stat().st_size,
    )


def iter_bts_archive(
    archive_path: Path,
    airports: Mapping[str, AirportMetadata],
    *,
    retrieved_at_utc: datetime,
    strict: bool = True,
    audit: BtsIngestionAudit | None = None,
) -> Iterator[NormalizedFlightMapping]:
    """Stream an official monthly ZIP while attaching archive provenance."""

    if not strict and audit is None:
        raise ValueError("non-strict BTS parsing requires a BtsIngestionAudit")
    provenance = inspect_bts_archive(
        archive_path, retrieved_at_utc=retrieved_at_utc
    )
    active_audit = audit if audit is not None else BtsIngestionAudit()
    _start_audit(active_audit, provenance.source_url, provenance)
    try:
        with zipfile.ZipFile(Path(provenance.archive_path)) as archive:
            with archive.open(provenance.csv_member) as raw_stream:
                with io.TextIOWrapper(
                    raw_stream, encoding=BTS_ENCODING, newline=""
                ) as text_stream:
                    yield from _iter_csv(
                        text_stream,
                        airports,
                        source_url=provenance.source_url,
                        strict=strict,
                        audit=active_audit,
                    )
    except zipfile.BadZipFile as error:
        raise BtsRowError(
            f"Invalid BTS ZIP archive: {provenance.archive_path}"
        ) from error
