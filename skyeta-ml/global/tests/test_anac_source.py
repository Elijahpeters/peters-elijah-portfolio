"""Synthetic checks for the official Brazil ANAC VRA source adapter."""

from __future__ import annotations

import importlib
import hashlib
import io
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
anac = importlib.import_module("global.sources.anac")


SOURCE_URL = anac.build_vra_url(2026, 1)
HEADER = (
    "Sigla ICAO Empresa Aérea;Número Voo;Código DI;Código Tipo Linha;"
    "Modelo Equipamento;Sigla ICAO Aeroporto Origem;Partida Prevista;"
    "Partida Real;Sigla ICAO Aeroporto Destino;Chegada Prevista;"
    "Chegada Real;Situação Voo;Referência\n"
)


def airport(
    icao: str,
    iata: str | None,
    latitude: float,
    longitude: float,
    country: str,
    region: str,
    timezone_name: str,
):
    return anac.AirportMetadata(
        icao=icao,
        iata=iata,
        latitude=latitude,
        longitude=longitude,
        country_code=country,
        region_code=region,
        timezone_name=timezone_name,
    )


AIRPORTS = {
    "SKBO": airport("SKBO", "BOG", 4.7016, -74.1469, "CO", "South America", "America/Bogota"),
    "SBEG": airport("SBEG", "MAO", -3.0386, -60.0497, "BR", "South America", "America/Manaus"),
    "KMIA": airport("KMIA", "MIA", 25.7959, -80.2870, "US", "North America", "America/New_York"),
    "SBGL": airport("SBGL", "GIG", -22.8099, -43.2506, "BR", "South America", "America/Sao_Paulo"),
}


def row(**overrides: str) -> dict[str, str]:
    values = {
        "Sigla ICAO Empresa Aerea": "1ED",
        "Numero Voo": "3301",
        "Codigo DI": "6",
        "Codigo Tipo Linha": "I",
        "Modelo Equipamento": "E145",
        "Sigla ICAO Aeroporto Origem": "SKBO",
        "Partida Prevista": "14/01/2026 11:30",
        "Partida Real": "14/01/2026 11:55",
        "Sigla ICAO Aeroporto Destino": "SBEG",
        "Chegada Prevista": "14/01/2026 14:30",
        "Chegada Real": "14/01/2026 14:20",
        "Situacao Voo": "REALIZADO",
        "Referencia": "14/01/2026 00:00:00",
    }
    values.update(overrides)
    return values


class AnacManifestTests(unittest.TestCase):
    def test_official_url_and_inclusive_manifest(self) -> None:
        self.assertEqual(
            SOURCE_URL,
            "https://siros.anac.gov.br/siros/registros/diversos/vra/2026/"
            "VRA_2026_01.csv",
        )
        manifest = anac.build_vra_manifest(2025, 11, 2026, 2)
        self.assertEqual(
            [(item.year, item.month) for item in manifest],
            [(2025, 11), (2025, 12), (2026, 1), (2026, 2)],
        )
        self.assertTrue(all(item.reporting_timezone == "America/Sao_Paulo" for item in manifest))
        self.assertTrue(all(item.delimiter == ";" for item in manifest))

    def test_manifest_rejects_invalid_ranges(self) -> None:
        with self.assertRaises(ValueError):
            anac.build_vra_url(2026, 13)
        with self.assertRaisesRegex(ValueError, "legacy CSV format"):
            anac.build_vra_url(2009, 12)
        with self.assertRaisesRegex(ValueError, "unreviewed future"):
            anac.build_vra_url(2027, 1)
        with self.assertRaises(ValueError):
            anac.build_vra_manifest(2026, 2, 2026, 1)

    def test_manifest_exposes_download_targets_without_network_io(self) -> None:
        manifest = anac.build_vra_manifest(2026, 1, 2026, 2)
        root = Path("anac-cache")
        targets = anac.manifest_download_targets(manifest, root)
        self.assertEqual([url for url, _ in targets], [item.url for item in manifest])
        self.assertEqual(
            [target.name for _, target in targets],
            ["VRA_2026_01.csv", "VRA_2026_02.csv"],
        )

    def test_download_targets_reject_tampered_manifest_identity(self) -> None:
        item = anac.monthly_file(2026, 1)
        with self.assertRaisesRegex(ValueError, "metadata"):
            anac.manifest_download_targets(
                [replace(item, url=anac.build_vra_url(2026, 2))], Path("cache")
            )
        with self.assertRaisesRegex(ValueError, "metadata"):
            anac.manifest_download_targets(
                [replace(item, filename="VRA_2026_02.csv")], Path("cache")
            )


