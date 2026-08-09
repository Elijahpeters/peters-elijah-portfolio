"""Synthetic checks for the strict ANAC airport identity merge."""

from __future__ import annotations

import importlib
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import MappingProxyType


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
merge = importlib.import_module("global.sources.anac_airport_index")
airports = importlib.import_module("global.sources.airports")
anac_aerodromes = importlib.import_module("global.sources.anac_aerodromes")


SNAPSHOT_DATE = date(2025, 4, 15)


def official_record(**overrides):
    values = {
        "icao": "SBBR",
        "ciad": "DF0001",
        "name": "Presidente Juscelino Kubitschek International Airport",
        "state": "DF",
        "latitude_wgs84": -15.8697,
        "longitude_wgs84": -47.9208,
        "aerodrome_type": "public",
        "snapshot_updated_on": SNAPSHOT_DATE,
    }
    values.update(overrides)
    return anac_aerodromes.AnacAerodromeRecord(**values)


def official_catalog(*records):
    row_audit = tuple(
        anac_aerodromes.AnacAerodromeRowAudit(
            row_number=index + 3,
            disposition="accepted",
            record_hint=f"{record.icao}|{record.ciad}",
        )
        for index, record in enumerate(records)
    )
    provenance = anac_aerodromes.AnacAerodromeProvenance(
        source_id="anac_aerodrome_registry",
        source_provider="Brazil ANAC",
        dataset_name="ANAC public aerodromes CSV",
        aerodrome_type="public",
        source_url="https://sistemas.anac.gov.br/official.csv",
        archive_url="https://web.archive.org/web/20250418153253id_/https://example.test/official.csv",
        file_path="C:/reference/anac-aerodromes-public-20250418.csv",
        filename="anac-aerodromes-public-20250418.csv",
        archived_at_utc=datetime(2025, 4, 18, 15, 32, 53, tzinfo=timezone.utc),
        snapshot_updated_on=SNAPSHOT_DATE,
        raw_file_sha256="a" * 64,
        raw_bytes=1000,
        raw_row_count=len(records),
        accepted_row_count=len(records),
        rejected_row_count=0,
    )
    audit = anac_aerodromes.AnacAerodromeAudit(
        provenance=provenance,
        source_headers=("Código OACI",),
        normalized_headers=("codigo_oaci",),
        row_audit=row_audit,
        rejected_rows=(),
    )
    return anac_aerodromes.AnacAerodromeCatalog(
        records=records,
        by_icao={record.icao: record for record in records},
        audits=(audit,),
    )


def secondary_record(**overrides):
    values = {
        "icao": "SBBR",
        "iata": "BSB",
        "latitude": -15.8698,
        "longitude": -47.9209,
        "country_code": "BR",
        "subdivision": "Distrito Federal",
        "timezone_name": "America/Sao_Paulo",
    }
    values.update(overrides)
    return airports.AirportReferenceRecord(**values)


def secondary_catalog(*records):
    by_icao = {record.icao: record for record in records if record.icao is not None}
    by_iata = {record.iata: record for record in records if record.iata is not None}
    provenance = airports.AirportReferenceProvenance(
        source_id="mborsetti_airportsdata",
        source_provider="mborsetti/airportsdata",
        dataset_name="airportsdata airports.csv",
        source_url="https://example.test/airports.csv",
        file_path="C:/reference/airports.csv",
        filename="airports.csv",
        retrieved_at_utc=datetime(2026, 8, 9, tzinfo=timezone.utc),
        raw_file_sha256="b" * 64,
        raw_bytes=500,
        raw_row_count=len(records),
        accepted_row_count=len(records),
        skipped_row_count=0,
        icao_count=len(by_icao),
        iata_count=len(by_iata),
    )
    audit = airports.AirportReferenceAudit(
        provenance=provenance,
        headers=("icao", "iata", "lat", "lon", "country", "tz"),
        skipped_rows=(),
    )
    return airports.AirportReferenceCatalog(
        records=records,
        by_icao=by_icao,
        by_iata=by_iata,
        audit=audit,
    )


def build(official, *, timezones=None, secondary=None):
    return merge.build_anac_airport_index(
        official,
        timezones or {},
        region_code="South America",
        secondary=secondary,
    )


