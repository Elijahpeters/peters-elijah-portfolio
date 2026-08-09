"""Brazil ANAC VRA adapter for the normalized global flight schema.

ANAC documents every VRA timestamp as Brasilia civil time, including times for
international endpoints.  This adapter therefore interprets all source clock
values in ``America/Sao_Paulo`` before converting them to UTC.  Airport-local
offsets are calculated separately from caller-supplied airport metadata.

The module deliberately contains no download side effects.  ``build_vra_url``
and ``build_vra_manifest`` describe the official monthly CSV resources; a
pipeline runner can decide when and where to fetch them.
"""

from __future__ import annotations

import csv
import hashlib
import math
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Iterable,
    Iterator,
    Literal,
    Mapping,
    TextIO,
    TypedDict,
)
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ANAC_SOURCE_ID = "anac_vra"
ANAC_PUBLISHER = "Agencia Nacional de Aviacao Civil (ANAC), Brazil"
ANAC_DATASET_NAME = "Voo Regular Ativo (VRA)"
ANAC_DOCUMENTATION_URL = (
    "https://www.anac.gov.br/acesso-a-informacao/dados-abertos/"
    "areas-de-atuacao/voos-e-operacoes-aereas/voo-regular-ativo-vra/"
    "62-voo-regular-ativo-vra"
)
ANAC_BASE_URL = "https://siros.anac.gov.br/siros/registros/diversos/vra"
ANAC_REPORTING_TIMEZONE = "America/Sao_Paulo"
ANAC_DELIMITER = ";"
ANAC_ENCODING = "utf-8-sig"
# ANAC's 2000-2009 exports use a different filename convention, delimiter,
# encoding, and header vocabulary.  The official directory confirms the
# ``VRA_YYYY_MM.csv`` convention for 2010-2026.  Keep this reviewed archive
# window explicit; extending it should be a deliberate metadata review rather
# than generating plausible-looking URLs for unverified years.
ANAC_SUPPORTED_START_YEAR = 2010
ANAC_SUPPORTED_END_YEAR = 2026

_BRASILIA_ZONE = ZoneInfo(ANAC_REPORTING_TIMEZONE)
_ICAO = re.compile(r"^[A-Z0-9]{4}$")
_CARRIER = re.compile(r"^[A-Z0-9]{3}$")
_FLIGHT_NUMBER = re.compile(r"^[A-Z0-9]{1,6}$")
_CODESHARE = re.compile(r"^([A-Z0-9]{3})/([A-Z0-9]{1,6})$")
_DATE_FORMATS = ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S")
_OFFICIAL_FILENAME = re.compile(r"^VRA_(\d{4})_(0[1-9]|1[0-2])\.csv$")
_OFFICIAL_FILE_PATH = re.compile(
    r"^/siros/registros/diversos/vra/(\d{4})/VRA_\1_(0[1-9]|1[0-2])\.csv$"
)

if TYPE_CHECKING:
    from ..schema import GlobalFlightRecord


class AnacRowError(ValueError):
    """A VRA row cannot safely enter the normalized training corpus."""


class AnacUnplannedRowError(AnacRowError):
    """An operated but unplanned stage is outside the scheduled-flight corpus."""


@dataclass(frozen=True)
class AirportMetadata:
    """Minimum airport information needed by the normalized global schema."""

    icao: str
    iata: str | None
    latitude: float
    longitude: float
    country_code: str
    region_code: str
    timezone_name: str

    def __post_init__(self) -> None:
        icao = self.icao.strip().upper()
        iata = str(self.iata or "").strip().upper() or None
        country = self.country_code.strip().upper()
        region = self.region_code.strip()
        timezone_name = self.timezone_name.strip()
        if not _ICAO.fullmatch(icao):
            raise ValueError(f"Invalid airport ICAO code: {self.icao!r}")
        if iata is not None and not re.fullmatch(r"[A-Z]{3}", iata):
            raise ValueError(f"Invalid airport IATA code: {self.iata!r}")
        if not re.fullmatch(r"[A-Z]{2}", country):
            raise ValueError(f"Invalid airport country code: {self.country_code!r}")
        if not region:
            raise ValueError("Airport region code is required")
        if not math.isfinite(self.latitude) or not -90 <= self.latitude <= 90:
            raise ValueError("Airport latitude must be finite and within [-90, 90]")
        if not math.isfinite(self.longitude) or not -180 <= self.longitude <= 180:
            raise ValueError("Airport longitude must be finite and within [-180, 180]")
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"Unknown airport timezone: {timezone_name!r}") from error
        object.__setattr__(self, "icao", icao)
        object.__setattr__(self, "iata", iata)
        object.__setattr__(self, "country_code", country)
        object.__setattr__(self, "region_code", region)
        object.__setattr__(self, "timezone_name", timezone_name)

    @property
    def training_code(self) -> str:
        """Use IATA where available, otherwise retain the official ICAO code."""

        return self.iata or self.icao