class AnacRowTests(unittest.TestCase):
    def test_operated_international_row_normalizes_brasilia_clock_to_utc(self) -> None:
        record = anac.parse_vra_row(row(), AIRPORTS, source_url=SOURCE_URL)
        self.assertEqual(record["status"], "landed")
        self.assertEqual(record["service_date"], date(2026, 1, 14))
        self.assertEqual(record["operating_carrier"], "1ED")
        self.assertEqual(record["operating_flight_number"], "3301")
        self.assertEqual(record["origin"], "BOG")
        self.assertEqual(record["destination"], "MAO")
        self.assertEqual(
            record["scheduled_departure_utc"],
            datetime(2026, 1, 14, 14, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(
            record["actual_arrival_utc"],
            datetime(2026, 1, 14, 17, 20, tzinfo=timezone.utc),
        )
        self.assertEqual(record["origin_timezone_offset_minutes"], -300)
        self.assertEqual(record["destination_timezone_offset_minutes"], -240)
        self.assertEqual(record["origin_country"], "CO")
        self.assertEqual(record["destination_country"], "BR")
        self.assertEqual(record["aircraft_family"], "E145")
        self.assertIsNone(record["schedule_observed_at"])
        self.assertIsNone(record["schedule_revision"])
        self.assertIsNone(record["outcome_observed_at"])
        self.assertEqual(record["source"], SOURCE_URL)
        self.assertRegex(record["record_id"], r"^anac-vra-[0-9a-f]{24}$")

    def test_service_date_is_the_origin_local_departure_date(self) -> None:
        record = anac.parse_vra_row(
            row(
                **{
                    "Partida Prevista": "01/01/2026 01:30",
                    "Partida Real": "01/01/2026 01:45",
                    "Chegada Prevista": "01/01/2026 04:30",
                    "Chegada Real": "01/01/2026 04:20",
                }
            ),
            AIRPORTS,
            source_url=SOURCE_URL,
        )
        self.assertEqual(record["service_date"], date(2025, 12, 31))

    def test_incomplete_realized_rows_remain_valid_outcomes(self) -> None:
        for missing in ("Partida Real", "Chegada Real"):
            with self.subTest(missing=missing):
                record = anac.parse_vra_record(
                    row(**{missing: ""}), AIRPORTS, source_url=SOURCE_URL
                )
                self.assertEqual(record.status, "landed")
        record = anac.parse_vra_record(
            row(**{"Partida Real": "", "Chegada Real": ""}),
            AIRPORTS,
            source_url=SOURCE_URL,
        )
        self.assertIsNone(record.actual_departure_utc)
        self.assertIsNone(record.actual_arrival_utc)

    def test_mapping_constructs_the_shared_global_record(self) -> None:
        record = anac.parse_vra_record(row(), AIRPORTS, source_url=SOURCE_URL)
        schema = importlib.import_module("global.schema")
        self.assertIsInstance(record, schema.GlobalFlightRecord)
        self.assertEqual(record.origin, "BOG")
        self.assertEqual(record.destination, "MAO")
        self.assertEqual(record.status, "landed")

    def test_icao_only_aerodrome_remains_a_real_schema_identity(self) -> None:
        airports = dict(AIRPORTS)
        airports["SBEG"] = airport(
            "SBEG",
            None,
            -3.0386,
            -60.0497,
            "BR",
            "South America",
            "America/Manaus",
        )

        record = anac.parse_vra_record(row(), airports, source_url=SOURCE_URL)

        self.assertEqual(record.origin, "BOG")
        self.assertEqual(record.destination, "SBEG")
        self.assertEqual(record.destination_code_scheme, "icao")

    def test_cancelled_row_keeps_outcome_without_inventing_actual_times(self) -> None:
        record = anac.parse_vra_row(
            row(
                **{
                    "Partida Real": "",
                    "Chegada Real": "",
                    "Situacao Voo": "CANCELADO",
                }
            ),
            AIRPORTS,
            source_url=SOURCE_URL,
        )
        self.assertEqual(record["status"], "cancelled")
        self.assertIsNone(record["actual_departure_utc"])
        self.assertIsNone(record["actual_arrival_utc"])

    def test_not_informed_row_maps_to_scheduled_without_a_delay_label(self) -> None:
        record = anac.parse_vra_row(
            row(
                **{
                    "Partida Real": "",
                    "Chegada Real": "",
                    "Situacao Voo": "NAO INFORMADO",
                }
            ),
            AIRPORTS,
            source_url=SOURCE_URL,
        )
        self.assertEqual(record["status"], "scheduled")

    def test_historical_brasilia_dst_uses_zone_database(self) -> None:
        record = anac.parse_vra_row(
            row(
                **{
                    "Partida Prevista": "15/01/2018 11:30",
                    "Partida Real": "15/01/2018 11:40",
                    "Chegada Prevista": "15/01/2018 14:30",
                    "Chegada Real": "15/01/2018 14:35",
                }
            ),
            AIRPORTS,
            source_url=anac.build_vra_url(2018, 1),
        )
        self.assertEqual(
            record["scheduled_departure_utc"],
            datetime(2018, 1, 15, 13, 30, tzinfo=timezone.utc),
        )

    def test_nonexistent_brasilia_dst_wall_time_is_rejected(self) -> None:
        with self.assertRaisesRegex(anac.AnacRowError, "Nonexistent Brasilia"):
            anac.parse_vra_row(
                row(
                    **{
                        "Partida Prevista": "04/11/2018 00:30",
                        "Partida Real": "04/11/2018 01:35",
                        "Chegada Prevista": "04/11/2018 03:30",
                        "Chegada Real": "04/11/2018 03:35",
                    }
                ),
                AIRPORTS,
                source_url=anac.build_vra_url(2018, 11),
            )

    def test_malformed_and_contradictory_rows_are_rejected(self) -> None:
        malformed_rows = (
            row(**{"Partida Prevista": "2026/01/14 11:30"}),
            row(**{"Situacao Voo": "DESCONHECIDO"}),
            row(**{"Situacao Voo": "CANCELADO"}),
            row(**{"Chegada Prevista": "14/01/2026 10:30"}),
            row(**{"Sigla ICAO Aeroporto Destino": "ZZZZ"}),
        )
        for malformed in malformed_rows:
            with self.subTest(malformed=malformed):
                with self.assertRaises(anac.AnacRowError):
                    anac.parse_vra_row(malformed, AIRPORTS, source_url=SOURCE_URL)

    def test_unplanned_operation_is_distinct_from_a_malformed_row(self) -> None:
        with self.assertRaisesRegex(anac.AnacUnplannedRowError, "Unplanned"):
            anac.parse_vra_row(
                row(**{"Partida Prevista": "", "Chegada Prevista": ""}),
                AIRPORTS,
                source_url=SOURCE_URL,
            )

    def test_row_must_belong_to_source_partition(self) -> None:
        with self.assertRaisesRegex(anac.AnacRowError, "source VRA month"):
            anac.parse_vra_row(
                row(), AIRPORTS, source_url=anac.build_vra_url(2026, 2)
            )

    def test_unofficial_source_url_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            anac.parse_vra_row(
                row(), AIRPORTS, source_url="https://example.com/vra.csv"
            )


class AnacCsvTests(unittest.TestCase):
    def test_accent_insensitive_headers_and_non_strict_rejection_audit(self) -> None:
        valid = "1ED;3301;6;I;E145;SKBO;14/01/2026 11:30;14/01/2026 11:55;SBEG;14/01/2026 14:30;14/01/2026 14:20;REALIZADO;14/01/2026 00:00:00\n"
        invalid = "1ED;3302;6;I;E145;SKBO;bad;;SBEG;14/01/2026 14:30;;CANCELADO;14/01/2026 00:00:00\n"
        rejected = []
        audit = anac.AnacPartitionAudit()
        records = list(
            anac.iter_vra_csv(
                io.StringIO(HEADER + valid + invalid),
                AIRPORTS,
                source_url=SOURCE_URL,
                strict=False,
                rejected=rejected,
                audit=audit,
            )
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].row_number, 3)
        self.assertIn("scheduled_departure", rejected[0].reason)
        self.assertEqual(audit.raw_row_count, 2)
        self.assertEqual(audit.accepted_row_count, 1)
        self.assertEqual(audit.rejected_row_count, 1)
        self.assertTrue(audit.completed)
        self.assertEqual(
            [item.disposition for item in audit.row_provenance],
            ["accepted", "rejected"],
        )

    def test_unplanned_rows_are_audited_and_do_not_abort_strict_bulk_parse(self) -> None:
        valid_one = "1ED;3301;6;I;E145;SKBO;14/01/2026 11:30;14/01/2026 11:55;SBEG;14/01/2026 14:30;14/01/2026 14:20;REALIZADO;14/01/2026 00:00:00\n"
        unplanned = "1ED;3302;6;I;E145;SKBO;;14/01/2026 11:55;SBEG;;14/01/2026 14:20;REALIZADO;14/01/2026 00:00:00\n"
        valid_two = valid_one.replace("3301", "3303", 1)
        audit = anac.AnacPartitionAudit()
        records = list(
            anac.iter_vra_csv(
                io.StringIO(HEADER + valid_one + unplanned + valid_two),
                AIRPORTS,
                source_url=SOURCE_URL,
                audit=audit,
            )
        )
        self.assertEqual([item["operating_flight_number"] for item in records], ["3301", "3303"])
        self.assertEqual(audit.raw_row_count, 3)
        self.assertEqual(audit.accepted_row_count, 2)
        self.assertEqual(audit.excluded_unplanned_row_count, 1)
        self.assertEqual(audit.rejected_row_count, 0)
        self.assertIn("Unplanned", audit.excluded_unplanned_rows[0].reason)
        self.assertEqual(
            [item.disposition for item in audit.row_provenance],
            ["accepted", "excluded_unplanned", "accepted"],
        )
        self.assertTrue(audit.completed)

    def test_codeshare_and_raw_clocks_are_partition_provenance_only(self) -> None:
        header = HEADER.rstrip("\n") + ";Codeshare\n"
        valid = "1ED;3301;6;I;E145;SKBO;14/01/2026 11:30;14/01/2026 11:55;SBEG;14/01/2026 14:30;14/01/2026 14:20;REALIZADO;14/01/2026 00:00:00;GLO/1234, TAM/567\n"
        audit = anac.AnacPartitionAudit()
        [record] = list(
            anac.iter_vra_csv(
                io.StringIO(header + valid),
                AIRPORTS,
                source_url=SOURCE_URL,
                audit=audit,
            )
        )
        self.assertIsNone(record["marketing_carrier"])
        self.assertIsNone(record["marketing_flight_number"])
        provenance = audit.row_provenance[0]
        self.assertEqual(provenance.scheduled_departure_raw, "14/01/2026 11:30")
        self.assertEqual(provenance.codeshare_raw, "GLO/1234, TAM/567")
        self.assertEqual(
            [(item.carrier, item.flight_number) for item in provenance.marketing_flights],
            [("GLO", "1234"), ("TAM", "567")],
        )
        self.assertIsNone(provenance.codeshare_parse_error)

    def test_strict_csv_reports_source_row_number(self) -> None:
        invalid = "1ED;3302;6;I;E145;SKBO;bad;;SBEG;14/01/2026 14:30;;CANCELADO;14/01/2026 00:00:00\n"
        with self.assertRaisesRegex(anac.AnacRowError, "row 2"):
            list(
                anac.iter_vra_csv(
                    io.StringIO(HEADER + invalid),
                    AIRPORTS,
                    source_url=SOURCE_URL,
                )
            )

    def test_local_file_iteration_records_hash_retrieval_and_counts(self) -> None:
        valid = "1ED;3301;6;I;E145;SKBO;14/01/2026 11:30;14/01/2026 11:55;SBEG;14/01/2026 14:30;14/01/2026 14:20;REALIZADO;14/01/2026 00:00:00\n"
        unplanned = "1ED;3302;6;I;E145;SKBO;;14/01/2026 11:55;SBEG;;14/01/2026 14:20;REALIZADO;14/01/2026 00:00:00\n"
        retrieved = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "VRA_2026_01.csv"
            path.write_text(HEADER + valid + unplanned, encoding="utf-8-sig")
            expected_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            expected_bytes = path.stat().st_size
            audit = anac.AnacPartitionAudit()
            records = list(
                anac.iter_vra_file(
                    path,
                    AIRPORTS,
                    retrieved_at_utc=retrieved,
                    audit=audit,
                )
            )

        self.assertEqual(len(records), 1)
        self.assertIsNotNone(audit.provenance)
        assert audit.provenance is not None
        self.assertEqual(audit.provenance.source_url, SOURCE_URL)
        self.assertEqual(audit.provenance.raw_file_sha256, expected_hash)
        self.assertEqual(audit.provenance.raw_bytes, expected_bytes)
        self.assertEqual(audit.provenance.retrieved_at_utc, retrieved)
        self.assertEqual(audit.raw_row_count, 2)
        self.assertEqual(audit.accepted_row_count, 1)
        self.assertEqual(audit.excluded_unplanned_row_count, 1)
        self.assertTrue(audit.completed)

    def test_local_file_source_identity_and_retrieval_time_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "VRA_2026_01.csv"
            path.write_text(HEADER, encoding="utf-8-sig")
            with self.assertRaisesRegex(ValueError, "does not match"):
                anac.inspect_vra_file(
                    path,
                    retrieved_at_utc=datetime(2026, 2, 1, tzinfo=timezone.utc),
                    source_url=anac.build_vra_url(2026, 2),
                )
            with self.assertRaisesRegex(ValueError, "aware datetime"):
                anac.inspect_vra_file(
                    path,
                    retrieved_at_utc=datetime(2026, 2, 1),
                )


if __name__ == "__main__":
    unittest.main()
