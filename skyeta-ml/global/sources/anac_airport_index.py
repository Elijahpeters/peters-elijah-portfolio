"""Fail-closed ANAC aerodrome identity enrichment.

The ANAC aerodrome registry is authoritative for Brazilian ICAO identity,
CIAD identity, name and WGS84 coordinates.  It does not publish IATA codes or
IANA timezones.  This module joins those official records to an independently
resolved timezone mapping and, optionally, uses ``airportsdata`` as a
secondary IATA source and timezone QA signal.

No network I/O, geographic guessing or hand-written airport overrides occur
here.  A secondary row can contribute only an IATA code, and only after an
exact ICAO/country/coordinate/uniqueness check.  All other official fields are
retained verbatim from ANAC.  Rows without an independently supplied valid
timezone are excluded from the adapter index rather than borrowing the
secondary source's timezone.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Any, Literal, TypeAlias
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .airports import AirportReferenceCatalog, AirportReferenceRecord
from .anac import AirportMetadata
from .anac_aerodromes import (
    AnacAerodromeCatalog,
    AnacAerodromeProvenance,
    AnacAerodromeRecord,
)


_ICAO = re.compile(r"^[A-Z0-9]{4}$")
_IATA = re.compile(r"^[A-Z]{3}$")
_BRAZIL_COUNTRY_CODE = "BR"
_SAFE_ENRICHMENT_KM = 1.0
_MANUAL_REVIEW_KM = 5.0
_EARTH_RADIUS_KM = 6371.0088

MergeDisposition: TypeAlias = Literal[
    "enriched_iata",
    "icao_only_no_secondary",
    "icao_only_secondary_without_iata",
    "icao_only_manual_review",
    "icao_only_conflict",
    "excluded_missing_timezone",
    "excluded_invalid_timezone",
]


@dataclass(frozen=True, slots=True)
class AnacAirportIdentityProvenance:
    """Official snapshot facts retained for one merged airport record."""

    source_id: str
    source_provider: str
    dataset_name: str
    source_url: str
    archive_url: str
    raw_file_sha256: str
    snapshot_updated_on: str
    aerodrome_type: str
    ciad: str
    official_name: str


@dataclass(frozen=True, slots=True)
class AnacAirportMergeEntry:
    """One official aerodrome's inclusion and enrichment decision."""

    icao: str
    metadata: AirportMetadata | None
    disposition: MergeDisposition
    reason_code: str
    reason: str
    provenance: AnacAirportIdentityProvenance
    independent_timezone: str | None
    enriched_iata: str | None
    secondary_icao: str | None
    secondary_iata: str | None
    secondary_country_code: str | None
    secondary_distance_km: float | None
    secondary_timezone_name: str | None
    secondary_timezone_matches: bool | None
    secondary_source_id: str | None
    secondary_raw_file_sha256: str | None

    @property
    def included(self) -> bool:
        return self.metadata is not None

    @property
    def requires_manual_review(self) -> bool:
        return self.disposition == "icao_only_manual_review"

    @property
    def has_conflict(self) -> bool:
        return self.disposition == "icao_only_conflict"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.metadata is not None:
            result["metadata"] = asdict(self.metadata)
        return result


@dataclass(frozen=True, slots=True)
class AnacAirportIndexAudit:
    """Complete reconciliation and reason counts for an index build."""

    official_record_count: int
    indexed_record_count: int
    excluded_record_count: int
    enriched_iata_count: int
    icao_only_count: int
    manual_review_count: int
    conflict_count: int
    missing_timezone_count: int
    invalid_timezone_count: int
    secondary_timezone_match_count: int
    secondary_timezone_mismatch_count: int
    disposition_counts: Mapping[str, int]
    reason_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        disposition_counts = dict(self.disposition_counts)
        reason_counts = dict(self.reason_counts)
        if self.indexed_record_count + self.excluded_record_count != self.official_record_count:
            raise ValueError("index audit does not reconcile official aerodrome records")
        if self.enriched_iata_count + self.icao_only_count != self.indexed_record_count:
            raise ValueError("index audit does not reconcile indexed aerodromes")
        if sum(disposition_counts.values()) != self.official_record_count:
            raise ValueError("disposition counts do not reconcile official records")
        if sum(reason_counts.values()) != self.official_record_count:
            raise ValueError("reason counts do not reconcile official records")
        object.__setattr__(
            self, "disposition_counts", MappingProxyType(disposition_counts)
        )
        object.__setattr__(self, "reason_counts", MappingProxyType(reason_counts))

    def to_dict(self) -> dict[str, Any]:
        return {
            "official_record_count": self.official_record_count,
            "indexed_record_count": self.indexed_record_count,
            "excluded_record_count": self.excluded_record_count,
            "enriched_iata_count": self.enriched_iata_count,
            "icao_only_count": self.icao_only_count,
            "manual_review_count": self.manual_review_count,
            "conflict_count": self.conflict_count,
            "missing_timezone_count": self.missing_timezone_count,
            "invalid_timezone_count": self.invalid_timezone_count,
            "secondary_timezone_match_count": (
                self.secondary_timezone_match_count
            ),
            "secondary_timezone_mismatch_count": (
                self.secondary_timezone_mismatch_count
            ),
            "disposition_counts": dict(self.disposition_counts),
            "reason_counts": dict(self.reason_counts),
        }


