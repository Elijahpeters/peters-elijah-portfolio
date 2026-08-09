"""Strict offline loader for dated ANAC SIROS future-schedule snapshots.

ANAC's official SIROS directory exposes annual ZIP containers for 2018-2023
and daily CSV snapshots for 2024-2026.  A reviewed daily file has this exact
shape:

* UTF-8 BOM;
* first line ``Importante: Horários em UTC``; and
* the exact Portuguese header tuple in :data:`ANAC_SIROS_SERIES_HEADERS`.

The note is the source evidence that the two schedule clock columns are UTC.
``Data Registro`` has no documented timezone in the reviewed material.  It is
therefore retained and syntax-checked as a raw source string, but is never
labelled UTC, converted, or used to decide whether a row was visible at a
prediction cutoff.  Point-in-time visibility comes only from an independently
pinned Wayback capture, HTTP ``Last-Modified`` value, or (least preferably) the
retrieval time.

This module performs no network I/O.  It validates already downloaded bytes,
their hash, size, filename, source URL, and availability evidence before
parsing.  Malformed data rows are excluded with complete audit accounting;
ambiguous partition metadata and duplicate/conflicting SIROS identities fail
the entire load.
"""

from __future__ import annotations

import codecs
import csv
import hashlib
import io
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, TypeAlias
from urllib.parse import unquote, urlsplit


ANAC_SIROS_SOURCE_ID = "anac_siros_future_schedule"
ANAC_SIROS_SOURCE_PROVIDER = "Brazil ANAC"
ANAC_SIROS_DATASET_NAME = "SIROS future planned-service snapshots"
ANAC_SIROS_BASE_URL = "https://siros.anac.gov.br/siros/registros/futuro/serie"
ANAC_SIROS_DOCUMENTATION_URL = ANAC_SIROS_BASE_URL + "/"
ANAC_SIROS_ANNUAL_YEARS = frozenset(range(2018, 2024))
ANAC_SIROS_DAILY_YEARS = frozenset(range(2024, 2027))
ANAC_SIROS_ENCODING = "utf-8-sig"
ANAC_SIROS_DELIMITER = ";"
ANAC_SIROS_UTC_NOTE = "Importante: Horários em UTC"
ANAC_SIROS_SERIES_HEADERS = (
    "Cód. Empresa",
    "Empresa",
    "Nº Voo",
    "Equip.",
    "Seg",
    "Ter",
    "Qua",
    "Qui",
    "Sex",
    "Sáb",
    "Dom",
    "Quant. Assentos",
    "Nº SIROS",
    "Situação SIROS",
    "Data Registro",
    "Início Operação",
    "Fim Operação",
    "Natureza Operação",
    "Nº Etapa",
    "Cód. Origem",
    "Arpt Origem",
    "Cód Destino",
    "Arpt Destino",
    "Horário Partida",
    "Horário Chegada",
    "Tipo Serviço",
    "Objeto Transporte",
    "Codeshare",
)
ANAC_SIROS_WEEKDAY_HEADERS = (
    ("Seg", 1),
    ("Ter", 2),
    ("Qua", 3),
    ("Qui", 4),
    ("Sex", 5),
    ("Sáb", 6),
    ("Dom", 7),
)

ResourceKind: TypeAlias = Literal["annual_zip", "daily_csv"]
AvailabilityEvidenceKind: TypeAlias = Literal[
    "wayback_capture", "http_last_modified", "retrieved_at"
]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ICAO = re.compile(r"^[A-Z0-9]{4}$")
_CARRIER = re.compile(r"^[A-Z0-9]{3}$")
_FLIGHT_NUMBER = re.compile(r"^[A-Z0-9]{1,6}$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CLOCK = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_REGISTRATION = re.compile(
    r"^(?:0[1-9]|[12]\d|3[01])/(?:0[1-9]|1[0-2])/\d{4} "
    r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d$"
)
_WAYBACK = re.compile(
    r"^/web/(\d{14})(?:id_)?/(https?://.+)$",
    re.IGNORECASE,
)


class AnacSirosError(ValueError):
    """Base class for a SIROS integrity failure."""


class AnacSirosSourceError(AnacSirosError):
    """A resource, local file, hash, or availability pin is inconsistent."""


class AnacSirosUnsupportedSchemaError(AnacSirosError):
    """A resource shape has not been proven safe to parse."""


class AnacSirosRowError(AnacSirosError):
    """One source row cannot safely enter the normalized schedule corpus."""


class AnacSirosDuplicateError(AnacSirosError):
    """One exact SIROS stage appears more than once in a snapshot."""


class AnacSirosConflictError(AnacSirosError):
    """One SIROS stage identity contains contradictory series facts."""


def _required_text(value: object, name: str) -> str:
    if value is None:
        raise ValueError(f"{name} is required")
    text = " ".join(str(value).strip().split())
    if not text:
        raise ValueError(f"{name} is required")
    if any(ord(character) < 32 for character in text):
        raise ValueError(f"{name} contains a control character")
    return text


