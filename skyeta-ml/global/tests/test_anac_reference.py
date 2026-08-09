"""End-to-end synthetic checks for offline ANAC reference preparation."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
with mock.patch("zoneinfo.ZoneInfo", return_value=object()):
    reference = importlib.import_module("global.anac_reference")
    airports = importlib.import_module("global.sources.airports")
    airport_index = importlib.import_module("global.sources.anac_airport_index")
    aerodromes = importlib.import_module("global.sources.anac_aerodromes")
    boundaries = importlib.import_module("global.sources.timezone_boundaries")


PUBLIC_CAPTURE = datetime(2025, 4, 18, 15, 32, 53, tzinfo=timezone.utc)
PRIVATE_CAPTURE = datetime(2024, 11, 2, 1, 44, 36, tzinfo=timezone.utc)
BOUNDARY_RETRIEVED = datetime(2026, 8, 9, 8, 30, tzinfo=timezone.utc)
AIRPORTS_RETRIEVED = datetime(2026, 8, 9, 9, 0, tzinfo=timezone.utc)


def memento(source_url: str, captured: datetime) -> str:
    stamp = captured.strftime("%Y%m%d%H%M%S")
    return f"https://web.archive.org/web/{stamp}id_/{source_url}"


def snapshot_bytes(updated: str, *rows: str) -> bytes:
    header = (
        "Código OACI;CIAD;Nome;Município;UF;LATGEOPOINT;LONGEOPOINT\r\n"
    )
    return (f"Atualizado em: {updated}\r\n{header}" + "".join(rows)).encode(
        "cp1252"
    )


def row(
    icao: str,
    ciad: str,
    name: str,
    latitude: float,
    longitude: float,
) -> str:
    return (
        f"{icao};{ciad};{name};Test city;SP;{latitude};{longitude}\r\n"
    )


class FakeResolver:
    def __init__(self, path: Path) -> None:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        provenance = boundaries.TimezoneBoundaryProvenance(
            source_id="timezone_boundary_builder_land",
            source_provider="Timezone Boundary Builder",
            source_url="https://example.test/timezones.geojson",
            release="2026c",
            commit="7c04f5c",
            asset_name=path.name,
            file_path=str(path.resolve()),
            filename=path.name,
            retrieved_at_utc=BOUNDARY_RETRIEVED,
            source_file_sha256=digest,
            source_file_bytes=path.stat().st_size,
            container_type="geojson",
            asset_entry_name=path.name,
            asset_entry_sha256=digest,
            asset_entry_bytes=path.stat().st_size,
        )
        self.audit = boundaries.TimezoneBoundaryLoadAudit(
            provenance=provenance,
            algorithm_version="skyeta-timezone-boundary-v1",
            shapely_version="2.1.0-test",
            raw_feature_count=1,
            accepted_feature_count=1,
            rejected_feature_count=0,
            unique_timezone_count=1,
            default_guard_distance_km=1.0,
            default_guard_bearing_count=16,
            completed=True,
        )

    def resolve_many(
        self,
        coordinates,
        *,
        guard_distance_km: float,
        guard_bearing_count: int,
    ):
        results = []
        for latitude, longitude in tuple(coordinates):
            rejected = longitude == -41.0
            probes = (
                ()
                if rejected
                else tuple(
                    boundaries.TimezoneGuardProbe(
                        bearing_degrees=index * (360 / guard_bearing_count),
                        latitude=latitude,
                        longitude=longitude,
                        candidates=("Etc/UTC",),
                    )
                    for index in range(guard_bearing_count)
                )
            )
            results.append(
                boundaries.TimezoneResolution(
                    latitude=latitude,
                    longitude=longitude,
                    timezone_id=None if rejected else "Etc/UTC",
                    disposition="rejected" if rejected else "accepted",
                    reason="uncovered" if rejected else "resolved",
                    center_candidates=() if rejected else ("Etc/UTC",),
                    guard_distance_km=guard_distance_km,
                    guard_bearing_count=guard_bearing_count,
                    guard_probes=probes,
                    algorithm_version="skyeta-timezone-boundary-v1",
                    provenance=self.audit.provenance,
                )
            )
        counts_by_key = {}
        for result in results:
            key = (result.disposition, result.reason)
            counts_by_key[key] = counts_by_key.get(key, 0) + 1
        counts = tuple(
            boundaries.TimezoneResolutionCount(disposition, reason, count)
            for (disposition, reason), count in sorted(counts_by_key.items())
        )
        accepted = sum(item.disposition == "accepted" for item in results)
        return boundaries.TimezoneResolutionBatchAudit(
            results=tuple(results),
            counts=counts,
            input_count=len(results),
            accepted_count=accepted,
            rejected_count=len(results) - accepted,
            completed=True,
        )


class TruncatedResolver(FakeResolver):
    def resolve_many(self, coordinates, **kwargs):
        batch = super().resolve_many(coordinates, **kwargs)
        return boundaries.TimezoneResolutionBatchAudit(
            results=batch.results[:-1],
            counts=batch.counts[:-1],
            input_count=len(batch.results) - 1,
            accepted_count=max(0, batch.accepted_count - 1),
            rejected_count=batch.rejected_count,
            completed=True,
        )


class AnacReferencePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

        self.public_path = self.directory / "anac-aerodromes-public-20250418.csv"
        self.public_data = snapshot_bytes(
            "2025-04-15",
            row("SAAA", "SP0001", "Accepted public", -10.0, -40.0),
            row("SBBB", "SP0002", "Boundary public", -10.0, -41.0),
        )
        self.public_path.write_bytes(self.public_data)
        self.private_path = self.directory / "anac-aerodromes-private-20241102.csv"
        self.private_data = snapshot_bytes(
            "2024-11-01",
            row("SJCC", "SP0003", "Accepted private", -11.0, -42.0),
        )
        self.private_path.write_bytes(self.private_data)

        self.boundary_path = self.directory / "timezones.geojson"
        self.boundary_path.write_text("{}", encoding="utf-8")
        boundary_digest = hashlib.sha256(self.boundary_path.read_bytes()).hexdigest()
        self.boundary_pin = boundaries.TimezoneBoundarySourcePin(
            release="2026c",
            commit="7c04f5c",
            asset_name=self.boundary_path.name,
            expected_sha256=boundary_digest,
            source_url="https://example.test/timezones.geojson",
        )

        self.airports_path = self.directory / "airports.csv"
        self.airports_data = (
            "icao,iata,lat,lon,country,tz,subd\n"
            "SAAA,AAA,-10,-40,BR,Etc/UTC,SP\n"
            "SBBB,BBB,-10,-41,BR,Etc/UTC,SP\n"
            "SJCC,CCC,-11,-42,BR,Etc/UTC,SP\n"
        ).encode("utf-8")
        self.airports_path.write_bytes(self.airports_data)

    def inputs(self, *, public_digest: str | None = None):
        public = reference.ArchivedAnacSnapshotInput(
            path=self.public_path,
            source_url=aerodromes.ANAC_PUBLIC_AERODROMES_SOURCE_URL,
            archive_url=memento(
                aerodromes.ANAC_PUBLIC_AERODROMES_SOURCE_URL, PUBLIC_CAPTURE
            ),
            archived_at_utc=PUBLIC_CAPTURE,
            expected_sha256=public_digest
            or hashlib.sha256(self.public_data).hexdigest(),
        )
        private = reference.ArchivedAnacSnapshotInput(
            path=self.private_path,
            source_url=aerodromes.ANAC_PRIVATE_AERODROMES_SOURCE_URL,
            archive_url=memento(
                aerodromes.ANAC_PRIVATE_AERODROMES_SOURCE_URL, PRIVATE_CAPTURE
            ),
            archived_at_utc=PRIVATE_CAPTURE,
            expected_sha256=hashlib.sha256(self.private_data).hexdigest(),
        )
        timezone_input = reference.TimezoneBoundaryInput(
            path=self.boundary_path,
            retrieved_at_utc=BOUNDARY_RETRIEVED,
            pin=self.boundary_pin,
        )
        secondary = reference.AirportsdataFileInput(
            path=self.airports_path,
            retrieved_at_utc=AIRPORTS_RETRIEVED,
            expected_sha256=hashlib.sha256(self.airports_data).hexdigest(),
        )
        return public, private, timezone_input, secondary

    def prepare(self, resolver=None):
        public, private, timezone_input, secondary = self.inputs()
        resolver = resolver or FakeResolver(self.boundary_path)
        with mock.patch.object(
            reference, "load_timezone_boundary_resolver", return_value=resolver
        ) as loader, mock.patch.object(
            airports, "ZoneInfo", return_value=object()
        ), mock.patch.object(
            airport_index, "ZoneInfo", return_value=object()
        ):
            artifact = reference.prepare_anac_reference(
                public_snapshot=public,
                private_snapshot=private,
                timezone_boundaries=timezone_input,
                region_code="South America",
                airportsdata=secondary,
            )
        loader.assert_called_once_with(
            str(self.boundary_path.resolve()),
            retrieved_at_utc=BOUNDARY_RETRIEVED,
            pin=self.boundary_pin,
        )
        return artifact

    def test_prepares_complete_audit_and_excludes_rejected_timezone(self):
        artifact = self.prepare()

        self.assertEqual(artifact.audit.official_record_count, 3)
        self.assertEqual(artifact.audit.timezone_accepted_count, 2)
        self.assertEqual(artifact.audit.timezone_rejected_count, 1)
        self.assertEqual(artifact.audit.timezone_reason_counts["uncovered"], 1)
        self.assertEqual(set(artifact.airport_index), {"SAAA", "SJCC"})
        rejected = next(item for item in artifact.timezone_results if item.icao == "SBBB")
        self.assertEqual(rejected.resolution.disposition, "rejected")
        self.assertEqual(rejected.resolution.reason, "uncovered")
        merge_entry = next(
            item for item in artifact.airport_index.entries if item.icao == "SBBB"
        )
        self.assertEqual(merge_entry.disposition, "excluded_missing_timezone")
        self.assertIsNone(merge_entry.metadata)
        self.assertEqual(artifact.airport_index["SAAA"].iata, "AAA")

        exported = artifact.to_dict()
        self.assertEqual(
            exported["sources"]["official_snapshots"][0]["provenance"][
                "raw_file_sha256"
            ],
            hashlib.sha256(self.public_data).hexdigest(),
        )
        self.assertEqual(
            exported["sources"]["timezone_boundaries"]["provenance"][
                "source_file_sha256"
            ],
            hashlib.sha256(self.boundary_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            exported["sources"]["secondary_airportsdata"]["provenance"][
                "raw_file_sha256"
            ],
            hashlib.sha256(self.airports_data).hexdigest(),
        )

    def test_digest_is_deterministic_and_atomic_json_is_replaced(self):
        first = self.prepare()
        second = self.prepare()
        self.assertEqual(first.corpus_digest, second.corpus_digest)

        target = self.directory / "derived" / "anac-reference.json"
        target.parent.mkdir()
        target.write_text("old partial data", encoding="utf-8")
        written = reference.write_anac_reference_artifact(first, target)
        self.assertEqual(written, target.resolve())
        document = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(document["corpus_digest"], first.corpus_digest)
        self.assertEqual(document["audit"]["timezone_input_count"], 3)
        self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])

    def test_rejects_tampered_snapshot_before_combining_sources(self):
        public, private, timezone_input, _ = self.inputs(public_digest="0" * 64)
        with self.assertRaisesRegex(
            reference.AnacReferenceIntegrityError,
            "public ANAC snapshot SHA-256 mismatch",
        ):
            reference.prepare_anac_reference(
                public_snapshot=public,
                private_snapshot=private,
                timezone_boundaries=timezone_input,
                region_code="South America",
            )

    def test_rejects_duplicate_ciad_across_official_catalogues(self):
        self.private_data = snapshot_bytes(
            "2024-11-01",
            row("SJCC", "SP0001", "Duplicate CIAD", -11.0, -42.0),
        )
        self.private_path.write_bytes(self.private_data)
        public, private, timezone_input, _ = self.inputs()
        with self.assertRaisesRegex(
            reference.AnacReferenceReconciliationError, "duplicate official CIAD"
        ):
            reference.prepare_anac_reference(
                public_snapshot=public,
                private_snapshot=private,
                timezone_boundaries=timezone_input,
                region_code="South America",
            )

    def test_rejects_timezone_result_reconciliation_gap(self):
        public, private, timezone_input, _ = self.inputs()
        resolver = TruncatedResolver(self.boundary_path)
        with mock.patch.object(
            reference, "load_timezone_boundary_resolver", return_value=resolver
        ):
            with self.assertRaisesRegex(
                reference.AnacReferenceReconciliationError,
                "one result per aerodrome",
            ):
                reference.prepare_anac_reference(
                    public_snapshot=public,
                    private_snapshot=private,
                    timezone_boundaries=timezone_input,
                    region_code="South America",
                )


if __name__ == "__main__":
    unittest.main()
