"""Synthetic and archive-level checks for the U.S. BTS source adapter."""

from __future__ import annotations

import csv
import hashlib
import importlib
import io
import sys
import tempfile
import unittest
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
bts = importlib.import_module("global.sources.bts")


SOURCE_URL = bts.build_ontime_url(2025, 1)
CSV_FIELDS = [
    "Year",
    "Month",
    "DayofMonth",
    "FlightDate",
    "Reporting_Airline",
    "IATA_CODE_Reporting_Airline",
    "DOT_ID_Reporting_Airline",
    "Flight_Number_Reporting_Airline",
    "OriginAirportID",
    "Origin",
    "DestAirportID",
    "Dest",
    "CRSDepTime",
    "DepTime",
    "DepDelay",
    "CRSArrTime",
    "ArrTime",
    "ArrDelay",
    "Cancelled",
    "Diverted",
    "CRSElapsedTime",
    "ActualElapsedTime",
    "DivReachedDest",
    "DivActualElapsedTime",
    "DivArrDelay",
]


def airport(
    iata: str,
    latitude: float,
    longitude: float,
    region: str,
    timezone_name: str,
):
    return bts.AirportMetadata(
        iata=iata,
        latitude=latitude,
        longitude=longitude,
        country_code="US",
        region_code=region,
        timezone_name=timezone_name,
    )


AIRPORTS = {
    "BOS": airport("BOS", 42.3629, -71.0064, "North America", "America/New_York"),
    "DFW": airport("DFW", 32.8998, -97.0403, "North America", "America/Chicago"),
    "JAX": airport("JAX", 30.4941, -81.6879, "North America", "America/New_York"),
    "JFK": airport("JFK", 40.6413, -73.7781, "North America", "America/New_York"),
    "LAX": airport("LAX", 33.9416, -118.4085, "North America", "America/Los_Angeles"),
    "MIA": airport("MIA", 25.7959, -80.2870, "North America", "America/New_York"),
}


def row(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "Year": "2025",
        "Month": "1",
        "DayofMonth": "1",
        "FlightDate": "2025-01-01",
        "Reporting_Airline": "AA",
        "IATA_CODE_Reporting_Airline": "AA",
        "DOT_ID_Reporting_Airline": "19805",
        "Flight_Number_Reporting_Airline": "1",
        "OriginAirportID": "12478",
        "Origin": "JFK",
        "DestAirportID": "12892",
        "Dest": "LAX",
        "CRSDepTime": "0659",
        "DepTime": "0656",
        "DepDelay": "-3.00",
        "CRSArrTime": "1020",
        "ArrTime": "1013",
        "ArrDelay": "-7.00",
        "Cancelled": "0.00",
        "Diverted": "0.00",
        "CRSElapsedTime": "381.00",
        "ActualElapsedTime": "377.00",
        "DivReachedDest": "",
        "DivActualElapsedTime": "",
        "DivArrDelay": "",
    }
    values.update(overrides)
    return values


