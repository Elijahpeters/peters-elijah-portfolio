"""Synthetic tests for archived ANAC public/private aerodrome snapshots."""

from __future__ import annotations

import hashlib
import importlib
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
aerodromes = importlib.import_module("global.sources.anac_aerodromes")


PUBLIC_CAPTURE = datetime(2025, 4, 18, 15, 32, 53, tzinfo=timezone.utc)
PRIVATE_CAPTURE = datetime(2024, 11, 2, 1, 44, 36, tzinfo=timezone.utc)

HEADER = (
    "Código OACI;CIAD;Nome;Município;UF;LATGEOPOINT;LONGEOPOINT\r\n"
)


def archive_url(source_url: str, captured: datetime, *, raw: bool = True) -> str:
    timestamp = captured.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")
    modifier = "id_" if raw else ""
    return f"https://web.archive.org/web/{timestamp}{modifier}/{source_url}"


def fixture(
    *rows: str,
    updated_on: str = "2025-04-15",
) -> bytes:
    content = f"Atualizado em: {updated_on}\r\n{HEADER}" + "".join(rows)
    return content.encode("cp1252")


def row(
    icao: str = "SBGL",
    ciad: str = "RJ0001",
    name: str = "Galeão - Antônio Carlos Jobim",
    municipality: str = "Rio de Janeiro",
    state: str = "Rio de Janeiro",
    latitude: str = "-22.8099",
    longitude: str = "-43.2506",
) -> str:
    return ";".join(
        (icao, ciad, name, municipality, state, latitude, longitude)
    ) + "\r\n"


