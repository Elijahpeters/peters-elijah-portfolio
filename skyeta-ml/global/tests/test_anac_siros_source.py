"""Synthetic tests mirroring the exact reviewed SIROS daily-series format."""

from __future__ import annotations

import hashlib
import importlib
import sys
import tempfile
from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
siros = importlib.import_module("global.sources.anac_siros")


RETRIEVED = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
SAMPLE_OBSERVED = datetime(2025, 1, 1, 7, 26, 25, tzinfo=timezone.utc)
SAMPLE_LAST_MODIFIED = "Wed, 01 Jan 2025 07:26:25 GMT"


def source_row(**overrides: str) -> tuple[str, ...]:
    values = {
        "Cód. Empresa": "AAL",
        "Empresa": "AMERICAN AIRLINES INC.",
        "Nº Voo": "0904",
        "Equip.": "B772",
        "Seg": "1",
        "Ter": "2",
        "Qua": "3",
        "Qui": "4",
        "Sex": "5",
        "Sáb": "6",
        "Dom": "7",
        "Quant. Assentos": "288",
        "Nº SIROS": "AAL-0000000000031095703",
        "Situação SIROS": "A Operar",
        "Data Registro": "26/09/2024 11:06:09",
        "Início Operação": "2025-03-30",
        "Fim Operação": "2025-10-25",
        "Natureza Operação": "INTERNACIONAL",
        "Nº Etapa": "1",
        "Cód. Origem": "SBGL",
        "Arpt Origem": "RIO DE JANEIRO/GALEAO",
        "Cód Destino": "KMIA",
        "Arpt Destino": "MIAMI INTERNATIONAL",
        "Horário Partida": "02:00",
        "Horário Chegada": "10:35",
        "Tipo Serviço": "REGULAR DE PASSAGEIROS",
        "Objeto Transporte": "PASSAGEIROS",
        "Codeshare": "",
    }
    unknown = set(overrides) - set(values)
    if unknown:
        raise AssertionError(f"unknown fixture columns: {sorted(unknown)}")
    values.update(overrides)
    return tuple(values[header] for header in siros.ANAC_SIROS_SERIES_HEADERS)


def series_bytes(
    *rows: tuple[str, ...],
    note: str = siros.ANAC_SIROS_UTC_NOTE,
    headers: tuple[str, ...] = siros.ANAC_SIROS_SERIES_HEADERS,
    bom: bool = True,
) -> bytes:
    text = "\r\n".join(
        [note, ";".join(headers), *(";".join(row) for row in rows)]
    ) + "\r\n"
    return text.encode("utf-8-sig" if bom else "utf-8")