def _utc(value: datetime, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(value: object, name: str) -> str:
    digest = str(value or "").strip().lower()
    if not _SHA256.fullmatch(digest):
        raise ValueError(f"{name} must contain 64 hexadecimal characters")
    return digest


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class AnacSirosResource:
    """One resource whose URL pattern is proven by the official listing."""

    kind: ResourceKind
    year: int
    filename: str
    url: str
    snapshot_date: date | None

    def __post_init__(self) -> None:
        if isinstance(self.year, bool) or not isinstance(self.year, int):
            raise ValueError("resource year must be an integer")
        if self.kind == "annual_zip":
            if self.year not in ANAC_SIROS_ANNUAL_YEARS:
                raise ValueError("annual SIROS ZIP resources cover 2018 through 2023")
            expected_filename = f"{self.year}.zip"
            expected_url = f"{ANAC_SIROS_BASE_URL}/{expected_filename}"
            if self.snapshot_date is not None:
                raise ValueError("an annual ZIP has no single snapshot date")
        elif self.kind == "daily_csv":
            if self.year not in ANAC_SIROS_DAILY_YEARS:
                raise ValueError("daily SIROS CSV resources cover 2024 through 2026")
            if not isinstance(self.snapshot_date, date) or isinstance(
                self.snapshot_date, datetime
            ):
                raise ValueError("a daily SIROS resource requires a snapshot date")
            if self.snapshot_date.year != self.year:
                raise ValueError("daily resource year and snapshot date disagree")
            rendered = self.snapshot_date.isoformat()
            expected_filename = f"futuro_{rendered}.csv"
            expected_url = (
                f"{ANAC_SIROS_BASE_URL}/{self.year}/{expected_filename}"
            )
        else:
            raise ValueError("resource kind must be 'annual_zip' or 'daily_csv'")
        if self.filename != expected_filename or self.url != expected_url:
            raise ValueError("SIROS resource metadata does not match its official URL")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["snapshot_date"] = (
            self.snapshot_date.isoformat() if self.snapshot_date else None
        )
        return result


def annual_zip_resource(year: int) -> AnacSirosResource:
    filename = f"{year}.zip"
    return AnacSirosResource(
        kind="annual_zip",
        year=year,
        filename=filename,
        url=f"{ANAC_SIROS_BASE_URL}/{filename}",
        snapshot_date=None,
    )


def daily_snapshot_resource(snapshot_date: date) -> AnacSirosResource:
    if not isinstance(snapshot_date, date) or isinstance(snapshot_date, datetime):
        raise ValueError("snapshot_date must be a date")
    filename = f"futuro_{snapshot_date.isoformat()}.csv"
    return AnacSirosResource(
        kind="daily_csv",
        year=snapshot_date.year,
        filename=filename,
        url=f"{ANAC_SIROS_BASE_URL}/{snapshot_date.year}/{filename}",
        snapshot_date=snapshot_date,
    )


def annual_archive_manifest() -> tuple[AnacSirosResource, ...]:
    return tuple(
        annual_zip_resource(year) for year in sorted(ANAC_SIROS_ANNUAL_YEARS)
    )


def daily_snapshot_manifest(
    start: date,
    end: date,
) -> tuple[AnacSirosResource, ...]:
    """Describe an inclusive range without asserting every URL exists."""

    if not isinstance(start, date) or isinstance(start, datetime):
        raise ValueError("manifest start must be a date")
    if not isinstance(end, date) or isinstance(end, datetime):
        raise ValueError("manifest end must be a date")
    if end < start:
        raise ValueError("manifest end must not precede its start")
    if (
        start.year not in ANAC_SIROS_DAILY_YEARS
        or end.year not in ANAC_SIROS_DAILY_YEARS
    ):
        raise ValueError("daily SIROS manifests are bounded to 2024 through 2026")
    return tuple(
        daily_snapshot_resource(start + timedelta(days=offset))
        for offset in range((end - start).days + 1)
    )


@dataclass(frozen=True, slots=True)
class AnacSirosSnapshotPin:
    """Byte and availability evidence for one already downloaded resource.

    The filename date identifies the snapshot, but never implies an availability
    time.  ``snapshot_observed_at_utc`` must be backed by the selected evidence
    kind and must not follow retrieval.
    """

    resource: AnacSirosResource
    source_url: str
    availability_evidence_kind: AvailabilityEvidenceKind
    snapshot_observed_at_utc: datetime
    retrieved_at_utc: datetime
    expected_sha256: str
    expected_bytes: int
    archive_url: str | None = None
    http_last_modified_utc: datetime | None = None
    http_last_modified_raw: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.resource, AnacSirosResource):
            raise TypeError("resource must be an AnacSirosResource")
        if self.source_url != self.resource.url:
            raise AnacSirosSourceError("source URL does not match the SIROS resource")
        observed = _utc(self.snapshot_observed_at_utc, "snapshot_observed_at_utc")
        retrieved = _utc(self.retrieved_at_utc, "retrieved_at_utc")
        if observed > retrieved:
            raise AnacSirosSourceError("snapshot availability cannot follow retrieval")
        if (
            isinstance(self.expected_bytes, bool)
            or not isinstance(self.expected_bytes, int)
            or self.expected_bytes < 0
        ):
            raise ValueError("expected_bytes must be a non-negative integer")
        digest = _digest(self.expected_sha256, "expected_sha256")

        last_modified: datetime | None = None
        last_modified_raw: str | None = None
        if self.availability_evidence_kind == "wayback_capture":
            if self.archive_url is None:
                raise AnacSirosSourceError(
                    "wayback_capture evidence requires archive_url"
                )
            if self.http_last_modified_utc is not None or self.http_last_modified_raw is not None:
                raise AnacSirosSourceError(
                    "Wayback evidence must not include HTTP Last-Modified fields"
                )
            parsed = urlsplit(self.archive_url)
            if parsed.scheme != "https" or parsed.hostname != "web.archive.org":
                raise AnacSirosSourceError(
                    "archive_url must be an HTTPS Internet Archive memento"
                )
            match = _WAYBACK.fullmatch(unquote(parsed.path))
            if match is None:
                raise AnacSirosSourceError("archive_url is not a dated raw memento")
            captured = datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(
                tzinfo=timezone.utc
            )
            if match.group(2) != self.source_url:
                raise AnacSirosSourceError(
                    "archive memento target does not match source_url"
                )
            if captured != observed:
                raise AnacSirosSourceError(
                    "archive capture timestamp does not match snapshot availability"
                )
        elif self.availability_evidence_kind == "http_last_modified":
            if self.archive_url is not None:
                raise AnacSirosSourceError(
                    "HTTP Last-Modified evidence must not include archive_url"
                )
            if self.http_last_modified_utc is None or self.http_last_modified_raw is None:
                raise AnacSirosSourceError(
                    "http_last_modified evidence requires raw and parsed values"
                )
            last_modified_raw = str(self.http_last_modified_raw)
            if not last_modified_raw or last_modified_raw != last_modified_raw.strip():
                raise AnacSirosSourceError(
                    "http_last_modified_raw must preserve one exact non-blank header value"
                )
            try:
                parsed_http = parsedate_to_datetime(last_modified_raw)
            except (TypeError, ValueError) as error:
                raise AnacSirosSourceError(
                    "http_last_modified_raw is not an RFC HTTP-date"
                ) from error
            last_modified = _utc(
                self.http_last_modified_utc, "http_last_modified_utc"
            )
            if _utc(parsed_http, "parsed HTTP Last-Modified") != last_modified:
                raise AnacSirosSourceError(
                    "raw and parsed HTTP Last-Modified values disagree"
                )
            if last_modified != observed:
                raise AnacSirosSourceError(
                    "HTTP Last-Modified does not match snapshot availability"
                )
        elif self.availability_evidence_kind == "retrieved_at":
            if (
                self.archive_url is not None
                or self.http_last_modified_utc is not None
                or self.http_last_modified_raw is not None
            ):
                raise AnacSirosSourceError(
                    "retrieved_at evidence cannot include archive or Last-Modified fields"
                )
            if observed != retrieved:
                raise AnacSirosSourceError(
                    "retrieved_at evidence requires availability to equal retrieval"
                )
        else:
            raise ValueError(
                "availability_evidence_kind must be wayback_capture, "
                "http_last_modified, or retrieved_at"
            )

        if self.resource.snapshot_date is not None:
            if observed.date() < self.resource.snapshot_date:
                raise AnacSirosSourceError(
                    "snapshot availability predates the date encoded in its filename"
                )

        object.__setattr__(self, "snapshot_observed_at_utc", observed)
        object.__setattr__(self, "retrieved_at_utc", retrieved)
        object.__setattr__(self, "expected_sha256", digest)
        object.__setattr__(self, "http_last_modified_utc", last_modified)
        object.__setattr__(self, "http_last_modified_raw", last_modified_raw)


