"""Strict local loader for archived ANAC aerodrome reference snapshots.

ANAC publishes separate public- and private-use aerodrome CSV catalogues.  The
live files are overwritten in place, so reproducible model inputs need both
the canonical ANAC URL and the exact Internet Archive memento that supplied
the local bytes.  This module validates that identity and performs no network
I/O: callers must provide an already archived file and its capture metadata.

The ANAC catalogue contains neither IATA codes nor IANA timezones.  This
loader intentionally does not infer either field.  It retains only the
source-backed identity, name, state and WGS84 decimal coordinates needed to
join a separate, independently provenanced airport reference.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, TypeAlias
from urllib.parse import unquote, urlsplit


ANAC_AERODROME_SOURCE_ID = "anac_aerodrome_registry"
ANAC_AERODROME_SOURCE_PROVIDER = "Brazil ANAC"
ANAC_AERODROME_ENCODING = "cp1252"

ANAC_PUBLIC_AERODROMES_SOURCE_URL = (
    "https://sistemas.anac.gov.br/dadosabertos/Aerodromos/"
    "Aer%C3%B3dromos%20P%C3%BAblicos/"
    "Lista%20de%20aer%C3%B3dromos%20p%C3%BAblicos/"
    "AerodromosPublicos.csv"
)
ANAC_PRIVATE_AERODROMES_SOURCE_URL = (
    "https://sistemas.anac.gov.br/dadosabertos/Aerodromos/"
    "Aer%C3%B3dromos%20Privados/"
    "Lista%20de%20aer%C3%B3dromos%20privados/"
    "Aerodromos%20Privados/AerodromosPrivados.csv"
)

AerodromeType: TypeAlias = Literal["public", "private"]

ANAC_AERODROME_SOURCE_URLS: Mapping[AerodromeType, str] = MappingProxyType(
    {
        "public": ANAC_PUBLIC_AERODROMES_SOURCE_URL,
        "private": ANAC_PRIVATE_AERODROMES_SOURCE_URL,
    }
)

ANAC_AERODROME_REQUIRED_HEADERS = frozenset(
    {
        "codigo_oaci",
        "ciad",
        "nome",
        "uf",
        "latgeopoint",
        "longeopoint",
    }
)

_FILENAME = re.compile(
    r"^anac-aerodromes-(public|private)-(\d{8})\.csv$"
)
_WAYBACK_PATH = re.compile(
    r"^/web/(\d{14})(id_)?/(https://.+)$",
    re.IGNORECASE,
)
_UPDATED_LINE = re.compile(
    r"^\s*Atualizado\s+em\s*:\s*(\d{4}-\d{2}-\d{2})\s*$"
)
_ICAO = re.compile(r"^[A-Z0-9]{4}$")
_CIAD = re.compile(r"^[A-Z]{2}\d{4}$")
_DECIMAL = re.compile(r"^[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)$")


class AnacAerodromeError(ValueError):
    """An ANAC aerodrome snapshot cannot be safely loaded."""


class AnacAerodromeSourceError(AnacAerodromeError):
    """The local filename or source/archive provenance is inconsistent."""


class AnacAerodromeDuplicateError(AnacAerodromeError):
    """Two source rows claim the same ICAO code with duplicate facts."""


class AnacAerodromeConflictError(AnacAerodromeError):
    """Two source rows or catalogues claim one ICAO with different facts."""


def normalize_portuguese_header(value: str) -> str:
    """Return an accent-insensitive, stable identifier for a CSV header."""

    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    ascii_like = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", "_", ascii_like.casefold()).strip("_")


def _required_text(value: object, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} is required")
    text = " ".join(str(value).strip().split())
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _wgs84_decimal(
    value: object,
    field_name: str,
    minimum: float,
    maximum: float,
) -> float:
    text = _required_text(value, field_name)
    if not _DECIMAL.fullmatch(text):
        raise ValueError(f"{field_name} must be one decimal-degree number")
    parsed = float(text.replace(",", "."))
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise ValueError(f"{field_name} must be within [{minimum}, {maximum}]")
    return parsed


@dataclass(frozen=True, slots=True)
class AnacAerodromeRecord:
    """One source-backed ANAC aerodrome, with no inferred IATA or timezone."""

    icao: str
    ciad: str
    name: str
    state: str
    latitude_wgs84: float
    longitude_wgs84: float
    aerodrome_type: AerodromeType
    snapshot_updated_on: date

    def __post_init__(self) -> None:
        icao = _required_text(self.icao, "ICAO code").upper()
        ciad = _required_text(self.ciad, "CIAD code").upper()
        if not _ICAO.fullmatch(icao):
            raise ValueError(f"Invalid ANAC ICAO code: {self.icao!r}")
        if not _CIAD.fullmatch(ciad):
            raise ValueError(f"Invalid ANAC CIAD code: {self.ciad!r}")
        aerodrome_type = str(self.aerodrome_type).strip().casefold()
        if aerodrome_type not in ANAC_AERODROME_SOURCE_URLS:
            raise ValueError("aerodrome_type must be 'public' or 'private'")
        if not isinstance(self.snapshot_updated_on, date) or isinstance(
            self.snapshot_updated_on, datetime
        ):
            raise ValueError("snapshot_updated_on must be a date")

        object.__setattr__(self, "icao", icao)
        object.__setattr__(self, "ciad", ciad)
        object.__setattr__(self, "name", _required_text(self.name, "aerodrome name"))
        object.__setattr__(self, "state", _required_text(self.state, "aerodrome state"))
        object.__setattr__(
            self,
            "latitude_wgs84",
            _wgs84_decimal(self.latitude_wgs84, "LATGEOPOINT", -90, 90),
        )
        object.__setattr__(
            self,
            "longitude_wgs84",
            _wgs84_decimal(self.longitude_wgs84, "LONGEOPOINT", -180, 180),
        )
        object.__setattr__(self, "aerodrome_type", aerodrome_type)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["snapshot_updated_on"] = self.snapshot_updated_on.isoformat()
        return result


@dataclass(frozen=True, slots=True)
class AnacAerodromeRejectedRow:
    """One malformed or incomplete source row excluded from the ICAO index."""

    row_number: int
    reason: str
    record_hint: str


@dataclass(frozen=True, slots=True)
class AnacAerodromeRowAudit:
    """Accounting disposition for every CSV data row read by the loader."""

    row_number: int
    disposition: Literal["accepted", "rejected"]
    record_hint: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.disposition == "accepted" and self.reason is not None:
            raise ValueError("An accepted row cannot have a rejection reason")
        if self.disposition == "rejected" and not self.reason:
            raise ValueError("A rejected row must have a reason")


@dataclass(frozen=True, slots=True)
class AnacAerodromeProvenance:
    """Identity and byte-level provenance for one archived ANAC CSV."""

    source_id: str
    source_provider: str
    dataset_name: str
    aerodrome_type: AerodromeType
    source_url: str
    archive_url: str
    file_path: str
    filename: str
    archived_at_utc: datetime
    snapshot_updated_on: date
    raw_file_sha256: str
    raw_bytes: int
    raw_row_count: int
    accepted_row_count: int
    rejected_row_count: int

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["archived_at_utc"] = self.archived_at_utc.isoformat().replace(
            "+00:00", "Z"
        )
        result["snapshot_updated_on"] = self.snapshot_updated_on.isoformat()
        return result


@dataclass(frozen=True, slots=True)
class AnacAerodromeAudit:
    """Complete accepted/rejected accounting for one archived snapshot."""

    provenance: AnacAerodromeProvenance
    source_headers: tuple[str, ...]
    normalized_headers: tuple[str, ...]
    row_audit: tuple[AnacAerodromeRowAudit, ...]
    rejected_rows: tuple[AnacAerodromeRejectedRow, ...]
    completed: bool = True

    def __post_init__(self) -> None:
        row_audit = tuple(self.row_audit)
        rejected = tuple(self.rejected_rows)
        accepted_count = sum(
            item.disposition == "accepted" for item in row_audit
        )
        rejected_count = sum(
            item.disposition == "rejected" for item in row_audit
        )
        provenance = self.provenance
        if len(row_audit) != provenance.raw_row_count:
            raise ValueError("row audit must account for every raw CSV row")
        if accepted_count != provenance.accepted_row_count:
            raise ValueError("accepted row audit count does not match provenance")
        if rejected_count != provenance.rejected_row_count:
            raise ValueError("rejected row audit count does not match provenance")
        if len(rejected) != provenance.rejected_row_count:
            raise ValueError("rejected row details do not match provenance")
        object.__setattr__(self, "source_headers", tuple(self.source_headers))
        object.__setattr__(self, "normalized_headers", tuple(self.normalized_headers))
        object.__setattr__(self, "row_audit", row_audit)
        object.__setattr__(self, "rejected_rows", rejected)

    @property
    def raw_row_count(self) -> int:
        return self.provenance.raw_row_count

    @property
    def accepted_row_count(self) -> int:
        return self.provenance.accepted_row_count

    @property
    def rejected_row_count(self) -> int:
        return self.provenance.rejected_row_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "provenance": self.provenance.to_dict(),
            "source_headers": list(self.source_headers),
            "normalized_headers": list(self.normalized_headers),
            "row_audit": [asdict(item) for item in self.row_audit],
            "rejected_rows": [asdict(item) for item in self.rejected_rows],
            "completed": self.completed,
        }


@dataclass(frozen=True, slots=True)
class AnacAerodromeCatalog:
    """Immutable ICAO index assembled from one or more validated snapshots."""

    records: tuple[AnacAerodromeRecord, ...]
    by_icao: Mapping[str, AnacAerodromeRecord]
    audits: tuple[AnacAerodromeAudit, ...]

    def __post_init__(self) -> None:
        records = tuple(self.records)
        by_icao = dict(self.by_icao)
        audits = tuple(self.audits)
        if len(by_icao) != len(records):
            raise ValueError("ANAC aerodrome index must contain every record once")
        for record in records:
            if by_icao.get(record.icao) != record:
                raise ValueError(
                    f"ANAC aerodrome ICAO index is inconsistent for {record.icao}"
                )
        if sum(audit.accepted_row_count for audit in audits) != len(records):
            raise ValueError("snapshot accepted counts do not match catalog records")
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "by_icao", MappingProxyType(by_icao))
        object.__setattr__(self, "audits", audits)

    def __len__(self) -> int:
        return len(self.records)

    @property
    def raw_row_count(self) -> int:
        return sum(audit.raw_row_count for audit in self.audits)

    @property
    def accepted_row_count(self) -> int:
        return sum(audit.accepted_row_count for audit in self.audits)

    @property
    def rejected_row_count(self) -> int:
        return sum(audit.rejected_row_count for audit in self.audits)


def _aware_utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise AnacAerodromeSourceError(
            "archived_at_utc must be an aware datetime"
        )
    return value.astimezone(timezone.utc)


def _snapshot_identity(path: Path) -> tuple[AerodromeType, date]:
    match = _FILENAME.fullmatch(path.name)
    if match is None:
        raise AnacAerodromeSourceError(
            "ANAC aerodrome filename must match "
            "anac-aerodromes-{public|private}-YYYYMMDD.csv"
        )
    aerodrome_type = match.group(1)
    try:
        filename_date = datetime.strptime(match.group(2), "%Y%m%d").date()
    except ValueError as error:
        raise AnacAerodromeSourceError(
            f"Invalid archive date in filename: {path.name}"
        ) from error
    return aerodrome_type, filename_date  # type: ignore[return-value]


def _validate_source_and_archive(
    *,
    aerodrome_type: AerodromeType,
    filename_date: date,
    source_url: str,
    archive_url: str,
    archived_at_utc: datetime,
) -> datetime:
    expected_source = ANAC_AERODROME_SOURCE_URLS[aerodrome_type]
    if source_url != expected_source:
        raise AnacAerodromeSourceError(
            f"source_url is not the canonical ANAC {aerodrome_type} CSV URL"
        )

    archived = _aware_utc(archived_at_utc)
    if archived.date() != filename_date:
        raise AnacAerodromeSourceError(
            "filename archive date does not match archived_at_utc"
        )

    parsed = urlsplit(str(archive_url))
    try:
        archive_port = parsed.port
    except ValueError as error:
        raise AnacAerodromeSourceError(
            "archive_url contains an invalid network port"
        ) from error
    if (
        parsed.scheme != "https"
        or parsed.hostname != "web.archive.org"
        or parsed.username is not None
        or parsed.password is not None
        or archive_port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise AnacAerodromeSourceError(
            "archive_url must be an HTTPS web.archive.org memento URL"
        )
    match = _WAYBACK_PATH.fullmatch(parsed.path)
    if match is None:
        raise AnacAerodromeSourceError(
            "archive_url must contain a 14-digit Wayback timestamp; "
            "plain replay and id_ raw replay are supported"
        )
    try:
        memento_time = datetime.strptime(match.group(1), "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError as error:
        raise AnacAerodromeSourceError(
            "archive_url contains an invalid Wayback timestamp"
        ) from error
    if memento_time != archived:
        raise AnacAerodromeSourceError(
            "archive_url timestamp does not match archived_at_utc"
        )
    if unquote(match.group(3)) != unquote(expected_source):
        raise AnacAerodromeSourceError(
            "Wayback memento does not target the canonical source_url"
        )
    return archived


def _parse_updated_line(value: str, archived_on: date) -> date:
    match = _UPDATED_LINE.fullmatch(value.rstrip("\r\n"))
    if match is None:
        raise AnacAerodromeError(
            "first line must be 'Atualizado em: YYYY-MM-DD'"
        )
    try:
        updated_on = date.fromisoformat(match.group(1))
    except ValueError as error:
        raise AnacAerodromeError("invalid 'Atualizado em' date") from error
    if updated_on > archived_on:
        raise AnacAerodromeSourceError(
            "embedded snapshot update date is later than its archive capture"
        )
    return updated_on


def _headers(fieldnames: list[str] | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if fieldnames is None:
        raise AnacAerodromeError("ANAC aerodrome CSV has no semicolon header")
    source_headers = tuple(str(item or "").strip() for item in fieldnames)
    if any(not item for item in source_headers):
        raise AnacAerodromeError("ANAC aerodrome CSV has a blank column name")
    normalized = tuple(normalize_portuguese_header(item) for item in source_headers)
    duplicates = sorted({item for item in normalized if normalized.count(item) > 1})
    if duplicates:
        raise AnacAerodromeError(
            "ANAC aerodrome CSV has duplicate normalized columns: "
            + ", ".join(duplicates)
        )
    missing = sorted(ANAC_AERODROME_REQUIRED_HEADERS - set(normalized))
    if missing:
        raise AnacAerodromeError(
            "ANAC aerodrome CSV is missing required columns: "
            + ", ".join(missing)
        )
    return source_headers, normalized


def _normalized_row(
    row: Mapping[str | None, object],
) -> dict[str, object]:
    if None in row:
        raise ValueError("row contains more values than the semicolon header")
    return {
        normalize_portuguese_header(str(header)): value
        for header, value in row.items()
    }


def _record_hint(row: Mapping[str, object]) -> str:
    return "|".join(
        (
            str(row.get("codigo_oaci") or "?").strip().upper() or "?",
            str(row.get("ciad") or "?").strip().upper() or "?",
        )
    )


def _claim_facts(row: Mapping[str, object]) -> tuple[str, ...]:
    """Build stable retained-field facts before deciding duplicate/conflict."""

    def text(name: str, *, upper: bool = False) -> str:
        value = " ".join(str(row.get(name) or "").strip().split())
        return value.upper() if upper else value

    def decimal(name: str) -> str:
        value = text(name).replace(",", ".")
        try:
            return format(float(value), ".15g")
        except ValueError:
            return value

    return (
        text("codigo_oaci", upper=True),
        text("ciad", upper=True),
        text("nome"),
        text("uf"),
        decimal("latgeopoint"),
        decimal("longeopoint"),
    )


def _parse_record(
    row: Mapping[str, object],
    *,
    aerodrome_type: AerodromeType,
    snapshot_updated_on: date,
) -> AnacAerodromeRecord:
    return AnacAerodromeRecord(
        icao=str(row.get("codigo_oaci") or ""),
        ciad=str(row.get("ciad") or ""),
        name=str(row.get("nome") or ""),
        state=str(row.get("uf") or ""),
        latitude_wgs84=_wgs84_decimal(
            row.get("latgeopoint"), "LATGEOPOINT", -90, 90
        ),
        longitude_wgs84=_wgs84_decimal(
            row.get("longeopoint"), "LONGEOPOINT", -180, 180
        ),
        aerodrome_type=aerodrome_type,
        snapshot_updated_on=snapshot_updated_on,
    )


def load_anac_aerodrome_snapshot(
    file_path: str | Path,
    *,
    source_url: str,
    archive_url: str,
    archived_at_utc: datetime,
) -> AnacAerodromeCatalog:
    """Load one archived public/private ANAC CSV into an immutable ICAO index.

    Invalid or incomplete non-duplicate rows are retained in the rejection
    audit.  Any second claim to a valid ICAO code aborts the load, even if the
    two claims are textually identical; silently choosing a row would make the
    reference depend on source order.
    """

    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    aerodrome_type, filename_date = _snapshot_identity(path)
    archived = _validate_source_and_archive(
        aerodrome_type=aerodrome_type,
        filename_date=filename_date,
        source_url=source_url,
        archive_url=archive_url,
        archived_at_utc=archived_at_utc,
    )

    raw_data = path.read_bytes()
    digest = hashlib.sha256(raw_data).hexdigest()
    try:
        text = raw_data.decode(ANAC_AERODROME_ENCODING)
    except UnicodeDecodeError as error:
        raise AnacAerodromeError(
            "ANAC aerodrome CSV is not valid Windows-1252 text"
        ) from error

    stream = io.StringIO(text, newline="")
    first_line = stream.readline()
    if not first_line:
        raise AnacAerodromeError("ANAC aerodrome CSV is empty")
    snapshot_updated_on = _parse_updated_line(first_line, archived.date())

    records: list[AnacAerodromeRecord] = []
    by_icao: dict[str, AnacAerodromeRecord] = {}
    rejected: list[AnacAerodromeRejectedRow] = []
    row_audit: list[AnacAerodromeRowAudit] = []
    claims: dict[str, tuple[int, tuple[str, ...]]] = {}

    try:
        reader = csv.DictReader(stream, delimiter=";", strict=True)
        source_headers, normalized_headers = _headers(reader.fieldnames)
        for row in reader:
            # DictReader's line numbers begin at the semicolon header (the
            # already-consumed update line is therefore added back here).
            row_number = reader.line_num + 1
            try:
                normalized_row = _normalized_row(row)
            except ValueError as error:
                hint = "?|?"
                rejected.append(
                    AnacAerodromeRejectedRow(row_number, str(error), hint)
                )
                row_audit.append(
                    AnacAerodromeRowAudit(
                        row_number, "rejected", hint, str(error)
                    )
                )
                continue

            hint = _record_hint(normalized_row)
            raw_icao = str(normalized_row.get("codigo_oaci") or "").strip().upper()
            if _ICAO.fullmatch(raw_icao):
                facts = _claim_facts(normalized_row)
                previous = claims.get(raw_icao)
                if previous is not None:
                    first_row, first_facts = previous
                    if first_facts == facts:
                        raise AnacAerodromeDuplicateError(
                            f"ANAC aerodrome CSV row {row_number} duplicates row "
                            f"{first_row} for ICAO {raw_icao}"
                        )
                    raise AnacAerodromeConflictError(
                        f"ANAC aerodrome CSV row {row_number} conflicts with row "
                        f"{first_row} for ICAO {raw_icao}"
                    )
                claims[raw_icao] = (row_number, facts)

            try:
                record = _parse_record(
                    normalized_row,
                    aerodrome_type=aerodrome_type,
                    snapshot_updated_on=snapshot_updated_on,
                )
            except ValueError as error:
                reason = str(error)
                rejected.append(
                    AnacAerodromeRejectedRow(row_number, reason, hint)
                )
                row_audit.append(
                    AnacAerodromeRowAudit(
                        row_number, "rejected", hint, reason
                    )
                )
                continue

            records.append(record)
            by_icao[record.icao] = record
            row_audit.append(
                AnacAerodromeRowAudit(row_number, "accepted", hint)
            )
    except csv.Error as error:
        raise AnacAerodromeError(
            f"Malformed ANAC aerodrome semicolon CSV: {error}"
        ) from error

    provenance = AnacAerodromeProvenance(
        source_id=ANAC_AERODROME_SOURCE_ID,
        source_provider=ANAC_AERODROME_SOURCE_PROVIDER,
        dataset_name=f"ANAC {aerodrome_type} aerodromes CSV",
        aerodrome_type=aerodrome_type,
        source_url=source_url,
        archive_url=archive_url,
        file_path=str(path),
        filename=path.name,
        archived_at_utc=archived,
        snapshot_updated_on=snapshot_updated_on,
        raw_file_sha256=digest,
        raw_bytes=len(raw_data),
        raw_row_count=len(row_audit),
        accepted_row_count=len(records),
        rejected_row_count=len(rejected),
    )
    audit = AnacAerodromeAudit(
        provenance=provenance,
        source_headers=source_headers,
        normalized_headers=normalized_headers,
        row_audit=tuple(row_audit),
        rejected_rows=tuple(rejected),
    )
    return AnacAerodromeCatalog(
        records=tuple(records),
        by_icao=by_icao,
        audits=(audit,),
    )


def merge_anac_aerodrome_catalogs(
    *catalogs: AnacAerodromeCatalog,
) -> AnacAerodromeCatalog:
    """Merge validated snapshots without silently resolving ICAO collisions."""

    if not catalogs:
        raise ValueError("at least one ANAC aerodrome catalog is required")
    records: list[AnacAerodromeRecord] = []
    by_icao: dict[str, AnacAerodromeRecord] = {}
    audits: list[AnacAerodromeAudit] = []
    archive_rows: dict[str, str] = {}

    for catalog in catalogs:
        if not isinstance(catalog, AnacAerodromeCatalog):
            raise TypeError("catalogs must be AnacAerodromeCatalog instances")
        for audit in catalog.audits:
            archive_url = audit.provenance.archive_url
            previous_file = archive_rows.get(archive_url)
            if previous_file is not None:
                raise AnacAerodromeDuplicateError(
                    "ANAC aerodrome archive was supplied more than once: "
                    f"{previous_file} and {audit.provenance.filename}"
                )
            archive_rows[archive_url] = audit.provenance.filename
            audits.append(audit)
        for record in catalog.records:
            existing = by_icao.get(record.icao)
            if existing is None:
                records.append(record)
                by_icao[record.icao] = record
                continue
            if existing == record:
                raise AnacAerodromeDuplicateError(
                    f"Duplicate ICAO {record.icao} across ANAC catalogues"
                )
            raise AnacAerodromeConflictError(
                f"Conflicting ICAO {record.icao} across ANAC catalogues"
            )

    return AnacAerodromeCatalog(
        records=tuple(records),
        by_icao=by_icao,
        audits=tuple(audits),
    )


__all__ = [
    "ANAC_AERODROME_ENCODING",
    "ANAC_AERODROME_REQUIRED_HEADERS",
    "ANAC_AERODROME_SOURCE_ID",
    "ANAC_AERODROME_SOURCE_PROVIDER",
    "ANAC_AERODROME_SOURCE_URLS",
    "ANAC_PRIVATE_AERODROMES_SOURCE_URL",
    "ANAC_PUBLIC_AERODROMES_SOURCE_URL",
    "AerodromeType",
    "AnacAerodromeAudit",
    "AnacAerodromeCatalog",
    "AnacAerodromeConflictError",
    "AnacAerodromeDuplicateError",
    "AnacAerodromeError",
    "AnacAerodromeProvenance",
    "AnacAerodromeRecord",
    "AnacAerodromeRejectedRow",
    "AnacAerodromeRowAudit",
    "AnacAerodromeSourceError",
    "load_anac_aerodrome_snapshot",
    "merge_anac_aerodrome_catalogs",
    "normalize_portuguese_header",
]