def http_date(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def write_http_pinned(
    directory: str,
    raw: bytes,
    *,
    snapshot_date: date = date(2025, 1, 1),
    observed_at: datetime = SAMPLE_OBSERVED,
    last_modified_raw: str = SAMPLE_LAST_MODIFIED,
) -> tuple[Path, siros.AnacSirosSnapshotPin]:
    resource = siros.daily_snapshot_resource(snapshot_date)
    path = Path(directory) / resource.filename
    path.write_bytes(raw)
    pin = siros.AnacSirosSnapshotPin(
        resource=resource,
        source_url=resource.url,
        availability_evidence_kind="http_last_modified",
        snapshot_observed_at_utc=observed_at,
        retrieved_at_utc=RETRIEVED,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        expected_bytes=len(raw),
        http_last_modified_utc=observed_at,
        http_last_modified_raw=last_modified_raw,
    )
    return path, pin


def load_rows(
    directory: str,
    *rows: tuple[str, ...],
    snapshot_date: date = date(2025, 1, 1),
    observed_at: datetime = SAMPLE_OBSERVED,
    last_modified_raw: str = SAMPLE_LAST_MODIFIED,
) -> siros.AnacSirosSeriesSnapshot:
    raw = series_bytes(*rows)
    path, pin = write_http_pinned(
        directory,
        raw,
        snapshot_date=snapshot_date,
        observed_at=observed_at,
        last_modified_raw=last_modified_raw,
    )
    return siros.load_siros_series_snapshot(path, pin=pin)


def test_official_manifest_covers_proven_annual_and_daily_shapes() -> None:
    annual = siros.annual_archive_manifest()
    assert [resource.year for resource in annual] == list(range(2018, 2024))
    assert annual[0].url.endswith("/2018.zip")
    assert annual[-1].url.endswith("/2023.zip")
    assert all(resource.kind == "annual_zip" for resource in annual)

    daily = siros.daily_snapshot_manifest(date(2024, 2, 28), date(2024, 3, 1))
    assert [resource.snapshot_date for resource in daily] == [
        date(2024, 2, 28),
        date(2024, 2, 29),
        date(2024, 3, 1),
    ]
    assert daily[1].url.endswith("/2024/futuro_2024-02-29.csv")
    with pytest.raises(ValueError, match="2024 through 2026"):
        siros.daily_snapshot_resource(date(2023, 12, 31))


def test_loads_exact_reviewed_note_headers_and_full_source_strings() -> None:
    raw = series_bytes(source_row())
    with tempfile.TemporaryDirectory() as directory:
        path, pin = write_http_pinned(directory, raw)
        snapshot = siros.load_siros_series_snapshot(path, pin=pin)

    assert len(snapshot.rows) == 1
    row = snapshot.rows[0]
    assert row.siros_id == "AAL-0000000000031095703"
    assert row.revision_identity == row.siros_id
    assert row.stage_revision_key.endswith(":AAL-0000000000031095703:stage:1")
    assert row.operating_carrier == "AAL"
    assert row.operating_flight_number == "0904"
    assert row.aircraft_family == "B772"
    assert row.origin_icao == "SBGL"
    assert row.destination_icao == "KMIA"
    assert row.valid_from == date(2025, 3, 30)
    assert row.valid_until == date(2025, 10, 25)
    assert row.active_weekdays == (True, True, True, True, True, True, True)
    assert row.registration_raw == "26/09/2024 11:06:09"
    assert row.source_strings["Empresa"] == "AMERICAN AIRLINES INC."
    assert row.source_strings["Equip."] == "B772"
    assert row.source_strings["Quant. Assentos"] == "288"
    assert row.source_strings["Situação SIROS"] == "A Operar"
    assert row.source_strings["Codeshare"] == ""
    assert not hasattr(row, "registered_at_utc")
    assert not hasattr(row, "replaces_siros_id")

    audit = snapshot.audit
    assert audit.note_line == "Importante: Horários em UTC"
    assert audit.exact_headers == siros.ANAC_SIROS_SERIES_HEADERS
    assert audit.raw_row_count == 1
    assert audit.accepted_row_count == 1
    assert audit.rejected_row_count == 0
    assert audit.file.raw_file_sha256 == hashlib.sha256(raw).hexdigest()
    assert audit.file.raw_bytes == len(raw)
    assert audit.file.availability_evidence_kind == "http_last_modified"
    assert audit.file.snapshot_observed_at_utc == SAMPLE_OBSERVED
    assert audit.file.http_last_modified_utc == SAMPLE_OBSERVED
    assert audit.file.http_last_modified_raw == SAMPLE_LAST_MODIFIED
    assert audit.file.to_dict()["http_last_modified_utc"] == "2025-01-01T07:26:25Z"
    assert audit.file.to_dict()["http_last_modified_raw"] == SAMPLE_LAST_MODIFIED

    with pytest.raises(FrozenInstanceError):
        row.siros_id = "changed"
    with pytest.raises(TypeError):
        row.source_strings["Empresa"] = "changed"


def test_equipment_is_normalized_from_schedule_and_blank_stays_unknown() -> None:
    with tempfile.TemporaryDirectory() as directory:
        normalized = load_rows(
            directory, source_row(**{"Equip.": "  b772  "})
        ).rows[0]
        unknown = load_rows(
            directory, source_row(**{"Equip.": "   "})
        ).rows[0]

    assert normalized.aircraft_family == "B772"
    assert normalized.to_dict()["aircraft_family"] == "B772"
    assert unknown.aircraft_family is None
    assert normalized.series_facts_sha256 != unknown.series_facts_sha256

    expanded = siros.expand_siros_series_row(normalized, date(2025, 3, 30))
    assert expanded is not None
    assert expanded.aircraft_family == "B772"
    assert expanded.to_dict()["aircraft_family"] == "B772"


def test_weekday_and_validity_control_deterministic_service_expansion() -> None:
    sunday_only = source_row(
        Seg="0",
        Ter="0",
        Qua="0",
        Qui="0",
        Sex="0",
        Sáb="0",
        Dom="7",
    )
    with tempfile.TemporaryDirectory() as directory:
        row = load_rows(directory, sunday_only).rows[0]

    active = siros.expand_siros_series_row(row, date(2025, 3, 30))
    assert active is not None
    assert active.scheduled_departure_utc == datetime(
        2025, 3, 30, 2, 0, tzinfo=timezone.utc
    )
    assert active.scheduled_arrival_utc == datetime(
        2025, 3, 30, 10, 35, tzinfo=timezone.utc
    )
    assert siros.expand_siros_series_row(row, date(2025, 3, 31)) is None
    assert siros.expand_siros_series_row(row, date(2025, 3, 23)) is None
    assert siros.expand_siros_series_row(row, date(2025, 10, 26)) is None

    boundary = source_row(
        **{
            "Início Operação": "2025-03-30",
            "Fim Operação": "2025-03-30",
        }
    )
    with tempfile.TemporaryDirectory() as directory:
        boundary_row = load_rows(directory, boundary).rows[0]
    assert siros.expand_siros_series_row(boundary_row, date(2025, 3, 30)) is not None


def test_overnight_arrival_is_minimal_positive_utc_interval() -> None:
    overnight = source_row(
        **{
            "Horário Partida": "23:30",
            "Horário Chegada": "05:15",
        }
    )
    with tempfile.TemporaryDirectory() as directory:
        row = load_rows(directory, overnight).rows[0]
    observation = siros.expand_siros_series_row(row, date(2025, 3, 30))
    assert observation is not None
    assert observation.scheduled_departure_utc == datetime(
        2025, 3, 30, 23, 30, tzinfo=timezone.utc
    )
    assert observation.scheduled_arrival_utc == datetime(
        2025, 3, 31, 5, 15, tzinfo=timezone.utc
    )
    assert observation.scheduled_arrival_utc - observation.scheduled_departure_utc == timedelta(
        hours=5, minutes=45
    )


def test_data_registro_is_preserved_but_never_used_for_leakage() -> None:
    undocumented_future_clock = source_row(
        **{"Data Registro": "31/12/2099 23:59:59"}
    )
    with tempfile.TemporaryDirectory() as directory:
        row = load_rows(directory, undocumented_future_clock).rows[0]
    assert row.registration_raw == "31/12/2099 23:59:59"
    assert not row.visible_at(SAMPLE_OBSERVED - timedelta(seconds=1))
    assert row.visible_at(SAMPLE_OBSERVED)
    observation = siros.expand_siros_series_row(row, date(2025, 3, 30))
    assert observation is not None
    assert observation.registration_raw == "31/12/2099 23:59:59"
    assert observation.visible_at(SAMPLE_OBSERVED)


def test_malformed_rows_are_excluded_and_fully_reconciled() -> None:
    malformed_clock = source_row(
        **{
            "Nº SIROS": "BAD-CLOCK",
            "Horário Partida": "25:00",
        }
    )
    equal_clocks = source_row(
        **{
            "Nº SIROS": "EQUAL-CLOCKS",
            "Horário Partida": "10:00",
            "Horário Chegada": "10:00",
        }
    )
    bad_registration = source_row(
        **{
            "Nº SIROS": "BAD-REGISTRATION",
            "Data Registro": "2024-09-26T11:06:09Z",
        }
    )
    with tempfile.TemporaryDirectory() as directory:
        snapshot = load_rows(
            directory,
            source_row(),
            malformed_clock,
            equal_clocks,
            bad_registration,
        )

    assert len(snapshot.rows) == 1
    assert snapshot.audit.raw_row_count == 4
    assert snapshot.audit.accepted_row_count == 1
    assert snapshot.audit.rejected_row_count == 3
    assert snapshot.audit.raw_row_count == (
        snapshot.audit.accepted_row_count + snapshot.audit.rejected_row_count
    )
    assert [audit.disposition for audit in snapshot.audit.row_audit] == [
        "accepted",
        "rejected",
        "rejected",
        "rejected",
    ]
    assert [row.row_number for row in snapshot.audit.rejected_rows] == [4, 5, 6]
    assert "Horário Partida" in snapshot.audit.rejected_rows[0].reason
    assert "equal departure" in snapshot.audit.rejected_rows[1].reason
    assert "Data Registro" in snapshot.audit.rejected_rows[2].reason


def test_legitimate_multistage_siros_registration_is_composite_identity() -> None:
    stage_one = source_row()
    stage_two = source_row(
        **{
            "Nº Etapa": "2",
            "Cód. Origem": "KMIA",
            "Arpt Origem": "MIAMI INTERNATIONAL",
            "Cód Destino": "KJFK",
            "Arpt Destino": "JOHN F KENNEDY INTERNATIONAL",
            "Horário Partida": "12:30",
            "Horário Chegada": "15:20",
        }
    )
    with tempfile.TemporaryDirectory() as directory:
        snapshot = load_rows(directory, stage_one, stage_two)
    assert len(snapshot.rows) == 2
    assert snapshot.rows[0].siros_id == snapshot.rows[1].siros_id
    assert snapshot.rows[0].stage_revision_key != snapshot.rows[1].stage_revision_key

    with tempfile.TemporaryDirectory() as directory:
        raw = series_bytes(stage_one, stage_one)
        path, pin = write_http_pinned(directory, raw)
        with pytest.raises(siros.AnacSirosDuplicateError, match="duplicate SIROS stage"):
            siros.load_siros_series_snapshot(path, pin=pin)

    conflicting_stage = source_row(**{"Horário Partida": "03:00"})
    with tempfile.TemporaryDirectory() as directory:
        raw = series_bytes(stage_one, conflicting_stage)
        path, pin = write_http_pinned(directory, raw)
        with pytest.raises(siros.AnacSirosConflictError, match="conflicting facts"):
            siros.load_siros_series_snapshot(path, pin=pin)


def test_t_minus_7_selection_uses_snapshot_observation_not_registration() -> None:
    target_departure = datetime(2025, 1, 10, 12, tzinfo=timezone.utc)
    cutoff = target_departure - timedelta(days=7)
    assert cutoff == datetime(2025, 1, 3, 12, tzinfo=timezone.utc)
    base_source = source_row(
        **{
            "Início Operação": "2025-01-02",
            "Fim Operação": "2025-01-31",
            "Horário Partida": "12:00",
            "Horário Chegada": "14:00",
            "Data Registro": "31/12/2099 23:59:59",
        }
    )

    with tempfile.TemporaryDirectory() as first_directory:
        first = load_rows(
            first_directory,
            base_source,
            snapshot_date=date(2025, 1, 2),
            observed_at=datetime(2025, 1, 2, 4, tzinfo=timezone.utc),
            last_modified_raw="Thu, 02 Jan 2025 04:00:00 GMT",
        ).rows[0]
    visible_revision_source = source_row(
        **{
            "Início Operação": "2025-01-02",
            "Fim Operação": "2025-01-31",
            "Horário Partida": "12:20",
            "Horário Chegada": "14:20",
            "Data Registro": "31/12/2099 23:59:59",
        }
    )
    with tempfile.TemporaryDirectory() as second_directory:
        visible_revision = load_rows(
            second_directory,
            visible_revision_source,
            snapshot_date=date(2025, 1, 3),
            observed_at=datetime(2025, 1, 3, 11, 59, tzinfo=timezone.utc),
            last_modified_raw="Fri, 03 Jan 2025 11:59:00 GMT",
        ).rows[0]
    late_revision_source = source_row(
        **{
            "Início Operação": "2025-01-02",
            "Fim Operação": "2025-01-31",
            "Horário Partida": "12:40",
            "Horário Chegada": "14:40",
            "Data Registro": "01/01/1900 00:00:00",
        }
    )
    with tempfile.TemporaryDirectory() as third_directory:
        late_revision = load_rows(
            third_directory,
            late_revision_source,
            snapshot_date=date(2025, 1, 3),
            observed_at=datetime(2025, 1, 3, 12, 1, tzinfo=timezone.utc),
            last_modified_raw="Fri, 03 Jan 2025 12:01:00 GMT",
        ).rows[0]

    selected = siros.select_services_at_t_minus_7(
        (first, visible_revision, late_revision),
        service_date=date(2025, 1, 10),
        target_departure_utc=target_departure,
    )
    assert len(selected) == 1
    assert selected[0].scheduled_departure_utc.hour == 12
    assert selected[0].scheduled_departure_utc.minute == 20
    assert selected[0].schedule_observed_at_utc == datetime(
        2025, 1, 3, 11, 59, tzinfo=timezone.utc
    )
    assert selected[0].registration_raw == "31/12/2099 23:59:59"


def test_distinct_siros_ids_are_not_inferred_as_replacements() -> None:
    first_source = source_row(**{"Nº SIROS": "SERIES-A"})
    second_source = source_row(**{"Nº SIROS": "SERIES-B"})
    with tempfile.TemporaryDirectory() as directory:
        snapshot = load_rows(directory, first_source, second_source)
    selected = siros.select_latest_visible_services(
        snapshot.rows,
        service_date=date(2025, 3, 30),
        as_of_utc=SAMPLE_OBSERVED,
    )
    assert len(selected) == 2
    assert {row.revision_identity for row in selected} == {"SERIES-A", "SERIES-B"}


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (
            series_bytes(source_row(), note="Importante: Horarios em UTC"),
            "UTC note",
        ),
        (
            series_bytes(
                source_row(),
                headers=("Wrong", *siros.ANAC_SIROS_SERIES_HEADERS[1:]),
            ),
            "headers",
        ),
        (series_bytes(source_row(), bom=False), "UTF-8 BOM"),
    ],
)
def test_note_header_and_bom_must_match_proven_format(
    raw: bytes,
    message: str,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path, pin = write_http_pinned(directory, raw)
        with pytest.raises(siros.AnacSirosUnsupportedSchemaError, match=message):
            siros.load_siros_series_snapshot(path, pin=pin)


def test_http_last_modified_pin_is_strict_and_preserves_raw_evidence() -> None:
    raw = series_bytes(source_row())
    resource = siros.daily_snapshot_resource(date(2025, 1, 1))
    common = dict(
        resource=resource,
        source_url=resource.url,
        availability_evidence_kind="http_last_modified",
        snapshot_observed_at_utc=SAMPLE_OBSERVED,
        retrieved_at_utc=RETRIEVED,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        expected_bytes=len(raw),
        archive_url=None,
        http_last_modified_utc=SAMPLE_OBSERVED,
    )
    with pytest.raises(siros.AnacSirosSourceError, match="raw and parsed"):
        siros.AnacSirosSnapshotPin(
            http_last_modified_raw="Wed, 01 Jan 2025 07:27:25 GMT",
            **common,
        )
    with pytest.raises(siros.AnacSirosSourceError, match="requires raw and parsed"):
        siros.AnacSirosSnapshotPin(http_last_modified_raw=None, **common)

    before_filename = datetime(2024, 12, 31, 23, 59, tzinfo=timezone.utc)
    with pytest.raises(siros.AnacSirosSourceError, match="predates"):
        siros.AnacSirosSnapshotPin(
            resource=resource,
            source_url=resource.url,
            availability_evidence_kind="http_last_modified",
            snapshot_observed_at_utc=before_filename,
            retrieved_at_utc=RETRIEVED,
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            expected_bytes=len(raw),
            http_last_modified_utc=before_filename,
            http_last_modified_raw="Tue, 31 Dec 2024 23:59:00 GMT",
        )


def test_annual_container_bytes_validate_but_member_parsing_stays_gated() -> None:
    raw = b"PK\x03\x04synthetic annual SIROS container"
    resource = siros.annual_zip_resource(2018)
    retrieved = datetime(2020, 12, 26, 8, 20, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / resource.filename
        path.write_bytes(raw)
        pin = siros.AnacSirosSnapshotPin(
            resource=resource,
            source_url=resource.url,
            availability_evidence_kind="retrieved_at",
            snapshot_observed_at_utc=retrieved,
            retrieved_at_utc=retrieved,
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            expected_bytes=len(raw),
        )
        provenance = siros.validate_siros_file(path, pin)
        assert provenance.raw_bytes == len(raw)
        with pytest.raises(siros.AnacSirosUnsupportedSchemaError, match="annual ZIP"):
            siros.load_siros_series_snapshot(path, pin=pin)