@dataclass(frozen=True, slots=True)
class AnacSirosFileProvenance:
    """Byte-level and point-in-time evidence established before parsing."""

    source_id: str
    source_provider: str
    dataset_name: str
    resource_kind: ResourceKind
    snapshot_date: date | None
    source_url: str
    availability_evidence_kind: AvailabilityEvidenceKind
    archive_url: str | None
    http_last_modified_utc: datetime | None
    http_last_modified_raw: str | None
    file_path: str
    filename: str
    snapshot_observed_at_utc: datetime
    retrieved_at_utc: datetime
    raw_file_sha256: str
    raw_bytes: int

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["snapshot_date"] = (
            self.snapshot_date.isoformat() if self.snapshot_date else None
        )
        result["snapshot_observed_at_utc"] = _iso_utc(
            self.snapshot_observed_at_utc
        )
        result["retrieved_at_utc"] = _iso_utc(self.retrieved_at_utc)
        result["http_last_modified_utc"] = (
            _iso_utc(self.http_last_modified_utc)
            if self.http_last_modified_utc
            else None
        )
        return result


def validate_siros_file(
    path: Path,
    pin: AnacSirosSnapshotPin,
) -> AnacSirosFileProvenance:
    """Validate local bytes and source identity without network access."""

    if not isinstance(pin, AnacSirosSnapshotPin):
        raise TypeError("pin must be an AnacSirosSnapshotPin")
    resolved = Path(path).expanduser().resolve()
    if resolved.name != pin.resource.filename:
        raise AnacSirosSourceError(
            "local filename does not match the pinned SIROS resource"
        )
    if not resolved.is_file():
        raise AnacSirosSourceError(f"SIROS local file does not exist: {resolved}")
    raw = resolved.read_bytes()
    actual_digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != pin.expected_bytes:
        raise AnacSirosSourceError(
            f"SIROS byte count mismatch: expected {pin.expected_bytes}, got {len(raw)}"
        )
    if actual_digest != pin.expected_sha256:
        raise AnacSirosSourceError(
            f"SIROS SHA-256 mismatch: expected {pin.expected_sha256}, got {actual_digest}"
        )
    return AnacSirosFileProvenance(
        source_id=ANAC_SIROS_SOURCE_ID,
        source_provider=ANAC_SIROS_SOURCE_PROVIDER,
        dataset_name=ANAC_SIROS_DATASET_NAME,
        resource_kind=pin.resource.kind,
        snapshot_date=pin.resource.snapshot_date,
        source_url=pin.source_url,
        availability_evidence_kind=pin.availability_evidence_kind,
        archive_url=pin.archive_url,
        http_last_modified_utc=pin.http_last_modified_utc,
        http_last_modified_raw=pin.http_last_modified_raw,
        file_path=str(resolved),
        filename=resolved.name,
        snapshot_observed_at_utc=pin.snapshot_observed_at_utc,
        retrieved_at_utc=pin.retrieved_at_utc,
        raw_file_sha256=actual_digest,
        raw_bytes=len(raw),
    )


def _parse_date(value: object, name: str) -> date:
    raw = _required_text(value, name)
    if not _ISO_DATE.fullmatch(raw):
        raise AnacSirosRowError(f"{name} must use the proven YYYY-MM-DD format")
    try:
        return date.fromisoformat(raw)
    except ValueError as error:
        raise AnacSirosRowError(f"{name} is not a valid calendar date") from error


