"""Strict local loader for the UN M49 geographic overview.

The United Nations Statistics Division publishes the M49 overview as a page
containing one table per language.  This module parses the first English table
(``table#downloadTableEN``) from bytes that a caller has already saved.  It
performs no network or filesystem I/O at import time.

UN geography and SkyETA model geography are deliberately separate.  Every
record retains its UN region, sub-region, and intermediate-region fields.  The
derived SkyETA region uses the following documented policy:

* Africa, Asia, Europe, and Oceania map directly.
* The UN Americas region maps its South America branch to ``South America``;
  its Caribbean, Central America, and Northern America branches map to
  ``North America``.
* SkyETA's ``Middle East`` operational bucket is an explicit ISO-alpha2 set:
  all 18 UN Western Asia entries, plus Iran and Egypt.  Iran and Egypt are
  included because the product's intended aviation market grouping spans the
  Gulf/Levant and those two adjacent major markets; this does not alter or
  misrepresent their UN classifications (Southern Asia and Northern Africa).
* Antarctica maps to the model's ``Other`` feature token.

The current UN table does not include Taiwan (TW) or Kosovo (XK), although both
occur in the airport reference used by the adapters.  They are explicit
compatibility mappings (TW to Asia, XK to Europe), recorded separately from UN
rows so source provenance remains truthful.  Every other unknown ISO2 lookup,
unknown source geography, and duplicate/conflicting identity fails closed.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from ..features import REGION_TOKENS


M49_SOURCE_ID = "un_m49_overview"
M49_SOURCE_PROVIDER = "United Nations Statistics Division"
M49_DATASET_NAME = "Standard country or area codes for statistical use (M49)"
UN_M49_OVERVIEW_URL = "https://unstats.un.org/unsd/methodology/m49/overview/"
M49_SOURCE_URL = UN_M49_OVERVIEW_URL
M49_ENGLISH_TABLE_ID = "downloadTableEN"
M49_ENCODING = "utf-8-sig"

M49_REQUIRED_COLUMNS = (
    "Global Code",
    "Global Name",
    "Region Code",
    "Region Name",
    "Sub-region Code",
    "Sub-region Name",
    "Intermediate Region Code",
    "Intermediate Region Name",
    "Country or Area",
    "M49 Code",
    "ISO-alpha2 Code",
    "ISO-alpha3 Code",
)

# These labels normalize one-to-one to features.REGION_TOKENS.  Keeping the
# human-readable labels here lets the catalog be passed directly to the airport
# adapters and GlobalFlightRecord while the feature builder retains its stable
# lower-snake-case vocabulary.
SKYETA_REGION_LABELS = frozenset(
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


def _feature_token(label: str) -> str:
    return "_".join(label.strip().casefold().replace("-", " ").split())


if {_feature_token(label) for label in SKYETA_REGION_LABELS} != set(REGION_TOKENS):
    raise RuntimeError(
        "SkyETA region labels must normalize exactly to features.REGION_TOKENS"
    )


# UN M49 Western Asia (sub-region 145), captured explicitly so a future source
# change cannot silently expand or shrink the product's Middle East semantics.
WESTERN_ASIA_ISO2 = frozenset(
    {
        "AE",
        "AM",
        "AZ",
        "BH",
        "CY",
        "GE",
        "IL",
        "IQ",
        "JO",
        "KW",
        "LB",
        "OM",
        "PS",
        "QA",
        "SA",
        "SY",
        "TR",
        "YE",
    }
)
MIDDLE_EAST_ADDITIONAL_ISO2 = frozenset({"EG", "IR"})
MIDDLE_EAST_ISO2_OVERRIDES = frozenset(
    WESTERN_ASIA_ISO2 | MIDDLE_EAST_ADDITIONAL_ISO2
)
MIDDLE_EAST_OVERRIDE_RATIONALE = (
    "SkyETA operational aviation bucket: UN Western Asia plus Iran and Egypt; "
    "the original UN geography remains on every source record."
)

COMPATIBILITY_ISO2_OVERRIDES: Mapping[str, str] = MappingProxyType(
    {"TW": "Asia", "XK": "Europe"}
)
COMPATIBILITY_OVERRIDE_RATIONALE = (
    "TW and XK occur in the airport reference but have no country rows in the "
    "UN M49 overview; they are explicit compatibility mappings, not UN facts."
)

_UN_REGION_CODES = {
    "Africa": "002",
    "Americas": "019",
    "Asia": "142",
    "Europe": "150",
    "Oceania": "009",
}
_DIRECT_REGION_MAP = {
    "Africa": "Africa",
    "Asia": "Asia",
    "Europe": "Europe",
    "Oceania": "Oceania",
}
_CODE_2 = re.compile(r"^[A-Z]{2}$")
_CODE_3 = re.compile(r"^[A-Z]{3}$")
_M49_CODE = re.compile(r"^\d{3}$")


class M49RegionError(ValueError):
    """A saved M49 page cannot be converted safely."""


class M49RegionDuplicateError(M49RegionError):
    """The English table repeats a country identity, including exact repeats."""


class M49RegionConflictError(M49RegionError):
    """Two identities or classification facts conflict."""


class UnknownCountryError(KeyError):
    """An ISO-alpha2 code has no UN row or documented compatibility mapping."""


def _clean_text(value: object) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _required_text(value: object, field_name: str) -> str:
    text = _clean_text(value)
    if not text:
        raise M49RegionError(f"{field_name} is required")
    return text


def _optional_text(value: object) -> str | None:
    return _clean_text(value) or None


def _optional_pair(
    code: object,
    name: object,
    field_name: str,
) -> tuple[str | None, str | None]:
    clean_code = _optional_text(code)
    clean_name = _optional_text(name)
    if (clean_code is None) != (clean_name is None):
        raise M49RegionConflictError(
            f"{field_name} code and name must either both be present or both be blank"
        )
    if clean_code is not None and not _M49_CODE.fullmatch(clean_code):
        raise M49RegionError(f"{field_name} code must be three digits")
    return clean_code, clean_name


@dataclass(frozen=True, slots=True)
class M49RegionRecord:
    """One English M49 country row plus its separately derived model region."""

    global_code: str
    global_name: str
    un_region_code: str | None
    un_region_name: str | None
    un_subregion_code: str | None
    un_subregion_name: str | None
    un_intermediate_region_code: str | None
    un_intermediate_region_name: str | None
    country_or_area: str
    m49_code: str
    iso_alpha2: str
    iso_alpha3: str
    skyeta_region: str

    def __post_init__(self) -> None:
        global_code = _required_text(self.global_code, "global_code")
        global_name = _required_text(self.global_name, "global_name")
        if global_code != "001" or global_name != "World":
            raise M49RegionConflictError(
                "English M49 country rows must belong to global code 001 (World)"
            )

        region_code, region_name = _optional_pair(
            self.un_region_code, self.un_region_name, "UN region"
        )
        subregion_code, subregion_name = _optional_pair(
            self.un_subregion_code, self.un_subregion_name, "UN sub-region"
        )
        intermediate_code, intermediate_name = _optional_pair(
            self.un_intermediate_region_code,
            self.un_intermediate_region_name,
            "UN intermediate region",
        )
        if region_name is not None:
            expected_code = _UN_REGION_CODES.get(region_name)
            if expected_code is None:
                raise M49RegionError(f"Unknown UN region: {region_name!r}")
            if region_code != expected_code:
                raise M49RegionConflictError(
                    f"UN region {region_name!r} must use code {expected_code}, "
                    f"not {region_code!r}"
                )

        country = _required_text(self.country_or_area, "country_or_area")
        m49_code = _required_text(self.m49_code, "m49_code")
        iso2 = _required_text(self.iso_alpha2, "iso_alpha2").upper()
        iso3 = _required_text(self.iso_alpha3, "iso_alpha3").upper()
        skyeta_region = _required_text(self.skyeta_region, "skyeta_region")
        if not _M49_CODE.fullmatch(m49_code):
            raise M49RegionError("m49_code must be three digits")
        if not _CODE_2.fullmatch(iso2):
            raise M49RegionError("iso_alpha2 must contain exactly two ASCII letters")
        if not _CODE_3.fullmatch(iso3):
            raise M49RegionError("iso_alpha3 must contain exactly three ASCII letters")
        if skyeta_region not in SKYETA_REGION_LABELS:
            allowed = ", ".join(sorted(SKYETA_REGION_LABELS))
            raise M49RegionError(
                f"Unknown SkyETA region {skyeta_region!r}; expected one of: {allowed}"
            )

        object.__setattr__(self, "global_code", global_code)
        object.__setattr__(self, "global_name", global_name)
        object.__setattr__(self, "un_region_code", region_code)
        object.__setattr__(self, "un_region_name", region_name)
        object.__setattr__(self, "un_subregion_code", subregion_code)
        object.__setattr__(self, "un_subregion_name", subregion_name)
        object.__setattr__(self, "un_intermediate_region_code", intermediate_code)
        object.__setattr__(self, "un_intermediate_region_name", intermediate_name)
        object.__setattr__(self, "country_or_area", country)
        object.__setattr__(self, "m49_code", m49_code)
        object.__setattr__(self, "iso_alpha2", iso2)
        object.__setattr__(self, "iso_alpha3", iso3)
        object.__setattr__(self, "skyeta_region", skyeta_region)

    @property
    def skyeta_region_token(self) -> str:
        return _feature_token(self.skyeta_region)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["skyeta_region_token"] = self.skyeta_region_token
        return result


@dataclass(frozen=True, slots=True)
class M49RegionProvenance:
    """Exact input bytes, source identity, and completed row accounting."""

    source_id: str
    source_provider: str
    dataset_name: str
    source_url: str
    file_path: str
    filename: str
    retrieved_at_utc: datetime
    raw_file_sha256: str
    raw_bytes: int
    table_id: str
    raw_row_count: int
    accepted_row_count: int
    compatibility_override_count: int
    mapping_count: int

    @property
    def record_count(self) -> int:
        return self.accepted_row_count

    @property
    def rejected_row_count(self) -> int:
        # Invalid rows are fatal rather than skipped.
        return 0

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["retrieved_at_utc"] = self.retrieved_at_utc.isoformat().replace(
            "+00:00", "Z"
        )
        result["record_count"] = self.record_count
        result["rejected_row_count"] = self.rejected_row_count
        return result


@dataclass(frozen=True, slots=True)
class M49RegionAudit:
    """Source structure and explicit non-UN classification policy."""

    provenance: M49RegionProvenance
    headers: tuple[str, ...]
    completed: bool = True

    @property
    def raw_row_count(self) -> int:
        return self.provenance.raw_row_count

    @property
    def accepted_row_count(self) -> int:
        return self.provenance.accepted_row_count

    @property
    def rejected_row_count(self) -> int:
        return self.provenance.rejected_row_count

    @property
    def mapping_count(self) -> int:
        return self.provenance.mapping_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "provenance": self.provenance.to_dict(),
            "headers": list(self.headers),
            "raw_row_count": self.raw_row_count,
            "accepted_row_count": self.accepted_row_count,
            "rejected_row_count": self.rejected_row_count,
            "mapping_count": self.mapping_count,
            "completed": self.completed,
            "middle_east_iso2_overrides": sorted(MIDDLE_EAST_ISO2_OVERRIDES),
            "middle_east_override_rationale": MIDDLE_EAST_OVERRIDE_RATIONALE,
            "compatibility_iso2_overrides": dict(COMPATIBILITY_ISO2_OVERRIDES),
            "compatibility_override_rationale": COMPATIBILITY_OVERRIDE_RATIONALE,
        }


@dataclass(frozen=True, slots=True)
class M49RegionCatalog(Mapping[str, str]):
    """Immutable ISO2-to-region resolver with source records and provenance.

    The catalog itself satisfies ``Mapping[str, str]``, so it can be supplied
    directly anywhere the airport loader accepts a country-region mapping.
    ``by_iso2`` contains only actual UN rows; ``regions_by_iso2`` additionally
    contains the explicit TW/XK compatibility entries.
    """

    records: tuple[M49RegionRecord, ...]
    by_iso2: Mapping[str, M49RegionRecord]
    regions_by_iso2: Mapping[str, str]
    audit: M49RegionAudit

    def __post_init__(self) -> None:
        records = tuple(self.records)
        by_iso2 = dict(self.by_iso2)
        regions = dict(self.regions_by_iso2)
        if len(records) != len(by_iso2):
            raise ValueError("M49 by_iso2 index must contain every source record once")
        for record in records:
            if by_iso2.get(record.iso_alpha2) != record:
                raise ValueError(
                    f"M49 by_iso2 index is inconsistent for {record.iso_alpha2}"
                )
            if regions.get(record.iso_alpha2) != record.skyeta_region:
                raise ValueError(
                    f"M49 region mapping is inconsistent for {record.iso_alpha2}"
                )
        for iso2, region in COMPATIBILITY_ISO2_OVERRIDES.items():
            if regions.get(iso2) != region:
                raise ValueError(
                    f"M49 compatibility mapping is inconsistent for {iso2}"
                )
        if any(region not in SKYETA_REGION_LABELS for region in regions.values()):
            raise ValueError("M49 mapping contains an unknown SkyETA region")
        if self.audit.provenance.accepted_row_count != len(records):
            raise ValueError("M49 provenance accepted-row count is inconsistent")
        if self.audit.provenance.mapping_count != len(regions):
            raise ValueError("M49 provenance mapping count is inconsistent")

        object.__setattr__(self, "records", records)
        object.__setattr__(self, "by_iso2", MappingProxyType(by_iso2))
        object.__setattr__(self, "regions_by_iso2", MappingProxyType(regions))

    @property
    def provenance(self) -> M49RegionProvenance:
        return self.audit.provenance

    @property
    def country_to_region(self) -> Mapping[str, str]:
        return self.regions_by_iso2

    def region_for_iso2(self, iso_alpha2: str) -> str:
        iso2 = _required_text(iso_alpha2, "iso_alpha2").upper()
        if not _CODE_2.fullmatch(iso2):
            raise ValueError("iso_alpha2 must contain exactly two ASCII letters")
        try:
            return self.regions_by_iso2[iso2]
        except KeyError as error:
            raise UnknownCountryError(
                f"No SkyETA region mapping for ISO-alpha2 country {iso2}"
            ) from error

    def __getitem__(self, iso_alpha2: str) -> str:
        return self.region_for_iso2(iso_alpha2)

    def __iter__(self) -> Iterator[str]:
        return iter(self.regions_by_iso2)

    def __len__(self) -> int:
        return len(self.regions_by_iso2)


class _EnglishM49TableParser(HTMLParser):
    """Extract rows from the first table whose id is ``downloadTableEN``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, ...]] = []
        self.found = False
        self.finished = False
        self._inside = False
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None
        self._cell_tag: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        tag = tag.casefold()
        if tag == "table":
            if self._inside:
                raise M49RegionError("English M49 table contains a nested table")
            if not self.found:
                ids = [value for name, value in attrs if name.casefold() == "id"]
                if len(ids) > 1:
                    raise M49RegionError("HTML table has duplicate id attributes")
                table_id = _clean_text(ids[0]) if ids else ""
                if table_id.casefold() == M49_ENGLISH_TABLE_ID.casefold():
                    self.found = True
                    self._inside = True
            return
        if not self._inside:
            return
        if tag == "tr":
            if self._row is not None:
                raise M49RegionError("English M49 table contains nested rows")
            self._row = []
        elif tag in {"td", "th"}:
            if self._row is None:
                raise M49RegionError("English M49 table cell appears outside a row")
            if self._cell_parts is not None:
                raise M49RegionError("English M49 table contains nested cells")
            self._cell_parts = []
            self._cell_tag = tag

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if not self._inside:
            return
        if tag in {"td", "th"}:
            if self._cell_parts is None or self._cell_tag != tag:
                raise M49RegionError("English M49 table has mismatched cell tags")
            assert self._row is not None
            self._row.append(_clean_text("".join(self._cell_parts)))
            self._cell_parts = None
            self._cell_tag = None
        elif tag == "tr":
            if self._row is None:
                raise M49RegionError("English M49 table has a stray row close tag")
            if self._cell_parts is not None:
                raise M49RegionError("English M49 table row ends inside a cell")
            self.rows.append(tuple(self._row))
            self._row = None
        elif tag == "table":
            if self._row is not None or self._cell_parts is not None:
                raise M49RegionError("English M49 table ends inside a row")
            self._inside = False
            self.finished = True

    def handle_data(self, data: str) -> None:
        if self._inside and self._cell_parts is not None:
            self._cell_parts.append(data)


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


