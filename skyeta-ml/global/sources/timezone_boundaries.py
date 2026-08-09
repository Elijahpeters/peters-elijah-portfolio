"""Strict, offline coordinate-to-IANA-timezone resolution.

The resolver consumes a Timezone Boundary Builder GeoJSON asset that has
already been cached locally.  It never downloads data and it never guesses a
timezone from longitude, a nearby polygon, or a default value.  The production
source pin identifies the comprehensive, land-only 2026c release asset.

Resolution is deliberately conservative:

* the cached asset must match its pinned filename and SHA-256 digest;
* each GeoJSON timezone identifier must be accepted by :class:`zoneinfo.ZoneInfo`;
* a coordinate must be covered by exactly one timezone polygon; and
* the same polygon must cover a configurable ring around the coordinate
  (1 kilometre at 16 bearings by default).

Shapely is an optional runtime dependency.  Importing this module does not
require it, but loading a valid boundary dataset does.  Shapely 2.x is required
for its immutable geometry objects and indexed candidate queries.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


TIMEZONE_BOUNDARY_SOURCE_ID = "timezone_boundary_builder_land"
TIMEZONE_BOUNDARY_SOURCE_PROVIDER = "Timezone Boundary Builder"
TIMEZONE_BOUNDARY_RELEASE = "2026c"
TIMEZONE_BOUNDARY_COMMIT = "7c04f5c"
TIMEZONE_BOUNDARY_ASSET_NAME = "timezones.geojson.zip"
TIMEZONE_BOUNDARY_EXPECTED_SHA256 = (
    "7d3f0c5a33b6acd891335c0ad5ba767736b6914cb1a1d68c71921c17ce358948"
)
TIMEZONE_BOUNDARY_SOURCE_URL = (
    "https://github.com/evansiroky/timezone-boundary-builder/releases/"
    f"download/{TIMEZONE_BOUNDARY_RELEASE}/{TIMEZONE_BOUNDARY_ASSET_NAME}"
)
TIMEZONE_BOUNDARY_ALGORITHM_VERSION = "skyeta-timezone-boundary-v1"
DEFAULT_GUARD_DISTANCE_KM = 1.0
DEFAULT_GUARD_BEARING_COUNT = 16
EARTH_MEAN_RADIUS_KM = 6371.0088

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RELEASE = re.compile(r"^\d{4}[a-z]$")
_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_JSON_SUFFIXES = frozenset({".json", ".geojson"})


class TimezoneBoundaryError(ValueError):
    """A boundary asset or resolution request cannot be trusted."""


class TimezoneBoundaryDependencyError(TimezoneBoundaryError):
    """The optional geometry dependency is unavailable or incompatible."""


class TimezoneBoundaryIntegrityError(TimezoneBoundaryError):
    """A cached source file does not match its explicit source pin."""


class TimezoneBoundarySchemaError(TimezoneBoundaryError):
    """The pinned bytes are not a valid timezone FeatureCollection."""


@dataclass(frozen=True, slots=True)
class TimezoneBoundarySourcePin:
    """Identity and content digest of one allowed local source asset.

    ``asset_name`` may identify either the official ZIP asset or a separately
    pinned, directly cached GeoJSON file.  SkyETA's production default is the
    official ZIP pin below; alternate pins are intended for deterministic
    tests and independently audited mirrors, not as a checksum bypass.
    """

    release: str
    commit: str
    asset_name: str
    expected_sha256: str
    source_url: str
    source_id: str = TIMEZONE_BOUNDARY_SOURCE_ID
    source_provider: str = TIMEZONE_BOUNDARY_SOURCE_PROVIDER

    def __post_init__(self) -> None:
        release = str(self.release).strip()
        commit = str(self.commit).strip().lower()
        asset_name = str(self.asset_name).strip()
        digest = str(self.expected_sha256).strip().lower()
        source_url = str(self.source_url).strip()
        source_id = str(self.source_id).strip()
        source_provider = str(self.source_provider).strip()

        if not _RELEASE.fullmatch(release):
            raise TimezoneBoundaryIntegrityError(
                "release must use an IANA-style YYYYx identifier"
            )
        if release != TIMEZONE_BOUNDARY_RELEASE:
            raise TimezoneBoundaryIntegrityError(
                f"release must equal the reviewed pin {TIMEZONE_BOUNDARY_RELEASE!r}"
            )
        if not _COMMIT.fullmatch(commit):
            raise TimezoneBoundaryIntegrityError(
                "commit must contain 7 to 40 lowercase hexadecimal characters"
            )
        if commit != TIMEZONE_BOUNDARY_COMMIT:
            raise TimezoneBoundaryIntegrityError(
                f"commit must equal the reviewed pin {TIMEZONE_BOUNDARY_COMMIT!r}"
            )
        if not asset_name or Path(asset_name).name != asset_name:
            raise TimezoneBoundaryIntegrityError(
                "asset_name must be one plain filename"
            )
        if not _SHA256.fullmatch(digest):
            raise TimezoneBoundaryIntegrityError(
                "expected_sha256 must contain exactly 64 hexadecimal characters"
            )
        if not source_url.startswith("https://"):
            raise TimezoneBoundaryIntegrityError("source_url must use HTTPS")
        if not source_id or not source_provider:
            raise TimezoneBoundaryIntegrityError(
                "source_id and source_provider are required"
            )

        object.__setattr__(self, "release", release)
        object.__setattr__(self, "commit", commit)
        object.__setattr__(self, "asset_name", asset_name)
        object.__setattr__(self, "expected_sha256", digest)
        object.__setattr__(self, "source_url", source_url)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "source_provider", source_provider)


DEFAULT_TIMEZONE_BOUNDARY_PIN = TimezoneBoundarySourcePin(
    release=TIMEZONE_BOUNDARY_RELEASE,
    commit=TIMEZONE_BOUNDARY_COMMIT,
    asset_name=TIMEZONE_BOUNDARY_ASSET_NAME,
    expected_sha256=TIMEZONE_BOUNDARY_EXPECTED_SHA256,
    source_url=TIMEZONE_BOUNDARY_SOURCE_URL,
)


def _utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TimezoneBoundaryIntegrityError(
            f"{field_name} must be a timezone-aware datetime"
        )
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class TimezoneBoundaryProvenance:
    """Exact outer file, selected asset entry, and release identity."""

    source_id: str
    source_provider: str
    source_url: str
    release: str
    commit: str
    asset_name: str
    file_path: str
    filename: str
    retrieved_at_utc: datetime
    source_file_sha256: str
    source_file_bytes: int
    container_type: Literal["zip", "geojson"]
    asset_entry_name: str
    asset_entry_sha256: str
    asset_entry_bytes: int

    def __post_init__(self) -> None:
        if self.source_file_bytes <= 0 or self.asset_entry_bytes <= 0:
            raise TimezoneBoundaryIntegrityError(
                "source and asset-entry byte counts must be positive"
            )
        if not _SHA256.fullmatch(self.source_file_sha256):
            raise TimezoneBoundaryIntegrityError("invalid source file SHA-256")
        if not _SHA256.fullmatch(self.asset_entry_sha256):
            raise TimezoneBoundaryIntegrityError("invalid asset-entry SHA-256")
        if self.container_type not in {"zip", "geojson"}:
            raise TimezoneBoundaryIntegrityError("unknown source container type")
        object.__setattr__(
            self, "retrieved_at_utc", _utc(self.retrieved_at_utc, "retrieved_at_utc")
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["retrieved_at_utc"] = _iso_utc(self.retrieved_at_utc)
        return result


@dataclass(frozen=True, slots=True)
class TimezoneBoundaryFeature:
    """Auditable identity of one accepted GeoJSON feature."""

    feature_index: int
    timezone_id: str
    geometry_type: Literal["Polygon", "MultiPolygon"]


@dataclass(frozen=True, slots=True)
class TimezoneBoundaryLoadAudit:
    """Immutable proof that a complete pinned asset loaded without skips."""

    provenance: TimezoneBoundaryProvenance
    algorithm_version: str
    shapely_version: str
    raw_feature_count: int
    accepted_feature_count: int
    rejected_feature_count: int
    unique_timezone_count: int
    default_guard_distance_km: float
    default_guard_bearing_count: int
    completed: bool

    def __post_init__(self) -> None:
        if self.raw_feature_count <= 0:
            raise TimezoneBoundarySchemaError("boundary dataset cannot be empty")
        if self.accepted_feature_count != self.raw_feature_count:
            raise TimezoneBoundarySchemaError(
                "every boundary feature must be accepted or loading must fail"
            )
        if self.rejected_feature_count != 0:
            raise TimezoneBoundarySchemaError(
                "invalid boundary features may not be silently skipped"
            )
        if self.unique_timezone_count != self.accepted_feature_count:
            raise TimezoneBoundarySchemaError(
                "each accepted feature must have one unique timezone identity"
            )
        if not self.completed:
            raise TimezoneBoundarySchemaError("incomplete boundary audit")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["provenance"] = self.provenance.to_dict()
        return result


@dataclass(frozen=True, slots=True)
class TimezoneGuardProbe:
    """One point on the guard ring and every timezone covering it."""

    bearing_degrees: float
    latitude: float
    longitude: float
    candidates: tuple[str, ...]

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["candidate_count"] = self.candidate_count
        return result


ResolutionDisposition = Literal["accepted", "rejected"]
ResolutionReason = Literal[
    "resolved",
    "uncovered",
    "ambiguous",
    "guard_band_uncovered",
    "guard_band_ambiguous",
    "guard_band_crosses_timezone",
]


@dataclass(frozen=True, slots=True)
class TimezoneResolution:
    """Immutable accepted or fail-closed coordinate resolution result."""

    latitude: float
    longitude: float
    timezone_id: str | None
    disposition: ResolutionDisposition
    reason: ResolutionReason
    center_candidates: tuple[str, ...]
    guard_distance_km: float
    guard_bearing_count: int
    guard_probes: tuple[TimezoneGuardProbe, ...]
    algorithm_version: str
    provenance: TimezoneBoundaryProvenance

    def __post_init__(self) -> None:
        accepted = self.disposition == "accepted"
        if accepted != (self.reason == "resolved"):
            raise TimezoneBoundaryError(
                "only a resolved result may have an accepted disposition"
            )
        if accepted:
            if self.timezone_id is None or len(self.center_candidates) != 1:
                raise TimezoneBoundaryError(
                    "accepted result requires one center candidate and timezone_id"
                )
            if self.center_candidates[0] != self.timezone_id:
                raise TimezoneBoundaryError(
                    "accepted timezone_id must equal the center candidate"
                )
            if len(self.guard_probes) != self.guard_bearing_count:
                raise TimezoneBoundaryError(
                    "accepted result requires a complete guard-ring audit"
                )
        elif self.timezone_id is not None:
            raise TimezoneBoundaryError(
                "rejected result may not expose a fallback timezone_id"
            )

    @property
    def center_candidate_count(self) -> int:
        return len(self.center_candidates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "timezone_id": self.timezone_id,
            "disposition": self.disposition,
            "reason": self.reason,
            "center_candidates": list(self.center_candidates),
            "center_candidate_count": self.center_candidate_count,
            "guard_distance_km": self.guard_distance_km,
            "guard_bearing_count": self.guard_bearing_count,
            "guard_probes": [probe.to_dict() for probe in self.guard_probes],
            "algorithm_version": self.algorithm_version,
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class TimezoneResolutionCount:
    disposition: ResolutionDisposition
    reason: ResolutionReason
    count: int


@dataclass(frozen=True, slots=True)
class TimezoneResolutionBatchAudit:
    """Immutable accounting for a batch of independent resolutions."""

    results: tuple[TimezoneResolution, ...]
    counts: tuple[TimezoneResolutionCount, ...]
    input_count: int
    accepted_count: int
    rejected_count: int
    completed: bool

    def __post_init__(self) -> None:
        if self.input_count != len(self.results):
            raise TimezoneBoundaryError("batch input/result count mismatch")
        if self.accepted_count + self.rejected_count != self.input_count:
            raise TimezoneBoundaryError("batch disposition counts do not reconcile")
        if sum(item.count for item in self.counts) != self.input_count:
            raise TimezoneBoundaryError("batch reason counts do not reconcile")
        if not self.completed:
            raise TimezoneBoundaryError("incomplete timezone resolution batch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [result.to_dict() for result in self.results],
            "counts": [asdict(item) for item in self.counts],
            "input_count": self.input_count,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "completed": self.completed,
        }


class _Geometry(Protocol):
    geom_type: str
    is_empty: bool
    is_valid: bool

    def covers(self, other: object) -> bool: ...


class _SpatialIndex(Protocol):
    def query(self, geometry: object) -> Sequence[object]: ...


@dataclass(frozen=True, slots=True)
class _GeometryBackend:
    version: str
    point_factory: Any
    shape_factory: Any
    tree_factory: Any


def _require_geometry_backend() -> _GeometryBackend:
    try:
        import shapely  # type: ignore[import-not-found]
        from shapely.geometry import Point, shape  # type: ignore[import-not-found]
        from shapely.strtree import STRtree  # type: ignore[import-not-found]
    except (ImportError, ModuleNotFoundError) as exc:
        raise TimezoneBoundaryDependencyError(
            "Timezone boundary resolution requires optional dependency "
            "Shapely >=2.0,<3.0; install it in the global-model environment"
        ) from exc

    version = str(getattr(shapely, "__version__", ""))
    match = re.match(r"^(\d+)\.(\d+)", version)
    if match is None or int(match.group(1)) != 2:
        raise TimezoneBoundaryDependencyError(
            f"Timezone boundary resolution requires Shapely >=2.0,<3.0; found {version!r}"
        )
    return _GeometryBackend(
        version=version,
        point_factory=Point,
        shape_factory=shape,
        tree_factory=STRtree,
    )


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe_zip_entry_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} for part in path.parts)
    ):
        raise TimezoneBoundaryIntegrityError(
            f"unsafe ZIP asset entry name: {name!r}"
        )
    return path.as_posix()


def _read_pinned_asset(
    path: Path,
    *,
    pin: TimezoneBoundarySourcePin,
    retrieved_at_utc: datetime,
) -> tuple[bytes, TimezoneBoundaryProvenance]:
    if not path.is_file():
        raise TimezoneBoundaryIntegrityError(
            f"timezone boundary asset is not a file: {path}"
        )
    if path.name != pin.asset_name:
        raise TimezoneBoundaryIntegrityError(
            f"boundary asset filename {path.name!r} does not match pin {pin.asset_name!r}"
        )
    raw = path.read_bytes()
    if not raw:
        raise TimezoneBoundaryIntegrityError("timezone boundary asset is empty")
    digest = _sha256(raw)
    if digest != pin.expected_sha256:
        raise TimezoneBoundaryIntegrityError(
            "timezone boundary SHA-256 mismatch: "
            f"expected {pin.expected_sha256}, got {digest}"
        )

    is_zip = zipfile.is_zipfile(path)
    if is_zip:
        try:
            with zipfile.ZipFile(path, "r") as archive:
                members = [item for item in archive.infolist() if not item.is_dir()]
                if len(members) != 1:
                    raise TimezoneBoundaryIntegrityError(
                        "timezone boundary ZIP must contain exactly one regular asset entry"
                    )
                member = members[0]
                entry_name = _safe_zip_entry_name(member.filename)
                if PurePosixPath(entry_name).suffix.casefold() not in _JSON_SUFFIXES:
                    raise TimezoneBoundaryIntegrityError(
                        "timezone boundary ZIP entry must be .json or .geojson"
                    )
                if member.flag_bits & 0x1:
                    raise TimezoneBoundaryIntegrityError(
                        "encrypted timezone boundary ZIP entries are not allowed"
                    )
                entry_raw = archive.read(member)
        except zipfile.BadZipFile as exc:
            raise TimezoneBoundaryIntegrityError(
                "timezone boundary asset is not a readable ZIP"
            ) from exc
        container_type: Literal["zip", "geojson"] = "zip"
    else:
        if path.suffix.casefold() not in _JSON_SUFFIXES:
            raise TimezoneBoundaryIntegrityError(
                "non-ZIP timezone boundary asset must be .json or .geojson"
            )
        entry_name = path.name
        entry_raw = raw
        container_type = "geojson"

    if not entry_raw:
        raise TimezoneBoundaryIntegrityError("timezone boundary GeoJSON entry is empty")
    provenance = TimezoneBoundaryProvenance(
        source_id=pin.source_id,
        source_provider=pin.source_provider,
        source_url=pin.source_url,
        release=pin.release,
        commit=pin.commit,
        asset_name=pin.asset_name,
        file_path=str(path.resolve()),
        filename=path.name,
        retrieved_at_utc=_utc(retrieved_at_utc, "retrieved_at_utc"),
        source_file_sha256=digest,
        source_file_bytes=len(raw),
        container_type=container_type,
        asset_entry_name=entry_name,
        asset_entry_sha256=_sha256(entry_raw),
        asset_entry_bytes=len(entry_raw),
    )
    return entry_raw, provenance


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def _parse_geojson(raw: bytes) -> Mapping[str, Any]:
    try:
        document = json.loads(
            raw.decode("utf-8-sig"),
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise TimezoneBoundarySchemaError(
            "timezone boundary entry is not valid UTF-8 GeoJSON"
        ) from exc
    if not isinstance(document, Mapping):
        raise TimezoneBoundarySchemaError("GeoJSON root must be an object")
    if document.get("type") != "FeatureCollection":
        raise TimezoneBoundarySchemaError(
            "GeoJSON root type must be FeatureCollection"
        )
    features = document.get("features")
    if not isinstance(features, list) or not features:
        raise TimezoneBoundarySchemaError(
            "GeoJSON FeatureCollection must contain at least one feature"
        )
    return document


def _zoneinfo_timezone_id(value: object, feature_index: int) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise TimezoneBoundarySchemaError(
            f"feature {feature_index} properties.tzid must be a non-empty trimmed string"
        )
    try:
        zone = ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise TimezoneBoundarySchemaError(
            f"feature {feature_index} has unknown IANA timezone identifier {value!r}"
        ) from exc
    if zone.key != value:
        raise TimezoneBoundarySchemaError(
            f"feature {feature_index} timezone identifier was not preserved exactly"
        )
    return value


def _require_zoneinfo_database() -> None:
    """Distinguish a missing IANA database from an invalid feature tzid."""

    try:
        ZoneInfo("Etc/UTC")
    except ZoneInfoNotFoundError as exc:
        raise TimezoneBoundaryDependencyError(
            "IANA ZoneInfo data is unavailable; install the Python tzdata release "
            "matching Timezone Boundary Builder 2026c (tzdata==2026.3 on Windows)"
        ) from exc


def _coordinates(latitude: float, longitude: float) -> tuple[float, float]:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError) as exc:
        raise TimezoneBoundaryError("latitude and longitude must be numeric") from exc
    if not math.isfinite(lat) or not -90.0 <= lat <= 90.0:
        raise TimezoneBoundaryError("latitude must be finite and between -90 and 90")
    if not math.isfinite(lon) or not -180.0 <= lon <= 180.0:
        raise TimezoneBoundaryError("longitude must be finite and between -180 and 180")
    return lat, lon


def _guard_settings(
    distance_km: float,
    bearing_count: int,
) -> tuple[float, int]:
    try:
        distance = float(distance_km)
    except (TypeError, ValueError) as exc:
        raise TimezoneBoundaryError("guard_distance_km must be numeric") from exc
    if not math.isfinite(distance) or distance <= 0.0:
        raise TimezoneBoundaryError("guard_distance_km must be finite and positive")
    if isinstance(bearing_count, bool) or not isinstance(bearing_count, int):
        raise TimezoneBoundaryError("guard_bearing_count must be an integer")
    if bearing_count < 4 or bearing_count > 360:
        raise TimezoneBoundaryError(
            "guard_bearing_count must be between 4 and 360"
        )
    return distance, bearing_count


def _destination_point(
    latitude: float,
    longitude: float,
    bearing_degrees: float,
    distance_km: float,
) -> tuple[float, float]:
    """Return a spherical-Earth destination point in decimal degrees."""

    angular_distance = distance_km / EARTH_MEAN_RADIUS_KM
    bearing = math.radians(bearing_degrees)
    lat1 = math.radians(latitude)
    lon1 = math.radians(longitude)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_distance)
        + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing)
    )
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1),
        math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
    )
    normalized_lon = (math.degrees(lon2) + 540.0) % 360.0 - 180.0
    return math.degrees(lat2), normalized_lon


@dataclass(frozen=True, slots=True)
class TimezoneBoundaryResolver:
    """An immutable catalog plus a Shapely spatial index."""

    features: tuple[TimezoneBoundaryFeature, ...]
    audit: TimezoneBoundaryLoadAudit
    _geometries: tuple[_Geometry, ...]
    _index: _SpatialIndex
    _point_factory: Any

    def _candidates(self, latitude: float, longitude: float) -> tuple[str, ...]:
        point = self._point_factory(longitude, latitude)
        candidate_indices = self._index.query(point)
        timezone_ids: list[str] = []
        for raw_index in candidate_indices:
            try:
                index = int(raw_index)
            except (TypeError, ValueError, OverflowError) as exc:
                raise TimezoneBoundaryDependencyError(
                    "Shapely STRtree returned a non-index result; Shapely 2.x is required"
                ) from exc
            if not 0 <= index < len(self._geometries):
                raise TimezoneBoundaryDependencyError(
                    "Shapely STRtree returned an out-of-range geometry index"
                )
            polygon = self._geometries[index]
            # Explicit polygon.covers(point), rather than contains, deliberately
            # includes exact boundaries so adjoining zones become ambiguous.
            if polygon.covers(point):
                timezone_ids.append(self.features[index].timezone_id)
        return tuple(sorted(set(timezone_ids)))

    def resolve(
        self,
        latitude: float,
        longitude: float,
        *,
        guard_distance_km: float = DEFAULT_GUARD_DISTANCE_KM,
        guard_bearing_count: int = DEFAULT_GUARD_BEARING_COUNT,
    ) -> TimezoneResolution:
        """Resolve one coordinate, returning a rejection instead of a guess."""

        lat, lon = _coordinates(latitude, longitude)
        guard_distance, bearing_count = _guard_settings(
            guard_distance_km, guard_bearing_count
        )
        center = self._candidates(lat, lon)
        if len(center) != 1:
            return TimezoneResolution(
                latitude=lat,
                longitude=lon,
                timezone_id=None,
                disposition="rejected",
                reason="uncovered" if not center else "ambiguous",
                center_candidates=center,
                guard_distance_km=guard_distance,
                guard_bearing_count=bearing_count,
                guard_probes=(),
                algorithm_version=TIMEZONE_BOUNDARY_ALGORITHM_VERSION,
                provenance=self.audit.provenance,
            )

        selected = center[0]
        probes: list[TimezoneGuardProbe] = []
        rejection_reason: ResolutionReason | None = None
        for index in range(bearing_count):
            bearing = index * (360.0 / bearing_count)
            probe_lat, probe_lon = _destination_point(
                lat, lon, bearing, guard_distance
            )
            candidates = self._candidates(probe_lat, probe_lon)
            probes.append(
                TimezoneGuardProbe(
                    bearing_degrees=bearing,
                    latitude=probe_lat,
                    longitude=probe_lon,
                    candidates=candidates,
                )
            )
            if rejection_reason is None and candidates != (selected,):
                if not candidates:
                    rejection_reason = "guard_band_uncovered"
                elif len(candidates) > 1:
                    rejection_reason = "guard_band_ambiguous"
                else:
                    rejection_reason = "guard_band_crosses_timezone"

        accepted = rejection_reason is None
        return TimezoneResolution(
            latitude=lat,
            longitude=lon,
            timezone_id=selected if accepted else None,
            disposition="accepted" if accepted else "rejected",
            reason="resolved" if accepted else rejection_reason,
            center_candidates=center,
            guard_distance_km=guard_distance,
            guard_bearing_count=bearing_count,
            guard_probes=tuple(probes),
            algorithm_version=TIMEZONE_BOUNDARY_ALGORITHM_VERSION,
            provenance=self.audit.provenance,
        )

    def resolve_many(
        self,
        coordinates: Iterable[tuple[float, float]],
        *,
        guard_distance_km: float = DEFAULT_GUARD_DISTANCE_KM,
        guard_bearing_count: int = DEFAULT_GUARD_BEARING_COUNT,
    ) -> TimezoneResolutionBatchAudit:
        results = tuple(
            self.resolve(
                latitude,
                longitude,
                guard_distance_km=guard_distance_km,
                guard_bearing_count=guard_bearing_count,
            )
            for latitude, longitude in coordinates
        )
        reason_counts: dict[tuple[ResolutionDisposition, ResolutionReason], int] = {}
        for result in results:
            key = (result.disposition, result.reason)
            reason_counts[key] = reason_counts.get(key, 0) + 1
        counts = tuple(
            TimezoneResolutionCount(disposition, reason, count)
            for (disposition, reason), count in sorted(reason_counts.items())
        )
        accepted_count = sum(result.disposition == "accepted" for result in results)
        return TimezoneResolutionBatchAudit(
            results=results,
            counts=counts,
            input_count=len(results),
            accepted_count=accepted_count,
            rejected_count=len(results) - accepted_count,
            completed=True,
        )


def load_timezone_boundary_resolver(
    path: str | Path,
    *,
    retrieved_at_utc: datetime,
    pin: TimezoneBoundarySourcePin = DEFAULT_TIMEZONE_BOUNDARY_PIN,
) -> TimezoneBoundaryResolver:
    """Load a complete pinned local asset into a strict spatial resolver.

    No network request is attempted.  Invalid features, duplicate timezone
    identities, bad geometries, missing tzdata, or an incompatible Shapely
    runtime abort the whole load rather than reducing coverage silently.
    """

    source_path = Path(path)
    raw, provenance = _read_pinned_asset(
        source_path,
        pin=pin,
        retrieved_at_utc=retrieved_at_utc,
    )
    document = _parse_geojson(raw)
    _require_zoneinfo_database()
    backend = _require_geometry_backend()
    raw_features = document["features"]

    identities: list[TimezoneBoundaryFeature] = []
    geometries: list[_Geometry] = []
    seen_timezone_ids: dict[str, int] = {}
    for feature_index, feature in enumerate(raw_features):
        if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
            raise TimezoneBoundarySchemaError(
                f"feature {feature_index} must be a GeoJSON Feature object"
            )
        properties = feature.get("properties")
        if not isinstance(properties, Mapping):
            raise TimezoneBoundarySchemaError(
                f"feature {feature_index} properties must be an object"
            )
        timezone_id = _zoneinfo_timezone_id(properties.get("tzid"), feature_index)
        previous = seen_timezone_ids.get(timezone_id)
        if previous is not None:
            raise TimezoneBoundarySchemaError(
                f"timezone identifier {timezone_id!r} is repeated by features "
                f"{previous} and {feature_index}"
            )
        geometry_mapping = feature.get("geometry")
        if not isinstance(geometry_mapping, Mapping):
            raise TimezoneBoundarySchemaError(
                f"feature {feature_index} geometry must be an object"
            )
        declared_type = geometry_mapping.get("type")
        if declared_type not in {"Polygon", "MultiPolygon"}:
            raise TimezoneBoundarySchemaError(
                f"feature {feature_index} must use Polygon or MultiPolygon geometry"
            )
        try:
            geometry = backend.shape_factory(geometry_mapping)
        except Exception as exc:
            raise TimezoneBoundarySchemaError(
                f"feature {feature_index} geometry cannot be constructed"
            ) from exc
        if geometry.geom_type != declared_type:
            raise TimezoneBoundarySchemaError(
                f"feature {feature_index} geometry type changed during construction"
            )
        if geometry.is_empty:
            raise TimezoneBoundarySchemaError(
                f"feature {feature_index} geometry is empty"
            )
        if not geometry.is_valid:
            raise TimezoneBoundarySchemaError(
                f"feature {feature_index} geometry is invalid"
            )

        seen_timezone_ids[timezone_id] = feature_index
        identities.append(
            TimezoneBoundaryFeature(
                feature_index=feature_index,
                timezone_id=timezone_id,
                geometry_type=declared_type,
            )
        )
        geometries.append(geometry)

    try:
        spatial_index = backend.tree_factory(geometries)
    except Exception as exc:
        raise TimezoneBoundaryDependencyError(
            "Shapely could not build the timezone boundary spatial index"
        ) from exc

    audit = TimezoneBoundaryLoadAudit(
        provenance=provenance,
        algorithm_version=TIMEZONE_BOUNDARY_ALGORITHM_VERSION,
        shapely_version=backend.version,
        raw_feature_count=len(raw_features),
        accepted_feature_count=len(identities),
        rejected_feature_count=0,
        unique_timezone_count=len(seen_timezone_ids),
        default_guard_distance_km=DEFAULT_GUARD_DISTANCE_KM,
        default_guard_bearing_count=DEFAULT_GUARD_BEARING_COUNT,
        completed=True,
    )
    return TimezoneBoundaryResolver(
        features=tuple(identities),
        audit=audit,
        _geometries=tuple(geometries),
        _index=spatial_index,
        _point_factory=backend.point_factory,
    )


__all__ = [
    "DEFAULT_GUARD_BEARING_COUNT",
    "DEFAULT_GUARD_DISTANCE_KM",
    "DEFAULT_TIMEZONE_BOUNDARY_PIN",
    "TIMEZONE_BOUNDARY_ALGORITHM_VERSION",
    "TIMEZONE_BOUNDARY_ASSET_NAME",
    "TIMEZONE_BOUNDARY_COMMIT",
    "TIMEZONE_BOUNDARY_EXPECTED_SHA256",
    "TIMEZONE_BOUNDARY_RELEASE",
    "TIMEZONE_BOUNDARY_SOURCE_ID",
    "TIMEZONE_BOUNDARY_SOURCE_PROVIDER",
    "TIMEZONE_BOUNDARY_SOURCE_URL",
    "TimezoneBoundaryDependencyError",
    "TimezoneBoundaryError",
    "TimezoneBoundaryFeature",
    "TimezoneBoundaryIntegrityError",
    "TimezoneBoundaryLoadAudit",
    "TimezoneBoundaryProvenance",
    "TimezoneBoundaryResolver",
    "TimezoneBoundarySchemaError",
    "TimezoneBoundarySourcePin",
    "TimezoneGuardProbe",
    "TimezoneResolution",
    "TimezoneResolutionBatchAudit",
    "TimezoneResolutionCount",
    "load_timezone_boundary_resolver",
]
