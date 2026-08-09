"""Synthetic checks for the shared airportsdata reference loader."""

from __future__ import annotations

import csv
import hashlib
import importlib
import io
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
airports = importlib.import_module("global.sources.airports")
anac = importlib.import_module("global.sources.anac")
bts = importlib.import_module("global.sources.bts")


FIELDS = [
    "icao",
    "iata",
    "name",
    "city",
    "subd",
    "country",
    "elevation",
    "lat",
    "lon",
    "tz",
    "lid",
]
SOURCE_URL = "https://example.test/reference/airports.csv"
RETRIEVED = datetime(2026, 8, 9, 2, 30, tzinfo=timezone(timedelta(hours=1)))


def row(**overrides: str) -> dict[str, str]:
    values = {
        "icao": "KMIA",
        "iata": "MIA",
        "name": "Miami International Airport",
        "city": "Miami",
        "subd": "Florida",
        "country": "US",
        "elevation": "9",
        "lat": "25.7959",
        "lon": "-80.2870",
        "tz": "America/New_York",
        "lid": "MIA",
    }
    values.update(overrides)
    return values


def csv_bytes(*rows: dict[str, str], fields: list[str] | None = None) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=fields or FIELDS,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def load(raw: bytes):
    temporary = tempfile.TemporaryDirectory()
    path = Path(temporary.name) / "airports.csv"
    path.write_bytes(raw)
    catalog = airports.load_airport_reference(
        path,
        retrieved_at_utc=RETRIEVED,
        source_url=SOURCE_URL,
    )
    return temporary, path, catalog


