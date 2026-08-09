"""Offline preparation of a provenance-complete ANAC airport reference.

This module is deliberately an orchestration layer.  The source loaders retain
their individual responsibilities:

* :mod:`global.sources.anac_aerodromes` validates archived ANAC snapshots;
* :mod:`global.sources.timezone_boundaries` resolves coordinates fail-closed;
* :mod:`global.sources.airports` optionally loads secondary IATA evidence; and
* :mod:`global.sources.anac_airport_index` performs the conservative merge.

No function here performs network I/O.  Every file must already exist locally,
and every file-backed input is either protected by an explicit SHA-256 digest
or by the reviewed Timezone Boundary Builder source pin.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .sources.airports import (
    AIRPORTS_SOURCE_URL,
    AirportReferenceAudit,
    AirportReferenceCatalog,
    load_airport_reference,
)
from .sources.anac_aerodromes import (
    AnacAerodromeAudit,
    AnacAerodromeCatalog,
    AnacAerodromeRecord,
    load_anac_aerodrome_snapshot,
    merge_anac_aerodrome_catalogs,
)
from .sources.anac_airport_index import (
    AnacAirportIndex,
    AnacAirportIndexAudit,
    build_anac_airport_index,
)
from .sources.timezone_boundaries import (
    DEFAULT_GUARD_BEARING_COUNT,
    DEFAULT_GUARD_DISTANCE_KM,
    DEFAULT_TIMEZONE_BOUNDARY_PIN,
    TimezoneBoundaryLoadAudit,
    TimezoneBoundarySourcePin,
    TimezoneResolution,
    load_timezone_boundary_resolver,
)


ANAC_REFERENCE_SCHEMA_VERSION = "skyeta-anac-reference-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ICAO = re.compile(r"^[A-Z0-9]{4}$")


class AnacReferenceError(ValueError):
    """The combined ANAC reference cannot be prepared safely."""


class AnacReferenceIntegrityError(AnacReferenceError):
    """A local input differs from its reviewed identity or digest."""


class AnacReferenceReconciliationError(AnacReferenceError):
    """Source, resolution, and merge accounting do not reconcile."""


def _utc(value: datetime, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise AnacReferenceIntegrityError(
            f"{field_name} must be a timezone-aware datetime"
        )
    return value.astimezone(timezone.utc)


def _digest(value: object, field_name: str) -> str:
    digest = str(value or "").strip().lower()
    if not _SHA256.fullmatch(digest):
        raise AnacReferenceIntegrityError(
            f"{field_name} must contain exactly 64 hexadecimal characters"
        )
    return digest


def _local_path(value: str | Path, field_name: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise AnacReferenceIntegrityError(f"{field_name} is required")
    return str(Path(raw).resolve())


@dataclass(frozen=True, slots=True)
class ArchivedAnacSnapshotInput:
    """Exact local bytes and memento identity for one ANAC snapshot."""

    path: str | Path
    source_url: str
    archive_url: str
    archived_at_utc: datetime
    expected_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _local_path(self.path, "snapshot path"))
        object.__setattr__(
            self,
            "archived_at_utc",
            _utc(self.archived_at_utc, "archived_at_utc"),
        )
        object.__setattr__(
            self,
            "expected_sha256",
            _digest(self.expected_sha256, "expected_sha256"),
        )
        if not str(self.source_url).strip() or not str(self.archive_url).strip():
            raise AnacReferenceIntegrityError(
                "source_url and archive_url are required"
            )


@dataclass(frozen=True, slots=True)
class TimezoneBoundaryInput:
    """One already-cached, content-pinned timezone boundary asset."""

    path: str | Path
    retrieved_at_utc: datetime
    pin: TimezoneBoundarySourcePin = DEFAULT_TIMEZONE_BOUNDARY_PIN

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "path", _local_path(self.path, "timezone boundary path")
        )
        object.__setattr__(
            self,
            "retrieved_at_utc",
            _utc(self.retrieved_at_utc, "timezone boundary retrieved_at_utc"),
        )
        if not isinstance(self.pin, TimezoneBoundarySourcePin):
            raise TypeError("pin must be a TimezoneBoundarySourcePin")


@dataclass(frozen=True, slots=True)
class AirportsdataFileInput:
    """Optional locally cached airportsdata CSV plus retrieval provenance."""

    path: str | Path
    retrieved_at_utc: datetime
    expected_sha256: str
    source_url: str = AIRPORTS_SOURCE_URL

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _local_path(self.path, "airportsdata path"))
        object.__setattr__(
            self,
            "retrieved_at_utc",
            _utc(self.retrieved_at_utc, "airportsdata retrieved_at_utc"),
        )
        object.__setattr__(
            self,
            "expected_sha256",
            _digest(self.expected_sha256, "airportsdata expected_sha256"),
        )
        if not str(self.source_url).strip():
            raise AnacReferenceIntegrityError(
                "airportsdata source_url is required"
            )


@dataclass(frozen=True, slots=True)
class AnacAerodromeTimezoneResult:
    """One official ICAO identity paired with its exact resolver result."""

    icao: str
    ciad: str
    aerodrome_type: str
    resolution: TimezoneResolution

    def __post_init__(self) -> None:
        icao = str(self.icao or "").strip().upper()
        if not _ICAO.fullmatch(icao):
            raise AnacReferenceReconciliationError(
                f"invalid timezone-result ICAO: {self.icao!r}"
            )
        if not str(self.ciad or "").strip():
            raise AnacReferenceReconciliationError(
                f"timezone result {icao} is missing CIAD identity"
            )
        if self.aerodrome_type not in {"public", "private"}:
            raise AnacReferenceReconciliationError(
                f"timezone result {icao} has an invalid aerodrome type"
            )
        if not isinstance(self.resolution, TimezoneResolution):
            raise TypeError("resolution must be a TimezoneResolution")
        object.__setattr__(self, "icao", icao)

    @property
    def accepted(self) -> bool:
        return self.resolution.disposition == "accepted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "icao": self.icao,
            "ciad": self.ciad,
            "aerodrome_type": self.aerodrome_type,
            "resolution": self.resolution.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AnacReferenceAudit:
    """Source provenance and reconciled counts for one prepared artifact."""

    official_snapshot_audits: tuple[AnacAerodromeAudit, ...]
    timezone_boundary_audit: TimezoneBoundaryLoadAudit
    secondary_reference_audit: AirportReferenceAudit | None
    index_audit: AnacAirportIndexAudit
    official_raw_row_count: int
    official_record_count: int
    official_rejected_row_count: int
    timezone_input_count: int
    timezone_accepted_count: int
    timezone_rejected_count: int
    timezone_reason_counts: Mapping[str, int]
    corpus_digest: str
    completed: bool = True

    def __post_init__(self) -> None:
        source_audits = tuple(self.official_snapshot_audits)
        if len(source_audits) != 2:
            raise AnacReferenceReconciliationError(
                "exactly one public and one private ANAC snapshot are required"
            )
        source_types = {
            audit.provenance.aerodrome_type for audit in source_audits
        }
        if source_types != {"public", "private"}:
            raise AnacReferenceReconciliationError(
                "snapshot audits must contain one public and one private source"
            )
        if sum(item.raw_row_count for item in source_audits) != self.official_raw_row_count:
            raise AnacReferenceReconciliationError(
                "official raw-row counts do not reconcile"
            )
        if sum(item.accepted_row_count for item in source_audits) != self.official_record_count:
            raise AnacReferenceReconciliationError(
                "official accepted-row counts do not reconcile"
            )
        if sum(item.rejected_row_count for item in source_audits) != self.official_rejected_row_count:
            raise AnacReferenceReconciliationError(
                "official rejected-row counts do not reconcile"
            )
        if self.timezone_input_count != self.official_record_count:
            raise AnacReferenceReconciliationError(
                "every official aerodrome must have one timezone result"
            )
        if (
            self.timezone_accepted_count + self.timezone_rejected_count
            != self.timezone_input_count
        ):
            raise AnacReferenceReconciliationError(
                "timezone disposition counts do not reconcile"
            )
        reason_counts = dict(self.timezone_reason_counts)
        if any(not reason or count <= 0 for reason, count in reason_counts.items()):
            raise AnacReferenceReconciliationError(
                "timezone reason counts must use non-empty positive entries"
            )
        if sum(reason_counts.values()) != self.timezone_input_count:
            raise AnacReferenceReconciliationError(
                "timezone reason counts do not reconcile"
            )
        if self.index_audit.official_record_count != self.official_record_count:
            raise AnacReferenceReconciliationError(
                "airport-index counts do not reconcile official records"
            )
        if not self.timezone_boundary_audit.completed or not self.completed:
            raise AnacReferenceReconciliationError(
                "only completed source and preparation audits may be published"
            )
        object.__setattr__(self, "official_snapshot_audits", source_audits)
        object.__setattr__(
            self, "timezone_reason_counts", MappingProxyType(reason_counts)
        )
        object.__setattr__(
            self, "corpus_digest", _digest(self.corpus_digest, "corpus_digest")
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "official_snapshot_audits": [
                audit.to_dict() for audit in self.official_snapshot_audits
            ],
            "timezone_boundary_audit": self.timezone_boundary_audit.to_dict(),
            "secondary_reference_audit": (
                self.secondary_reference_audit.to_dict()
                if self.secondary_reference_audit is not None
                else None
            ),
            "index_audit": self.index_audit.to_dict(),
            "official_raw_row_count": self.official_raw_row_count,
            "official_record_count": self.official_record_count,
            "official_rejected_row_count": self.official_rejected_row_count,
            "timezone_input_count": self.timezone_input_count,
            "timezone_accepted_count": self.timezone_accepted_count,
            "timezone_rejected_count": self.timezone_rejected_count,
            "timezone_reason_counts": dict(self.timezone_reason_counts),
            "corpus_digest": self.corpus_digest,
            "completed": self.completed,
        }


def _record_dict(record: AnacAerodromeRecord) -> dict[str, Any]:
    return record.to_dict()


def _metadata_dict(index: AnacAirportIndex) -> dict[str, dict[str, Any]]:
    return {
        icao: asdict(index.by_icao[icao])
        for icao in sorted(index.by_icao)
    }


def _without_local_paths(value: object) -> object:
    """Remove machine-local paths from the otherwise complete digest payload."""

    if isinstance(value, Mapping):
        return {
            str(key): _without_local_paths(item)
            for key, item in value.items()
            if str(key) != "file_path"
        }
    if isinstance(value, (list, tuple)):
        return [_without_local_paths(item) for item in value]
    return value


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(
        _without_local_paths(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _digest_payload(
    *,
    region_code: str,
    official: AnacAerodromeCatalog,
    timezone_results: tuple[AnacAerodromeTimezoneResult, ...],
    timezone_boundary_audit: TimezoneBoundaryLoadAudit,
    secondary: AirportReferenceCatalog | None,
    index: AnacAirportIndex,
) -> dict[str, Any]:
    return {
        "schema_version": ANAC_REFERENCE_SCHEMA_VERSION,
        "region_code": region_code,
        "official_sources": [audit.to_dict() for audit in official.audits],
        "official_aerodromes": [
            _record_dict(record) for record in sorted(official.records, key=lambda item: item.icao)
        ],
        "timezone_boundary_audit": timezone_boundary_audit.to_dict(),
        "timezone_results": [item.to_dict() for item in timezone_results],
        "secondary_reference": (
            {
                "audit": secondary.audit.to_dict(),
                "records": [
                    record.to_dict()
                    for record in sorted(
                        secondary.records,
                        key=lambda item: (item.icao or "", item.iata or ""),
                    )
                ],
            }
            if secondary is not None
            else None
        ),
        "airport_index": {
            "by_icao": _metadata_dict(index),
            "entries": [
                entry.to_dict() for entry in sorted(index.entries, key=lambda item: item.icao)
            ],
            "audit": index.audit.to_dict(),
        },
    }


@dataclass(frozen=True, slots=True)
class AnacReferenceArtifact:
    """Immutable offline ANAC reference, decisions, and corpus identity."""

    schema_version: str
    region_code: str
    official_catalog: AnacAerodromeCatalog
    timezone_results: tuple[AnacAerodromeTimezoneResult, ...]
    secondary_catalog: AirportReferenceCatalog | None
    airport_index: AnacAirportIndex
    audit: AnacReferenceAudit
    corpus_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != ANAC_REFERENCE_SCHEMA_VERSION:
            raise AnacReferenceReconciliationError(
                "unsupported ANAC reference schema version"
            )
        region = str(self.region_code or "").strip()
        if not region:
            raise AnacReferenceReconciliationError("region_code is required")
        if not isinstance(self.official_catalog, AnacAerodromeCatalog):
            raise TypeError("official_catalog must be an AnacAerodromeCatalog")
        if not isinstance(self.airport_index, AnacAirportIndex):
            raise TypeError("airport_index must be an AnacAirportIndex")
        if self.secondary_catalog is not None:
            _validate_secondary_catalog(self.secondary_catalog)
        if (self.secondary_catalog is None) != (
            self.audit.secondary_reference_audit is None
        ):
            raise AnacReferenceReconciliationError(
                "secondary catalog and secondary audit presence disagree"
            )
        if (
            self.secondary_catalog is not None
            and self.secondary_catalog.audit != self.audit.secondary_reference_audit
        ):
            raise AnacReferenceReconciliationError(
                "secondary catalog and secondary source audit disagree"
            )

        results = tuple(self.timezone_results)
        official_by_icao = self.official_catalog.by_icao
        result_by_icao = {item.icao: item for item in results}
        if len(result_by_icao) != len(results):
            raise AnacReferenceReconciliationError(
                "timezone results contain duplicate ICAO identities"
            )
        if set(result_by_icao) != set(official_by_icao):
            raise AnacReferenceReconciliationError(
                "timezone results do not cover the official ICAO corpus exactly"
            )
        merge_by_icao = {entry.icao: entry for entry in self.airport_index.entries}
        if set(merge_by_icao) != set(official_by_icao):
            raise AnacReferenceReconciliationError(
                "merge decisions do not cover the official ICAO corpus exactly"
            )

        for icao, official_record in official_by_icao.items():
            timezone_result = result_by_icao[icao]
            resolution = timezone_result.resolution
            if resolution.provenance != self.audit.timezone_boundary_audit.provenance:
                raise AnacReferenceReconciliationError(
                    f"timezone result provenance does not match the pinned asset for {icao}"
                )
            if timezone_result.ciad != official_record.ciad:
                raise AnacReferenceReconciliationError(
                    f"timezone result CIAD does not match official {icao}"
                )
            if timezone_result.aerodrome_type != official_record.aerodrome_type:
                raise AnacReferenceReconciliationError(
                    f"timezone result aerodrome type does not match official {icao}"
                )
            if (
                resolution.latitude != official_record.latitude_wgs84
                or resolution.longitude != official_record.longitude_wgs84
            ):
                raise AnacReferenceReconciliationError(
                    f"timezone result coordinates do not match official {icao}"
                )
            merge_entry = merge_by_icao[icao]
            if timezone_result.accepted:
                if (
                    not merge_entry.included
                    or merge_entry.independent_timezone != resolution.timezone_id
                ):
                    raise AnacReferenceReconciliationError(
                        f"accepted timezone was not retained for {icao}"
                    )
            elif merge_entry.included or merge_entry.disposition != "excluded_missing_timezone":
                raise AnacReferenceReconciliationError(
                    f"rejected timezone did not fail closed for {icao}"
                )

        actual_accepted = sum(item.accepted for item in results)
        if (
            self.audit.timezone_input_count != len(results)
            or self.audit.timezone_accepted_count != actual_accepted
            or self.audit.timezone_rejected_count != len(results) - actual_accepted
        ):
            raise AnacReferenceReconciliationError(
                "timezone audit counts do not match the preserved results"
            )
        actual_reasons = Counter(item.resolution.reason for item in results)
        if dict(self.audit.timezone_reason_counts) != dict(actual_reasons):
            raise AnacReferenceReconciliationError(
                "timezone audit reason counts do not match the preserved results"
            )

        digest = _digest(self.corpus_digest, "corpus_digest")
        calculated = _canonical_sha256(
            _digest_payload(
                region_code=region,
                official=self.official_catalog,
                timezone_results=results,
                timezone_boundary_audit=self.audit.timezone_boundary_audit,
                secondary=self.secondary_catalog,
                index=self.airport_index,
            )
        )
        if calculated != digest:
            raise AnacReferenceReconciliationError(
                "corpus digest does not match the prepared artifact"
            )
        if self.audit.corpus_digest != digest:
            raise AnacReferenceReconciliationError(
                "artifact and audit corpus digests disagree"
            )
        object.__setattr__(self, "region_code", region)
        object.__setattr__(self, "timezone_results", results)
        object.__setattr__(self, "corpus_digest", digest)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "region_code": self.region_code,
            "corpus_digest": self.corpus_digest,
            "sources": {
                "official_snapshots": [
                    audit.to_dict() for audit in self.audit.official_snapshot_audits
                ],
                "timezone_boundaries": self.audit.timezone_boundary_audit.to_dict(),
                "secondary_airportsdata": (
                    self.audit.secondary_reference_audit.to_dict()
                    if self.audit.secondary_reference_audit is not None
                    else None
                ),
            },
            "official_aerodromes": [
                _record_dict(record)
                for record in sorted(
                    self.official_catalog.records, key=lambda item: item.icao
                )
            ],
            "timezone_results": [item.to_dict() for item in self.timezone_results],
            "airport_index": {
                "by_icao": _metadata_dict(self.airport_index),
                "entries": [
                    entry.to_dict()
                    for entry in sorted(
                        self.airport_index.entries, key=lambda item: item.icao
                    )
                ],
                "audit": self.airport_index.audit.to_dict(),
            },
            "audit": self.audit.to_dict(),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=indent,
            separators=(",", ":") if indent is None else None,
        )
def _validate_expected_hash(actual: str, expected: str, source_name: str) -> None:
    if actual.lower() != expected.lower():
        raise AnacReferenceIntegrityError(
            f"{source_name} SHA-256 mismatch: expected {expected}, got {actual}"
        )


def _validate_official_identities(catalog: AnacAerodromeCatalog) -> None:
    ciad_owner: dict[str, str] = {}
    for record in catalog.records:
        previous = ciad_owner.get(record.ciad)
        if previous is not None:
            raise AnacReferenceReconciliationError(
                f"duplicate official CIAD {record.ciad} is claimed by "
                f"{previous} and {record.icao}"
            )
        ciad_owner[record.ciad] = record.icao


def _validate_secondary_catalog(catalog: AirportReferenceCatalog) -> None:
    if not isinstance(catalog, AirportReferenceCatalog):
        raise TypeError(
            "airportsdata must be an AirportsdataFileInput, "
            "AirportReferenceCatalog, or None"
        )
    provenance = catalog.provenance
    if provenance.accepted_row_count != len(catalog.records):
        raise AnacReferenceReconciliationError(
            "secondary accepted-row count does not match catalog records"
        )
    if provenance.raw_row_count != (
        provenance.accepted_row_count + provenance.skipped_row_count
    ):
        raise AnacReferenceReconciliationError(
            "secondary raw-row accounting does not reconcile"
        )
    if provenance.skipped_row_count != len(catalog.audit.skipped_rows):
        raise AnacReferenceReconciliationError(
            "secondary skipped-row accounting does not reconcile"
        )
    if provenance.icao_count != len(catalog.by_icao):
        raise AnacReferenceReconciliationError(
            "secondary ICAO index count does not reconcile"
        )
    if provenance.iata_count != len(catalog.by_iata):
        raise AnacReferenceReconciliationError(
            "secondary IATA index count does not reconcile"
        )
    identities = [
        (record.icao, record.iata) for record in catalog.records
    ]
    if len(set(identities)) != len(identities):
        raise AnacReferenceReconciliationError(
            "secondary catalog contains duplicate normalized identities"
        )


def _load_secondary(
    value: AirportsdataFileInput | AirportReferenceCatalog | None,
) -> AirportReferenceCatalog | None:
    if value is None:
        return None
    if isinstance(value, AirportReferenceCatalog):
        _validate_secondary_catalog(value)
        return value
    if not isinstance(value, AirportsdataFileInput):
        raise TypeError(
            "airportsdata must be an AirportsdataFileInput, "
            "AirportReferenceCatalog, or None"
        )
    catalog = load_airport_reference(
        value.path,
        retrieved_at_utc=value.retrieved_at_utc,
        source_url=value.source_url,
    )
    _validate_expected_hash(
        catalog.provenance.raw_file_sha256,
        value.expected_sha256,
        "airportsdata",
    )
    _validate_secondary_catalog(catalog)
    return catalog


def prepare_anac_reference(
    *,
    public_snapshot: ArchivedAnacSnapshotInput,
    private_snapshot: ArchivedAnacSnapshotInput,
    timezone_boundaries: TimezoneBoundaryInput,
    region_code: str,
    airportsdata: AirportsdataFileInput | AirportReferenceCatalog | None = None,
    guard_distance_km: float = DEFAULT_GUARD_DISTANCE_KM,
    guard_bearing_count: int = DEFAULT_GUARD_BEARING_COUNT,
) -> AnacReferenceArtifact:
    """Prepare one strict ANAC airport reference from already-local sources."""

    if not isinstance(public_snapshot, ArchivedAnacSnapshotInput):
        raise TypeError("public_snapshot must be an ArchivedAnacSnapshotInput")
    if not isinstance(private_snapshot, ArchivedAnacSnapshotInput):
        raise TypeError("private_snapshot must be an ArchivedAnacSnapshotInput")
    if not isinstance(timezone_boundaries, TimezoneBoundaryInput):
        raise TypeError("timezone_boundaries must be a TimezoneBoundaryInput")
    region = str(region_code or "").strip()
    if not region:
        raise AnacReferenceError("region_code is required")

    public = load_anac_aerodrome_snapshot(
        public_snapshot.path,
        source_url=public_snapshot.source_url,
        archive_url=public_snapshot.archive_url,
        archived_at_utc=public_snapshot.archived_at_utc,
    )
    private = load_anac_aerodrome_snapshot(
        private_snapshot.path,
        source_url=private_snapshot.source_url,
        archive_url=private_snapshot.archive_url,
        archived_at_utc=private_snapshot.archived_at_utc,
    )
    if public.audits[0].provenance.aerodrome_type != "public":
        raise AnacReferenceReconciliationError(
            "public_snapshot did not load as the public ANAC catalogue"
        )
    if private.audits[0].provenance.aerodrome_type != "private":
        raise AnacReferenceReconciliationError(
            "private_snapshot did not load as the private ANAC catalogue"
        )
    _validate_expected_hash(
        public.audits[0].provenance.raw_file_sha256,
        public_snapshot.expected_sha256,
        "public ANAC snapshot",
    )
    _validate_expected_hash(
        private.audits[0].provenance.raw_file_sha256,
        private_snapshot.expected_sha256,
        "private ANAC snapshot",
    )

    official = merge_anac_aerodrome_catalogs(public, private)
    _validate_official_identities(official)
    ordered_records = tuple(sorted(official.records, key=lambda item: item.icao))

    resolver = load_timezone_boundary_resolver(
        timezone_boundaries.path,
        retrieved_at_utc=timezone_boundaries.retrieved_at_utc,
        pin=timezone_boundaries.pin,
    )
    batch = resolver.resolve_many(
        (
            (record.latitude_wgs84, record.longitude_wgs84)
            for record in ordered_records
        ),
        guard_distance_km=guard_distance_km,
        guard_bearing_count=guard_bearing_count,
    )
    if batch.input_count != len(ordered_records) or len(batch.results) != len(
        ordered_records
    ):
        raise AnacReferenceReconciliationError(
            "timezone resolver did not return one result per aerodrome"
        )
    timezone_results = tuple(
        AnacAerodromeTimezoneResult(
            icao=record.icao,
            ciad=record.ciad,
            aerodrome_type=record.aerodrome_type,
            resolution=resolution,
        )
        for record, resolution in zip(ordered_records, batch.results, strict=True)
    )
    actual_accepted_count = sum(item.accepted for item in timezone_results)
    if (
        batch.accepted_count != actual_accepted_count
        or batch.rejected_count != len(timezone_results) - actual_accepted_count
    ):
        raise AnacReferenceReconciliationError(
            "timezone batch counts do not match its preserved results"
        )
    if any(
        item.resolution.provenance != resolver.audit.provenance
        for item in timezone_results
    ):
        raise AnacReferenceReconciliationError(
            "timezone result provenance does not match the loaded pinned asset"
        )
    accepted_timezones = {
        item.icao: item.resolution.timezone_id
        for item in timezone_results
        if item.accepted and item.resolution.timezone_id is not None
    }

    secondary = _load_secondary(airportsdata)
    index = build_anac_airport_index(
        official,
        accepted_timezones,
        region_code=region,
        secondary=secondary,
    )

    digest_payload = _digest_payload(
        region_code=region,
        official=official,
        timezone_results=timezone_results,
        timezone_boundary_audit=resolver.audit,
        secondary=secondary,
        index=index,
    )
    corpus_digest = _canonical_sha256(digest_payload)
    reasons = Counter(item.resolution.reason for item in timezone_results)
    audit = AnacReferenceAudit(
        official_snapshot_audits=official.audits,
        timezone_boundary_audit=resolver.audit,
        secondary_reference_audit=(secondary.audit if secondary is not None else None),
        index_audit=index.audit,
        official_raw_row_count=official.raw_row_count,
        official_record_count=len(official.records),
        official_rejected_row_count=official.rejected_row_count,
        timezone_input_count=batch.input_count,
        timezone_accepted_count=batch.accepted_count,
        timezone_rejected_count=batch.rejected_count,
        timezone_reason_counts=reasons,
        corpus_digest=corpus_digest,
    )
    return AnacReferenceArtifact(
        schema_version=ANAC_REFERENCE_SCHEMA_VERSION,
        region_code=region,
        official_catalog=official,
        timezone_results=timezone_results,
        secondary_catalog=secondary,
        airport_index=index,
        audit=audit,
        corpus_digest=corpus_digest,
    )


def write_anac_reference_artifact(
    artifact: AnacReferenceArtifact,
    output_path: str | Path,
) -> Path:
    """Atomically write a derived artifact JSON file on the local filesystem."""

    if not isinstance(artifact, AnacReferenceArtifact):
        raise TypeError("artifact must be an AnacReferenceArtifact")
    target = Path(output_path).resolve()
    if target.exists() and target.is_dir():
        raise IsADirectoryError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = artifact.to_json(indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


__all__ = [
    "ANAC_REFERENCE_SCHEMA_VERSION",
    "AirportsdataFileInput",
    "AnacAerodromeTimezoneResult",
    "AnacReferenceArtifact",
    "AnacReferenceAudit",
    "AnacReferenceError",
    "AnacReferenceIntegrityError",
    "AnacReferenceReconciliationError",
    "ArchivedAnacSnapshotInput",
    "TimezoneBoundaryInput",
    "prepare_anac_reference",
    "write_anac_reference_artifact",
]