def _headers(row: tuple[str, ...]) -> tuple[str, ...]:
    headers = tuple(_clean_text(value) for value in row)
    if any(not value for value in headers):
        raise M49RegionError("English M49 table contains a blank column name")
    duplicates = sorted({value for value in headers if headers.count(value) > 1})
    if duplicates:
        raise M49RegionError(
            "English M49 table has duplicate columns: " + ", ".join(duplicates)
        )
    missing = sorted(set(M49_REQUIRED_COLUMNS) - set(headers))
    if missing:
        raise M49RegionError(
            "English M49 table is missing required columns: " + ", ".join(missing)
        )
    return headers


def _validate_middle_east_source(
    iso2: str,
    region_name: str | None,
    subregion_name: str | None,
) -> None:
    if iso2 in WESTERN_ASIA_ISO2:
        if region_name != "Asia" or subregion_name != "Western Asia":
            raise M49RegionConflictError(
                f"Middle East override {iso2} is no longer classified by UN as "
                "Western Asia"
            )
    elif iso2 == "IR":
        if region_name != "Asia" or subregion_name != "Southern Asia":
            raise M49RegionConflictError(
                "Middle East override IR is no longer classified by UN as Southern Asia"
            )
    elif iso2 == "EG":
        if region_name != "Africa" or subregion_name != "Northern Africa":
            raise M49RegionConflictError(
                "Middle East override EG is no longer classified by UN as Northern Africa"
            )