def _parse_clock(value: object, name: str) -> time:
    raw = _required_text(value, name)
    if not _CLOCK.fullmatch(raw):
        raise AnacSirosRowError(f"{name} must use the proven HH:MM format")
    hour, minute = (int(part) for part in raw.split(":"))
    return time(hour, minute)


def _validate_registration_raw(value: object) -> str:
    raw = _required_text(value, "Data Registro")
    if not _REGISTRATION.fullmatch(raw):
        raise AnacSirosRowError(
            "Data Registro must use the proven DD/MM/YYYY HH:MM:SS shape"
        )
    try:
        datetime.strptime(raw, "%d/%m/%Y %H:%M:%S")
    except ValueError as error:
        raise AnacSirosRowError("Data Registro is not a valid civil timestamp") from error
    return raw


def _parse_weekdays(source: Mapping[str, str]) -> tuple[bool, ...]:
    mask: list[bool] = []
    for header, marker in ANAC_SIROS_WEEKDAY_HEADERS:
        value = str(source[header]).strip()
        if value == "0":
            mask.append(False)
        elif value == str(marker):
            mask.append(True)
        else:
            raise AnacSirosRowError(
                f"{header} must be 0 or its proven weekday marker {marker}"
            )
    if not any(mask):
        raise AnacSirosRowError("at least one weekday must be active")
    return tuple(mask)


@dataclass(frozen=True, slots=True)
class AnacSirosSeriesRow:
    """One immutable recurring SIROS stage observed in one daily snapshot."""

    siros_id: str
    operating_carrier: str
    operating_flight_number: str
    stage_number: int
    origin_icao: str
    destination_icao: str
    valid_from: date
    valid_until: date
    active_weekdays: tuple[bool, ...]
    scheduled_departure_time_utc: time
    scheduled_arrival_time_utc: time
    registration_raw: str
    snapshot_date: date
    schedule_observed_at_utc: datetime
    source_url: str
    raw_file_sha256: str
    row_number: int
    source_values: tuple[str, ...]

    def __post_init__(self) -> None:
        siros_id = _required_text(self.siros_id, "Nº SIROS")
        if len(siros_id) > 128:
            raise ValueError("Nº SIROS must not exceed 128 characters")
        carrier = _required_text(self.operating_carrier, "Cód. Empresa").upper()
        flight = _required_text(self.operating_flight_number, "Nº Voo").upper()
        origin = _required_text(self.origin_icao, "Cód. Origem").upper()
        destination = _required_text(self.destination_icao, "Cód Destino").upper()
        if not _CARRIER.fullmatch(carrier):
            raise ValueError("Cód. Empresa must be a three-character ICAO designator")
        if not _FLIGHT_NUMBER.fullmatch(flight):
            raise ValueError("Nº Voo must be 1-6 alphanumeric characters")
        if not _ICAO.fullmatch(origin) or not _ICAO.fullmatch(destination):
            raise ValueError("origin and destination must be four-character ICAO codes")
        if origin == destination:
            raise ValueError("origin and destination must differ")
        if (
            isinstance(self.stage_number, bool)
            or not isinstance(self.stage_number, int)
            or self.stage_number < 1
        ):
            raise ValueError("Nº Etapa must be a positive integer")
        if self.valid_until < self.valid_from:
            raise ValueError("Fim Operação precedes Início Operação")
        weekdays = tuple(self.active_weekdays)
        if len(weekdays) != 7 or any(not isinstance(value, bool) for value in weekdays):
            raise ValueError("active_weekdays must contain seven booleans")
        if not any(weekdays):
            raise ValueError("at least one weekday must be active")
        if self.scheduled_departure_time_utc == self.scheduled_arrival_time_utc:
            raise ValueError("equal departure and arrival clocks imply an unsupported 24h stage")
        if self.scheduled_departure_time_utc.tzinfo is not None or self.scheduled_arrival_time_utc.tzinfo is not None:
            raise ValueError("series clocks store source UTC wall values without duplicate tzinfo")
        if not isinstance(self.snapshot_date, date) or isinstance(self.snapshot_date, datetime):
            raise ValueError("snapshot_date must be a date")
        observed = _utc(self.schedule_observed_at_utc, "schedule_observed_at_utc")
        if observed.date() < self.snapshot_date:
            raise ValueError("schedule evidence predates snapshot_date")
        parsed_source = urlsplit(self.source_url)
        if parsed_source.scheme != "https" or parsed_source.hostname != "siros.anac.gov.br":
            raise ValueError("source_url must be an official HTTPS SIROS URL")
        if isinstance(self.row_number, bool) or not isinstance(self.row_number, int) or self.row_number < 3:
            raise ValueError("row_number must identify a series data row after note/header")
        values = tuple(self.source_values)
        if len(values) != len(ANAC_SIROS_SERIES_HEADERS):
            raise ValueError("source_values must preserve every exact source column")

        object.__setattr__(self, "siros_id", siros_id)
        object.__setattr__(self, "operating_carrier", carrier)
        object.__setattr__(self, "operating_flight_number", flight)
        object.__setattr__(self, "origin_icao", origin)
        object.__setattr__(self, "destination_icao", destination)
        object.__setattr__(self, "active_weekdays", weekdays)
        object.__setattr__(self, "schedule_observed_at_utc", observed)
        object.__setattr__(self, "raw_file_sha256", _digest(self.raw_file_sha256, "raw_file_sha256"))
        object.__setattr__(self, "registration_raw", _validate_registration_raw(self.registration_raw))
        object.__setattr__(self, "source_values", values)

    @property
    def source_strings(self) -> Mapping[str, str]:
        return MappingProxyType(dict(zip(ANAC_SIROS_SERIES_HEADERS, self.source_values)))

    @property
    def revision_identity(self) -> str:
        """Source revision identity; no replacement lineage is inferred."""

        return self.siros_id

    @property
    def stage_revision_key(self) -> str:
        return f"{ANAC_SIROS_SOURCE_ID}:{self.siros_id}:stage:{self.stage_number}"

    @property
    def series_facts_sha256(self) -> str:
        return _canonical_hash(
            {
                "stageRevisionKey": self.stage_revision_key,
                "carrier": self.operating_carrier,
                "flight": self.operating_flight_number,
                "origin": self.origin_icao,
                "destination": self.destination_icao,
                "validFrom": self.valid_from.isoformat(),
                "validUntil": self.valid_until.isoformat(),
                "activeWeekdays": list(self.active_weekdays),
                "departureUtc": self.scheduled_departure_time_utc.strftime("%H:%M"),
                "arrivalUtc": self.scheduled_arrival_time_utc.strftime("%H:%M"),
            }
        )

    @property
    def observation_key(self) -> str:
        return _canonical_hash(
            {
                "seriesFactsSha256": self.series_facts_sha256,
                "observedAtUtc": _iso_utc(self.schedule_observed_at_utc),
                "rawFileSha256": self.raw_file_sha256,
                "rowNumber": self.row_number,
            }
        )

    def is_active_on(self, service_date: date) -> bool:
        if not isinstance(service_date, date) or isinstance(service_date, datetime):
            raise ValueError("service_date must be a date")
        return (
            self.valid_from <= service_date <= self.valid_until
            and self.active_weekdays[service_date.weekday()]
        )

    def visible_at(self, as_of_utc: datetime) -> bool:
        """Visibility depends only on pinned snapshot evidence, not registration."""

        return self.schedule_observed_at_utc <= _utc(as_of_utc, "as_of_utc")

    def to_dict(self) -> dict[str, Any]:
        return {
            "siros_id": self.siros_id,
            "revision_identity": self.revision_identity,
            "stage_revision_key": self.stage_revision_key,
            "series_facts_sha256": self.series_facts_sha256,
            "observation_key": self.observation_key,
            "operating_carrier": self.operating_carrier,
            "operating_flight_number": self.operating_flight_number,
            "stage_number": self.stage_number,
            "origin_icao": self.origin_icao,
            "destination_icao": self.destination_icao,
            "valid_from": self.valid_from.isoformat(),
            "valid_until": self.valid_until.isoformat(),
            "active_weekdays": list(self.active_weekdays),
            "scheduled_departure_time_utc": self.scheduled_departure_time_utc.strftime("%H:%M"),
            "scheduled_arrival_time_utc": self.scheduled_arrival_time_utc.strftime("%H:%M"),
            "registration_raw": self.registration_raw,
            "snapshot_date": self.snapshot_date.isoformat(),
            "schedule_observed_at_utc": _iso_utc(self.schedule_observed_at_utc),
            "source_url": self.source_url,
            "raw_file_sha256": self.raw_file_sha256,
            "row_number": self.row_number,
            "source_strings": dict(self.source_strings),
        }