@dataclass(frozen=True, slots=True)
class AnacAirportIndex(Mapping[str, AirportMetadata]):
    """Immutable ICAO-keyed metadata plus every merge decision."""

    by_icao: Mapping[str, AirportMetadata]
    entries: tuple[AnacAirportMergeEntry, ...]
    audit: AnacAirportIndexAudit

    def __post_init__(self) -> None:
        by_icao = dict(self.by_icao)
        entries = tuple(self.entries)
        included_entries = {entry.icao: entry for entry in entries if entry.included}
        if len(entries) != self.audit.official_record_count:
            raise ValueError("merge entries must account for every official record")
        if len({entry.icao for entry in entries}) != len(entries):
            raise ValueError("merge entries contain a duplicate official ICAO")
        if set(by_icao) != set(included_entries):
            raise ValueError("ICAO index and included merge entries disagree")
        for icao, metadata in by_icao.items():
            if metadata.icao != icao:
                raise ValueError(f"Airport metadata key/code mismatch for {icao}")
            if included_entries[icao].metadata != metadata:
                raise ValueError(f"Merge entry metadata mismatch for {icao}")
        object.__setattr__(self, "by_icao", MappingProxyType(by_icao))
        object.__setattr__(self, "entries", entries)

    def __getitem__(self, key: str) -> AirportMetadata:
        return self.by_icao[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.by_icao)

    def __len__(self) -> int:
        return len(self.by_icao)


def _haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    )
    return _EARTH_RADIUS_KM * 2 * math.asin(min(1.0, math.sqrt(haversine)))


def _normalized_timezones(values: Mapping[str, str]) -> Mapping[str, object]:
    if not isinstance(values, Mapping):
        raise TypeError("timezones_by_icao must be a mapping")
    normalized: dict[str, object] = {}
    for raw_icao, raw_timezone in values.items():
        icao = str(raw_icao or "").strip().upper()
        if not _ICAO.fullmatch(icao):
            raise ValueError(f"Invalid ICAO key in timezone mapping: {raw_icao!r}")
        if icao in normalized:
            raise ValueError(f"Duplicate normalized timezone key: {icao}")
        normalized[icao] = raw_timezone
    return MappingProxyType(normalized)


def _validated_timezone(value: object) -> tuple[str | None, str | None]:
    if value is None or not str(value).strip():
        return None, "missing_timezone"
    timezone_name = str(value).strip()
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return None, "invalid_timezone"
    return timezone_name, None


def _official_provenance(
    catalog: AnacAerodromeCatalog,
    record: AnacAerodromeRecord,
) -> AnacAirportIdentityProvenance:
    candidates = [
        audit.provenance
        for audit in catalog.audits
        if audit.provenance.aerodrome_type == record.aerodrome_type
        and audit.provenance.snapshot_updated_on == record.snapshot_updated_on
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"Official snapshot provenance for {record.icao} is "
            f"{'missing' if not candidates else 'ambiguous'}"
        )
    source: AnacAerodromeProvenance = candidates[0]
    return AnacAirportIdentityProvenance(
        source_id=source.source_id,
        source_provider=source.source_provider,
        dataset_name=source.dataset_name,
        source_url=source.source_url,
        archive_url=source.archive_url,
        raw_file_sha256=source.raw_file_sha256,
        snapshot_updated_on=record.snapshot_updated_on.isoformat(),
        aerodrome_type=record.aerodrome_type,
        ciad=record.ciad,
        official_name=record.name,
    )