def _derive_skyeta_region(
    *,
    iso2: str,
    iso3: str,
    m49_code: str,
    country: str,
    region_name: str | None,
    subregion_name: str | None,
    intermediate_region_name: str | None,
) -> str:
    if subregion_name == "Western Asia" and iso2 not in WESTERN_ASIA_ISO2:
        raise M49RegionError(
            f"Unknown Western Asia country {iso2}; update the explicit Middle East policy"
        )
    if iso2 in MIDDLE_EAST_ISO2_OVERRIDES:
        _validate_middle_east_source(iso2, region_name, subregion_name)
        return "Middle East"
    if region_name in _DIRECT_REGION_MAP:
        return _DIRECT_REGION_MAP[region_name]
    if region_name == "Americas":
        if "South America" in {subregion_name, intermediate_region_name}:
            return "South America"
        return "North America"
    if (
        iso2 == "AQ"
        and iso3 == "ATA"
        and m49_code == "010"
        and country == "Antarctica"
        and region_name is None
        and subregion_name is None
        and intermediate_region_name is None
    ):
        return "Other"
    if region_name is None:
        raise M49RegionError(f"Country {iso2} has no recognized UN region")
    raise M49RegionError(f"Unknown UN region {region_name!r} for country {iso2}")


def _record_from_row(
    row: tuple[str, ...],
    headers: tuple[str, ...],
    table_row_number: int,
) -> M49RegionRecord:
    if len(row) != len(headers):
        raise M49RegionError(
            f"English M49 table row {table_row_number} has {len(row)} cells; "
            f"expected {len(headers)}"
        )
    values = dict(zip(headers, row, strict=True))
    region_code = _optional_text(values["Region Code"])
    region_name = _optional_text(values["Region Name"])
    subregion_code = _optional_text(values["Sub-region Code"])
    subregion_name = _optional_text(values["Sub-region Name"])
    intermediate_code = _optional_text(values["Intermediate Region Code"])
    intermediate_name = _optional_text(values["Intermediate Region Name"])
    country = _required_text(values["Country or Area"], "country_or_area")
    m49_code = _required_text(values["M49 Code"], "m49_code")
    iso2 = _required_text(values["ISO-alpha2 Code"], "iso_alpha2").upper()
    iso3 = _required_text(values["ISO-alpha3 Code"], "iso_alpha3").upper()
    skyeta_region = _derive_skyeta_region(
        iso2=iso2,
        iso3=iso3,
        m49_code=m49_code,
        country=country,
        region_name=region_name,
        subregion_name=subregion_name,
        intermediate_region_name=intermediate_name,
    )
    return M49RegionRecord(
        global_code=values["Global Code"],
        global_name=values["Global Name"],
        un_region_code=region_code,
        un_region_name=region_name,
        un_subregion_code=subregion_code,
        un_subregion_name=subregion_name,
        un_intermediate_region_code=intermediate_code,
        un_intermediate_region_name=intermediate_name,
        country_or_area=country,
        m49_code=m49_code,
        iso_alpha2=iso2,
        iso_alpha3=iso3,
        skyeta_region=skyeta_region,
    )