class AnacAerodromeLoaderTests(unittest.TestCase):
    def _load(
        self,
        directory: str,
        data: bytes,
        *,
        aerodrome_type: str = "public",
        captured: datetime = PUBLIC_CAPTURE,
        source_url: str | None = None,
        memento_url: str | None = None,
        filename: str | None = None,
    ):
        source = source_url or aerodromes.ANAC_AERODROME_SOURCE_URLS[
            aerodrome_type
        ]
        name = filename or (
            f"anac-aerodromes-{aerodrome_type}-"
            f"{captured.strftime('%Y%m%d')}.csv"
        )
        path = Path(directory) / name
        path.write_bytes(data)
        return aerodromes.load_anac_aerodrome_snapshot(
            path,
            source_url=source,
            archive_url=memento_url or archive_url(source, captured),
            archived_at_utc=captured,
        )

    def test_loads_source_backed_fields_and_byte_provenance(self) -> None:
        data = fixture(
            row(
                icao=" sbgl ",
                ciad=" rj0001 ",
                name="Galeão   - Antônio Carlos Jobim",
                state="Rio  de Janeiro",
                latitude="-22,8099",
                longitude="-43,2506",
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            catalog = self._load(directory, data)
            file_path = str(
                (Path(directory) / "anac-aerodromes-public-20250418.csv").resolve()
            )

        self.assertEqual(len(catalog), 1)
        record = catalog.by_icao["SBGL"]
        self.assertEqual(record.icao, "SBGL")
        self.assertEqual(record.ciad, "RJ0001")
        self.assertEqual(record.name, "Galeão - Antônio Carlos Jobim")
        self.assertEqual(record.state, "Rio de Janeiro")
        self.assertAlmostEqual(record.latitude_wgs84, -22.8099)
        self.assertAlmostEqual(record.longitude_wgs84, -43.2506)
        self.assertEqual(record.aerodrome_type, "public")
        self.assertEqual(record.snapshot_updated_on, date(2025, 4, 15))
        self.assertFalse(hasattr(record, "iata"))
        self.assertFalse(hasattr(record, "timezone"))
        self.assertFalse(hasattr(record, "timezone_name"))

        audit = catalog.audits[0]
        provenance = audit.provenance
        self.assertEqual(provenance.file_path, file_path)
        self.assertEqual(provenance.raw_file_sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(provenance.raw_bytes, len(data))
        self.assertEqual(provenance.archived_at_utc, PUBLIC_CAPTURE)
        self.assertEqual(provenance.snapshot_updated_on, date(2025, 4, 15))
        self.assertEqual(provenance.source_url, aerodromes.ANAC_PUBLIC_AERODROMES_SOURCE_URL)
        self.assertEqual(provenance.archive_url, archive_url(provenance.source_url, PUBLIC_CAPTURE))
        self.assertEqual(audit.normalized_headers[:3], ("codigo_oaci", "ciad", "nome"))
        self.assertEqual(audit.raw_row_count, 1)
        self.assertEqual(audit.accepted_row_count, 1)
        self.assertEqual(audit.rejected_row_count, 0)
        self.assertEqual(audit.row_audit[0].row_number, 3)
        self.assertEqual(audit.row_audit[0].disposition, "accepted")

    def test_catalog_records_and_icao_index_are_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = self._load(directory, fixture(row()))
        with self.assertRaises(TypeError):
            catalog.by_icao["SBBR"] = catalog.records[0]
        with self.assertRaises(FrozenInstanceError):
            catalog.records[0].name = "Changed"

    def test_invalid_rows_are_fully_rejected_and_audited(self) -> None:
        data = fixture(
            row(),
            row(icao="", ciad="SP0099", name="No ICAO"),
            row(icao="SBAA", ciad="bad", name="Bad CIAD"),
            row(icao="SBBB", ciad="SP0100", state=""),
        )
        with tempfile.TemporaryDirectory() as directory:
            catalog = self._load(directory, data)

        audit = catalog.audits[0]
        self.assertEqual(catalog.raw_row_count, 4)
        self.assertEqual(catalog.accepted_row_count, 1)
        self.assertEqual(catalog.rejected_row_count, 3)
        self.assertEqual(
            [item.disposition for item in audit.row_audit],
            ["accepted", "rejected", "rejected", "rejected"],
        )
        self.assertEqual([item.row_number for item in audit.rejected_rows], [4, 5, 6])
        self.assertIn("ICAO", audit.rejected_rows[0].reason)
        self.assertIn("CIAD", audit.rejected_rows[1].reason)
        self.assertIn("state", audit.rejected_rows[2].reason)
        self.assertTrue(audit.completed)

    def test_private_snapshot_and_plain_wayback_replay_are_supported(self) -> None:
        data = fixture(
            row(icao="SJ4S", ciad="PR0191", name="Fazenda Candoara", state="PR"),
            updated_on="2024-11-01",
        )
        source = aerodromes.ANAC_PRIVATE_AERODROMES_SOURCE_URL
        with tempfile.TemporaryDirectory() as directory:
            catalog = self._load(
                directory,
                data,
                aerodrome_type="private",
                captured=PRIVATE_CAPTURE,
                memento_url=archive_url(source, PRIVATE_CAPTURE, raw=False),
            )
        record = catalog.by_icao["SJ4S"]
        self.assertEqual(record.aerodrome_type, "private")
        self.assertEqual(record.snapshot_updated_on, date(2024, 11, 1))

    def test_filename_source_and_archive_identity_fail_closed(self) -> None:
        data = fixture(row())
        source = aerodromes.ANAC_PUBLIC_AERODROMES_SOURCE_URL
        with tempfile.TemporaryDirectory() as directory:
            good = Path(directory) / "anac-aerodromes-public-20250418.csv"
            good.write_bytes(data)
            cases = (
                {
                    "file_path": Path(directory) / "AerodromosPublicos.csv",
                    "source_url": source,
                    "archive_url": archive_url(source, PUBLIC_CAPTURE),
                    "archived_at_utc": PUBLIC_CAPTURE,
                    "message": "filename",
                },
                {
                    "file_path": good,
                    "source_url": aerodromes.ANAC_PRIVATE_AERODROMES_SOURCE_URL,
                    "archive_url": archive_url(source, PUBLIC_CAPTURE),
                    "archived_at_utc": PUBLIC_CAPTURE,
                    "message": "canonical ANAC public",
                },
                {
                    "file_path": good,
                    "source_url": source,
                    "archive_url": archive_url(source, PUBLIC_CAPTURE),
                    "archived_at_utc": datetime(2025, 4, 18, 15, 32, 53),
                    "message": "aware datetime",
                },
                {
                    "file_path": good,
                    "source_url": source,
                    "archive_url": archive_url(source, PUBLIC_CAPTURE),
                    "archived_at_utc": datetime(2025, 4, 19, tzinfo=timezone.utc),
                    "message": "filename archive date",
                },
                {
                    "file_path": good,
                    "source_url": source,
                    "archive_url": archive_url(source, PRIVATE_CAPTURE),
                    "archived_at_utc": PUBLIC_CAPTURE,
                    "message": "timestamp",
                },
                {
                    "file_path": good,
                    "source_url": source,
                    "archive_url": archive_url(
                        aerodromes.ANAC_PRIVATE_AERODROMES_SOURCE_URL,
                        PUBLIC_CAPTURE,
                    ),
                    "archived_at_utc": PUBLIC_CAPTURE,
                    "message": "does not target",
                },
            )
            # The bad-name file must exist so filename validation, rather than
            # the ordinary missing-file check, is what fails.
            cases[0]["file_path"].write_bytes(data)
            for case in cases:
                message = case.pop("message")
                with self.subTest(message=message):
                    with self.assertRaisesRegex(
                        aerodromes.AnacAerodromeSourceError, message
                    ):
                        aerodromes.load_anac_aerodrome_snapshot(**case)

    def test_update_line_and_normalized_headers_are_strict(self) -> None:
        missing_column = (
            "Atualizado em: 2025-04-15\r\n"
            "Código OACI;CIAD;Nome;UF;LATGEOPOINT\r\n"
            "SBGL;RJ0001;Galeão;RJ;-22.8099\r\n"
        ).encode("cp1252")
        future_update = fixture(row(), updated_on="2025-04-19")
        bad_first_line = fixture(row()).replace(
            b"Atualizado em:", b"Updated:", 1
        )
        with tempfile.TemporaryDirectory() as directory:
            for index, (data, message) in enumerate(
                (
                    (missing_column, "missing required columns"),
                    (future_update, "later than"),
                    (bad_first_line, "first line"),
                )
            ):
                captured = PUBLIC_CAPTURE
                path = Path(directory) / (
                    f"case-{index}/anac-aerodromes-public-20250418.csv"
                )
                path.parent.mkdir()
                path.write_bytes(data)
                with self.subTest(message=message):
                    with self.assertRaisesRegex(aerodromes.AnacAerodromeError, message):
                        aerodromes.load_anac_aerodrome_snapshot(
                            path,
                            source_url=aerodromes.ANAC_PUBLIC_AERODROMES_SOURCE_URL,
                            archive_url=archive_url(
                                aerodromes.ANAC_PUBLIC_AERODROMES_SOURCE_URL,
                                captured,
                            ),
                            archived_at_utc=captured,
                        )

    def test_duplicate_and_conflicting_icao_claims_abort_the_load(self) -> None:
        duplicate = fixture(row(), row())
        conflict = fixture(row(), row(name="Different name"))
        with tempfile.TemporaryDirectory() as directory:
            for index, (data, error) in enumerate(
                (
                    (duplicate, aerodromes.AnacAerodromeDuplicateError),
                    (conflict, aerodromes.AnacAerodromeConflictError),
                )
            ):
                path = Path(directory) / (
                    f"case-{index}/anac-aerodromes-public-20250418.csv"
                )
                path.parent.mkdir()
                path.write_bytes(data)
                with self.subTest(error=error.__name__):
                    with self.assertRaisesRegex(error, "ICAO SBGL"):
                        aerodromes.load_anac_aerodrome_snapshot(
                            path,
                            source_url=aerodromes.ANAC_PUBLIC_AERODROMES_SOURCE_URL,
                            archive_url=archive_url(
                                aerodromes.ANAC_PUBLIC_AERODROMES_SOURCE_URL,
                                PUBLIC_CAPTURE,
                            ),
                            archived_at_utc=PUBLIC_CAPTURE,
                        )

    def test_merge_keeps_provenance_and_rejects_cross_catalog_conflicts(self) -> None:
        private_data = fixture(
            row(icao="SJ4S", ciad="PR0191", name="Fazenda Candoara", state="PR"),
            updated_on="2024-11-01",
        )
        conflicting_private = fixture(
            row(icao="SBGL", ciad="RJ0999", name="Private conflict", state="RJ"),
            updated_on="2024-11-01",
        )
        with tempfile.TemporaryDirectory() as directory:
            public = self._load(directory, fixture(row()))
            private_dir = Path(directory) / "private"
            private_dir.mkdir()
            private = self._load(
                str(private_dir),
                private_data,
                aerodrome_type="private",
                captured=PRIVATE_CAPTURE,
            )
            merged = aerodromes.merge_anac_aerodrome_catalogs(public, private)
            conflict_dir = Path(directory) / "conflict"
            conflict_dir.mkdir()
            conflict = self._load(
                str(conflict_dir),
                conflicting_private,
                aerodrome_type="private",
                captured=PRIVATE_CAPTURE,
            )

        self.assertEqual(set(merged.by_icao), {"SBGL", "SJ4S"})
        self.assertEqual(len(merged.audits), 2)
        self.assertEqual(merged.raw_row_count, 2)
        with self.assertRaises(aerodromes.AnacAerodromeDuplicateError):
            aerodromes.merge_anac_aerodrome_catalogs(public, public)
        with self.assertRaisesRegex(
            aerodromes.AnacAerodromeConflictError, "Conflicting ICAO SBGL"
        ):
            aerodromes.merge_anac_aerodrome_catalogs(public, conflict)


if __name__ == "__main__":
    unittest.main()