class NormalizedFlightMapping(TypedDict):
    """Mapping accepted by ``GlobalFlightRecord.from_mapping``."""

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
    aircraft_family: str | None
    source: str


@dataclass(frozen=True)
class AnacVraMonthlyFile:
    """One official ANAC monthly resource, with no implicit network access."""

    source_id: str
    publisher: str
    dataset: str
    year: int
    month: int
    filename: str
    url: str
    documentation_url: str
    reporting_timezone: str
    delimiter: str
    encoding: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AnacRejectedRow:
    row_number: int
    reason: str
    record_hint: str


@dataclass(frozen=True, slots=True)
class AnacExcludedRow:
    row_number: int
    reason: str
    record_hint: str


@dataclass(frozen=True, slots=True)
class AnacMarketingFlight:
    carrier: str
    flight_number: str


@dataclass(frozen=True, slots=True)
class AnacRowProvenance:
    """Raw clocks and codeshares retained outside the normalized schema."""

    row_number: int
    disposition: Literal["accepted", "excluded_unplanned", "rejected"]
    record_id: str | None
    record_hint: str
    reason: str | None
    scheduled_departure_raw: str
    actual_departure_raw: str
    scheduled_arrival_raw: str
    actual_arrival_raw: str
    status_raw: str
    reference_raw: str
    codeshare_raw: str
    marketing_flights: tuple[AnacMarketingFlight, ...]
    codeshare_parse_error: str | None


@dataclass(frozen=True, slots=True)
class AnacFileProvenance:
    """Reproducibility facts known for one locally cached monthly CSV."""

    source_id: str
    source_provider: str
    product_name: str
    source_url: str
    documentation_url: str
    year: int
    month: int
    file_path: str
    filename: str
    retrieved_at_utc: datetime
    raw_file_sha256: str
    raw_bytes: int
    reporting_timezone: str
    delimiter: str
    encoding: str

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["retrieved_at_utc"] = self.retrieved_at_utc.isoformat().replace(
            "+00:00", "Z"
        )
        return result


@dataclass(slots=True)
class AnacPartitionAudit:
    """Mutable partition accounting plus raw row-level source provenance."""

    source_url: str | None = None
    provenance: AnacFileProvenance | None = None
    headers: tuple[str, ...] = ()
    raw_row_count: int = 0
    accepted_row_count: int = 0
    excluded_unplanned_rows: list[AnacExcludedRow] = field(default_factory=list)
    rejected_rows: list[AnacRejectedRow] = field(default_factory=list)
    row_provenance: list[AnacRowProvenance] = field(default_factory=list)
    completed: bool = False

    @property
    def excluded_unplanned_row_count(self) -> int:
        return len(self.excluded_unplanned_rows)

    @property
    def rejected_row_count(self) -> int:
        return len(self.rejected_rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "provenance": (
                self.provenance.to_dict() if self.provenance is not None else None
            ),
            "headers": list(self.headers),
            "raw_row_count": self.raw_row_count,
            "accepted_row_count": self.accepted_row_count,
            "excluded_unplanned_row_count": self.excluded_unplanned_row_count,
            "rejected_row_count": self.rejected_row_count,
            "completed": self.completed,
            "excluded_unplanned_rows": [
                asdict(excluded) for excluded in self.excluded_unplanned_rows
            ],
            "rejected_rows": [asdict(rejected) for rejected in self.rejected_rows],
            "row_provenance": [asdict(row) for row in self.row_provenance],
        }