class AirportReferenceLoadTests(unittest.TestCase):
    def test_builds_strict_indexes_and_complete_provenance(self) -> None:
        raw = csv_bytes(
            row(),
            row(
                icao="EGLL",
                iata="LHR",
                name="Heathrow Airport",
                city="London",
                subd="",
                country="GB",
                lat="51.4700",
                lon="-0.4543",
                tz="Europe/London",
                lid="",
            ),
            row(icao="KZZZ", iata="", name="No IATA"),
            row(icao="KAAA", iata="AAA", lat="91"),
            row(icao="KBBB", iata="BBB", tz="Mars/Olympus_Mons"),
        )
        temporary, path, catalog = load(raw)
        self.addCleanup(temporary.cleanup)

        self.assertEqual(len(catalog), 3)
        self.assertEqual(set(catalog.by_icao), {"KMIA", "EGLL", "KZZZ"})
        self.assertEqual(set(catalog.by_iata), {"MIA", "LHR"})
        self.assertIs(catalog.by_icao["KMIA"], catalog.by_iata["MIA"])
        self.assertIsNone(catalog.by_icao["KZZZ"].iata)
        self.assertEqual(catalog.by_icao["KMIA"].subdivision, "Florida")
        self.assertIsNone(catalog.by_icao["EGLL"].subdivision)
        with self.assertRaises(TypeError):
            catalog.by_icao["XXXX"] = catalog.records[0]  # type: ignore[index]

        provenance = catalog.provenance
        self.assertEqual(provenance.source_url, SOURCE_URL)
        self.assertEqual(provenance.file_path, str(path.resolve()))
        self.assertEqual(
            provenance.retrieved_at_utc,
            datetime(2026, 8, 9, 1, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(provenance.raw_file_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(provenance.raw_bytes, len(raw))
        self.assertEqual(provenance.raw_row_count, 5)
        self.assertEqual(provenance.accepted_row_count, 3)
        self.assertEqual(provenance.record_count, 3)
        self.assertEqual(provenance.skipped_row_count, 2)
        self.assertEqual(provenance.icao_count, 3)
        self.assertEqual(provenance.iata_count, 2)
        self.assertTrue(catalog.audit.completed)
        self.assertEqual([item.row_number for item in catalog.audit.skipped_rows], [5, 6])
        reasons = " ".join(item.reason for item in catalog.audit.skipped_rows)
        self.assertIn("within [-90, 90]", reasons)
        self.assertIn("Unknown airport IANA timezone", reasons)
        exported = catalog.audit.to_dict()
        self.assertEqual(exported["accepted_row_count"], 3)
        self.assertEqual(exported["provenance"]["retrieved_at_utc"], "2026-08-09T01:30:00Z")

    def test_normalizes_codes_and_audits_an_exact_duplicate(self) -> None:
        raw = csv_bytes(
            row(icao=" kmia ", iata=" mia ", country=" us ", subd=" Florida "),
            row(),
        )
        temporary, _, catalog = load(raw)
        self.addCleanup(temporary.cleanup)

        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog.records[0].icao, "KMIA")
        self.assertEqual(catalog.records[0].iata, "MIA")
        self.assertEqual(catalog.records[0].country_code, "US")
        self.assertEqual(catalog.audit.skipped_row_count, 1)
        self.assertIn(
            "duplicate normalized airport record from source row 2",
            catalog.audit.skipped_rows[0].reason,
        )

    def test_keeps_iata_only_placeholder_out_of_icao_index(self) -> None:
        raw = csv_bytes(
            row(
                icao="_AYM",
                iata="AYM",
                name="Yas Island Seaplane Base",
                city="Abu Dhabi",
                subd="Abu Dhabi",
                country="AE",
                lat="24.467",
                lon="54.6103",
                tz="Asia/Dubai",
                lid="",
            ),
            row(icao="", iata="ZZZ", name="Airport with no source ICAO"),
            row(icao="KZZZ", iata="", name="Valid ICAO-only aerodrome"),
            row(icao="BAD", iata="BAD", name="Malformed non-placeholder ICAO"),
            row(icao="_XYZ", iata="QQQ", name="Mismatched placeholder ICAO"),
        )
        temporary, _, catalog = load(raw)
        self.addCleanup(temporary.cleanup)

        self.assertEqual(len(catalog), 3)
        reference = catalog.by_iata["AYM"]
        self.assertIsNone(reference.icao)
        self.assertIsNone(catalog.by_iata["ZZZ"].icao)
        icao_only = catalog.by_icao["KZZZ"]
        self.assertIsNone(icao_only.iata)
        self.assertEqual(set(catalog.by_icao), {"KZZZ"})
        self.assertEqual(catalog.provenance.iata_count, 2)
        self.assertEqual(catalog.provenance.icao_count, 1)
        self.assertEqual(catalog.audit.skipped_row_count, 2)
        self.assertTrue(
            all(
                "Invalid airport ICAO code" in skipped.reason
                for skipped in catalog.audit.skipped_rows
            )
        )

        metadata = airports.to_bts_airport_metadata(reference, {"AE": "Middle East"})
        self.assertEqual(metadata.iata, "AYM")
        with self.assertRaisesRegex(ValueError, "requires a valid ICAO"):
            airports.to_anac_airport_metadata(reference, {"AE": "Middle East"})

        anac_metadata = airports.to_anac_airport_metadata(
            icao_only, {"US": "North America"}
        )
        self.assertEqual(anac_metadata.icao, "KZZZ")
        self.assertIsNone(anac_metadata.iata)
        self.assertEqual(anac_metadata.training_code, "KZZZ")
        with self.assertRaisesRegex(ValueError, "requires a valid IATA"):
            airports.to_bts_airport_metadata(icao_only, {"US": "North America"})

    def test_rejects_conflicting_icao_and_iata_duplicates(self) -> None:
        with self.subTest("ICAO"):
            raw = csv_bytes(row(), row(iata="FLL"))
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "airports.csv"
                path.write_bytes(raw)
                with self.assertRaisesRegex(
                    airports.AirportReferenceConflictError,
                    r"row 3 conflicts with row 2 for ICAO KMIA",
                ):
                    airports.load_airport_reference(
                        path,
                        retrieved_at_utc=RETRIEVED,
                        source_url=SOURCE_URL,
                    )

        with self.subTest("IATA"):
            raw = csv_bytes(row(), row(icao="KFLL"))
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "airports.csv"
                path.write_bytes(raw)
                with self.assertRaisesRegex(
                    airports.AirportReferenceConflictError,
                    r"row 3 conflicts with row 2 for IATA MIA",
                ):
                    airports.load_airport_reference(
                        path,
                        retrieved_at_utc=RETRIEVED,
                        source_url=SOURCE_URL,
                    )

    def test_rejects_missing_or_duplicate_required_headers(self) -> None:
        without_subdivision = [name for name in FIELDS if name != "subd"]
        raw = csv_bytes(row(), fields=without_subdivision)
        temporary, _, catalog = load(raw)
        self.addCleanup(temporary.cleanup)
        self.assertIsNone(catalog.records[0].subdivision)

        missing_tz = [name for name in FIELDS if name != "tz"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "airports.csv"
            path.write_bytes(csv_bytes(row(), fields=missing_tz))
            with self.assertRaisesRegex(
                airports.AirportReferenceError, "missing required columns: tz"
            ):
                airports.load_airport_reference(
                    path,
                    retrieved_at_utc=RETRIEVED,
                    source_url=SOURCE_URL,
                )

        raw = (
            b"icao,iata,lat,lat,lon,country,subd,tz\n"
            b"KMIA,MIA,25,25,-80,US,Florida,America/New_York\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "airports.csv"
            path.write_bytes(raw)
            with self.assertRaisesRegex(
                airports.AirportReferenceError, "duplicate columns: lat"
            ):
                airports.load_airport_reference(
                    path,
                    retrieved_at_utc=RETRIEVED,
                    source_url=SOURCE_URL,
                )

    def test_audits_invalid_codes_countries_and_nonfinite_coordinates(self) -> None:
        raw = csv_bytes(
            row(icao="KAAA", iata="A1A"),
            row(icao="KBBB", iata="BBB", country="USA"),
            row(icao="KCCC", iata="CCC", lat="NaN"),
            row(icao="KDDD", iata="DDD", lon="inf"),
            row(icao="KEEE", iata="EEE", lon="-181"),
            row(icao="KFFF", iata="FFF", tz=""),
            row(icao="KGGG", iata="GGG", lat="90", lon="-180", tz="UTC"),
        )
        temporary, _, catalog = load(raw)
        self.addCleanup(temporary.cleanup)

        self.assertEqual(set(catalog.by_iata), {"GGG"})
        self.assertEqual(catalog.audit.raw_row_count, 7)
        self.assertEqual(catalog.audit.skipped_row_count, 6)
        reasons = " ".join(item.reason for item in catalog.audit.skipped_rows)
        self.assertIn("Invalid airport IATA code", reasons)
        self.assertIn("Invalid airport country code", reasons)
        self.assertIn("airport latitude must be within [-90, 90]", reasons)
        self.assertIn("airport longitude must be within [-180, 180]", reasons)
        self.assertIn("missing required fields: tz", reasons)

        with self.assertRaisesRegex(ValueError, "must be numeric"):
            airports.AirportReferenceRecord(
                icao="KAAA",
                iata="AAA",
                latitude=True,
                longitude=0,
                country_code="US",
                subdivision=None,
                timezone_name="UTC",
            )

    def test_rejects_naive_retrieval_time_bad_url_and_invalid_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "airports.csv"
            path.write_bytes(csv_bytes(row()))
            with self.assertRaisesRegex(ValueError, "aware datetime"):
                airports.load_airport_reference(
                    path,
                    retrieved_at_utc=datetime(2026, 8, 9),
                )
            with self.assertRaisesRegex(ValueError, "absolute HTTPS"):
                airports.load_airport_reference(
                    path,
                    retrieved_at_utc=RETRIEVED,
                    source_url="file:///airports.csv",
                )
            path.write_bytes(b"icao,iata,lat,lon,country,subd,tz\n\xff")
            with self.assertRaisesRegex(
                airports.AirportReferenceError, "not valid UTF-8"
            ):
                airports.load_airport_reference(
                    path,
                    retrieved_at_utc=RETRIEVED,
                    source_url=SOURCE_URL,
                )


class AirportReferenceConversionTests(unittest.TestCase):
    def setUp(self) -> None:
        raw = csv_bytes(
            row(),
            row(
                icao="KJFK",
                iata="JFK",
                name="John F Kennedy International Airport",
                city="New York",
                subd="New York",
                lat="40.6399",
                lon="-73.7787",
                lid="JFK",
            ),
        )
        self.temporary, _, self.catalog = load(raw)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_converts_to_anac_and_bts_without_treating_subdivision_as_region(self) -> None:
        regions = {"US": "North America"}
        reference = self.catalog.by_icao["KMIA"]
        anac_metadata = airports.to_anac_airport_metadata(reference, regions)
        bts_metadata = airports.to_bts_airport_metadata(reference, regions)

        self.assertIsInstance(anac_metadata, anac.AirportMetadata)
        self.assertIsInstance(bts_metadata, bts.AirportMetadata)
        self.assertEqual(anac_metadata.icao, "KMIA")
        self.assertEqual(anac_metadata.region_code, "North America")
        self.assertEqual(bts_metadata.region_code, "North America")
        self.assertNotEqual(reference.subdivision, anac_metadata.region_code)
        self.assertEqual(
            set(self.catalog.to_anac_airports(regions)), {"KMIA", "KJFK"}
        )
        self.assertEqual(
            set(self.catalog.to_bts_airports(regions)), {"MIA", "JFK"}
        )

    def test_converted_indexes_are_accepted_by_both_source_adapters(self) -> None:
        regions = {"US": "North America"}
        anac_record = anac.parse_vra_row(
            {
                "Sigla ICAO Empresa Aerea": "1ED",
                "Numero Voo": "101",
                "Sigla ICAO Aeroporto Origem": "KMIA",
                "Partida Prevista": "14/01/2026 11:30",
                "Partida Real": "14/01/2026 11:35",
                "Sigla ICAO Aeroporto Destino": "KJFK",
                "Chegada Prevista": "14/01/2026 14:30",
                "Chegada Real": "14/01/2026 14:35",
                "Situacao Voo": "REALIZADO",
            },
            self.catalog.to_anac_airports(regions),
            source_url=anac.build_vra_url(2026, 1),
        )
        self.assertEqual((anac_record["origin"], anac_record["destination"]), ("MIA", "JFK"))

        bts_record = bts.parse_bts_row(
            {
                "Year": "2025",
                "Month": "1",
                "DayofMonth": "1",
                "FlightDate": "2025-01-01",
                "Reporting_Airline": "AA",
                "Flight_Number_Reporting_Airline": "1",
                "Origin": "MIA",
                "Dest": "JFK",
                "CRSDepTime": "0659",
                "CRSArrTime": "0959",
                "CRSElapsedTime": "180",
                "DepTime": "0659",
                "DepDelay": "0",
                "ArrTime": "0959",
                "ArrDelay": "0",
                "Cancelled": "0",
                "Diverted": "0",
                "ActualElapsedTime": "180",
                "DivReachedDest": "",
                "DivActualElapsedTime": "",
                "DivArrDelay": "",
            },
            self.catalog.to_bts_airports(regions),
            source_url=bts.build_ontime_url(2025, 1),
        )
        self.assertEqual((bts_record["origin"], bts_record["destination"]), ("MIA", "JFK"))

    def test_region_resolution_is_explicit_and_fail_closed(self) -> None:
        reference = self.catalog.records[0]
        with self.assertRaisesRegex(ValueError, "No SkyETA region mapping"):
            airports.to_anac_airport_metadata(reference, {})
        with self.assertRaisesRegex(ValueError, "Invalid SkyETA region 'Florida'"):
            airports.to_bts_airport_metadata(reference, {"US": "Florida"})

        seen: list[tuple[str, str | None]] = []

        def resolver(record: airports.AirportReferenceRecord) -> str:
            seen.append((record.country_code, record.subdivision))
            return "North America"

        metadata = airports.to_bts_airport_metadata(reference, resolver)
        self.assertEqual(metadata.region_code, "North America")
        self.assertEqual(seen, [("US", "Florida")])

        other = airports.to_bts_airport_metadata(reference, {"US": "Other"})
        self.assertEqual(other.region_code, "Other")
        with self.assertRaisesRegex(ValueError, "Invalid SkyETA region None"):
            airports.to_bts_airport_metadata(reference, {"US": None})


if __name__ == "__main__":
    unittest.main()