class AnacAirportIdentityMergeTests(unittest.TestCase):
    def test_safe_enrichment_preserves_official_identity_and_coordinates(self):
        record = official_record()
        reference = secondary_record(
            latitude=-15.8699,
            longitude=-47.9206,
            timezone_name="America/Fortaleza",
        )

        index = build(
            official_catalog(record),
            timezones={"SBBR": "America/Sao_Paulo"},
            secondary=secondary_catalog(reference),
        )

        metadata = index["SBBR"]
        self.assertEqual(metadata.iata, "BSB")
        self.assertEqual(metadata.latitude, record.latitude_wgs84)
        self.assertEqual(metadata.longitude, record.longitude_wgs84)
        self.assertEqual(metadata.timezone_name, "America/Sao_Paulo")
        entry = index.entries[0]
        self.assertEqual(entry.disposition, "enriched_iata")
        self.assertFalse(entry.secondary_timezone_matches)
        self.assertEqual(entry.provenance.ciad, "DF0001")
        self.assertEqual(entry.provenance.official_name, record.name)
        self.assertEqual(index.audit.enriched_iata_count, 1)
        self.assertEqual(index.audit.secondary_timezone_mismatch_count, 1)
        with self.assertRaises(TypeError):
            index.by_icao["SBBR"] = metadata

    def test_exact_icao_without_iata_is_accepted_as_icao_only(self):
        index = build(
            official_catalog(official_record()),
            timezones={"SBBR": "America/Sao_Paulo"},
            secondary=secondary_catalog(secondary_record(iata=None)),
        )

        self.assertIsNone(index["SBBR"].iata)
        self.assertEqual(
            index.entries[0].disposition,
            "icao_only_secondary_without_iata",
        )
        self.assertEqual(index.audit.icao_only_count, 1)

    def test_country_mismatch_fails_closed_but_keeps_official_icao(self):
        index = build(
            official_catalog(official_record()),
            timezones={"SBBR": "America/Sao_Paulo"},
            secondary=secondary_catalog(secondary_record(country_code="US")),
        )

        self.assertIsNone(index["SBBR"].iata)
        self.assertEqual(index.entries[0].disposition, "icao_only_conflict")
        self.assertEqual(
            index.entries[0].reason_code, "secondary_country_mismatch"
        )
        self.assertEqual(index.audit.conflict_count, 1)

    def test_coordinate_manual_review_and_conflict_never_enrich_iata(self):
        review_record = official_record(icao="SBRV", ciad="RO0001")
        conflict_record = official_record(icao="SBPV", ciad="RO0002")
        official = official_catalog(review_record, conflict_record)
        secondary = secondary_catalog(
            secondary_record(
                icao="SBRV",
                iata="RVI",
                latitude=review_record.latitude_wgs84 + 0.018,
            ),
            secondary_record(
                icao="SBPV",
                iata="PVI",
                latitude=conflict_record.latitude_wgs84 + 0.10,
            ),
        )

        index = build(
            official,
            timezones={
                "SBRV": "America/Porto_Velho",
                "SBPV": "America/Porto_Velho",
            },
            secondary=secondary,
        )

        by_entry = {entry.icao: entry for entry in index.entries}
        self.assertEqual(
            by_entry["SBRV"].disposition, "icao_only_manual_review"
        )
        self.assertGreater(by_entry["SBRV"].secondary_distance_km, 1)
        self.assertLess(by_entry["SBRV"].secondary_distance_km, 5)
        self.assertEqual(by_entry["SBPV"].disposition, "icao_only_conflict")
        self.assertGreater(by_entry["SBPV"].secondary_distance_km, 5)
        self.assertIsNone(index["SBRV"].iata)
        self.assertIsNone(index["SBPV"].iata)
        self.assertEqual(index.audit.manual_review_count, 1)
        self.assertEqual(index.audit.conflict_count, 1)

    def test_missing_or_invalid_independent_timezone_excludes_record(self):
        first = official_record(icao="SBBR", ciad="DF0001")
        second = official_record(icao="SBGR", ciad="SP0001")
        official = official_catalog(first, second)
        secondary = secondary_catalog(
            secondary_record(icao="SBBR", iata="BSB"),
            secondary_record(icao="SBGR", iata="GRU"),
        )

        index = build(
            official,
            timezones={"SBGR": "Not/A_Real_Zone"},
            secondary=secondary,
        )

        self.assertEqual(len(index), 0)
        by_entry = {entry.icao: entry for entry in index.entries}
        self.assertEqual(
            by_entry["SBBR"].disposition, "excluded_missing_timezone"
        )
        self.assertEqual(
            by_entry["SBGR"].disposition, "excluded_invalid_timezone"
        )
        self.assertIsNone(by_entry["SBBR"].independent_timezone)
        self.assertEqual(index.audit.missing_timezone_count, 1)
        self.assertEqual(index.audit.invalid_timezone_count, 1)

    def test_pseudo_icao_iata_collision_fails_closed(self):
        candidate = secondary_record()
        pseudo_owner = secondary_record(icao=None)
        valid = secondary_catalog(candidate)
        # The loader normally rejects this duplicate IATA.  Constructing a
        # deliberately corrupt catalogue proves the merge also defends its
        # boundary instead of trusting a pseudo-ICAO collision silently.
        corrupt = object.__new__(airports.AirportReferenceCatalog)
        object.__setattr__(corrupt, "records", (candidate, pseudo_owner))
        object.__setattr__(
            corrupt, "by_icao", MappingProxyType({"SBBR": candidate})
        )
        object.__setattr__(
            corrupt, "by_iata", MappingProxyType({"BSB": pseudo_owner})
        )
        object.__setattr__(corrupt, "audit", valid.audit)

        index = build(
            official_catalog(official_record()),
            timezones={"SBBR": "America/Sao_Paulo"},
            secondary=corrupt,
        )

        self.assertIsNone(index["SBBR"].iata)
        self.assertEqual(index.entries[0].disposition, "icao_only_conflict")
        self.assertEqual(index.entries[0].reason_code, "secondary_iata_collision")


if __name__ == "__main__":
    unittest.main()
