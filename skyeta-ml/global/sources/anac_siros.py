"""Strict offline loader for dated ANAC SIROS future-schedule snapshots.

ANAC's official SIROS directory exposes annual ZIP containers for 2018-2023
and daily CSV snapshots for 2024-2026.  The reviewed daily files and annual
members have this exact shape:

* UTF-8 BOM;
* first line ``Importante: Horários em UTC``; and
* the exact Portuguese header tuple in :data:`ANAC_SIROS_SERIES_HEADERS`.

The note is the source evidence that the two schedule clock columns are UTC.
``Data Registro`` has no documented timezone in the reviewed material.  It is
therefore retained and syntax-checked as a raw source string, but is never
labelled UTC, converted, or used to decide whether a row was visible at a
prediction cutoff.  Point-in-time visibility comes only from an independently
pinned Wayback capture, HTTP ``Last-Modified`` value, or (least preferably) the
retrieval time.  Annual-member filenames provide only retrospective
recorded-snapshot evidence; they never establish historical public
availability.

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
import stat
import unicodedata
import zlib
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Iterator, Literal, TypeAlias
from urllib.parse import quote, unquote, urlsplit


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
ANAC_SIROS_2023_ARCHIVE_BYTES = 340_405_397
ANAC_SIROS_2023_ARCHIVE_LAST_MODIFIED_UTC = datetime(
    2024, 7, 5, 1, 38, 23, tzinfo=timezone.utc
)
ANAC_SIROS_2023_ARCHIVE_LAST_MODIFIED_RAW = "Fri, 05 Jul 2024 01:38:23 GMT"
ANAC_SIROS_RETROSPECTIVE_POLICY_ID = (
    "anac_siros_member_date_next_day_bound_retrospective_only_v1"
)
ANAC_SIROS_MAX_MEMBER_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
ANAC_SIROS_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 128 * 1024 * 1024 * 1024
ANAC_SIROS_ANNUAL_REJECTION_DETAIL_LIMIT = 100

ResourceKind: TypeAlias = Literal["annual_zip", "daily_csv"]
AvailabilityEvidenceKind: TypeAlias = Literal[
    "wayback_capture",
    "http_last_modified",
    "retrieved_at",
]
SeriesEvidenceKind: TypeAlias = Literal[
    "wayback_capture",
    "http_last_modified",
    "retrieved_at",
    "retrospective_filename_date_bound",
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


def _optional_equipment(value: object) -> str | None:
    """Normalize SIROS ``Equip.`` without inventing a missing type."""

    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = " ".join(normalized.strip().upper().split())
    if not normalized:
        return None
    if any(ord(character) < 32 for character in normalized):
        raise ValueError("Equip. contains a control character")
    return normalized


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
class AnacSirosAnnualArchivePin:
    """Integrity metadata for an annual container, never snapshot visibility.

    ``archive_last_modified_utc`` describes the downloadable ZIP object.  It
    must not be copied onto a historical member or interpreted as the time at
    which any daily schedule snapshot was public.
    """

    resource: AnacSirosResource
    source_url: str
    retrieved_at_utc: datetime
    expected_sha256: str
    expected_bytes: int
    archive_last_modified_utc: datetime
    archive_last_modified_raw: str

    def __post_init__(self) -> None:
        if not isinstance(self.resource, AnacSirosResource):
            raise TypeError("resource must be an AnacSirosResource")
        if self.resource.kind != "annual_zip":
            raise AnacSirosSourceError("annual archive pin requires annual_zip")
        if self.source_url != self.resource.url:
            raise AnacSirosSourceError(
                "source URL does not match the annual SIROS resource"
            )
        retrieved = _utc(self.retrieved_at_utc, "retrieved_at_utc")
        last_modified = _utc(
            self.archive_last_modified_utc, "archive_last_modified_utc"
        )
        raw = str(self.archive_last_modified_raw)
        if not raw or raw != raw.strip():
            raise AnacSirosSourceError(
                "archive_last_modified_raw must preserve one exact HTTP-date"
            )
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError) as error:
            raise AnacSirosSourceError(
                "archive_last_modified_raw is not an RFC HTTP-date"
            ) from error
        if _utc(parsed, "parsed archive Last-Modified") != last_modified:
            raise AnacSirosSourceError(
                "raw and parsed archive Last-Modified values disagree"
            )
        if last_modified > retrieved:
            raise AnacSirosSourceError(
                "archive Last-Modified cannot follow the retrieval time"
            )
        if (
            isinstance(self.expected_bytes, bool)
            or not isinstance(self.expected_bytes, int)
            or self.expected_bytes <= 0
        ):
            raise ValueError("expected_bytes must be a positive integer")
        object.__setattr__(self, "retrieved_at_utc", retrieved)
        object.__setattr__(self, "archive_last_modified_utc", last_modified)
        object.__setattr__(self, "archive_last_modified_raw", raw)
        object.__setattr__(
            self, "expected_sha256", _digest(self.expected_sha256, "expected_sha256")
        )


def official_2023_annual_archive_pin(
    *,
    expected_sha256: str,
    retrieved_at_utc: datetime,
) -> AnacSirosAnnualArchivePin:
    """Build the reviewed 2023 pin without conflating archive and member time."""

    resource = annual_zip_resource(2023)
    return AnacSirosAnnualArchivePin(
        resource=resource,
        source_url=resource.url,
        retrieved_at_utc=retrieved_at_utc,
        expected_sha256=expected_sha256,
        expected_bytes=ANAC_SIROS_2023_ARCHIVE_BYTES,
        archive_last_modified_utc=ANAC_SIROS_2023_ARCHIVE_LAST_MODIFIED_UTC,
        archive_last_modified_raw=ANAC_SIROS_2023_ARCHIVE_LAST_MODIFIED_RAW,
    )


@dataclass(frozen=True, slots=True)
class AnacSirosRetrospectiveEvidencePolicy:
    """Explicit non-public evidence rule for archived dated members.

    A member named ``futuro_YYYY-MM-DD.csv`` proves that ANAC recorded a daily
    snapshot with that date.  For retrospective evaluation only, this policy
    assigns a conservative *recorded-snapshot bound* of next-day 00:00 UTC.
    It does not establish a historical HTTP publication time, point-in-time
    availability, or eligibility for a deployable backtest.
    """

    policy_id: str = ANAC_SIROS_RETROSPECTIVE_POLICY_ID
    scope: Literal["retrospective_only"] = "retrospective_only"
    bound_rule: Literal["member_date_plus_one_day_00_00_utc"] = (
        "member_date_plus_one_day_00_00_utc"
    )
    public_availability_proven: bool = False
    point_in_time_eligible: bool = False

    def __post_init__(self) -> None:
        if self.policy_id != ANAC_SIROS_RETROSPECTIVE_POLICY_ID:
            raise ValueError("unsupported retrospective evidence policy")
        if self.scope != "retrospective_only":
            raise ValueError("annual member evidence must remain retrospective-only")
        if self.bound_rule != "member_date_plus_one_day_00_00_utc":
            raise ValueError("unsupported retrospective member-date bound")
        if self.public_availability_proven or self.point_in_time_eligible:
            raise ValueError(
                "retrospective archive evidence cannot prove public availability"
            )

    def bound_for(self, snapshot_date: date) -> datetime:
        if not isinstance(snapshot_date, date) or isinstance(snapshot_date, datetime):
            raise ValueError("snapshot_date must be a date")
        return datetime.combine(
            snapshot_date + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AnacSirosFileProvenance:
    """Byte-level and point-in-time evidence established before parsing."""

    source_id: str
    source_provider: str
    dataset_name: str
    resource_kind: ResourceKind
    snapshot_date: date | None
    source_url: str
    availability_evidence_kind: SeriesEvidenceKind
    archive_url: str | None
    http_last_modified_utc: datetime | None
    http_last_modified_raw: str | None
    file_path: str
    filename: str
    snapshot_observed_at_utc: datetime
    retrieved_at_utc: datetime
    raw_file_sha256: str
    raw_bytes: int
    public_availability_proven: bool = True
    point_in_time_eligible: bool = True
    evidence_policy_id: str | None = None

    def __post_init__(self) -> None:
        observed = _utc(self.snapshot_observed_at_utc, "snapshot_observed_at_utc")
        retrieved = _utc(self.retrieved_at_utc, "retrieved_at_utc")
        if observed > retrieved:
            raise ValueError("snapshot evidence cannot follow retrieval")
        if (
            isinstance(self.raw_bytes, bool)
            or not isinstance(self.raw_bytes, int)
            or self.raw_bytes <= 0
        ):
            raise ValueError("raw_bytes must be positive")
        if not isinstance(self.public_availability_proven, bool):
            raise TypeError("public_availability_proven must be boolean")
        if not isinstance(self.point_in_time_eligible, bool):
            raise TypeError("point_in_time_eligible must be boolean")
        if self.point_in_time_eligible and not self.public_availability_proven:
            raise ValueError(
                "point-in-time eligibility requires proven public availability"
            )
        if self.availability_evidence_kind == "retrospective_filename_date_bound":
            if self.resource_kind != "annual_zip":
                raise ValueError(
                    "retrospective filename evidence requires an annual member"
                )
            if self.snapshot_date is None:
                raise ValueError(
                    "retrospective filename evidence requires a snapshot date"
                )
            expected_bound = AnacSirosRetrospectiveEvidencePolicy().bound_for(
                self.snapshot_date
            )
            if observed != expected_bound:
                raise ValueError(
                    "retrospective filename evidence must use the reviewed next-day bound"
                )
            if self.archive_url is not None or self.http_last_modified_utc is not None:
                raise ValueError(
                    "annual member evidence must not inherit archive publication fields"
                )
            if self.http_last_modified_raw is not None:
                raise ValueError(
                    "annual member evidence must not inherit archive publication fields"
                )
        elif self.availability_evidence_kind not in {
            "wayback_capture",
            "http_last_modified",
            "retrieved_at",
        }:
            raise ValueError("unsupported SIROS series evidence kind")

        if self.point_in_time_eligible:
            if self.evidence_policy_id is not None:
                raise ValueError(
                    "point-in-time provenance must not use a retrospective policy"
                )
            if self.availability_evidence_kind == "retrospective_filename_date_bound":
                raise ValueError(
                    "retrospective filename evidence cannot be point-in-time eligible"
                )
        elif self.evidence_policy_id != ANAC_SIROS_RETROSPECTIVE_POLICY_ID:
            raise ValueError(
                "non-point-in-time provenance requires the reviewed retrospective policy"
            )
        elif self.availability_evidence_kind != "retrospective_filename_date_bound":
            raise ValueError(
                "the reviewed retrospective policy requires filename-date evidence"
            )
        object.__setattr__(
            self, "raw_file_sha256", _digest(self.raw_file_sha256, "raw_file_sha256")
        )
        object.__setattr__(self, "snapshot_observed_at_utc", observed)
        object.__setattr__(self, "retrieved_at_utc", retrieved)

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


def _stream_file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            count += len(chunk)
    return digest.hexdigest(), count


def _stream_open_file_sha256(stream: Any) -> tuple[str, int]:
    """Hash one already-open seekable handle and rewind it for the next reader."""

    stream.seek(0)
    digest = hashlib.sha256()
    count = 0
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
        count += len(chunk)
    stream.seek(0)
    return digest.hexdigest(), count


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
    actual_digest, actual_bytes = _stream_file_sha256(resolved)
    if actual_bytes != pin.expected_bytes:
        raise AnacSirosSourceError(
            f"SIROS byte count mismatch: expected {pin.expected_bytes}, got {actual_bytes}"
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
        raw_bytes=actual_bytes,
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
    aircraft_family: str | None
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
    public_availability_proven: bool = True
    point_in_time_eligible: bool = True
    evidence_policy_id: str | None = None

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
        if not isinstance(self.public_availability_proven, bool):
            raise TypeError("public_availability_proven must be boolean")
        if not isinstance(self.point_in_time_eligible, bool):
            raise TypeError("point_in_time_eligible must be boolean")
        if self.point_in_time_eligible and not self.public_availability_proven:
            raise ValueError(
                "point-in-time eligibility requires proven public availability"
            )
        if self.point_in_time_eligible:
            if self.evidence_policy_id is not None:
                raise ValueError(
                    "point-in-time rows must not use a retrospective policy"
                )
        elif self.evidence_policy_id != ANAC_SIROS_RETROSPECTIVE_POLICY_ID:
            raise ValueError(
                "annual archive rows require the reviewed retrospective policy"
            )

        object.__setattr__(self, "siros_id", siros_id)
        object.__setattr__(self, "operating_carrier", carrier)
        object.__setattr__(self, "operating_flight_number", flight)
        object.__setattr__(
            self, "aircraft_family", _optional_equipment(self.aircraft_family)
        )
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
                "aircraftFamily": self.aircraft_family,
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

        if not self.point_in_time_eligible:
            raise AnacSirosSourceError(
                "retrospective annual-member evidence cannot establish public visibility"
            )
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
            "aircraft_family": self.aircraft_family,
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
            "public_availability_proven": self.public_availability_proven,
            "point_in_time_eligible": self.point_in_time_eligible,
            "evidence_policy_id": self.evidence_policy_id,
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
    aircraft_family = _optional_equipment(source["Equip."])
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
            aircraft_family=aircraft_family,
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
            public_availability_proven=file.public_availability_proven,
            point_in_time_eligible=file.point_in_time_eligible,
            evidence_policy_id=file.evidence_policy_id,
        )
    except ValueError as error:
        if isinstance(error, AnacSirosError):
            raise
        raise AnacSirosRowError(str(error)) from error


def _build_siros_series_snapshot(
    *,
    file: AnacSirosFileProvenance,
    note: str,
    headers: tuple[str, ...],
    source_rows: Iterable[tuple[int, tuple[str, ...]]],
) -> AnacSirosSeriesSnapshot:
    """Build one snapshot from an already decoded stream of exact source rows."""

    if note != ANAC_SIROS_UTC_NOTE:
        raise AnacSirosUnsupportedSchemaError(
            "first line does not exactly match the proven SIROS UTC note"
        )
    if headers != ANAC_SIROS_SERIES_HEADERS:
        raise AnacSirosUnsupportedSchemaError(
            "SIROS headers do not exactly match the reviewed series schema"
        )

    accepted: list[AnacSirosSeriesRow] = []
    rejected: list[AnacSirosRejectedRow] = []
    row_audit: list[AnacSirosRowAudit] = []
    by_stage_identity: dict[str, AnacSirosSeriesRow] = {}
    for row_number, values in source_rows:
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


def load_siros_series_snapshot(
    path: Path,
    *,
    pin: AnacSirosSnapshotPin,
) -> AnacSirosSeriesSnapshot:
    """Load the exact proven daily SIROS series format from pinned local bytes."""

    file = validate_siros_file(path, pin)
    if pin.resource.kind != "daily_csv":
        raise AnacSirosUnsupportedSchemaError(
            "annual ZIP resources require the strict annual archive API"
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

    return _build_siros_series_snapshot(
        file=file,
        note=note,
        headers=headers,
        source_rows=(
            (row_number, tuple(raw_values))
            for row_number, raw_values in enumerate(reader, start=3)
        ),
    )


@dataclass(frozen=True, slots=True)
class AnacSirosAnnualArchiveProvenance:
    """Pinned annual-container facts with no historical member-time claim."""

    source_url: str
    year: int
    file_path: str
    filename: str
    retrieved_at_utc: datetime
    archive_last_modified_utc: datetime
    archive_last_modified_raw: str
    archive_sha256: str
    archive_bytes: int

    def __post_init__(self) -> None:
        if self.year not in ANAC_SIROS_ANNUAL_YEARS:
            raise ValueError("annual archive year must be between 2018 and 2023")
        resource = annual_zip_resource(self.year)
        if self.source_url != resource.url or self.filename != resource.filename:
            raise ValueError("annual archive provenance does not match its resource")
        retrieved = _utc(self.retrieved_at_utc, "retrieved_at_utc")
        modified = _utc(
            self.archive_last_modified_utc, "archive_last_modified_utc"
        )
        if modified > retrieved:
            raise ValueError("archive Last-Modified cannot follow retrieval")
        if (
            isinstance(self.archive_bytes, bool)
            or not isinstance(self.archive_bytes, int)
            or self.archive_bytes <= 0
        ):
            raise ValueError("archive_bytes must be positive")
        object.__setattr__(self, "retrieved_at_utc", retrieved)
        object.__setattr__(self, "archive_last_modified_utc", modified)
        object.__setattr__(
            self, "archive_sha256", _digest(self.archive_sha256, "archive_sha256")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "year": self.year,
            "file_path": self.file_path,
            "filename": self.filename,
            "retrieved_at_utc": _iso_utc(self.retrieved_at_utc),
            "archive_last_modified_utc": _iso_utc(
                self.archive_last_modified_utc
            ),
            "archive_last_modified_raw": self.archive_last_modified_raw,
            "archive_sha256": self.archive_sha256,
            "archive_bytes": self.archive_bytes,
            "archive_time_is_member_availability": False,
        }


@dataclass(frozen=True, slots=True)
class AnacSirosAnnualMemberAudit:
    """Bounded member summary with complete counts and full-row audit digest.

    ``rejected_rows`` contains at most ``rejection_detail_limit`` examples;
    ``rejected_row_count`` and ``row_audit_sha256`` still cover every row.
    """

    member_name: str
    snapshot_date: date
    compression_method: Literal["deflate"]
    compressed_bytes: int
    uncompressed_bytes: int
    central_crc32: int
    computed_crc32: int
    member_sha256: str
    note_line: str
    exact_headers: tuple[str, ...]
    raw_row_count: int
    accepted_row_count: int
    rejected_row_count: int
    rejected_rows: tuple[AnacSirosRejectedRow, ...]
    rejection_detail_limit: int
    rejection_detail_count: int
    rejection_detail_truncated_count: int
    row_audit_sha256: str
    accepted_series_facts_sha256: str
    retrospective_evidence_bound_utc: datetime
    member_content_sha256: str
    public_availability_proven: bool = False
    point_in_time_eligible: bool = False

    def __post_init__(self) -> None:
        if self.compression_method != "deflate":
            raise ValueError("annual SIROS members must use DEFLATE")
        if self.note_line != ANAC_SIROS_UTC_NOTE:
            raise ValueError("annual member note does not match the proven UTC note")
        if tuple(self.exact_headers) != ANAC_SIROS_SERIES_HEADERS:
            raise ValueError("annual member headers do not match the proven schema")
        if self.raw_row_count != self.accepted_row_count + self.rejected_row_count:
            raise ValueError("annual member row counts do not reconcile")
        rejected = tuple(self.rejected_rows)
        if (
            isinstance(self.rejection_detail_limit, bool)
            or not isinstance(self.rejection_detail_limit, int)
            or self.rejection_detail_limit < 0
        ):
            raise ValueError("rejection_detail_limit must be a non-negative integer")
        if self.rejection_detail_count != len(rejected):
            raise ValueError("annual member rejection-detail count does not reconcile")
        if self.rejection_detail_count != min(
            self.rejected_row_count, self.rejection_detail_limit
        ):
            raise ValueError("annual member rejection details do not obey their bound")
        if self.rejection_detail_truncated_count != (
            self.rejected_row_count - self.rejection_detail_count
        ):
            raise ValueError("annual member truncated-rejection count does not reconcile")
        if self.uncompressed_bytes <= 0 or self.compressed_bytes <= 0:
            raise ValueError("annual member sizes must be positive")
        if self.central_crc32 != self.computed_crc32:
            raise ValueError("annual member CRC values do not reconcile")
        if self.public_availability_proven or self.point_in_time_eligible:
            raise ValueError("annual member audit must remain retrospective-only")
        bound = _utc(
            self.retrospective_evidence_bound_utc,
            "retrospective_evidence_bound_utc",
        )
        object.__setattr__(self, "retrospective_evidence_bound_utc", bound)
        object.__setattr__(self, "rejected_rows", rejected)
        for field_name in (
            "member_sha256",
            "row_audit_sha256",
            "accepted_series_facts_sha256",
            "member_content_sha256",
        ):
            object.__setattr__(self, field_name, _digest(getattr(self, field_name), field_name))

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["snapshot_date"] = self.snapshot_date.isoformat()
        result["retrospective_evidence_bound_utc"] = _iso_utc(
            self.retrospective_evidence_bound_utc
        )
        result["central_crc32"] = f"{self.central_crc32:08x}"
        result["computed_crc32"] = f"{self.computed_crc32:08x}"
        result["exact_headers"] = list(self.exact_headers)
        result["rejected_rows"] = [asdict(row) for row in self.rejected_rows]
        return result


@dataclass(frozen=True, slots=True)
class AnacSirosAnnualArchiveAudit:
    archive: AnacSirosAnnualArchiveProvenance
    evidence_policy: AnacSirosRetrospectiveEvidencePolicy
    directory_name: str
    directory_count: int
    expected_member_count: int
    actual_member_count: int
    first_snapshot_date: date
    last_snapshot_date: date
    calendar_complete: bool
    total_compressed_bytes: int
    total_uncompressed_bytes: int
    total_raw_row_count: int
    total_accepted_row_count: int
    total_rejected_row_count: int
    members: tuple[AnacSirosAnnualMemberAudit, ...]
    archive_content_sha256: str
    audit_sha256: str
    point_in_time_publication_evidence: bool = False
    completed: bool = True

    def __post_init__(self) -> None:
        members = tuple(self.members)
        if self.directory_name != f"{self.archive.year}/" or self.directory_count != 1:
            raise ValueError("annual archive must contain its one exact year directory")
        if self.expected_member_count != len(_calendar_dates(self.archive.year)):
            raise ValueError("expected member count does not match the full calendar")
        if self.actual_member_count != len(members):
            raise ValueError("actual member count does not match member audit")
        if self.actual_member_count != self.expected_member_count:
            raise ValueError("annual archive calendar is incomplete")
        if not self.calendar_complete:
            raise ValueError("annual archive must pass the exact calendar check")
        if members:
            if members[0].snapshot_date != self.first_snapshot_date:
                raise ValueError("first member date does not reconcile")
            if members[-1].snapshot_date != self.last_snapshot_date:
                raise ValueError("last member date does not reconcile")
            for snapshot_date, member in zip(
                _calendar_dates(self.archive.year), members, strict=True
            ):
                if member.snapshot_date != snapshot_date or member.member_name != (
                    _annual_member_name(self.archive.year, snapshot_date)
                ):
                    raise ValueError("annual member audit is not in exact calendar order")
        if self.total_compressed_bytes != sum(row.compressed_bytes for row in members):
            raise ValueError("compressed member bytes do not reconcile")
        if self.total_uncompressed_bytes != sum(row.uncompressed_bytes for row in members):
            raise ValueError("uncompressed member bytes do not reconcile")
        if self.total_raw_row_count != sum(row.raw_row_count for row in members):
            raise ValueError("raw archive rows do not reconcile")
        if self.total_accepted_row_count != sum(row.accepted_row_count for row in members):
            raise ValueError("accepted archive rows do not reconcile")
        if self.total_rejected_row_count != sum(row.rejected_row_count for row in members):
            raise ValueError("rejected archive rows do not reconcile")
        if self.total_raw_row_count != (
            self.total_accepted_row_count + self.total_rejected_row_count
        ):
            raise ValueError("annual archive row totals do not reconcile")
        if self.point_in_time_publication_evidence:
            raise ValueError("annual archive audit cannot claim publication evidence")
        object.__setattr__(self, "members", members)
        object.__setattr__(
            self,
            "archive_content_sha256",
            _digest(self.archive_content_sha256, "archive_content_sha256"),
        )
        object.__setattr__(
            self, "audit_sha256", _digest(self.audit_sha256, "audit_sha256")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "archive": self.archive.to_dict(),
            "evidence_policy": self.evidence_policy.to_dict(),
            "directory_name": self.directory_name,
            "directory_count": self.directory_count,
            "expected_member_count": self.expected_member_count,
            "actual_member_count": self.actual_member_count,
            "first_snapshot_date": self.first_snapshot_date.isoformat(),
            "last_snapshot_date": self.last_snapshot_date.isoformat(),
            "calendar_complete": self.calendar_complete,
            "total_compressed_bytes": self.total_compressed_bytes,
            "total_uncompressed_bytes": self.total_uncompressed_bytes,
            "total_raw_row_count": self.total_raw_row_count,
            "total_accepted_row_count": self.total_accepted_row_count,
            "total_rejected_row_count": self.total_rejected_row_count,
            "members": [row.to_dict() for row in self.members],
            "archive_content_sha256": self.archive_content_sha256,
            "audit_sha256": self.audit_sha256,
            "point_in_time_publication_evidence": False,
            "completed": self.completed,
        }


def _calendar_dates(year: int) -> tuple[date, ...]:
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    return tuple(
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
    )


def _annual_member_name(year: int, snapshot_date: date) -> str:
    return f"{year}/futuro_{snapshot_date.isoformat()}.csv"


def _validate_archive_member_path(name: str) -> None:
    if not name or "\x00" in name or "\\" in name:
        raise AnacSirosSourceError("annual ZIP contains an unsafe member path")
    parsed = PurePosixPath(name)
    if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
        raise AnacSirosSourceError("annual ZIP contains an unsafe member path")
    if re.match(r"^[A-Za-z]:", name):
        raise AnacSirosSourceError("annual ZIP contains an unsafe drive-qualified path")


def _validated_annual_member_infos(
    archive: zipfile.ZipFile,
    year: int,
) -> tuple[zipfile.ZipInfo, ...]:
    infos = archive.infolist()
    names = [info.filename for info in infos]
    for name in names:
        _validate_archive_member_path(name)
    if len(names) != len(set(names)):
        raise AnacSirosSourceError("annual ZIP contains a duplicate member name")
    if len(names) != len({name.casefold() for name in names}):
        raise AnacSirosSourceError(
            "annual ZIP contains case-insensitive duplicate member names"
        )
    for info in infos:
        unix_mode = (info.external_attr >> 16) & 0o170000
        if unix_mode == stat.S_IFLNK:
            raise AnacSirosSourceError("annual ZIP contains a symbolic-link member")
        if info.flag_bits & 0x1:
            raise AnacSirosSourceError("annual ZIP contains an encrypted member")

    directory_name = f"{year}/"
    directories = [info for info in infos if info.is_dir()]
    if len(directories) != 1 or directories[0].filename != directory_name:
        raise AnacSirosUnsupportedSchemaError(
            "annual ZIP must contain exactly one year directory"
        )
    expected_names = {
        _annual_member_name(year, snapshot_date)
        for snapshot_date in _calendar_dates(year)
    }
    files = [info for info in infos if not info.is_dir()]
    actual_names = {info.filename for info in files}
    if actual_names != expected_names or len(files) != len(expected_names):
        missing = sorted(expected_names - actual_names)
        extra = sorted(actual_names - expected_names)
        raise AnacSirosUnsupportedSchemaError(
            "annual ZIP calendar is not exact; "
            f"missing={missing[:3]!r}, extra={extra[:3]!r}"
        )
    total_uncompressed = 0
    for info in files:
        if info.compress_type != zipfile.ZIP_DEFLATED:
            raise AnacSirosUnsupportedSchemaError(
                f"annual member {info.filename!r} is not DEFLATE-compressed"
            )
        if info.file_size <= 0 or info.file_size > ANAC_SIROS_MAX_MEMBER_UNCOMPRESSED_BYTES:
            raise AnacSirosSourceError(
                f"annual member {info.filename!r} has an unsafe uncompressed size"
            )
        if info.compress_size <= 0:
            raise AnacSirosSourceError(
                f"annual member {info.filename!r} has an invalid compressed size"
            )
        if info.file_size > info.compress_size * 1000:
            raise AnacSirosSourceError(
                f"annual member {info.filename!r} exceeds the compression-ratio limit"
            )
        total_uncompressed += info.file_size
    if total_uncompressed > ANAC_SIROS_MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        raise AnacSirosSourceError("annual ZIP exceeds the uncompressed safety limit")
    by_name = {info.filename: info for info in files}
    return tuple(
        by_name[_annual_member_name(year, snapshot_date)]
        for snapshot_date in _calendar_dates(year)
    )


class _DigestingReader(io.RawIOBase):
    def __init__(self, source: Any) -> None:
        super().__init__()
        self._source = source
        self.sha256 = hashlib.sha256()
        self.crc32 = 0
        self.byte_count = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        data = self._source.read(len(buffer))
        if not data:
            return 0
        buffer[: len(data)] = data
        self.sha256.update(data)
        self.crc32 = zlib.crc32(data, self.crc32)
        self.byte_count += len(data)
        return len(data)

    def close(self) -> None:
        try:
            self._source.close()
        finally:
            super().close()


def _member_snapshot_date(year: int, member_name: str) -> date:
    prefix = f"{year}/futuro_"
    if not member_name.startswith(prefix) or not member_name.endswith(".csv"):
        raise AnacSirosUnsupportedSchemaError("annual member name is not canonical")
    rendered = member_name[len(prefix) : -4]
    try:
        parsed = date.fromisoformat(rendered)
    except ValueError as error:
        raise AnacSirosUnsupportedSchemaError(
            "annual member date is not a valid ISO calendar date"
        ) from error
    if parsed.year != year or member_name != _annual_member_name(year, parsed):
        raise AnacSirosUnsupportedSchemaError("annual member date is not canonical")
    return parsed


def _annual_member_source_url(archive_url: str, member_name: str) -> str:
    return f"{archive_url}#member={quote(member_name, safe='/-_.')}"


def _update_row_audit_digest(
    digest: Any,
    row: AnacSirosRowAudit,
) -> None:
    digest.update(
        json.dumps(
            asdict(row),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    digest.update(b"\n")


def _row_audit_digest(rows: Iterable[AnacSirosRowAudit]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        _update_row_audit_digest(digest, row)
    return digest.hexdigest()


def _read_annual_member_preamble(
    text_stream: Any,
    member_name: str,
) -> tuple[str, tuple[str, ...], Any]:
    note_raw = text_stream.readline()
    if not note_raw:
        raise AnacSirosUnsupportedSchemaError(
            f"annual member {member_name!r} has no UTC note line"
        )
    note = note_raw.rstrip("\r\n")
    if note != ANAC_SIROS_UTC_NOTE:
        raise AnacSirosUnsupportedSchemaError(
            f"annual member {member_name!r} has an invalid UTC note"
        )
    reader = csv.reader(text_stream, delimiter=ANAC_SIROS_DELIMITER)
    try:
        headers = tuple(next(reader))
    except StopIteration as error:
        raise AnacSirosUnsupportedSchemaError(
            f"annual member {member_name!r} has no header row"
        ) from error
    if headers != ANAC_SIROS_SERIES_HEADERS:
        raise AnacSirosUnsupportedSchemaError(
            f"annual member {member_name!r} headers do not match the reviewed schema"
        )
    return note, headers, reader


def _annual_member_file_provenance(
    *,
    archive_provenance: AnacSirosAnnualArchiveProvenance,
    info: zipfile.ZipInfo,
    evidence_policy: AnacSirosRetrospectiveEvidencePolicy,
    member_sha256: str,
    member_bytes: int,
) -> AnacSirosFileProvenance:
    snapshot_date = _member_snapshot_date(archive_provenance.year, info.filename)
    return AnacSirosFileProvenance(
        source_id=ANAC_SIROS_SOURCE_ID,
        source_provider=ANAC_SIROS_SOURCE_PROVIDER,
        dataset_name=ANAC_SIROS_DATASET_NAME,
        resource_kind="annual_zip",
        snapshot_date=snapshot_date,
        source_url=_annual_member_source_url(
            archive_provenance.source_url, info.filename
        ),
        availability_evidence_kind="retrospective_filename_date_bound",
        archive_url=None,
        http_last_modified_utc=None,
        http_last_modified_raw=None,
        file_path=f"{archive_provenance.file_path}!{info.filename}",
        filename=info.filename,
        snapshot_observed_at_utc=evidence_policy.bound_for(snapshot_date),
        retrieved_at_utc=archive_provenance.retrieved_at_utc,
        raw_file_sha256=member_sha256,
        raw_bytes=member_bytes,
        public_availability_proven=False,
        point_in_time_eligible=False,
        evidence_policy_id=evidence_policy.policy_id,
    )


def _verify_annual_member_metrics(
    info: zipfile.ZipInfo,
    *,
    actual_bytes: int,
    actual_crc: int,
) -> None:
    if actual_bytes != info.file_size:
        raise AnacSirosSourceError(
            f"annual member {info.filename!r} size disagrees with the central directory"
        )
    if actual_crc != info.CRC:
        raise AnacSirosSourceError(
            f"annual member {info.filename!r} CRC disagrees with the central directory"
        )


class _AnnualMemberAuditAccumulator:
    """Streaming row audit; retains no source rows or normalized row objects."""

    def __init__(
        self,
        file: AnacSirosFileProvenance,
        *,
        rejection_detail_limit: int,
    ) -> None:
        self.file = file
        self.rejection_detail_limit = rejection_detail_limit
        self.raw_row_count = 0
        self.accepted_row_count = 0
        self.rejected_row_count = 0
        self.rejected_rows: list[AnacSirosRejectedRow] = []
        self.row_audit_digest = hashlib.sha256()
        self.accepted_fact_digests: list[bytes] = []
        self.by_stage_identity: dict[str, str] = {}

    def consume(self, row_number: int, values: tuple[str, ...]) -> None:
        self.raw_row_count += 1
        hint = _row_hint(values)
        try:
            row = _parse_series_row(values, row_number=row_number, file=self.file)
        except (AnacSirosRowError, ValueError) as error:
            reason = str(error)
            self.rejected_row_count += 1
            if len(self.rejected_rows) < self.rejection_detail_limit:
                self.rejected_rows.append(
                    AnacSirosRejectedRow(
                        row_number=row_number,
                        reason=reason,
                        record_hint=hint,
                        source_values=values,
                    )
                )
            _update_row_audit_digest(
                self.row_audit_digest,
                AnacSirosRowAudit(
                    row_number=row_number,
                    disposition="rejected",
                    record_hint=hint,
                    stage_revision_key=None,
                    reason=reason,
                ),
            )
            return

        existing_digest = self.by_stage_identity.get(row.stage_revision_key)
        if existing_digest is not None:
            if existing_digest == row.series_facts_sha256:
                raise AnacSirosDuplicateError(
                    f"duplicate SIROS stage identity {row.stage_revision_key!r}"
                )
            raise AnacSirosConflictError(
                f"conflicting facts for SIROS stage {row.stage_revision_key!r}"
            )
        self.by_stage_identity[row.stage_revision_key] = row.series_facts_sha256
        self.accepted_fact_digests.append(row.series_facts_sha256.encode("ascii"))
        self.accepted_row_count += 1
        _update_row_audit_digest(
            self.row_audit_digest,
            AnacSirosRowAudit(
                row_number=row_number,
                disposition="accepted",
                record_hint=row.siros_id,
                stage_revision_key=row.stage_revision_key,
                reason=None,
            ),
        )

    @property
    def accepted_series_facts_sha256(self) -> str:
        return hashlib.sha256(
            b"\n".join(sorted(self.accepted_fact_digests))
        ).hexdigest()


def _build_annual_member_audit(
    *,
    info: zipfile.ZipInfo,
    file: AnacSirosFileProvenance,
    note: str,
    headers: tuple[str, ...],
    raw_row_count: int,
    accepted_row_count: int,
    rejected_row_count: int,
    rejected_rows: tuple[AnacSirosRejectedRow, ...],
    rejection_detail_limit: int,
    row_audit_sha256: str,
    accepted_series_facts_sha256: str,
    actual_crc: int,
) -> AnacSirosAnnualMemberAudit:
    rejection_detail_count = len(rejected_rows)
    content = {
        "memberName": info.filename,
        "snapshotDate": file.snapshot_date.isoformat(),  # type: ignore[union-attr]
        "compression": "deflate",
        "compressedBytes": info.compress_size,
        "uncompressedBytes": file.raw_bytes,
        "crc32": f"{actual_crc:08x}",
        "memberSha256": file.raw_file_sha256,
        "rawRowCount": raw_row_count,
        "acceptedRowCount": accepted_row_count,
        "rejectedRowCount": rejected_row_count,
        "rejectionDetailLimit": rejection_detail_limit,
        "rejectionDetailCount": rejection_detail_count,
        "rejectionDetailTruncatedCount": rejected_row_count - rejection_detail_count,
        "rowAuditSha256": row_audit_sha256,
        "acceptedSeriesFactsSha256": accepted_series_facts_sha256,
        "retrospectiveEvidenceBoundUtc": _iso_utc(
            file.snapshot_observed_at_utc
        ),
        "evidencePolicyId": file.evidence_policy_id,
        "publicAvailabilityProven": False,
        "pointInTimeEligible": False,
    }
    return AnacSirosAnnualMemberAudit(
        member_name=info.filename,
        snapshot_date=file.snapshot_date,  # type: ignore[arg-type]
        compression_method="deflate",
        compressed_bytes=info.compress_size,
        uncompressed_bytes=file.raw_bytes,
        central_crc32=info.CRC,
        computed_crc32=actual_crc,
        member_sha256=file.raw_file_sha256,
        note_line=note,
        exact_headers=headers,
        raw_row_count=raw_row_count,
        accepted_row_count=accepted_row_count,
        rejected_row_count=rejected_row_count,
        rejected_rows=rejected_rows,
        rejection_detail_limit=rejection_detail_limit,
        rejection_detail_count=rejection_detail_count,
        rejection_detail_truncated_count=rejected_row_count - rejection_detail_count,
        row_audit_sha256=row_audit_sha256,
        accepted_series_facts_sha256=accepted_series_facts_sha256,
        retrospective_evidence_bound_utc=file.snapshot_observed_at_utc,
        member_content_sha256=_canonical_hash(content),
    )


def _scan_annual_member_audit(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    archive_provenance: AnacSirosAnnualArchiveProvenance,
    evidence_policy: AnacSirosRetrospectiveEvidencePolicy,
    rejection_detail_limit: int = ANAC_SIROS_ANNUAL_REJECTION_DETAIL_LIMIT,
) -> AnacSirosAnnualMemberAudit:
    provisional_file = _annual_member_file_provenance(
        archive_provenance=archive_provenance,
        info=info,
        evidence_policy=evidence_policy,
        member_sha256="0" * 64,
        member_bytes=info.file_size,
    )
    accumulator = _AnnualMemberAuditAccumulator(
        provisional_file,
        rejection_detail_limit=rejection_detail_limit,
    )
    digesting: _DigestingReader | None = None
    try:
        with archive.open(info, "r") as compressed:
            digesting = _DigestingReader(compressed)
            with io.BufferedReader(digesting) as buffered:
                prefix = buffered.peek(len(codecs.BOM_UTF8))[: len(codecs.BOM_UTF8)]
                if prefix != codecs.BOM_UTF8:
                    raise AnacSirosUnsupportedSchemaError(
                        f"annual member {info.filename!r} is missing the UTF-8 BOM"
                    )
                with io.TextIOWrapper(
                    buffered,
                    encoding=ANAC_SIROS_ENCODING,
                    newline="",
                ) as text_stream:
                    note, headers, reader = _read_annual_member_preamble(
                        text_stream, info.filename
                    )
                    for row_number, values in enumerate(reader, start=3):
                        accumulator.consume(row_number, tuple(values))
    except UnicodeDecodeError as error:
        raise AnacSirosSourceError(
            f"annual member {info.filename!r} is not valid UTF-8"
        ) from error
    except csv.Error as error:
        raise AnacSirosSourceError(
            f"annual member {info.filename!r} is not valid CSV"
        ) from error
    except (zipfile.BadZipFile, zlib.error, EOFError) as error:
        raise AnacSirosSourceError(
            f"annual member {info.filename!r} failed ZIP CRC validation"
        ) from error
    if digesting is None:
        raise AssertionError("annual member stream was not initialized")
    actual_bytes = digesting.byte_count
    actual_crc = digesting.crc32 & 0xFFFFFFFF
    _verify_annual_member_metrics(
        info,
        actual_bytes=actual_bytes,
        actual_crc=actual_crc,
    )
    file = _annual_member_file_provenance(
        archive_provenance=archive_provenance,
        info=info,
        evidence_policy=evidence_policy,
        member_sha256=digesting.sha256.hexdigest(),
        member_bytes=actual_bytes,
    )
    return _build_annual_member_audit(
        info=info,
        file=file,
        note=note,
        headers=headers,
        raw_row_count=accumulator.raw_row_count,
        accepted_row_count=accumulator.accepted_row_count,
        rejected_row_count=accumulator.rejected_row_count,
        rejected_rows=tuple(accumulator.rejected_rows),
        rejection_detail_limit=rejection_detail_limit,
        row_audit_sha256=accumulator.row_audit_digest.hexdigest(),
        accepted_series_facts_sha256=accumulator.accepted_series_facts_sha256,
        actual_crc=actual_crc,
    )


def _hash_annual_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    actual_bytes = 0
    actual_crc = 0
    try:
        with archive.open(info, "r") as compressed:
            while chunk := compressed.read(1024 * 1024):
                digest.update(chunk)
                actual_crc = zlib.crc32(chunk, actual_crc)
                actual_bytes += len(chunk)
    except (zipfile.BadZipFile, zlib.error, EOFError) as error:
        raise AnacSirosSourceError(
            f"annual member {info.filename!r} failed ZIP CRC validation"
        ) from error
    actual_crc &= 0xFFFFFFFF
    _verify_annual_member_metrics(
        info,
        actual_bytes=actual_bytes,
        actual_crc=actual_crc,
    )
    return digest.hexdigest(), actual_bytes, actual_crc


def _load_annual_member_snapshot(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    *,
    archive_provenance: AnacSirosAnnualArchiveProvenance,
    evidence_policy: AnacSirosRetrospectiveEvidencePolicy,
) -> tuple[AnacSirosSeriesSnapshot, AnacSirosAnnualMemberAudit]:
    member_sha256, member_bytes, actual_crc = _hash_annual_member(archive, info)
    file = _annual_member_file_provenance(
        archive_provenance=archive_provenance,
        info=info,
        evidence_policy=evidence_policy,
        member_sha256=member_sha256,
        member_bytes=member_bytes,
    )
    try:
        with archive.open(info, "r") as compressed:
            with io.BufferedReader(compressed) as buffered:
                prefix = buffered.peek(len(codecs.BOM_UTF8))[: len(codecs.BOM_UTF8)]
                if prefix != codecs.BOM_UTF8:
                    raise AnacSirosUnsupportedSchemaError(
                        f"annual member {info.filename!r} is missing the UTF-8 BOM"
                    )
                with io.TextIOWrapper(
                    buffered,
                    encoding=ANAC_SIROS_ENCODING,
                    newline="",
                ) as text_stream:
                    note, headers, reader = _read_annual_member_preamble(
                        text_stream, info.filename
                    )
                    snapshot = _build_siros_series_snapshot(
                        file=file,
                        note=note,
                        headers=headers,
                        source_rows=(
                            (row_number, tuple(values))
                            for row_number, values in enumerate(reader, start=3)
                        ),
                    )
    except UnicodeDecodeError as error:
        raise AnacSirosSourceError(
            f"annual member {info.filename!r} is not valid UTF-8"
        ) from error
    except csv.Error as error:
        raise AnacSirosSourceError(
            f"annual member {info.filename!r} is not valid CSV"
        ) from error
    except (zipfile.BadZipFile, zlib.error, EOFError) as error:
        raise AnacSirosSourceError(
            f"annual member {info.filename!r} failed ZIP CRC validation"
        ) from error
    rejection_limit = ANAC_SIROS_ANNUAL_REJECTION_DETAIL_LIMIT
    member_audit = _build_annual_member_audit(
        info=info,
        file=file,
        note=note,
        headers=headers,
        raw_row_count=snapshot.audit.raw_row_count,
        accepted_row_count=snapshot.audit.accepted_row_count,
        rejected_row_count=snapshot.audit.rejected_row_count,
        rejected_rows=snapshot.audit.rejected_rows[:rejection_limit],
        rejection_detail_limit=rejection_limit,
        row_audit_sha256=_row_audit_digest(snapshot.audit.row_audit),
        accepted_series_facts_sha256=snapshot.audit.accepted_series_facts_sha256,
        actual_crc=actual_crc,
    )
    return snapshot, member_audit


def _validate_annual_archive_file(
    path: Path,
    pin: AnacSirosAnnualArchivePin,
    stream: Any,
) -> AnacSirosAnnualArchiveProvenance:
    if not isinstance(pin, AnacSirosAnnualArchivePin):
        raise TypeError("pin must be an AnacSirosAnnualArchivePin")
    resolved = Path(path).expanduser().resolve()
    if resolved.name != pin.resource.filename:
        raise AnacSirosSourceError(
            "local filename does not match the pinned annual SIROS resource"
        )
    if not resolved.is_file():
        raise AnacSirosSourceError(
            f"annual SIROS local file does not exist: {resolved}"
        )
    digest, byte_count = _stream_open_file_sha256(stream)
    if byte_count != pin.expected_bytes:
        raise AnacSirosSourceError(
            "annual SIROS byte count mismatch: "
            f"expected {pin.expected_bytes}, got {byte_count}"
        )
    if digest != pin.expected_sha256:
        raise AnacSirosSourceError(
            f"annual SIROS SHA-256 mismatch: expected {pin.expected_sha256}, got {digest}"
        )
    return AnacSirosAnnualArchiveProvenance(
        source_url=pin.source_url,
        year=pin.resource.year,
        file_path=str(resolved),
        filename=resolved.name,
        retrieved_at_utc=pin.retrieved_at_utc,
        archive_last_modified_utc=pin.archive_last_modified_utc,
        archive_last_modified_raw=pin.archive_last_modified_raw,
        archive_sha256=digest,
        archive_bytes=byte_count,
    )


def validate_siros_annual_archive(
    path: Path,
    *,
    pin: AnacSirosAnnualArchivePin,
    evidence_policy: AnacSirosRetrospectiveEvidencePolicy,
) -> AnacSirosAnnualArchiveAudit:
    """Fully validate every member without extracting anything to disk.

    The annual container's Last-Modified header is retained only as container
    provenance.  Member dates receive the explicit retrospective bound from
    ``evidence_policy`` and can never enter point-in-time selection APIs.

    Rows are consumed once into an audit-only accumulator.  Per-member memory
    retains only duplicate-detection keys, compact fact digests, and a bounded
    rejection sample; normalized rows and full row-audit objects are transient.
    The same open archive handle is hashed, scanned, and rehashed before return.
    """

    if not isinstance(evidence_policy, AnacSirosRetrospectiveEvidencePolicy):
        raise TypeError(
            "evidence_policy must be AnacSirosRetrospectiveEvidencePolicy"
        )
    member_audits: list[AnacSirosAnnualMemberAudit] = []
    resolved = Path(path).expanduser().resolve()
    try:
        with resolved.open("rb") as archive_stream:
            provenance = _validate_annual_archive_file(
                resolved, pin, archive_stream
            )
            with zipfile.ZipFile(archive_stream, "r") as archive:
                infos = _validated_annual_member_infos(archive, provenance.year)
                for info in infos:
                    member_audits.append(
                        _scan_annual_member_audit(
                            archive,
                            info,
                            archive_provenance=provenance,
                            evidence_policy=evidence_policy,
                        )
                    )
            final_digest, final_bytes = _stream_open_file_sha256(archive_stream)
            if (
                final_digest != provenance.archive_sha256
                or final_bytes != provenance.archive_bytes
            ):
                raise AnacSirosSourceError(
                    "annual archive bytes changed during validation"
                )
    except zipfile.BadZipFile as error:
        raise AnacSirosSourceError("annual SIROS file is not a valid ZIP") from error

    expected_dates = _calendar_dates(provenance.year)
    content_digest = hashlib.sha256(
        "\n".join(row.member_content_sha256 for row in member_audits).encode("ascii")
    ).hexdigest()
    totals = {
        "compressed": sum(row.compressed_bytes for row in member_audits),
        "uncompressed": sum(row.uncompressed_bytes for row in member_audits),
        "raw": sum(row.raw_row_count for row in member_audits),
        "accepted": sum(row.accepted_row_count for row in member_audits),
        "rejected": sum(row.rejected_row_count for row in member_audits),
    }
    audit_digest = _canonical_hash(
        {
            "sourceUrl": provenance.source_url,
            "year": provenance.year,
            "archiveSha256": provenance.archive_sha256,
            "archiveBytes": provenance.archive_bytes,
            "archiveLastModifiedUtc": _iso_utc(
                provenance.archive_last_modified_utc
            ),
            "evidencePolicy": evidence_policy.to_dict(),
            "memberCount": len(member_audits),
            "archiveContentSha256": content_digest,
            "totals": totals,
            "pointInTimePublicationEvidence": False,
        }
    )
    return AnacSirosAnnualArchiveAudit(
        archive=provenance,
        evidence_policy=evidence_policy,
        directory_name=f"{provenance.year}/",
        directory_count=1,
        expected_member_count=len(expected_dates),
        actual_member_count=len(member_audits),
        first_snapshot_date=expected_dates[0],
        last_snapshot_date=expected_dates[-1],
        calendar_complete=tuple(row.snapshot_date for row in member_audits)
        == expected_dates,
        total_compressed_bytes=totals["compressed"],
        total_uncompressed_bytes=totals["uncompressed"],
        total_raw_row_count=totals["raw"],
        total_accepted_row_count=totals["accepted"],
        total_rejected_row_count=totals["rejected"],
        members=tuple(member_audits),
        archive_content_sha256=content_digest,
        audit_sha256=audit_digest,
        point_in_time_publication_evidence=False,
        completed=True,
    )


def iter_siros_annual_snapshots(
    path: Path,
    *,
    audit: AnacSirosAnnualArchiveAudit,
    snapshot_dates: Iterable[date] | None = None,
) -> Iterator[AnacSirosSeriesSnapshot]:
    """Re-verify and stream selected full snapshots from one open file handle.

    Full normalized rows are constructed only for explicitly selected members,
    one snapshot at a time.  This intentionally has the memory cost of that one
    selected snapshot, unlike full-archive audit validation.
    """

    if not isinstance(audit, AnacSirosAnnualArchiveAudit) or not audit.completed:
        raise TypeError("audit must be a completed AnacSirosAnnualArchiveAudit")
    resolved = Path(path).expanduser().resolve()
    if str(resolved) != audit.archive.file_path:
        raise AnacSirosSourceError("annual archive path does not match its audit")
    all_dates = _calendar_dates(audit.archive.year)
    if snapshot_dates is None:
        selected_dates = set(all_dates)
    else:
        selected_dates = set(snapshot_dates)
        if any(
            not isinstance(value, date) or isinstance(value, datetime)
            for value in selected_dates
        ):
            raise ValueError("snapshot_dates must contain date values")
        unknown = selected_dates - set(all_dates)
        if unknown:
            raise ValueError(
                f"snapshot_dates fall outside archive year: {sorted(unknown)!r}"
            )
    expected_by_date = {row.snapshot_date: row for row in audit.members}
    try:
        with resolved.open("rb") as archive_stream:
            digest, byte_count = _stream_open_file_sha256(archive_stream)
            if (
                digest != audit.archive.archive_sha256
                or byte_count != audit.archive.archive_bytes
            ):
                raise AnacSirosSourceError(
                    "annual archive bytes changed after validation"
                )
            with zipfile.ZipFile(archive_stream, "r") as archive:
                infos = _validated_annual_member_infos(archive, audit.archive.year)
                for info in infos:
                    member_date = _member_snapshot_date(
                        audit.archive.year, info.filename
                    )
                    if member_date not in selected_dates:
                        continue
                    snapshot, member_audit = _load_annual_member_snapshot(
                        archive,
                        info,
                        archive_provenance=audit.archive,
                        evidence_policy=audit.evidence_policy,
                    )
                    expected = expected_by_date[member_date]
                    if (
                        member_audit.member_content_sha256
                        != expected.member_content_sha256
                    ):
                        raise AnacSirosSourceError(
                            f"annual member {info.filename!r} changed after validation"
                        )
                    yield snapshot
    except zipfile.BadZipFile as error:
        raise AnacSirosSourceError("annual SIROS file is not a valid ZIP") from error


def load_siros_annual_member(
    path: Path,
    *,
    audit: AnacSirosAnnualArchiveAudit,
    snapshot_date: date,
) -> AnacSirosSeriesSnapshot:
    """Load one retrospective member after full-archive validation."""

    snapshots = iter_siros_annual_snapshots(
        path,
        audit=audit,
        snapshot_dates=(snapshot_date,),
    )
    try:
        snapshot = next(snapshots)
    except StopIteration as error:
        raise AnacSirosSourceError("annual snapshot member was not found") from error
    try:
        next(snapshots)
    except StopIteration:
        return snapshot
    raise AnacSirosSourceError("annual snapshot selection returned multiple members")


@dataclass(frozen=True, slots=True)
class AnacSirosServiceObservation:
    """One expanded UTC operation backed by a dated SIROS series snapshot."""

    siros_id: str
    stage_revision_key: str
    series_facts_sha256: str
    service_date: date
    operating_carrier: str
    operating_flight_number: str
    aircraft_family: str | None
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
    public_availability_proven: bool = True
    point_in_time_eligible: bool = True
    evidence_policy_id: str | None = None

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
        object.__setattr__(
            self, "aircraft_family", _optional_equipment(self.aircraft_family)
        )
        object.__setattr__(self, "series_facts_sha256", _digest(self.series_facts_sha256, "series_facts_sha256"))
        object.__setattr__(self, "raw_file_sha256", _digest(self.raw_file_sha256, "raw_file_sha256"))
        object.__setattr__(self, "source_values", tuple(self.source_values))
        if not isinstance(self.public_availability_proven, bool):
            raise TypeError("public_availability_proven must be boolean")
        if not isinstance(self.point_in_time_eligible, bool):
            raise TypeError("point_in_time_eligible must be boolean")
        if self.point_in_time_eligible and not self.public_availability_proven:
            raise ValueError(
                "point-in-time eligibility requires proven public availability"
            )
        if self.point_in_time_eligible:
            if self.evidence_policy_id is not None:
                raise ValueError(
                    "point-in-time observations must not use a retrospective policy"
                )
        elif self.evidence_policy_id != ANAC_SIROS_RETROSPECTIVE_POLICY_ID:
            raise ValueError(
                "annual archive observations require the reviewed retrospective policy"
            )

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
        if not self.point_in_time_eligible:
            raise AnacSirosSourceError(
                "retrospective annual-member evidence cannot establish public visibility"
            )
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
            "aircraft_family": self.aircraft_family,
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
            "public_availability_proven": self.public_availability_proven,
            "point_in_time_eligible": self.point_in_time_eligible,
            "evidence_policy_id": self.evidence_policy_id,
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
        aircraft_family=row.aircraft_family,
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
        public_availability_proven=row.public_availability_proven,
        point_in_time_eligible=row.point_in_time_eligible,
        evidence_policy_id=row.evidence_policy_id,
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
        if not row.point_in_time_eligible:
            raise AnacSirosSourceError(
                "point-in-time selection cannot consume retrospective annual evidence"
            )
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


def select_retrospective_services_at_t_minus_7(
    rows: Iterable[AnacSirosSeriesRow],
    *,
    service_date: date,
    target_departure_utc: datetime,
) -> tuple[AnacSirosServiceObservation, ...]:
    """Select archived schedule evidence for a non-deployable evaluation only.

    The next-day bound is deliberately not called public visibility.  This API
    rejects ordinary point-in-time rows and its observations retain
    ``point_in_time_eligible=False`` so downstream code cannot silently present
    them as historically public schedule data.
    """

    cutoff = _utc(target_departure_utc, "target_departure_utc") - timedelta(days=7)
    latest: dict[str, AnacSirosServiceObservation] = {}
    for row in rows:
        if not isinstance(row, AnacSirosSeriesRow):
            raise TypeError("all rows must be AnacSirosSeriesRow values")
        if (
            row.point_in_time_eligible
            or row.public_availability_proven
            or row.evidence_policy_id != ANAC_SIROS_RETROSPECTIVE_POLICY_ID
        ):
            raise AnacSirosSourceError(
                "retrospective selection accepts only annual member-date evidence"
            )
        expanded = expand_siros_series_row(row, service_date)
        if expanded is None or expanded.schedule_observed_at_utc > cutoff:
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


__all__ = [
    "ANAC_SIROS_2023_ARCHIVE_BYTES",
    "ANAC_SIROS_2023_ARCHIVE_LAST_MODIFIED_RAW",
    "ANAC_SIROS_2023_ARCHIVE_LAST_MODIFIED_UTC",
    "ANAC_SIROS_ANNUAL_REJECTION_DETAIL_LIMIT",
    "ANAC_SIROS_ANNUAL_YEARS",
    "ANAC_SIROS_BASE_URL",
    "ANAC_SIROS_DAILY_YEARS",
    "ANAC_SIROS_DELIMITER",
    "ANAC_SIROS_DOCUMENTATION_URL",
    "ANAC_SIROS_ENCODING",
    "ANAC_SIROS_SERIES_HEADERS",
    "ANAC_SIROS_RETROSPECTIVE_POLICY_ID",
    "ANAC_SIROS_SOURCE_ID",
    "ANAC_SIROS_UTC_NOTE",
    "ANAC_SIROS_WEEKDAY_HEADERS",
    "AnacSirosAnnualArchiveAudit",
    "AnacSirosAnnualArchivePin",
    "AnacSirosAnnualArchiveProvenance",
    "AnacSirosAnnualMemberAudit",
    "AnacSirosConflictError",
    "AnacSirosDuplicateError",
    "AnacSirosError",
    "AnacSirosFileProvenance",
    "AnacSirosRejectedRow",
    "AnacSirosResource",
    "AnacSirosRetrospectiveEvidencePolicy",
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
    "load_siros_annual_member",
    "iter_siros_annual_snapshots",
    "official_2023_annual_archive_pin",
    "select_latest_visible_services",
    "select_retrospective_services_at_t_minus_7",
    "select_services_at_t_minus_7",
    "validate_siros_annual_archive",
    "validate_siros_file",
]