def csv_text(*rows: dict[str, object]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


class BtsRowTests(unittest.TestCase):
    def test_landed_row_normalizes_local_gate_times_and_metadata(self) -> None:
        record = bts.parse_bts_row(row(), AIRPORTS, source_url=SOURCE_URL)

        self.assertEqual(record["status"], "landed")
        self.assertEqual(record["service_date"], date(2025, 1, 1))
        self.assertEqual(record["operating_carrier"], "AA")
        self.assertEqual(record["operating_flight_number"], "1")
        self.assertIsNone(record["marketing_carrier"])
        self.assertIsNone(record["marketing_flight_number"])
        self.assertEqual(
            record["scheduled_departure_utc"],
            datetime(2025, 1, 1, 11, 59, tzinfo=timezone.utc),
        )
        self.assertEqual(
            record["scheduled_arrival_utc"],
            datetime(2025, 1, 1, 18, 20, tzinfo=timezone.utc),
        )
        self.assertEqual(
            record["actual_departure_utc"],
            datetime(2025, 1, 1, 11, 56, tzinfo=timezone.utc),
        )
        self.assertEqual(
            record["actual_arrival_utc"],
            datetime(2025, 1, 1, 18, 13, tzinfo=timezone.utc),
        )
        self.assertEqual(record["origin_timezone_offset_minutes"], -300)
        self.assertEqual(record["destination_timezone_offset_minutes"], -480)
        self.assertEqual(record["origin_region"], "North America")
        self.assertIsNone(record["aircraft_family"])
        self.assertIsNone(record["schedule_observed_at"])
        self.assertIsNone(record["schedule_revision"])
        self.assertIsNone(record["outcome_observed_at"])
        self.assertEqual(record["source"], SOURCE_URL)
        self.assertRegex(record["record_id"], r"^bts-otp-[0-9a-f]{24}$")

    def test_mapping_constructs_shared_global_record(self) -> None:
        record = bts.parse_bts_record(row(), AIRPORTS, source_url=SOURCE_URL)
        schema = importlib.import_module("global.schema")
        self.assertIsInstance(record, schema.GlobalFlightRecord)
        self.assertEqual(record.origin, "JFK")
        self.assertEqual(record.destination, "LAX")

    def test_overnight_and_2400_actual_departure_roll_forward(self) -> None:
        record = bts.parse_bts_row(
            row(
                DayofMonth="10",
                FlightDate="2025-01-10",
                Flight_Number_Reporting_Airline="333",
                Origin="MIA",
                Dest="JAX",
                CRSDepTime="2255",
                DepTime="2400",
                DepDelay="65.00",
                CRSArrTime="0023",
                ArrTime="0116",
                ArrDelay="53.00",
                CRSElapsedTime="88.00",
                ActualElapsedTime="76.00",
            ),
            AIRPORTS,
            source_url=SOURCE_URL,
        )
        self.assertEqual(
            record["scheduled_departure_utc"],
            datetime(2025, 1, 11, 3, 55, tzinfo=timezone.utc),
        )
        self.assertEqual(
            record["scheduled_arrival_utc"],
            datetime(2025, 1, 11, 5, 23, tzinfo=timezone.utc),
        )
        self.assertEqual(
            record["actual_departure_utc"],
            datetime(2025, 1, 11, 5, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(
            record["actual_arrival_utc"],
            datetime(2025, 1, 11, 6, 16, tzinfo=timezone.utc),
        )

    def test_cancelled_after_gate_departure_preserves_actual_departure(self) -> None:
        record = bts.parse_bts_row(
            row(
                DayofMonth="5",
                FlightDate="2025-01-05",
                Flight_Number_Reporting_Airline="509",
                Origin="DFW",
                Dest="LAX",
                CRSDepTime="2230",
                DepTime="0056",
                DepDelay="146.00",
                CRSArrTime="0020",
                ArrTime="",
                ArrDelay="",
                Cancelled="1.00",
                CRSElapsedTime="230.00",
                ActualElapsedTime="",
            ),
            AIRPORTS,
            source_url=SOURCE_URL,
        )
        self.assertEqual(record["status"], "cancelled")
        self.assertEqual(
            record["actual_departure_utc"],
            datetime(2025, 1, 6, 6, 56, tzinfo=timezone.utc),
        )
        self.assertIsNone(record["actual_arrival_utc"])

    def test_diversion_that_reached_destination_uses_diversion_fields(self) -> None:
        record = bts.parse_bts_row(
            row(
                DayofMonth="23",
                FlightDate="2025-01-23",
                Flight_Number_Reporting_Airline="2",
                Origin="LAX",
                Dest="JFK",
                CRSDepTime="0700",
                DepTime="0655",
                DepDelay="-5.00",
                CRSArrTime="1526",
                ArrTime="1818",
                ArrDelay="",
                Diverted="1.00",
                CRSElapsedTime="326.00",
                ActualElapsedTime="",
                DivReachedDest="1.00",
                DivActualElapsedTime="503.00",
                DivArrDelay="172.00",
            ),
            AIRPORTS,
            source_url=SOURCE_URL,
        )
        self.assertEqual(record["status"], "diverted")
        self.assertEqual(
            record["actual_arrival_utc"],
            datetime(2025, 1, 23, 23, 18, tzinfo=timezone.utc),
        )

    def test_diversion_not_reaching_destination_has_no_fabricated_arrival(self) -> None:
        record = bts.parse_bts_row(
            row(
                DayofMonth="29",
                FlightDate="2025-01-29",
                Flight_Number_Reporting_Airline="472",
                Origin="DFW",
                Dest="JFK",
                CRSDepTime="1708",
                DepTime="1706",
                DepDelay="-2.00",
                CRSArrTime="2059",
                ArrTime="",
                ArrDelay="",
                Diverted="1.00",
                CRSElapsedTime="171.00",
                ActualElapsedTime="",
                DivReachedDest="0.00",
                DivActualElapsedTime="",
                DivArrDelay="",
            ),
            AIRPORTS,
            source_url=SOURCE_URL,
        )
        self.assertEqual(record["status"], "diverted")
        self.assertIsNotNone(record["actual_departure_utc"])
        self.assertIsNone(record["actual_arrival_utc"])

    def test_fall_back_clock_is_resolved_by_scheduled_elapsed_time(self) -> None:
        november_url = bts.build_ontime_url(2025, 11)
        record = bts.parse_bts_row(
            row(
                Month="11",
                DayofMonth="2",
                FlightDate="2025-11-02",
                Origin="JFK",
                Dest="BOS",
                CRSDepTime="0130",
                DepTime="0130",
                DepDelay="0.00",
                CRSArrTime="0230",
                ArrTime="0230",
                ArrDelay="0.00",
                CRSElapsedTime="120.00",
                ActualElapsedTime="120.00",
            ),
            AIRPORTS,
            source_url=november_url,
        )
        self.assertEqual(
            record["scheduled_departure_utc"],
            datetime(2025, 11, 2, 5, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(record["origin_timezone_offset_minutes"], -240)
        self.assertEqual(record["destination_timezone_offset_minutes"], -300)

    def test_nonexistent_clock_and_missing_timezone_metadata_are_rejected(self) -> None:
        with self.assertRaisesRegex(bts.BtsRowError, "Scheduled local clocks"):
            bts.parse_bts_row(
                row(
                    Month="3",
                    DayofMonth="9",
                    FlightDate="2025-03-09",
                    Origin="JFK",
                    Dest="BOS",
                    CRSDepTime="0230",
                    DepTime="0230",
                    DepDelay="0",
                    CRSArrTime="0430",
                    ArrTime="0430",
                    ArrDelay="0",
                    CRSElapsedTime="60",
                    ActualElapsedTime="60",
                ),
                AIRPORTS,
                source_url=bts.build_ontime_url(2025, 3),
            )
        with self.assertRaisesRegex(bts.BtsRowError, "timezone was not inferred"):
            bts.parse_bts_row(row(Dest="ZZZ"), AIRPORTS, source_url=SOURCE_URL)

    def test_contradictory_outcomes_and_unofficial_source_are_rejected(self) -> None:
        malformed = (
            row(Cancelled="1", Diverted="1"),
            row(ArrTime="1014"),
            row(ActualElapsedTime="378"),
            row(CRSDepTime="2460"),
            row(Month="2"),
        )
        for candidate in malformed:
            with self.subTest(candidate=candidate):
                with self.assertRaises(bts.BtsRowError):
                    bts.parse_bts_row(candidate, AIRPORTS, source_url=SOURCE_URL)
        with self.assertRaises(ValueError):
            bts.parse_bts_row(
                row(), AIRPORTS, source_url="https://example.com/bts.zip"
            )


class BtsCsvAndArchiveTests(unittest.TestCase):
    def test_non_strict_csv_requires_and_populates_audit(self) -> None:
        valid = row()
        invalid = row(Flight_Number_Reporting_Airline="2", CRSDepTime="2561")
        audit = bts.BtsIngestionAudit()
        records = list(
            bts.iter_bts_csv(
                io.StringIO(csv_text(valid, invalid)),
                AIRPORTS,
                source_url=SOURCE_URL,
                strict=False,
                audit=audit,
            )
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(audit.raw_row_count, 2)
        self.assertEqual(audit.accepted_row_count, 1)
        self.assertEqual(audit.rejected_row_count, 1)
        self.assertEqual(audit.rejected_rows[0].row_number, 3)
        self.assertIn("2561", audit.rejected_rows[0].reason)
        self.assertIn("AA|2|JFK|LAX", audit.rejected_rows[0].record_hint)
        self.assertTrue(audit.completed)

        with self.assertRaisesRegex(ValueError, "requires a BtsIngestionAudit"):
            list(
                bts.iter_bts_csv(
                    io.StringIO(csv_text(valid)),
                    AIRPORTS,
                    source_url=SOURCE_URL,
                    strict=False,
                )
            )

    def test_strict_csv_reports_source_row_and_retains_rejection(self) -> None:
        audit = bts.BtsIngestionAudit()
        with self.assertRaisesRegex(bts.BtsRowError, "row 2"):
            list(
                bts.iter_bts_csv(
                    io.StringIO(csv_text(row(CRSDepTime="bad"))),
                    AIRPORTS,
                    source_url=SOURCE_URL,
                    audit=audit,
                )
            )
        self.assertEqual(audit.raw_row_count, 1)
        self.assertEqual(audit.rejected_row_count, 1)
        self.assertFalse(audit.completed)

    def test_archive_stream_attaches_hash_retrieval_time_and_counts(self) -> None:
        content = csv_text(row(), row(Flight_Number_Reporting_Airline="2", Dest="ZZZ"))
        retrieved = datetime(
            2025, 2, 8, 13, 45, tzinfo=timezone(timedelta(hours=1))
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / (
                "On_Time_Reporting_Carrier_On_Time_Performance_"
                "1987_present_2025_1.zip"
            )
            member = (
                "On_Time_Reporting_Carrier_On_Time_Performance_"
                "(1987_present)_2025_1.csv"
            )
            with zipfile.ZipFile(
                path, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                archive.writestr(member, content)

            expected_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            audit = bts.BtsIngestionAudit()
            records = list(
                bts.iter_bts_archive(
                    path,
                    AIRPORTS,
                    retrieved_at_utc=retrieved,
                    strict=False,
                    audit=audit,
                )
            )

            self.assertEqual(len(records), 1)
            self.assertTrue(audit.completed)
            self.assertEqual(audit.raw_row_count, 2)
            self.assertEqual(audit.accepted_row_count, 1)
            self.assertEqual(audit.rejected_row_count, 1)
            self.assertIsNotNone(audit.provenance)
            assert audit.provenance is not None
            self.assertEqual(audit.provenance.source_url, SOURCE_URL)
            self.assertEqual(audit.provenance.csv_member, member)
            self.assertEqual(audit.provenance.raw_file_sha256, expected_hash)
            self.assertEqual(audit.provenance.raw_bytes, path.stat().st_size)
            self.assertEqual(
                audit.provenance.retrieved_at_utc,
                datetime(2025, 2, 8, 12, 45, tzinfo=timezone.utc),
            )
            exported_audit = audit.to_dict()
            self.assertEqual(exported_audit["rejected_row_count"], 1)
            self.assertEqual(
                exported_audit["provenance"]["raw_file_sha256"], expected_hash
            )

    def test_archive_requires_explicit_aware_retrieval_timestamp(self) -> None:
        with self.assertRaises(ValueError):
            bts.inspect_bts_archive(
                Path("missing.zip"), retrieved_at_utc=datetime(2025, 1, 1)
            )


if __name__ == "__main__":
    unittest.main()