def _validate_year_month(year: int, month: int) -> None:
    if (
        isinstance(year, bool)
        or not isinstance(year, int)
        or not ANAC_SUPPORTED_START_YEAR <= year <= ANAC_SUPPORTED_END_YEAR
    ):
        raise ValueError(
            "year must be an integer from "
            f"{ANAC_SUPPORTED_START_YEAR} through {ANAC_SUPPORTED_END_YEAR}; "
            "the 2000-2009 legacy CSV format and unreviewed future archive "
            "years are not supported"
        )
    if isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12:
        raise ValueError("month must be an integer from 1 through 12")


def build_vra_url(year: int, month: int) -> str:
    """Return the official SIROS URL for one ANAC VRA monthly CSV."""

    _validate_year_month(year, month)
    return f"{ANAC_BASE_URL}/{year}/VRA_{year}_{month:02d}.csv"


def monthly_file(year: int, month: int) -> AnacVraMonthlyFile:
    _validate_year_month(year, month)
    filename = f"VRA_{year}_{month:02d}.csv"
    return AnacVraMonthlyFile(
        source_id=ANAC_SOURCE_ID,
        publisher=ANAC_PUBLISHER,
        dataset=ANAC_DATASET_NAME,
        year=year,
        month=month,
        filename=filename,
        url=build_vra_url(year, month),
        documentation_url=ANAC_DOCUMENTATION_URL,
        reporting_timezone=ANAC_REPORTING_TIMEZONE,
        delimiter=ANAC_DELIMITER,
        encoding=ANAC_ENCODING,
    )


def build_vra_manifest(
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
) -> list[AnacVraMonthlyFile]:
    """Build an inclusive chronological monthly manifest without downloading it."""

    _validate_year_month(start_year, start_month)
    _validate_year_month(end_year, end_month)
    start_index = start_year * 12 + start_month - 1
    end_index = end_year * 12 + end_month - 1
    if end_index < start_index:
        raise ValueError("manifest end month must not precede its start month")
    return [
        monthly_file(index // 12, index % 12 + 1)
        for index in range(start_index, end_index + 1)
    ]


def _header_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip())
    ascii_text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.casefold()).strip("_")


_HEADER_ALIASES = {
    "sigla_icao_empresa_aerea": "carrier",
    "numero_voo": "flight_number",
    "codigo_di": "identifier_digit",
    "codigo_tipo_linha": "line_type",
    "modelo_equipamento": "aircraft",
    "sigla_icao_aeroporto_origem": "origin",
    "partida_prevista": "scheduled_departure",
    "partida_real": "actual_departure",
    "sigla_icao_aeroporto_destino": "destination",
    "chegada_prevista": "scheduled_arrival",
    "chegada_real": "actual_arrival",
    "situacao_voo": "status",
    "situacao_do_voo": "status",
    "referencia": "reference",
    "codeshare": "codeshare",
}

_REQUIRED_FIELDS = frozenset(
    {
        "carrier",
        "flight_number",
        "origin",
        "destination",
        "scheduled_departure",
        "actual_departure",
        "scheduled_arrival",
        "actual_arrival",
        "status",
    }
)