@dataclass(frozen=True, slots=True)
class AnacSirosRejectedRow:
    row_number: int
    reason: str
    record_hint: str
    source_values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AnacSirosRowAudit:
    row_number: int
    disposition: Literal["accepted", "rejected"]
    record_hint: str
    stage_revision_key: str | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.disposition == "accepted":
            if self.reason is not None or self.stage_revision_key is None:
                raise ValueError("accepted row audit requires a key and no reason")
        elif self.disposition == "rejected":
            if not self.reason or self.stage_revision_key is not None:
                raise ValueError("rejected row audit requires a reason and no key")
        else:
            raise ValueError("invalid row-audit disposition")


@dataclass(frozen=True, slots=True)
class AnacSirosSeriesAudit:
    file: AnacSirosFileProvenance
    note_line: str
    exact_headers: tuple[str, ...]
    raw_row_count: int
    accepted_row_count: int
    rejected_row_count: int
    row_audit: tuple[AnacSirosRowAudit, ...]
    rejected_rows: tuple[AnacSirosRejectedRow, ...]
    accepted_series_facts_sha256: str
    completed: bool = True

    def __post_init__(self) -> None:
        rows = tuple(self.row_audit)
        rejected = tuple(self.rejected_rows)
        if self.note_line != ANAC_SIROS_UTC_NOTE:
            raise ValueError("audit note line is not the proven UTC statement")
        if tuple(self.exact_headers) != ANAC_SIROS_SERIES_HEADERS:
            raise ValueError("audit headers do not match the proven series schema")
        if self.raw_row_count != self.accepted_row_count + self.rejected_row_count:
            raise ValueError("SIROS series row counts do not reconcile")
        if len(rows) != self.raw_row_count:
            raise ValueError("row audit must account for every source row")
        if sum(row.disposition == "accepted" for row in rows) != self.accepted_row_count:
            raise ValueError("accepted row-audit count does not reconcile")
        if sum(row.disposition == "rejected" for row in rows) != self.rejected_row_count:
            raise ValueError("rejected row-audit count does not reconcile")
        if len(rejected) != self.rejected_row_count:
            raise ValueError("rejected row details do not reconcile")
        object.__setattr__(self, "row_audit", rows)
        object.__setattr__(self, "rejected_rows", rejected)
        object.__setattr__(
            self,
            "accepted_series_facts_sha256",
            _digest(self.accepted_series_facts_sha256, "accepted_series_facts_sha256"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file.to_dict(),
            "note_line": self.note_line,
            "exact_headers": list(self.exact_headers),
            "raw_row_count": self.raw_row_count,
            "accepted_row_count": self.accepted_row_count,
            "rejected_row_count": self.rejected_row_count,
            "row_audit": [asdict(row) for row in self.row_audit],
            "rejected_rows": [asdict(row) for row in self.rejected_rows],
            "accepted_series_facts_sha256": self.accepted_series_facts_sha256,
            "completed": self.completed,
        }


@dataclass(frozen=True, slots=True)
class AnacSirosSeriesSnapshot:
    rows: tuple[AnacSirosSeriesRow, ...]
    audit: AnacSirosSeriesAudit

    def __post_init__(self) -> None:
        rows = tuple(self.rows)
        if len(rows) != self.audit.accepted_row_count:
            raise ValueError("accepted count does not match parsed SIROS series rows")
        digest = hashlib.sha256(
            "\n".join(sorted(row.series_facts_sha256 for row in rows)).encode("ascii")
        ).hexdigest()
        if digest != self.audit.accepted_series_facts_sha256:
            raise ValueError("SIROS accepted-series digest does not reconcile")
        for row in rows:
            if row.raw_file_sha256 != self.audit.file.raw_file_sha256:
                raise ValueError("series row hash does not match file provenance")
            if row.source_url != self.audit.file.source_url:
                raise ValueError("series row source URL does not match file provenance")
            if row.snapshot_date != self.audit.file.snapshot_date:
                raise ValueError("series row snapshot date does not match provenance")
            if row.schedule_observed_at_utc != self.audit.file.snapshot_observed_at_utc:
                raise ValueError("series row observation time does not match provenance")
        object.__setattr__(self, "rows", rows)


def _row_hint(values: tuple[str, ...]) -> str:
    if len(values) > 12 and values[12].strip():
        return values[12].strip()[:128]
    if values:
        return " | ".join(value.strip() for value in values[:3])[:128]
    return "<blank row>"


def _parse_series_row(
    values: tuple[str, ...],
    *,
    row_number: int,
    file: AnacSirosFileProvenance,
) -> AnacSirosSeriesRow:
    if len(values) != len(ANAC_SIROS_SERIES_HEADERS):
        raise AnacSirosRowError(
            f"expected {len(ANAC_SIROS_SERIES_HEADERS)} columns, got {len(values)}"
        )
    source = dict(zip(ANAC_SIROS_SERIES_HEADERS, values))
    carrier = _required_text(source["Cód. Empresa"], "Cód. Empresa").upper()
    flight = _required_text(source["Nº Voo"], "Nº Voo").upper()
    siros_id = _required_text(source["Nº SIROS"], "Nº SIROS")
    registration_raw = _validate_registration_raw(source["Data Registro"])
    valid_from = _parse_date(source["Início Operação"], "Início Operação")
    valid_until = _parse_date(source["Fim Operação"], "Fim Operação")
    weekdays = _parse_weekdays(source)
    try:
        stage = int(_required_text(source["Nº Etapa"], "Nº Etapa"))
    except ValueError as error:
        raise AnacSirosRowError("Nº Etapa must be a positive integer") from error
    origin = _required_text(source["Cód. Origem"], "Cód. Origem").upper()
    destination = _required_text(source["Cód Destino"], "Cód Destino").upper()
    departure = _parse_clock(source["Horário Partida"], "Horário Partida")
    arrival = _parse_clock(source["Horário Chegada"], "Horário Chegada")
    try:
        return AnacSirosSeriesRow(
            siros_id=siros_id,
            operating_carrier=carrier,
            operating_flight_number=flight,
            stage_number=stage,
            origin_icao=origin,
            destination_icao=destination,
            valid_from=valid_from,
            valid_until=valid_until,
            active_weekdays=weekdays,
            scheduled_departure_time_utc=departure,
            scheduled_arrival_time_utc=arrival,
            registration_raw=registration_raw,
            snapshot_date=file.snapshot_date,  # type: ignore[arg-type]
            schedule_observed_at_utc=file.snapshot_observed_at_utc,
            source_url=file.source_url,
            raw_file_sha256=file.raw_file_sha256,
            row_number=row_number,
            source_values=values,
        )
    except ValueError as error:
        if isinstance(error, AnacSirosError):
            raise
        raise AnacSirosRowError(str(error)) from error


def load_siros_series_snapshot(
    path: Path,
    *,
    pin: AnacSirosSnapshotPin,
) -> AnacSirosSeriesSnapshot:
    """Load the exact proven daily SIROS series format from pinned local bytes."""

    file = validate_siros_file(path, pin)
    if pin.resource.kind != "daily_csv":
        raise AnacSirosUnsupportedSchemaError(
            "annual ZIP member names and schemas remain unreviewed"
        )
    raw = Path(path).expanduser().resolve().read_bytes()
    if not raw.startswith(codecs.BOM_UTF8):
        raise AnacSirosUnsupportedSchemaError(
            "daily SIROS series file is missing the proven UTF-8 BOM"
        )
    try:
        text = raw.decode(ANAC_SIROS_ENCODING)
    except UnicodeDecodeError as error:
        raise AnacSirosSourceError("daily SIROS file is not valid UTF-8") from error
    stream = io.StringIO(text, newline="")
    note_raw = stream.readline()
    if not note_raw:
        raise AnacSirosUnsupportedSchemaError("daily SIROS file has no UTC note line")
    note = note_raw.rstrip("\r\n")
    if note != ANAC_SIROS_UTC_NOTE:
        raise AnacSirosUnsupportedSchemaError(
            "first line does not exactly match the proven SIROS UTC note"
        )
    reader = csv.reader(stream, delimiter=ANAC_SIROS_DELIMITER)
    try:
        headers = tuple(next(reader))
    except StopIteration as error:
        raise AnacSirosUnsupportedSchemaError("daily SIROS file has no header row") from error
    if headers != ANAC_SIROS_SERIES_HEADERS:
        raise AnacSirosUnsupportedSchemaError(
            "SIROS headers do not exactly match the reviewed series schema"
        )

    accepted: list[AnacSirosSeriesRow] = []
    rejected: list[AnacSirosRejectedRow] = []
    row_audit: list[AnacSirosRowAudit] = []
    by_stage_identity: dict[str, AnacSirosSeriesRow] = {}
    for row_number, raw_values in enumerate(reader, start=3):
        values = tuple(raw_values)
        hint = _row_hint(values)
        try:
            row = _parse_series_row(values, row_number=row_number, file=file)
        except (AnacSirosRowError, ValueError) as error:
            reason = str(error)
            rejected.append(
                AnacSirosRejectedRow(
                    row_number=row_number,
                    reason=reason,
                    record_hint=hint,
                    source_values=values,
                )
            )
            row_audit.append(
                AnacSirosRowAudit(
                    row_number=row_number,
                    disposition="rejected",
                    record_hint=hint,
                    stage_revision_key=None,
                    reason=reason,
                )
            )
            continue

        existing = by_stage_identity.get(row.stage_revision_key)
        if existing is not None:
            if existing.series_facts_sha256 == row.series_facts_sha256:
                raise AnacSirosDuplicateError(
                    f"duplicate SIROS stage identity {row.stage_revision_key!r}"
                )
            raise AnacSirosConflictError(
                f"conflicting facts for SIROS stage {row.stage_revision_key!r}"
            )
        by_stage_identity[row.stage_revision_key] = row
        accepted.append(row)
        row_audit.append(
            AnacSirosRowAudit(
                row_number=row_number,
                disposition="accepted",
                record_hint=row.siros_id,
                stage_revision_key=row.stage_revision_key,
                reason=None,
            )
        )

    accepted_digest = hashlib.sha256(
        "\n".join(sorted(row.series_facts_sha256 for row in accepted)).encode("ascii")
    ).hexdigest()
    audit = AnacSirosSeriesAudit(
        file=file,
        note_line=note,
        exact_headers=headers,
        raw_row_count=len(row_audit),
        accepted_row_count=len(accepted),
        rejected_row_count=len(rejected),
        row_audit=tuple(row_audit),
        rejected_rows=tuple(rejected),
        accepted_series_facts_sha256=accepted_digest,
        completed=True,
    )
    return AnacSirosSeriesSnapshot(tuple(accepted), audit)


@dataclass(frozen=True, slots=True)
class AnacSirosServiceObservation:
    """One expanded UTC operation backed by a dated SIROS series snapshot."""

    siros_id: str
    stage_revision_key: str
    series_facts_sha256: str
    service_date: date
    operating_carrier: str
    operating_flight_number: str
    stage_number: int
    origin_icao: str
    destination_icao: str
    scheduled_departure_utc: datetime
    scheduled_arrival_utc: datetime
    schedule_observed_at_utc: datetime
    snapshot_date: date
    registration_raw: str
    source_url: str
    raw_file_sha256: str
    source_values: tuple[str, ...]

    def __post_init__(self) -> None:
        departure = _utc(self.scheduled_departure_utc, "scheduled_departure_utc")
        arrival = _utc(self.scheduled_arrival_utc, "scheduled_arrival_utc")
        observed = _utc(self.schedule_observed_at_utc, "schedule_observed_at_utc")
        duration = arrival - departure
        if not timedelta(0) < duration < timedelta(hours=24):
            raise ValueError("expanded SIROS block interval must be positive and under 24h")
        if departure.date() != self.service_date:
            raise ValueError("service_date must equal UTC scheduled departure date")
        object.__setattr__(self, "scheduled_departure_utc", departure)
        object.__setattr__(self, "scheduled_arrival_utc", arrival)
        object.__setattr__(self, "schedule_observed_at_utc", observed)
        object.__setattr__(self, "series_facts_sha256", _digest(self.series_facts_sha256, "series_facts_sha256"))
        object.__setattr__(self, "raw_file_sha256", _digest(self.raw_file_sha256, "raw_file_sha256"))
        object.__setattr__(self, "source_values", tuple(self.source_values))

    @property
    def revision_identity(self) -> str:
        return self.siros_id

    @property
    def service_identity_key(self) -> str:
        return _canonical_hash(
            {
                "stageRevisionKey": self.stage_revision_key,
                "serviceDate": self.service_date.isoformat(),
            }
        )

    @property
    def schedule_observation_key(self) -> str:
        return _canonical_hash(
            {
                "serviceIdentityKey": self.service_identity_key,
                "seriesFactsSha256": self.series_facts_sha256,
                "observedAtUtc": _iso_utc(self.schedule_observed_at_utc),
                "rawFileSha256": self.raw_file_sha256,
            }
        )

    def visible_at(self, as_of_utc: datetime) -> bool:
        return self.schedule_observed_at_utc <= _utc(as_of_utc, "as_of_utc")

    @property
    def source_strings(self) -> Mapping[str, str]:
        return MappingProxyType(dict(zip(ANAC_SIROS_SERIES_HEADERS, self.source_values)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "siros_id": self.siros_id,
            "revision_identity": self.revision_identity,
            "stage_revision_key": self.stage_revision_key,
            "series_facts_sha256": self.series_facts_sha256,
            "service_identity_key": self.service_identity_key,
            "schedule_observation_key": self.schedule_observation_key,
            "service_date": self.service_date.isoformat(),
            "operating_carrier": self.operating_carrier,
            "operating_flight_number": self.operating_flight_number,
            "stage_number": self.stage_number,
            "origin_icao": self.origin_icao,
            "destination_icao": self.destination_icao,
            "scheduled_departure_utc": _iso_utc(self.scheduled_departure_utc),
            "scheduled_arrival_utc": _iso_utc(self.scheduled_arrival_utc),
            "schedule_observed_at_utc": _iso_utc(self.schedule_observed_at_utc),
            "snapshot_date": self.snapshot_date.isoformat(),
            "registration_raw": self.registration_raw,
            "source_url": self.source_url,
            "raw_file_sha256": self.raw_file_sha256,
            "source_strings": dict(self.source_strings),
        }


def expand_siros_series_row(
    row: AnacSirosSeriesRow,
    service_date: date,
) -> AnacSirosServiceObservation | None:
    """Expand one active recurrence using the minimal positive UTC interval."""

    if not isinstance(row, AnacSirosSeriesRow):
        raise TypeError("row must be an AnacSirosSeriesRow")
    if not row.is_active_on(service_date):
        return None
    departure = datetime.combine(
        service_date,
        row.scheduled_departure_time_utc,
        tzinfo=timezone.utc,
    )
    arrival = datetime.combine(
        service_date,
        row.scheduled_arrival_time_utc,
        tzinfo=timezone.utc,
    )
    if arrival <= departure:
        arrival += timedelta(days=1)
    duration = arrival - departure
    if not timedelta(0) < duration < timedelta(hours=24):
        raise AnacSirosRowError(
            "series clocks do not form a minimal positive block interval under 24h"
        )
    return AnacSirosServiceObservation(
        siros_id=row.siros_id,
        stage_revision_key=row.stage_revision_key,
        series_facts_sha256=row.series_facts_sha256,
        service_date=service_date,
        operating_carrier=row.operating_carrier,
        operating_flight_number=row.operating_flight_number,
        stage_number=row.stage_number,
        origin_icao=row.origin_icao,
        destination_icao=row.destination_icao,
        scheduled_departure_utc=departure,
        scheduled_arrival_utc=arrival,
        schedule_observed_at_utc=row.schedule_observed_at_utc,
        snapshot_date=row.snapshot_date,
        registration_raw=row.registration_raw,
        source_url=row.source_url,
        raw_file_sha256=row.raw_file_sha256,
        source_values=row.source_values,
    )


def expand_siros_snapshot(
    snapshot: AnacSirosSeriesSnapshot,
    service_date: date,
) -> tuple[AnacSirosServiceObservation, ...]:
    if not isinstance(snapshot, AnacSirosSeriesSnapshot):
        raise TypeError("snapshot must be an AnacSirosSeriesSnapshot")
    expanded = (
        observation
        for row in snapshot.rows
        if (observation := expand_siros_series_row(row, service_date)) is not None
    )
    return tuple(
        sorted(
            expanded,
            key=lambda row: (
                row.scheduled_departure_utc,
                row.stage_revision_key,
            ),
        )
    )


def select_latest_visible_services(
    rows: Iterable[AnacSirosSeriesRow],
    *,
    service_date: date,
    as_of_utc: datetime,
) -> tuple[AnacSirosServiceObservation, ...]:
    """Keep the latest visible snapshot of each exact SIROS ID/stage.

    Distinct SIROS IDs are never joined as replacements because the reviewed
    raw format provides no replacement field.
    """

    cutoff = _utc(as_of_utc, "as_of_utc")
    latest: dict[str, AnacSirosServiceObservation] = {}
    for row in rows:
        if not isinstance(row, AnacSirosSeriesRow):
            raise TypeError("all rows must be AnacSirosSeriesRow values")
        expanded = expand_siros_series_row(row, service_date)
        if expanded is None or not expanded.visible_at(cutoff):
            continue
        existing = latest.get(expanded.service_identity_key)
        if existing is None or (
            expanded.schedule_observed_at_utc,
            expanded.series_facts_sha256,
        ) > (
            existing.schedule_observed_at_utc,
            existing.series_facts_sha256,
        ):
            latest[expanded.service_identity_key] = expanded
    return tuple(
        sorted(
            latest.values(),
            key=lambda row: (
                row.scheduled_departure_utc,
                row.stage_revision_key,
            ),
        )
    )


def select_services_at_t_minus_7(
    rows: Iterable[AnacSirosSeriesRow],
    *,
    service_date: date,
    target_departure_utc: datetime,
) -> tuple[AnacSirosServiceObservation, ...]:
    target = _utc(target_departure_utc, "target_departure_utc")
    return select_latest_visible_services(
        rows,
        service_date=service_date,
        as_of_utc=target - timedelta(days=7),
    )


__all__ = [
    "ANAC_SIROS_ANNUAL_YEARS",
    "ANAC_SIROS_BASE_URL",
    "ANAC_SIROS_DAILY_YEARS",
    "ANAC_SIROS_DELIMITER",
    "ANAC_SIROS_DOCUMENTATION_URL",
    "ANAC_SIROS_ENCODING",
    "ANAC_SIROS_SERIES_HEADERS",
    "ANAC_SIROS_SOURCE_ID",
    "ANAC_SIROS_UTC_NOTE",
    "ANAC_SIROS_WEEKDAY_HEADERS",
    "AnacSirosConflictError",
    "AnacSirosDuplicateError",
    "AnacSirosError",
    "AnacSirosFileProvenance",
    "AnacSirosRejectedRow",
    "AnacSirosResource",
    "AnacSirosRowAudit",
    "AnacSirosRowError",
    "AnacSirosSeriesAudit",
    "AnacSirosSeriesRow",
    "AnacSirosSeriesSnapshot",
    "AnacSirosServiceObservation",
    "AnacSirosSnapshotPin",
    "AnacSirosSourceError",
    "AnacSirosUnsupportedSchemaError",
    "annual_archive_manifest",
    "annual_zip_resource",
    "daily_snapshot_manifest",
    "daily_snapshot_resource",
    "expand_siros_series_row",
    "expand_siros_snapshot",
    "load_siros_series_snapshot",
    "select_latest_visible_services",
    "select_services_at_t_minus_7",
    "validate_siros_file",
]