def _index_records(
    rows: list[tuple[str, ...]], headers: tuple[str, ...]
) -> tuple[tuple[M49RegionRecord, ...], dict[str, M49RegionRecord]]:
    records: list[M49RegionRecord] = []
    by_iso2: dict[str, M49RegionRecord] = {}
    by_iso3: dict[str, M49RegionRecord] = {}
    by_m49: dict[str, M49RegionRecord] = {}
    by_name: dict[str, M49RegionRecord] = {}
    source_rows: dict[str, dict[str, int]] = {
        "ISO-alpha2": {},
        "ISO-alpha3": {},
        "M49": {},
        "country name": {},
    }

    for table_row_number, row in enumerate(rows, start=2):
        record = _record_from_row(row, headers, table_row_number)
        identity_values = (
            ("ISO-alpha2", record.iso_alpha2, by_iso2),
            ("ISO-alpha3", record.iso_alpha3, by_iso3),
            ("M49", record.m49_code, by_m49),
            ("country name", record.country_or_area.casefold(), by_name),
        )
        for identity_name, identity, index in identity_values:
            existing = index.get(identity)
            if existing is None:
                continue
            first_row = source_rows[identity_name][identity]
            if identity_name == "ISO-alpha2" and existing == record:
                raise M49RegionDuplicateError(
                    f"English M49 table row {table_row_number} exactly duplicates "
                    f"row {first_row} for ISO-alpha2 {record.iso_alpha2}"
                )
            raise M49RegionConflictError(
                f"English M49 table row {table_row_number} conflicts with row "
                f"{first_row} for {identity_name} {identity}"
            )

        records.append(record)
        for identity_name, identity, index in identity_values:
            index[identity] = record
            source_rows[identity_name][identity] = table_row_number

    return tuple(records), by_iso2


