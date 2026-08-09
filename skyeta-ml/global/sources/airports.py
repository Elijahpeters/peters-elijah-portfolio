"""Validated local loader for the ``mborsetti/airportsdata`` catalogue.

The module defines the identity and parsing contract for the airport reference
used by the global source adapters.  It deliberately performs no download (or
other file I/O) at import time: callers supply a previously retrieved
``airports.csv`` and the timestamp at which it was retrieved.

``airportsdata.subd`` is a state/province-style subdivision.  It is retained
as such and is never treated as SkyETA's continent-level region.  Converting a
reference row for ANAC or BTS therefore requires an explicit region mapping or
resolver.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, TypeAlias
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


if TYPE_CHECKING:
    from .anac import AirportMetadata as AnacAirportMetadata
    from .bts import AirportMetadata as BtsAirportMetadata
else:
    # Keep runtime annotation introspection resolvable without importing either
    # adapter (the concrete classes are imported only when conversion runs).
    AnacAirportMetadata = Any
    BtsAirportMetadata = Any


AIRPORTS_SOURCE_ID = "mborsetti_airportsdata"
AIRPORTS_SOURCE_PROVIDER = "mborsetti/airportsdata"
AIRPORTS_DATASET_NAME = "airportsdata airports.csv"
AIRPORTS_SOURCE_URL = (
    "https://raw.githubusercontent.com/mborsetti/airportsdata/"
    "main/airportsdata/airports.csv"
)
AIRPORTS_ENCODING = "utf-8-sig"
AIRPORTS_REQUIRED_COLUMNS = (
    "icao",
    "iata",
    "lat",
    "lon",
    "country",
    "tz",
)

SKYETA_REGIONS = frozenset(
    {
        "Africa",
        "Asia",
        "Europe",
        "Middle East",
        "North America",
        "Oceania",
        "Other",
        "South America",
    }
)

_REQUIRED_ROW_VALUES = ("lat", "lon", "country", "tz")
_ICAO = re.compile(r"^[A-Z0-9]{4}$")
_IATA = re.compile(r"^[A-Z]{3}$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")


class AirportReferenceError(ValueError):
    """The airport reference cannot be safely loaded."""


class AirportReferenceConflictError(AirportReferenceError):
    """Two source rows claim the same ICAO or IATA code with different facts."""


def _required_text(value: object, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} is required")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).strip().split())
    return text or None


def _coordinate(
    value: object,
    field_name: str,
    minimum: float,
    maximum: float,
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


@dataclass(frozen=True, slots=True)
class AirportReferenceRecord:
    """One validated airport identity from ``airportsdata``.

    ``airportsdata`` uses values such as ``_AYM`` when an airport has an IATA
    code but no real ICAO code.  Those records remain useful to IATA-based
    sources such as BTS. Conversely, many valid aerodromes have an ICAO code
    but no IATA code. Both identifiers are therefore optional individually,
    but at least one must be present; placeholders are never exposed as ICAO.
    """

    icao: str | None
    iata: str | None
    latitude: float
    longitude: float
    country_code: str
    subdivision: str | None
    timezone_name: str

    def __post_init__(self) -> None:
        icao = str(self.icao or "").strip().upper() or None
        iata = str(self.iata or "").strip().upper() or None
        country = _required_text(self.country_code, "airport country code").upper()
        timezone_name = _required_text(
            self.timezone_name, "airport timezone"
        )
        if icao is not None and not _ICAO.fullmatch(icao):
            raise ValueError(f"Invalid airport ICAO code: {self.icao!r}")
        if iata is not None and not _IATA.fullmatch(iata):
            raise ValueError(f"Invalid airport IATA code: {self.iata!r}")
        if icao is None and iata is None:
            raise ValueError("airport requires at least one valid ICAO or IATA code")
        if not _COUNTRY.fullmatch(country):
            raise ValueError(f"Invalid airport country code: {self.country_code!r}")
        latitude = _coordinate(self.latitude, "airport latitude", -90, 90)
        longitude = _coordinate(self.longitude, "airport longitude", -180, 180)
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(
                f"Unknown airport IANA timezone: {timezone_name!r}"
            ) from error

        object.__setattr__(self, "icao", icao)
        object.__setattr__(self, "iata", iata)
        object.__setattr__(self, "latitude", latitude)
        object.__setattr__(self, "longitude", longitude)
        object.__setattr__(self, "country_code", country)
        object.__setattr__(self, "subdivision", _optional_text(self.subdivision))
        object.__setattr__(self, "timezone_name", timezone_name)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CountryRegionResolver: TypeAlias = (
    Mapping[str, str] | Callable[[AirportReferenceRecord], str]
)


@dataclass(frozen=True, slots=True)
class AirportReferenceSkippedRow:
    """One incomplete or invalid source row omitted from both indexes."""

    row_number: int
    reason: str
    record_hint: str


@dataclass(frozen=True, slots=True)
class AirportReferenceProvenance:
    """Reproducibility facts for the exact bytes and rows that were loaded."""

    source_id: str
    source_provider: str
    dataset_name: str
    source_url: str
    file_path: str
    filename: str
    retrieved_at_utc: datetime
    raw_file_sha256: str
    raw_bytes: int
    raw_row_count: int
    accepted_row_count: int
    skipped_row_count: int
    icao_count: int
    iata_count: int

    @property
    def record_count(self) -> int:
        return self.accepted_row_count

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["retrieved_at_utc"] = self.retrieved_at_utc.isoformat().replace(
            "+00:00", "Z"
        )
        result["record_count"] = self.record_count
        return result


@dataclass(frozen=True, slots=True)
class AirportReferenceAudit:
    """Completed accounting for accepted and deliberately skipped source rows."""

    provenance: AirportReferenceProvenance
    headers: tuple[str, ...]
    skipped_rows: tuple[AirportReferenceSkippedRow, ...]
    completed: bool = True

    @property
    def raw_row_count(self) -> int:
        return self.provenance.raw_row_count

    @property
    def accepted_row_count(self) -> int:
        return self.provenance.accepted_row_count

    @property
    def skipped_row_count(self) -> int:
        return self.provenance.skipped_row_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "provenance": self.provenance.to_dict(),
            "headers": list(self.headers),
            "raw_row_count": self.raw_row_count,
            "accepted_row_count": self.accepted_row_count,
            "skipped_row_count": self.skipped_row_count,
            "completed": self.completed,
            "skipped_rows": [asdict(row) for row in self.skipped_rows],
        }


@dataclass(frozen=True, slots=True)
class AirportReferenceCatalog:
    """Immutable airport records with one-to-one ICAO and IATA indexes."""

    records: tuple[AirportReferenceRecord, ...]
    by_icao: Mapping[str, AirportReferenceRecord]
    by_iata: Mapping[str, AirportReferenceRecord]
    audit: AirportReferenceAudit

    def __post_init__(self) -> None:
        records = tuple(self.records)
        by_icao = dict(self.by_icao)
        by_iata = dict(self.by_iata)
        expected_icao_count = sum(record.icao is not None for record in records)
        expected_iata_count = sum(record.iata is not None for record in records)
        if len(by_icao) != expected_icao_count or len(by_iata) != expected_iata_count:
            raise ValueError(
                "Airport reference indexes must contain every eligible record once"
            )
        for record in records:
            if record.icao is not None and by_icao.get(record.icao) != record:
                raise ValueError(
                    f"Airport ICAO index is inconsistent for {record.icao}"
                )
            if record.iata is not None and by_iata.get(record.iata) != record:
                raise ValueError(
                    f"Airport IATA index is inconsistent for {record.iata}"
                )
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "by_icao", MappingProxyType(by_icao))
        object.__setattr__(self, "by_iata", MappingProxyType(by_iata))

    def __len__(self) -> int:
        return len(self.records)

    @property
    def provenance(self) -> AirportReferenceProvenance:
        return self.audit.provenance

    def to_anac_airports(
        self, region_resolver: CountryRegionResolver
    ) -> dict[str, AnacAirportMetadata]:
        return to_anac_airport_index(self, region_resolver)

    def to_bts_airports(
        self, region_resolver: CountryRegionResolver
    ) -> dict[str, BtsAirportMetadata]:
        return to_bts_airport_index(self, region_resolver)


def _retrieval_time(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("retrieved_at_utc must be an aware datetime")
    return value.astimezone(timezone.utc)


def _source_url(value: str) -> str:
    source_url = _required_text(value, "source_url")
    parsed = urlsplit(source_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("source_url must be an absolute HTTPS URL without credentials")
    return source_url


def _validate_headers(fieldnames: list[str] | None) -> tuple[str, ...]:
    if fieldnames is None:
        raise AirportReferenceError("Airport CSV has no header row")
    headers = tuple(fieldnames)
    blank_headers = [str(index + 1) for index, name in enumerate(headers) if not name]
    if blank_headers:
        raise AirportReferenceError(
            "Airport CSV has blank column names at positions: "
            + ", ".join(blank_headers)
        )
    duplicate_headers = sorted(
        {name for name in headers if headers.count(name) > 1}
    )
    if duplicate_headers:
        raise AirportReferenceError(
            "Airport CSV has duplicate columns: " + ", ".join(duplicate_headers)
        )
    missing = sorted(set(AIRPORTS_REQUIRED_COLUMNS) - set(headers))
    if missing:
        raise AirportReferenceError(
            "Airport CSV is missing required columns: " + ", ".join(missing)
        )
    return headers


def _record_hint(row: Mapping[str | None, object]) -> str:
    return "|".join(
        (
            str(row.get("icao") or "?").strip() or "?",
            str(row.get("iata") or "?").strip() or "?",
        )
    )


def _parse_record(
    row: Mapping[str | None, object],
) -> AirportReferenceRecord:
    if None in row:
        raise ValueError("row contains more values than the CSV header")
    missing = [
        name
        for name in _REQUIRED_ROW_VALUES
        if not str(row.get(name) or "").strip()
    ]
    if missing:
        raise ValueError("missing required fields: " + ", ".join(missing))
    iata = str(row.get("iata") or "").strip().upper() or None
    raw_icao = str(row.get("icao") or "").strip().upper()
    if not raw_icao or (iata is not None and raw_icao == f"_{iata}"):
        icao: str | None = None
    elif _ICAO.fullmatch(raw_icao):
        icao = raw_icao
    else:
        raise ValueError(f"Invalid airport ICAO code: {row.get('icao')!r}")
    return AirportReferenceRecord(
        icao=icao,
        iata=iata,
        latitude=str(row["lat"]),
        longitude=str(row["lon"]),
        country_code=str(row["country"]),
        subdivision=_optional_text(row.get("subd")),
        timezone_name=str(row["tz"]),
    )


def load_airport_reference(
    file_path: str | Path,
    *,
    retrieved_at_utc: datetime,
    source_url: str = AIRPORTS_SOURCE_URL,
) -> AirportReferenceCatalog:
    """Load and index one locally cached ``airportsdata`` CSV.

    Invalid or incomplete rows are omitted and retained in ``catalog.audit``.
    Duplicate normalized airport records are also audited as skipped.  A
    duplicate ICAO or IATA code with any differing normalized fact is a fatal
    conflict: choosing either row would make adapter output depend on source
    ordering.
    """

    retrieved = _retrieval_time(retrieved_at_utc)
    source = _source_url(source_url)
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    raw_data = path.read_bytes()
    digest = hashlib.sha256(raw_data).hexdigest()
    try:
        text = raw_data.decode(AIRPORTS_ENCODING)
    except UnicodeDecodeError as error:
        raise AirportReferenceError("Airport CSV is not valid UTF-8") from error

    records: list[AirportReferenceRecord] = []
    by_icao: dict[str, AirportReferenceRecord] = {}
    by_iata: dict[str, AirportReferenceRecord] = {}
    source_rows_by_icao: dict[str, int] = {}
    source_rows_by_iata: dict[str, int] = {}
    skipped: list[AirportReferenceSkippedRow] = []
    raw_row_count = 0

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = _validate_headers(reader.fieldnames)
        for row_number, row in enumerate(reader, start=2):
            raw_row_count += 1
            try:
                record = _parse_record(row)
            except ValueError as error:
                skipped.append(
                    AirportReferenceSkippedRow(
                        row_number=row_number,
                        reason=str(error),
                        record_hint=_record_hint(row),
                    )
                )
                continue

            existing_icao = (
                by_icao.get(record.icao) if record.icao is not None else None
            )
            existing_iata = (
                by_iata.get(record.iata) if record.iata is not None else None
            )
            if existing_icao is None and existing_iata is None:
                records.append(record)
                if record.icao is not None:
                    by_icao[record.icao] = record
                    source_rows_by_icao[record.icao] = row_number
                if record.iata is not None:
                    by_iata[record.iata] = record
                    source_rows_by_iata[record.iata] = row_number
                continue
            matching_icao = record.icao is None or existing_icao == record
            matching_iata = record.iata is None or existing_iata == record
            if matching_icao and matching_iata:
                first_rows = []
                if record.icao is not None and existing_icao == record:
                    first_rows.append(source_rows_by_icao[record.icao])
                if record.iata is not None and existing_iata == record:
                    first_rows.append(source_rows_by_iata[record.iata])
                if not first_rows:
                    raise AirportReferenceConflictError(
                        f"Airport CSV row {row_number} has an unresolved identity collision"
                    )
                first_row = min(first_rows)
                skipped.append(
                    AirportReferenceSkippedRow(
                        row_number=row_number,
                        reason=(
                            "duplicate normalized airport record from source "
                            f"row {first_row}"
                        ),
                        record_hint=_record_hint(row),
                    )
                )
                continue
            if record.icao is not None and existing_icao is not None:
                first_row = source_rows_by_icao[record.icao]
                raise AirportReferenceConflictError(
                    f"Airport CSV row {row_number} conflicts with row {first_row} "
                    f"for ICAO {record.icao}"
                )
            if record.iata is None or existing_iata is None:
                raise AirportReferenceConflictError(
                    f"Airport CSV row {row_number} has an unresolved code conflict"
                )
            first_row = source_rows_by_iata[record.iata]
            raise AirportReferenceConflictError(
                f"Airport CSV row {row_number} conflicts with row {first_row} "
                f"for IATA {record.iata}"
            )
    except csv.Error as error:
        raise AirportReferenceError(f"Malformed airport CSV: {error}") from error

    provenance = AirportReferenceProvenance(
        source_id=AIRPORTS_SOURCE_ID,
        source_provider=AIRPORTS_SOURCE_PROVIDER,
        dataset_name=AIRPORTS_DATASET_NAME,
        source_url=source,
        file_path=str(path),
        filename=path.name,
        retrieved_at_utc=retrieved,
        raw_file_sha256=digest,
        raw_bytes=len(raw_data),
        raw_row_count=raw_row_count,
        accepted_row_count=len(records),
        skipped_row_count=len(skipped),
        icao_count=len(by_icao),
        iata_count=len(by_iata),
    )
    audit = AirportReferenceAudit(
        provenance=provenance,
        headers=headers,
        skipped_rows=tuple(skipped),
    )
    return AirportReferenceCatalog(
        records=tuple(records),
        by_icao=by_icao,
        by_iata=by_iata,
        audit=audit,
    )


def _resolve_region(
    airport: AirportReferenceRecord,
    region_resolver: CountryRegionResolver,
) -> str:
    if isinstance(region_resolver, Mapping):
        if airport.country_code not in region_resolver:
            raise ValueError(
                "No SkyETA region mapping for airport country "
                f"{airport.country_code} ({airport.icao}/{airport.iata})"
            )
        raw_region: object = region_resolver[airport.country_code]
    elif callable(region_resolver):
        try:
            raw_region = region_resolver(airport)
        except (KeyError, LookupError) as error:
            raise ValueError(
                "SkyETA region resolver has no result for airport "
                f"{airport.icao}/{airport.iata}"
            ) from error
    else:
        raise TypeError("region_resolver must be a mapping or callable")

    region = str(raw_region).strip() if raw_region is not None else ""
    if region not in SKYETA_REGIONS:
        allowed = ", ".join(sorted(SKYETA_REGIONS))
        raise ValueError(
            f"Invalid SkyETA region {raw_region!r} for {airport.country_code}; "
            f"expected one of: {allowed}"
        )
    return region


def to_anac_airport_metadata(
    airport: AirportReferenceRecord,
    region_resolver: CountryRegionResolver,
) -> AnacAirportMetadata:
    """Convert one row for ANAC after explicitly resolving its model region."""

    if not isinstance(airport, AirportReferenceRecord):
        raise TypeError("airport must be an AirportReferenceRecord")
    if airport.icao is None:
        raise ValueError(
            f"ANAC airport metadata requires a valid ICAO code for {airport.iata}"
        )
    region = _resolve_region(airport, region_resolver)
    # Local import keeps importing this reference module independent of the
    # source adapters and avoids a module-level cycle through sources.__init__.
    from .anac import AirportMetadata

    return AirportMetadata(
        icao=airport.icao,
        iata=airport.iata,
        latitude=airport.latitude,
        longitude=airport.longitude,
        country_code=airport.country_code,
        region_code=region,
        timezone_name=airport.timezone_name,
    )


def to_bts_airport_metadata(
    airport: AirportReferenceRecord,
    region_resolver: CountryRegionResolver,
) -> BtsAirportMetadata:
    """Convert one row for BTS after explicitly resolving its model region."""

    if not isinstance(airport, AirportReferenceRecord):
        raise TypeError("airport must be an AirportReferenceRecord")
    if airport.iata is None:
        raise ValueError(
            f"BTS airport metadata requires a valid IATA code for {airport.icao}"
        )
    region = _resolve_region(airport, region_resolver)
    from .bts import AirportMetadata

    return AirportMetadata(
        iata=airport.iata,
        latitude=airport.latitude,
        longitude=airport.longitude,
        country_code=airport.country_code,
        region_code=region,
        timezone_name=airport.timezone_name,
    )


def to_anac_airport_index(
    catalog: AirportReferenceCatalog,
    region_resolver: CountryRegionResolver,
) -> dict[str, AnacAirportMetadata]:
    """Build the ICAO-keyed metadata mapping consumed by the ANAC adapter."""

    if not isinstance(catalog, AirportReferenceCatalog):
        raise TypeError("catalog must be an AirportReferenceCatalog")
    return {
        code: to_anac_airport_metadata(airport, region_resolver)
        for code, airport in catalog.by_icao.items()
    }


def to_bts_airport_index(
    catalog: AirportReferenceCatalog,
    region_resolver: CountryRegionResolver,
) -> dict[str, BtsAirportMetadata]:
    """Build the IATA-keyed metadata mapping consumed by the BTS adapter."""

    if not isinstance(catalog, AirportReferenceCatalog):
        raise TypeError("catalog must be an AirportReferenceCatalog")
    return {
        code: to_bts_airport_metadata(airport, region_resolver)
        for code, airport in catalog.by_iata.items()
    }