def _normalize_row(row: Mapping[str, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_name, raw_value in row.items():
        canonical = _HEADER_ALIASES.get(_header_key(raw_name))
        if canonical is not None:
            normalized[canonical] = str(raw_value or "").strip()
    return normalized


def _raw_source_fields(row: Mapping[str | None, object]) -> dict[str, str]:
    """Retain source text without applying normalized-schema transformations."""

    values: dict[str, str] = {}
    for raw_name, raw_value in row.items():
        canonical = _HEADER_ALIASES.get(_header_key(raw_name))
        if canonical is not None:
            values[canonical] = "" if raw_value is None else str(raw_value)
    return values


def _marketing_flights(
    raw_codeshare: str,
) -> tuple[tuple[AnacMarketingFlight, ...], str | None]:
    text = raw_codeshare.strip()
    if not text:
        return (), None
    parsed: list[AnacMarketingFlight] = []
    seen: set[tuple[str, str]] = set()
    for raw_item in text.split(","):
        item = raw_item.strip().upper()
        match = _CODESHARE.fullmatch(item)
        if match is None:
            return (
                tuple(parsed),
                f"Unsupported ANAC codeshare entry: {raw_item.strip()!r}",
            )
        identity = (match.group(1), match.group(2))
        if identity not in seen:
            seen.add(identity)
            parsed.append(AnacMarketingFlight(*identity))
    return tuple(parsed), None


def _record_hint(row: Mapping[str | None, object]) -> str:
    normalized = _normalize_row(row)
    values = (
        normalized.get("reference") or "?",
        normalized.get("carrier") or "?",
        normalized.get("flight_number") or "?",
        normalized.get("origin") or "?",
        normalized.get("destination") or "?",
    )
    return "|".join(values)


def _row_provenance(
    raw_row: Mapping[str | None, object],
    *,
    row_number: int,
    disposition: Literal["accepted", "excluded_unplanned", "rejected"],
    record_id: str | None,
    reason: str | None,
) -> AnacRowProvenance:
    raw = _raw_source_fields(raw_row)
    codeshares, codeshare_error = _marketing_flights(raw.get("codeshare", ""))
    return AnacRowProvenance(
        row_number=row_number,
        disposition=disposition,
        record_id=record_id,
        record_hint=_record_hint(raw_row),
        reason=reason,
        scheduled_departure_raw=raw.get("scheduled_departure", ""),
        actual_departure_raw=raw.get("actual_departure", ""),
        scheduled_arrival_raw=raw.get("scheduled_arrival", ""),
        actual_arrival_raw=raw.get("actual_arrival", ""),
        status_raw=raw.get("status", ""),
        reference_raw=raw.get("reference", ""),
        codeshare_raw=raw.get("codeshare", ""),
        marketing_flights=codeshares,
        codeshare_parse_error=codeshare_error,
    )


def _required(row: Mapping[str, str], field: str) -> str:
    value = row.get(field, "").strip()
    if not value:
        raise AnacRowError(f"Missing required ANAC field: {field}")
    return value


def _source_datetime(value: str, field: str, *, required: bool) -> datetime | None:
    text = value.strip()
    if not text:
        if required:
            raise AnacRowError(f"Missing required ANAC timestamp: {field}")
        return None
    parsed: datetime | None = None
    for date_format in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, date_format)
            break
        except ValueError:
            continue
    if parsed is None:
        raise AnacRowError(f"Invalid ANAC timestamp in {field}: {text!r}")
    # ANAC specifies Brasilia time for all four VRA clock fields, even where an
    # endpoint is outside Brazil.  ZoneInfo preserves historical DST rules.  A
    # transition can make a wall time ambiguous or nonexistent; silently
    # choosing a fold would corrupt a delay label, so reject either condition.
    candidates: set[datetime] = set()
    for fold in (0, 1):
        aware = parsed.replace(tzinfo=_BRASILIA_ZONE, fold=fold)
        utc_value = aware.astimezone(timezone.utc)
        round_trip = utc_value.astimezone(_BRASILIA_ZONE).replace(tzinfo=None)
        if round_trip == parsed:
            candidates.add(utc_value)
    if len(candidates) != 1:
        transition = "ambiguous" if candidates else "nonexistent"
        raise AnacRowError(
            f"{transition.capitalize()} Brasilia wall time in {field}: {text!r}"
        )
    return candidates.pop()


def _canonical_status(value: str) -> str:
    status = _header_key(value)
    if status == "realizado":
        return "landed"
    if status == "cancelado":
        return "cancelled"
    if status in {"nao_informado", "nao_informada"}:
        return "scheduled"
    raise AnacRowError(f"Unsupported ANAC flight status: {value!r}")


def _airport_metadata(
    airports: Mapping[str, AirportMetadata],
    raw_icao: str,
    field: str,
) -> AirportMetadata:
    icao = raw_icao.strip().upper()
    if not _ICAO.fullmatch(icao):
        raise AnacRowError(f"Invalid ICAO airport code in {field}: {raw_icao!r}")
    airport = airports.get(icao)
    if airport is None:
        raise AnacRowError(f"No airport metadata for {icao}")
    if not isinstance(airport, AirportMetadata):
        raise AnacRowError(f"Airport metadata for {icao} must be AirportMetadata")
    if airport.icao != icao:
        raise AnacRowError(f"Airport metadata key/code mismatch for {icao}")
    return airport


def _utc_offset_minutes(airport: AirportMetadata, instant: datetime) -> int:
    local = instant.astimezone(ZoneInfo(airport.timezone_name))
    offset = local.utcoffset()
    if offset is None:
        raise AnacRowError(f"Timezone offset unavailable for {airport.icao}")
    return int(offset.total_seconds() // 60)


def _record_id(row: Mapping[str, str], scheduled_departure: datetime) -> str:
    identity = "|".join(
        (
            row.get("carrier", ""),
            row.get("flight_number", ""),
            row.get("identifier_digit", ""),
            row.get("line_type", ""),
            row.get("origin", ""),
            row.get("destination", ""),
            scheduled_departure.isoformat(),
            row.get("reference", ""),
        )
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"anac-vra-{digest}"


def _validate_source_url(source_url: str) -> tuple[str, int, int]:
    if not isinstance(source_url, str):
        raise ValueError("source_url must be an official monthly ANAC VRA HTTPS URL")
    parsed = urlparse(source_url)
    match = _OFFICIAL_FILE_PATH.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "siros.anac.gov.br"
        or parsed.port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        raise ValueError("source_url must be an official monthly ANAC VRA HTTPS URL")
    year, month = int(match.group(1)), int(match.group(2))
    _validate_year_month(year, month)
    return source_url, year, month


def parse_vra_row(
    raw_row: Mapping[str, object],
    airports: Mapping[str, AirportMetadata],
    *,
    source_url: str,
) -> NormalizedFlightMapping:
    """Parse one ANAC VRA row into the global schema's snake-case mapping."""

    source, source_year, source_month = _validate_source_url(source_url)
    if None in raw_row:
        raise AnacRowError("ANAC row contains more values than its CSV header")
    row = _normalize_row(raw_row)
    missing_headers = sorted(_REQUIRED_FIELDS - row.keys())
    if missing_headers:
        raise AnacRowError(
            "ANAC row is missing required columns: " + ", ".join(missing_headers)
        )

    status = _canonical_status(_required(row, "status"))
    scheduled_departure_raw = row["scheduled_departure"].strip()
    scheduled_arrival_raw = row["scheduled_arrival"].strip()
    actual_departure_raw = row["actual_departure"].strip()
    actual_arrival_raw = row["actual_arrival"].strip()
    if (
        status == "landed"
        and not scheduled_departure_raw
        and not scheduled_arrival_raw
        and (actual_departure_raw or actual_arrival_raw)
    ):
        # ANAC explicitly includes operated "etapa nao prevista" rows in a
        # monthly VRA partition.  They have an outcome but no prediction-time
        # schedule, so they cannot honestly enter this scheduled-flight schema.
        raise AnacUnplannedRowError(
            "Unplanned ANAC operation has no scheduled departure or arrival; "
            "excluded from the scheduled-flight corpus"
        )

    carrier = _required(row, "carrier").upper()
    flight_number = _required(row, "flight_number").upper()
    if not _CARRIER.fullmatch(carrier):
        raise AnacRowError(f"Invalid ANAC carrier designator: {carrier!r}")
    if not _FLIGHT_NUMBER.fullmatch(flight_number):
        raise AnacRowError(f"Invalid ANAC flight number: {flight_number!r}")

    origin = _airport_metadata(airports, _required(row, "origin"), "origin")
    destination = _airport_metadata(
        airports, _required(row, "destination"), "destination"
    )
    if origin.icao == destination.icao:
        raise AnacRowError("Origin and destination airports must differ")

    scheduled_departure = _source_datetime(
        scheduled_departure_raw, "scheduled_departure", required=True
    )
    scheduled_arrival = _source_datetime(
        scheduled_arrival_raw, "scheduled_arrival", required=True
    )
    assert scheduled_departure is not None and scheduled_arrival is not None
    reporting_departure = scheduled_departure.astimezone(_BRASILIA_ZONE)
    if (reporting_departure.year, reporting_departure.month) != (
        source_year,
        source_month,
    ):
        raise AnacRowError(
            "Scheduled departure does not belong to the source VRA month"
        )
    scheduled_minutes = (
        scheduled_arrival - scheduled_departure
    ).total_seconds() / 60
    if not 0 < scheduled_minutes <= 36 * 60:
        raise AnacRowError(
            "Scheduled duration must be greater than 0 and at most 36 hours"
        )

    actual_departure = _source_datetime(
        actual_departure_raw, "actual_departure", required=False
    )
    actual_arrival = _source_datetime(
        actual_arrival_raw, "actual_arrival", required=False
    )
    if status != "landed" and (actual_departure is not None or actual_arrival is not None):
        raise AnacRowError(f"{status} row must not contain actual flight times")
    if actual_departure is not None and actual_arrival is not None:
        if actual_arrival <= actual_departure:
            raise AnacRowError("Actual arrival must be after actual departure")

    aircraft = row.get("aircraft", "").strip().upper() or None
    origin_zone = ZoneInfo(origin.timezone_name)
    return {
        "record_id": _record_id(row, scheduled_departure),
        "service_date": scheduled_departure.astimezone(origin_zone).date(),
        "operating_carrier": carrier,
        "operating_flight_number": flight_number,
        # The VRA Codeshare column does not document a stable mapping to one
        # marketing flight.  Leaving these unknown is safer than guessing.
        "marketing_carrier": None,
        "marketing_flight_number": None,
        "origin": origin.training_code,
        "destination": destination.training_code,
        "scheduled_departure_utc": scheduled_departure,
        "scheduled_arrival_utc": scheduled_arrival,
        # A final retrospective VRA file does not reveal when the schedule was
        # first visible or which revision it represents.  File retrieval time
        # is provenance, not a schedule observation timestamp.
        "schedule_observed_at": None,
        "schedule_revision": None,
        "actual_departure_utc": actual_departure,
        "actual_arrival_utc": actual_arrival,
        # Likewise, ANAC supplies the outcome but not its publication time.
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
        "origin_timezone_offset_minutes": _utc_offset_minutes(
            origin, scheduled_departure
        ),
        "destination_timezone_offset_minutes": _utc_offset_minutes(
            destination, scheduled_arrival
        ),
        "aircraft_family": aircraft,
        "source": source,
    }


def parse_vra_record(
    raw_row: Mapping[str, object],
    airports: Mapping[str, AirportMetadata],
    *,
    source_url: str,
) -> "GlobalFlightRecord":
    """Construct the pipeline's validated ``GlobalFlightRecord`` lazily."""

    # A relative import keeps this source adapter independently testable while
    # the global schema remains the sole owner of cross-source validation.
    from ..schema import GlobalFlightRecord

    return GlobalFlightRecord.from_mapping(
        parse_vra_row(raw_row, airports, source_url=source_url)
    )


def _validate_csv_headers(fieldnames: list[str] | None) -> tuple[str, ...]:
    if fieldnames is None:
        raise AnacRowError("ANAC CSV has no header row")
    headers = tuple(fieldnames)
    normalized_headers = [_header_key(header) for header in headers]
    duplicate_headers = sorted(
        {
            headers[index]
            for index, key in enumerate(normalized_headers)
            if key and normalized_headers.count(key) > 1
        }
    )
    if duplicate_headers:
        raise AnacRowError(
            "ANAC CSV has duplicate columns: " + ", ".join(duplicate_headers)
        )

    canonical_headers = [
        _HEADER_ALIASES[key]
        for key in normalized_headers
        if key in _HEADER_ALIASES
    ]
    duplicate_canonical = sorted(
        {
            name
            for name in canonical_headers
            if canonical_headers.count(name) > 1
        }
    )
    if duplicate_canonical:
        raise AnacRowError(
            "ANAC CSV maps multiple columns to: "
            + ", ".join(duplicate_canonical)
        )
    missing = sorted(_REQUIRED_FIELDS - set(canonical_headers))
    if missing:
        raise AnacRowError(
            "ANAC CSV is missing required columns: " + ", ".join(missing)
        )
    return headers


def _start_audit(
    audit: AnacPartitionAudit,
    source_url: str,
    provenance: AnacFileProvenance | None,
) -> None:
    if (
        audit.source_url is not None
        or audit.provenance is not None
        or audit.headers
        or audit.raw_row_count
        or audit.accepted_row_count
        or audit.excluded_unplanned_rows
        or audit.rejected_rows
        or audit.row_provenance
        or audit.completed
    ):
        raise ValueError("AnacPartitionAudit instances cannot be reused")
    audit.source_url = source_url
    audit.provenance = provenance


def _iter_vra_csv(
    stream: TextIO,
    airports: Mapping[str, AirportMetadata],
    *,
    source_url: str,
    strict: bool,
    rejected: list[AnacRejectedRow] | None,
    audit: AnacPartitionAudit,
) -> Iterator[NormalizedFlightMapping]:
    reader = csv.DictReader(stream, delimiter=ANAC_DELIMITER)
    audit.headers = _validate_csv_headers(reader.fieldnames)

    for row_number, raw_row in enumerate(reader, start=2):
        audit.raw_row_count += 1
        try:
            normalized = parse_vra_row(raw_row, airports, source_url=source_url)
        except AnacUnplannedRowError as error:
            reason = str(error)
            audit.excluded_unplanned_rows.append(
                AnacExcludedRow(row_number, reason, _record_hint(raw_row))
            )
            audit.row_provenance.append(
                _row_provenance(
                    raw_row,
                    row_number=row_number,
                    disposition="excluded_unplanned",
                    record_id=None,
                    reason=reason,
                )
            )
            # An operated stage with no planned schedule cannot be represented
            # as a scheduled-flight training example.  It is a documented
            # exclusion, not a malformed row, even when strict=True.
            continue
        except AnacRowError as error:
            rejection = AnacRejectedRow(
                row_number, str(error), _record_hint(raw_row)
            )
            audit.rejected_rows.append(rejection)
            if rejected is not None and rejected is not audit.rejected_rows:
                rejected.append(rejection)
            audit.row_provenance.append(
                _row_provenance(
                    raw_row,
                    row_number=row_number,
                    disposition="rejected",
                    record_id=None,
                    reason=str(error),
                )
            )
            if strict:
                raise AnacRowError(f"ANAC CSV row {row_number}: {error}") from error
            continue
        audit.accepted_row_count += 1
        audit.row_provenance.append(
            _row_provenance(
                raw_row,
                row_number=row_number,
                disposition="accepted",
                record_id=normalized["record_id"],
                reason=None,
            )
        )
        yield normalized
    audit.completed = True


def iter_vra_csv(
    stream: TextIO,
    airports: Mapping[str, AirportMetadata],
    *,
    source_url: str,
    strict: bool = True,
    rejected: list[AnacRejectedRow] | None = None,
    audit: AnacPartitionAudit | None = None,
) -> Iterator[NormalizedFlightMapping]:
    """Stream a VRA CSV with durable rejection and exclusion accounting.

    ``rejected`` remains supported for callers of the original adapter API.
    New ingestion code should pass ``audit`` so accepted, rejected, and
    intentionally excluded rows all retain their raw ANAC provenance.
    """

    source, _, _ = _validate_source_url(source_url)
    if not strict and audit is None and rejected is None:
        raise ValueError(
            "non-strict ANAC parsing requires an AnacPartitionAudit or "
            "rejected-row collection"
        )
    active_audit = audit if audit is not None else AnacPartitionAudit()
    _start_audit(active_audit, source, None)
    yield from _iter_vra_csv(
        stream,
        airports,
        source_url=source,
        strict=strict,
        rejected=rejected,
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


def inspect_vra_file(
    file_path: Path,
    *,
    retrieved_at_utc: datetime,
    source_url: str | None = None,
) -> AnacFileProvenance:
    """Validate one cached monthly CSV and compute static provenance."""

    path = Path(file_path).resolve()
    match = _OFFICIAL_FILENAME.fullmatch(path.name)
    if match is None:
        raise ValueError("file name is not an official modern ANAC monthly filename")
    year, month = int(match.group(1)), int(match.group(2))
    _validate_year_month(year, month)
    expected_source = build_vra_url(year, month)
    if source_url is not None:
        source, source_year, source_month = _validate_source_url(source_url)
        if (source_year, source_month) != (year, month) or source != expected_source:
            raise ValueError("source_url does not match the ANAC CSV filename")
    retrieved = _retrieval_time(retrieved_at_utc)
    if not path.is_file():
        raise FileNotFoundError(path)

    try:
        with path.open("r", encoding=ANAC_ENCODING, newline="") as stream:
            _validate_csv_headers(next(csv.reader(stream, delimiter=ANAC_DELIMITER), None))
    except UnicodeDecodeError as error:
        raise AnacRowError("ANAC CSV header is not valid UTF-8") from error

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return AnacFileProvenance(
        source_id=ANAC_SOURCE_ID,
        source_provider=ANAC_PUBLISHER,
        product_name=ANAC_DATASET_NAME,
        source_url=expected_source,
        documentation_url=ANAC_DOCUMENTATION_URL,
        year=year,
        month=month,
        file_path=str(path),
        filename=path.name,
        retrieved_at_utc=retrieved,
        raw_file_sha256=digest.hexdigest(),
        raw_bytes=path.stat().st_size,
        reporting_timezone=ANAC_REPORTING_TIMEZONE,
        delimiter=ANAC_DELIMITER,
        encoding=ANAC_ENCODING,
    )


def iter_vra_file(
    file_path: Path,
    airports: Mapping[str, AirportMetadata],
    *,
    retrieved_at_utc: datetime,
    source_url: str | None = None,
    strict: bool = True,
    rejected: list[AnacRejectedRow] | None = None,
    audit: AnacPartitionAudit | None = None,
) -> Iterator[NormalizedFlightMapping]:
    """Stream a cached monthly VRA CSV while attaching file provenance."""

    if not strict and audit is None and rejected is None:
        raise ValueError(
            "non-strict ANAC parsing requires an AnacPartitionAudit or "
            "rejected-row collection"
        )
    provenance = inspect_vra_file(
        file_path,
        retrieved_at_utc=retrieved_at_utc,
        source_url=source_url,
    )
    active_audit = audit if audit is not None else AnacPartitionAudit()
    _start_audit(active_audit, provenance.source_url, provenance)
    try:
        with Path(provenance.file_path).open(
            "r", encoding=ANAC_ENCODING, newline=""
        ) as stream:
            yield from _iter_vra_csv(
                stream,
                airports,
                source_url=provenance.source_url,
                strict=strict,
                rejected=rejected,
                audit=active_audit,
            )
    except UnicodeDecodeError as error:
        raise AnacRowError("ANAC CSV is not valid UTF-8") from error


def manifest_download_targets(
    manifest: Iterable[AnacVraMonthlyFile], destination: Path
) -> list[tuple[str, Path]]:
    """Resolve URL/path pairs for a downloader without performing I/O."""

    root = destination.resolve()
    targets: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for item in manifest:
        if not isinstance(item, AnacVraMonthlyFile):
            raise ValueError("ANAC manifest entries must be AnacVraMonthlyFile values")
        expected = monthly_file(item.year, item.month)
        if item != expected:
            raise ValueError(
                "ANAC manifest entry metadata does not match its year/month"
            )
        target = (root / item.filename).resolve()
        if target.parent != root:
            raise ValueError("ANAC manifest filename escapes its destination")
        if target in seen:
            raise ValueError(f"Duplicate ANAC manifest target: {item.filename}")
        seen.add(target)
        targets.append((item.url, target))
    return targets