def load_m49_region_catalog(
    file_path: Path,
    *,
    retrieved_at_utc: datetime,
    source_url: str = UN_M49_OVERVIEW_URL,
) -> M49RegionCatalog:
    """Parse a caller-provided saved M49 page into a strict ISO2 resolver.

    Invalid source rows are never skipped.  The returned provenance hashes the
    exact saved bytes and counts only rows in the selected English source table;
    ``mapping_count`` additionally reflects the separately documented TW/XK
    compatibility entries.
    """

    retrieved = _retrieval_time(retrieved_at_utc)
    source = _source_url(source_url)
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    raw_data = path.read_bytes()
    digest = hashlib.sha256(raw_data).hexdigest()
    try:
        html = raw_data.decode(M49_ENCODING)
    except UnicodeDecodeError as error:
        raise M49RegionError("Saved M49 overview is not valid UTF-8") from error

    parser = _EnglishM49TableParser()
    try:
        parser.feed(html)
        parser.close()
    except M49RegionError:
        raise
    except Exception as error:
        raise M49RegionError("Saved M49 overview contains malformed HTML") from error
    if not parser.found:
        raise M49RegionError(
            f"Saved M49 overview has no English table #{M49_ENGLISH_TABLE_ID}"
        )
    if not parser.finished or parser._inside:
        raise M49RegionError("Saved M49 English table is not closed")
    if not parser.rows:
        raise M49RegionError("Saved M49 English table is empty")

    headers = _headers(parser.rows[0])
    source_rows = parser.rows[1:]
    if not source_rows:
        raise M49RegionError("Saved M49 English table has no country rows")
    records, by_iso2 = _index_records(source_rows, headers)
    regions_by_iso2 = {
        record.iso_alpha2: record.skyeta_region for record in records
    }
    for iso2, region in COMPATIBILITY_ISO2_OVERRIDES.items():
        existing = regions_by_iso2.get(iso2)
        if existing is not None and existing != region:
            raise M49RegionConflictError(
                f"UN-derived region {existing!r} for {iso2} conflicts with the "
                f"documented compatibility region {region!r}"
            )
        regions_by_iso2[iso2] = region

    provenance = M49RegionProvenance(
        source_id=M49_SOURCE_ID,
        source_provider=M49_SOURCE_PROVIDER,
        dataset_name=M49_DATASET_NAME,
        source_url=source,
        file_path=str(path),
        filename=path.name,
        retrieved_at_utc=retrieved,
        raw_file_sha256=digest,
        raw_bytes=len(raw_data),
        table_id=M49_ENGLISH_TABLE_ID,
        raw_row_count=len(source_rows),
        accepted_row_count=len(records),
        compatibility_override_count=len(COMPATIBILITY_ISO2_OVERRIDES),
        mapping_count=len(regions_by_iso2),
    )
    audit = M49RegionAudit(provenance=provenance, headers=headers)
    return M49RegionCatalog(
        records=records,
        by_iso2=by_iso2,
        regions_by_iso2=regions_by_iso2,
        audit=audit,
    )


# Short discoverable aliases for callers that do not need the catalog wording.
load_m49_regions = load_m49_region_catalog
load_region_reference = load_m49_region_catalog