def _iata_claims(
    secondary: AirportReferenceCatalog | None,
) -> Mapping[str, tuple[AirportReferenceRecord, ...]]:
    claims: defaultdict[str, list[AirportReferenceRecord]] = defaultdict(list)
    if secondary is not None:
        for record in secondary.records:
            if record.iata is not None:
                claims[record.iata].append(record)
    return MappingProxyType({key: tuple(records) for key, records in claims.items()})


def _secondary_facts(
    secondary: AirportReferenceCatalog | None,
    record: AirportReferenceRecord | None,
    independent_timezone: str | None,
) -> dict[str, object]:
    if record is None:
        return {
            "secondary_icao": None,
            "secondary_iata": None,
            "secondary_country_code": None,
            "secondary_distance_km": None,
            "secondary_timezone_name": None,
            "secondary_timezone_matches": None,
            "secondary_source_id": None,
            "secondary_raw_file_sha256": None,
        }
    provenance = secondary.provenance if secondary is not None else None
    return {
        "secondary_icao": record.icao,
        "secondary_iata": record.iata,
        "secondary_country_code": record.country_code,
        "secondary_distance_km": None,
        "secondary_timezone_name": record.timezone_name,
        "secondary_timezone_matches": (
            record.timezone_name == independent_timezone
            if independent_timezone is not None
            else None
        ),
        "secondary_source_id": (
            provenance.source_id if provenance is not None else None
        ),
        "secondary_raw_file_sha256": (
            provenance.raw_file_sha256 if provenance is not None else None
        ),
    }


