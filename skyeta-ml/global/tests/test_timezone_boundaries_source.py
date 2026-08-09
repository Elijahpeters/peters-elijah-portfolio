"""Synthetic checks for strict offline timezone-boundary resolution."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
import zipfile
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfoNotFoundError


MODULE_PATH = Path(__file__).resolve().parents[1] / "sources" / "timezone_boundaries.py"
MODULE_NAME = "skyeta_timezone_boundaries_under_test"
MODULE_SPEC = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:  # pragma: no cover - import guard
    raise RuntimeError(f"Cannot load timezone boundary module from {MODULE_PATH}")
boundaries = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_NAME] = boundaries
MODULE_SPEC.loader.exec_module(boundaries)

RETRIEVED = datetime(2026, 8, 9, 9, 30, tzinfo=timezone(timedelta(hours=1)))
VALID_TZIDS = {"Etc/UTC", "Africa/Lagos", "Europe/London"}


def rectangle(
    timezone_id: str,
    minimum_longitude: float,
    minimum_latitude: float,
    maximum_longitude: float,
    maximum_latitude: float,
) -> dict[str, object]:
    return {
        "type": "Feature",
        "properties": {"tzid": timezone_id},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [minimum_longitude, minimum_latitude],
                    [maximum_longitude, minimum_latitude],
                    [maximum_longitude, maximum_latitude],
                    [minimum_longitude, maximum_latitude],
                    [minimum_longitude, minimum_latitude],
                ]
            ],
        },
    }


def geojson(*features: dict[str, object]) -> bytes:
    return json.dumps(
        {"type": "FeatureCollection", "features": list(features)},
        separators=(",", ":"),
    ).encode("utf-8")


def write_zip(directory: Path, raw: bytes, entry_name: str = "combined.json") -> Path:
    path = directory / "timezones.geojson.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(entry_name, raw)
    return path


def source_pin(path: Path, *, digest: str | None = None):
    return boundaries.TimezoneBoundarySourcePin(
        release="2026c",
        commit="7c04f5c",
        asset_name=path.name,
        expected_sha256=digest or hashlib.sha256(path.read_bytes()).hexdigest(),
        source_url="https://example.test/timezone-boundary-builder/2026c/"
        + path.name,
    )


class _FakePoint:
    def __init__(self, longitude: float, latitude: float) -> None:
        self.x = float(longitude)
        self.y = float(latitude)


class _FakePolygon:
    geom_type = "Polygon"

    def __init__(self, geometry: dict[str, object]) -> None:
        coordinates = geometry["coordinates"]
        ring = coordinates[0]  # type: ignore[index]
        self._points = tuple((float(item[0]), float(item[1])) for item in ring)
        self.is_empty = not self._points
        self.is_valid = (
            len(self._points) >= 4
            and self._points[0] == self._points[-1]
            and len(set(self._points[:-1])) >= 3
        )
        self.minimum_x = min(item[0] for item in self._points)
        self.maximum_x = max(item[0] for item in self._points)
        self.minimum_y = min(item[1] for item in self._points)
        self.maximum_y = max(item[1] for item in self._points)

    @staticmethod
    def _on_segment(
        point: _FakePoint,
        start: tuple[float, float],
        end: tuple[float, float],
    ) -> bool:
        cross = (point.y - start[1]) * (end[0] - start[0]) - (
            point.x - start[0]
        ) * (end[1] - start[1])
        if abs(cross) > 1e-12:
            return False
        return (
            min(start[0], end[0]) - 1e-12
            <= point.x
            <= max(start[0], end[0]) + 1e-12
            and min(start[1], end[1]) - 1e-12
            <= point.y
            <= max(start[1], end[1]) + 1e-12
        )

    def covers(self, point: _FakePoint) -> bool:
        if not (
            self.minimum_x <= point.x <= self.maximum_x
            and self.minimum_y <= point.y <= self.maximum_y
        ):
            return False
        inside = False
        previous = self._points[-1]
        for current in self._points:
            if self._on_segment(point, previous, current):
                return True
            if (current[1] > point.y) != (previous[1] > point.y):
                intersection_x = (
                    (previous[0] - current[0])
                    * (point.y - current[1])
                    / (previous[1] - current[1])
                    + current[0]
                )
                if point.x < intersection_x:
                    inside = not inside
            previous = current
        return inside


class _FakeTree:
    def __init__(self, geometries: list[_FakePolygon]) -> None:
        self._geometries = tuple(geometries)

    def query(self, point: _FakePoint) -> list[int]:
        # A real STRtree returns bounding-box candidates.  This tiny test index
        # does the same so the production code still performs polygon.covers.
        return [
            index
            for index, geometry in enumerate(self._geometries)
            if geometry.minimum_x <= point.x <= geometry.maximum_x
            and geometry.minimum_y <= point.y <= geometry.maximum_y
        ]


def _fake_shape(geometry: dict[str, object]) -> _FakePolygon:
    if geometry.get("type") != "Polygon":
        raise ValueError("synthetic backend only supports Polygon")
    return _FakePolygon(geometry)


FAKE_BACKEND = boundaries._GeometryBackend(
    version="2.1.0-test",
    point_factory=_FakePoint,
    shape_factory=_fake_shape,
    tree_factory=_FakeTree,
)


def _fake_zoneinfo(value: str):
    if value not in VALID_TZIDS:
        raise ZoneInfoNotFoundError(value)
    return SimpleNamespace(key=value)


def load(path: Path):
    with mock.patch.object(
        boundaries, "_require_zoneinfo_database", return_value=None
    ), mock.patch.object(
        boundaries, "_require_geometry_backend", return_value=FAKE_BACKEND
    ), mock.patch.object(boundaries, "ZoneInfo", side_effect=_fake_zoneinfo):
        return boundaries.load_timezone_boundary_resolver(
            path,
            retrieved_at_utc=RETRIEVED,
            pin=source_pin(path),
        )


class TimezoneBoundarySourceTests(unittest.TestCase):
    def temporary_directory(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return temporary, Path(temporary.name)

    def test_production_source_pin_is_exact(self) -> None:
        pin = boundaries.DEFAULT_TIMEZONE_BOUNDARY_PIN
        self.assertEqual(pin.release, "2026c")
        self.assertEqual(pin.commit, "7c04f5c")
        self.assertEqual(pin.asset_name, "timezones.geojson.zip")
        self.assertEqual(
            pin.expected_sha256,
            "7d3f0c5a33b6acd891335c0ad5ba767736b6914cb1a1d68c71921c17ce358948",
        )

    def test_zip_success_preserves_source_and_resolution_audit(self) -> None:
        _, directory = self.temporary_directory()
        raw = geojson(rectangle("Etc/UTC", -1.0, -1.0, 1.0, 1.0))
        path = write_zip(directory, raw)
        resolver = load(path)
        result = resolver.resolve(0.0, 0.0)

        self.assertEqual(result.disposition, "accepted")
        self.assertEqual(result.reason, "resolved")
        self.assertEqual(result.timezone_id, "Etc/UTC")
        self.assertEqual(result.center_candidates, ("Etc/UTC",))
        self.assertEqual(result.center_candidate_count, 1)
        self.assertEqual(len(result.guard_probes), 16)
        self.assertTrue(
            all(probe.candidates == ("Etc/UTC",) for probe in result.guard_probes)
        )

        audit = resolver.audit
        self.assertTrue(audit.completed)
        self.assertEqual(audit.shapely_version, "2.1.0-test")
        self.assertEqual(audit.raw_feature_count, 1)
        self.assertEqual(audit.accepted_feature_count, 1)
        self.assertEqual(audit.rejected_feature_count, 0)
        self.assertEqual(audit.unique_timezone_count, 1)
        provenance = audit.provenance
        outer = path.read_bytes()
        self.assertEqual(provenance.release, "2026c")
        self.assertEqual(provenance.commit, "7c04f5c")
        self.assertEqual(provenance.asset_entry_name, "combined.json")
        self.assertEqual(provenance.source_file_sha256, hashlib.sha256(outer).hexdigest())
        self.assertEqual(provenance.source_file_bytes, len(outer))
        self.assertEqual(provenance.asset_entry_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(provenance.asset_entry_bytes, len(raw))
        self.assertEqual(
            provenance.retrieved_at_utc,
            datetime(2026, 8, 9, 8, 30, tzinfo=timezone.utc),
        )
        exported = result.to_dict()
        self.assertEqual(exported["center_candidate_count"], 1)
        self.assertEqual(
            exported["provenance"]["retrieved_at_utc"], "2026-08-09T08:30:00Z"
        )
        with self.assertRaises(FrozenInstanceError):
            result.reason = "uncovered"  # type: ignore[misc]

    def test_direct_geojson_is_supported_when_independently_pinned(self) -> None:
        _, directory = self.temporary_directory()
        path = directory / "timezones.geojson"
        raw = geojson(rectangle("Africa/Lagos", 2.0, 3.0, 9.0, 14.0))
        path.write_bytes(raw)
        resolver = load(path)

        result = resolver.resolve(6.5, 3.4)
        self.assertEqual(result.timezone_id, "Africa/Lagos")
        self.assertEqual(resolver.audit.provenance.container_type, "geojson")
        self.assertEqual(resolver.audit.provenance.asset_entry_name, path.name)
        self.assertEqual(
            resolver.audit.provenance.source_file_sha256,
            hashlib.sha256(raw).hexdigest(),
        )
        self.assertEqual(
            resolver.audit.provenance.asset_entry_sha256,
            hashlib.sha256(raw).hexdigest(),
        )

    def test_ambiguous_and_uncovered_coordinates_fail_closed(self) -> None:
        _, directory = self.temporary_directory()
        path = write_zip(
            directory,
            geojson(
                rectangle("Etc/UTC", -1.0, -1.0, 1.0, 1.0),
                rectangle("Africa/Lagos", -0.5, -0.5, 1.5, 1.5),
            ),
        )
        resolver = load(path)

        ambiguous = resolver.resolve(0.0, 0.0)
        self.assertEqual(ambiguous.disposition, "rejected")
        self.assertEqual(ambiguous.reason, "ambiguous")
        self.assertIsNone(ambiguous.timezone_id)
        self.assertEqual(
            ambiguous.center_candidates, ("Africa/Lagos", "Etc/UTC")
        )
        self.assertEqual(ambiguous.center_candidate_count, 2)
        self.assertEqual(ambiguous.guard_probes, ())

        uncovered = resolver.resolve(20.0, 20.0)
        self.assertEqual(uncovered.disposition, "rejected")
        self.assertEqual(uncovered.reason, "uncovered")
        self.assertIsNone(uncovered.timezone_id)
        self.assertEqual(uncovered.center_candidate_count, 0)

    def test_guard_ring_rejects_coordinate_too_close_to_boundary(self) -> None:
        _, directory = self.temporary_directory()
        # Roughly 0.44 km from the centre to every edge at the equator, so the
        # default 1 km guard ring necessarily leaves the covered polygon.
        path = write_zip(
            directory,
            geojson(rectangle("Etc/UTC", -0.004, -0.004, 0.004, 0.004)),
        )
        resolver = load(path)

        result = resolver.resolve(0.0, 0.0)
        self.assertEqual(result.disposition, "rejected")
        self.assertEqual(result.reason, "guard_band_uncovered")
        self.assertIsNone(result.timezone_id)
        self.assertEqual(result.center_candidates, ("Etc/UTC",))
        self.assertEqual(len(result.guard_probes), 16)
        self.assertTrue(any(probe.candidate_count == 0 for probe in result.guard_probes))

    def test_batch_audit_reconciles_every_disposition(self) -> None:
        _, directory = self.temporary_directory()
        path = write_zip(
            directory,
            geojson(rectangle("Etc/UTC", -1.0, -1.0, 1.0, 1.0)),
        )
        resolver = load(path)

        batch = resolver.resolve_many(((0.0, 0.0), (20.0, 20.0)))
        self.assertTrue(batch.completed)
        self.assertEqual(batch.input_count, 2)
        self.assertEqual(batch.accepted_count, 1)
        self.assertEqual(batch.rejected_count, 1)
        self.assertEqual(sum(item.count for item in batch.counts), 2)

    def test_bad_checksum_is_rejected_before_parsing(self) -> None:
        _, directory = self.temporary_directory()
        path = write_zip(
            directory,
            geojson(rectangle("Etc/UTC", -1.0, -1.0, 1.0, 1.0)),
        )
        bad_pin = source_pin(path, digest="0" * 64)

        with self.assertRaisesRegex(
            boundaries.TimezoneBoundaryIntegrityError, "SHA-256 mismatch"
        ):
            boundaries.load_timezone_boundary_resolver(
                path, retrieved_at_utc=RETRIEVED, pin=bad_pin
            )

    def test_bad_or_ambiguous_zip_entry_is_rejected(self) -> None:
        _, directory = self.temporary_directory()
        bad_path = write_zip(directory, b"not GeoJSON", entry_name="README.txt")
        with self.assertRaisesRegex(
            boundaries.TimezoneBoundaryIntegrityError, "must be .json or .geojson"
        ):
            boundaries.load_timezone_boundary_resolver(
                bad_path,
                retrieved_at_utc=RETRIEVED,
                pin=source_pin(bad_path),
            )

        ambiguous_path = directory / "ambiguous.geojson.zip"
        with zipfile.ZipFile(ambiguous_path, "w") as archive:
            archive.writestr("one.json", geojson(rectangle("Etc/UTC", -1, -1, 1, 1)))
            archive.writestr(
                "two.json", geojson(rectangle("Africa/Lagos", 2, 2, 3, 3))
            )
        with self.assertRaisesRegex(
            boundaries.TimezoneBoundaryIntegrityError, "exactly one regular"
        ):
            boundaries.load_timezone_boundary_resolver(
                ambiguous_path,
                retrieved_at_utc=RETRIEVED,
                pin=source_pin(ambiguous_path),
            )

    def test_unknown_timezone_identifier_aborts_the_whole_load(self) -> None:
        _, directory = self.temporary_directory()
        path = write_zip(
            directory,
            geojson(rectangle("Mars/Olympus_Mons", -1.0, -1.0, 1.0, 1.0)),
        )
        with mock.patch.object(
            boundaries, "_require_zoneinfo_database", return_value=None
        ), mock.patch.object(
            boundaries, "_require_geometry_backend", return_value=FAKE_BACKEND
        ), mock.patch.object(boundaries, "ZoneInfo", side_effect=_fake_zoneinfo):
            with self.assertRaisesRegex(
                boundaries.TimezoneBoundarySchemaError, "unknown IANA timezone"
            ):
                boundaries.load_timezone_boundary_resolver(
                    path,
                    retrieved_at_utc=RETRIEVED,
                    pin=source_pin(path),
                )

    def test_missing_runtime_dependencies_fail_clearly(self) -> None:
        with mock.patch.object(
            boundaries, "ZoneInfo", side_effect=ZoneInfoNotFoundError("Etc/UTC")
        ):
            with self.assertRaisesRegex(
                boundaries.TimezoneBoundaryDependencyError, "tzdata==2026.3"
            ):
                boundaries._require_zoneinfo_database()

        with mock.patch.dict(sys.modules, {"shapely": None}):
            with self.assertRaisesRegex(
                boundaries.TimezoneBoundaryDependencyError, "Shapely >=2.0,<3.0"
            ):
                boundaries._require_geometry_backend()


if __name__ == "__main__":
    unittest.main()