def build_anac_airport_index(
    official: AnacAerodromeCatalog,
    timezones_by_icao: Mapping[str, str],
    *,
    region_code: str,
    secondary: AirportReferenceCatalog | None = None,
) -> AnacAirportIndex:
    """Build strict ANAC adapter metadata without guessing identity fields.

    ``timezones_by_icao`` is intentionally a small, provider-neutral contract
    so a future versioned timezone resolver can expose its accepted mapping
    directly.  Missing and invalid values exclude the official aerodrome.
    ``airportsdata`` never fills that gap: its timezone is retained only as a
    QA comparison.
    """

    if not isinstance(official, AnacAerodromeCatalog):
        raise TypeError("official must be an AnacAerodromeCatalog")
    if secondary is not None and not isinstance(secondary, AirportReferenceCatalog):
        raise TypeError("secondary must be an AirportReferenceCatalog or None")
    region = str(region_code or "").strip()
    if not region:
        raise ValueError("region_code is required")

    timezone_map = _normalized_timezones(timezones_by_icao)
    iata_claims = _iata_claims(secondary)
    entries: list[AnacAirportMergeEntry] = []
    by_icao: dict[str, AirportMetadata] = {}

    for official_record in official.records:
        provenance = _official_provenance(official, official_record)
        timezone_name, timezone_error = _validated_timezone(
            timezone_map.get(official_record.icao)
        )
        candidate = (
            secondary.by_icao.get(official_record.icao)
            if secondary is not None
            else None
        )
        facts = _secondary_facts(secondary, candidate, timezone_name)

        if timezone_error is not None:
            disposition: MergeDisposition = (
                "excluded_missing_timezone"
                if timezone_error == "missing_timezone"
                else "excluded_invalid_timezone"
            )
            reason = (
                "No independently resolved IANA timezone was supplied"
                if timezone_error == "missing_timezone"
                else "The independently supplied timezone is not a valid IANA zone"
            )
            entries.append(
                AnacAirportMergeEntry(
                    icao=official_record.icao,
                    metadata=None,
                    disposition=disposition,
                    reason_code=timezone_error,
                    reason=reason,
                    provenance=provenance,
                    independent_timezone=None,
                    enriched_iata=None,
                    **facts,
                )
            )
            continue

        assert timezone_name is not None
        enriched_iata: str | None = None
        disposition = "icao_only_no_secondary"
        reason_code = "no_secondary_exact_icao"
        reason = "No secondary record matched the official ICAO exactly"

        if candidate is not None:
            distance = _haversine_km(
                official_record.latitude_wgs84,
                official_record.longitude_wgs84,
                candidate.latitude,
                candidate.longitude,
            )
            facts["secondary_distance_km"] = distance
            if candidate.icao != official_record.icao:
                disposition = "icao_only_conflict"
                reason_code = "secondary_icao_mismatch"
                reason = "Secondary ICAO identity does not match the official key"
            elif candidate.country_code != _BRAZIL_COUNTRY_CODE:
                disposition = "icao_only_conflict"
                reason_code = "secondary_country_mismatch"
                reason = "Secondary country is not Brazil"
            elif distance > _MANUAL_REVIEW_KM:
                disposition = "icao_only_conflict"
                reason_code = "secondary_coordinate_conflict"
                reason = "Secondary coordinates differ from ANAC by more than 5 km"
            elif distance > _SAFE_ENRICHMENT_KM:
                disposition = "icao_only_manual_review"
                reason_code = "secondary_coordinate_manual_review"
                reason = "Secondary coordinates differ from ANAC by more than 1 km"
            elif candidate.iata is None:
                disposition = "icao_only_secondary_without_iata"
                reason_code = "secondary_has_no_iata"
                reason = "The matching secondary record has no valid IATA code"
            elif not _IATA.fullmatch(candidate.iata):
                disposition = "icao_only_conflict"
                reason_code = "secondary_invalid_iata"
                reason = "The secondary IATA claim is invalid"
            else:
                claims = iata_claims.get(candidate.iata, ())
                indexed_owner = secondary.by_iata.get(candidate.iata)
                if (
                    len(claims) != 1
                    or claims[0] != candidate
                    or indexed_owner != candidate
                    or indexed_owner.icao != official_record.icao
                ):
                    disposition = "icao_only_conflict"
                    reason_code = "secondary_iata_collision"
                    reason = (
                        "The secondary IATA claim collides with another or "
                        "pseudo-ICAO record"
                    )
                else:
                    enriched_iata = candidate.iata
                    disposition = "enriched_iata"
                    reason_code = "safe_exact_icao_enrichment"
                    reason = (
                        "Exact Brazilian ICAO match with coordinates within 1 km "
                        "and a unique IATA claim"
                    )

        metadata = AirportMetadata(
            icao=official_record.icao,
            iata=enriched_iata,
            latitude=official_record.latitude_wgs84,
            longitude=official_record.longitude_wgs84,
            country_code=_BRAZIL_COUNTRY_CODE,
            region_code=region,
            timezone_name=timezone_name,
        )
        entry = AnacAirportMergeEntry(
            icao=official_record.icao,
            metadata=metadata,
            disposition=disposition,
            reason_code=reason_code,
            reason=reason,
            provenance=provenance,
            independent_timezone=timezone_name,
            enriched_iata=enriched_iata,
            **facts,
        )
        entries.append(entry)
        by_icao[official_record.icao] = metadata

    dispositions = Counter(entry.disposition for entry in entries)
    reasons = Counter(entry.reason_code for entry in entries)
    included = [entry for entry in entries if entry.included]
    audit = AnacAirportIndexAudit(
        official_record_count=len(entries),
        indexed_record_count=len(included),
        excluded_record_count=len(entries) - len(included),
        enriched_iata_count=dispositions["enriched_iata"],
        icao_only_count=len(included) - dispositions["enriched_iata"],
        manual_review_count=dispositions["icao_only_manual_review"],
        conflict_count=dispositions["icao_only_conflict"],
        missing_timezone_count=dispositions["excluded_missing_timezone"],
        invalid_timezone_count=dispositions["excluded_invalid_timezone"],
        secondary_timezone_match_count=sum(
            entry.secondary_timezone_matches is True for entry in entries
        ),
        secondary_timezone_mismatch_count=sum(
            entry.secondary_timezone_matches is False for entry in entries
        ),
        disposition_counts=dispositions,
        reason_counts=reasons,
    )
    return AnacAirportIndex(by_icao=by_icao, entries=tuple(entries), audit=audit)


__all__ = [
    "AnacAirportIdentityProvenance",
    "AnacAirportIndex",
    "AnacAirportIndexAudit",
    "AnacAirportMergeEntry",
    "MergeDisposition",
    "build_anac_airport_index",
]
