"""Strict annual-container tests using a complete synthetic daily calendar."""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import struct
import sys
import tempfile
import warnings
import zipfile
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
siros = importlib.import_module("global.sources.anac_siros")


RETRIEVED = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
VALIDATOR_COMMIT = siros.ANAC_SIROS_ANNUAL_VALIDATOR_GENERATION_COMMIT
VALIDATOR_SOURCE_SHA256 = siros.ANAC_SIROS_ANNUAL_VALIDATOR_SOURCE_SHA256


def _calendar(year: int) -> tuple[date, ...]:
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    return tuple(
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
    )


def _source_row(year: int) -> tuple[str, ...]:
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
        "Nº SIROS": f"AAL-{year}-SERIES",
        "Situação SIROS": "A Operar",
        "Data Registro": f"01/01/{year} 01:02:03",
        "Início Operação": f"{year}-01-01",
        "Fim Operação": f"{year}-12-31",
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
    return tuple(values[header] for header in siros.ANAC_SIROS_SERIES_HEADERS)


def _member_bytes(
    year: int,
    *,
    wrong_schema: bool = False,
    rejected_count: int = 0,
) -> bytes:
    headers = list(siros.ANAC_SIROS_SERIES_HEADERS)
    if wrong_schema:
        headers[0] = "Wrong"
    rows = [list(_source_row(year))]
    siros_index = siros.ANAC_SIROS_SERIES_HEADERS.index("Nº SIROS")
    departure_index = siros.ANAC_SIROS_SERIES_HEADERS.index("Horário Partida")
    for index in range(rejected_count):
        rejected = list(_source_row(year))
        rejected[siros_index] = f"REJECTED-{index:04d}"
        rejected[departure_index] = "25:00"
        rows.append(rejected)
    text = "\r\n".join(
        [
            siros.ANAC_SIROS_UTC_NOTE,
            ";".join(headers),
            *(";".join(row) for row in rows),
            "",
        ]
    )
    return text.encode("utf-8-sig")


def _write_archive(
    path: Path,
    *,
    year: int = 2023,
    omit: date | None = None,
    stored: date | None = None,
    wrong_schema: date | None = None,
    extra_name: str | None = None,
    duplicate: date | None = None,
    rejected_at: date | None = None,
    rejected_count: int = 0,
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{year}/", b"")
        for snapshot_date in _calendar(year):
            if snapshot_date == omit:
                continue
            name = f"{year}/futuro_{snapshot_date.isoformat()}.csv"
            compression = (
                zipfile.ZIP_STORED
                if snapshot_date == stored
                else zipfile.ZIP_DEFLATED
            )
            archive.writestr(
                name,
                _member_bytes(
                    year,
                    wrong_schema=snapshot_date == wrong_schema,
                    rejected_count=(
                        rejected_count if snapshot_date == rejected_at else 0
                    ),
                ),
                compress_type=compression,
            )
            if snapshot_date == duplicate:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    archive.writestr(
                        name,
                        _member_bytes(year),
                        compress_type=zipfile.ZIP_DEFLATED,
                    )
        if extra_name is not None:
            archive.writestr(
                extra_name,
                _member_bytes(year),
                compress_type=zipfile.ZIP_DEFLATED,
            )


def _pin(path: Path, *, year: int = 2023) -> siros.AnacSirosAnnualArchivePin:
    raw = path.read_bytes()
    resource = siros.annual_zip_resource(year)
    return siros.AnacSirosAnnualArchivePin(
        resource=resource,
        source_url=resource.url,
        retrieved_at_utc=RETRIEVED,
        expected_sha256=hashlib.sha256(raw).hexdigest(),
        expected_bytes=len(raw),
        archive_last_modified_utc=siros.ANAC_SIROS_2023_ARCHIVE_LAST_MODIFIED_UTC,
        archive_last_modified_raw=siros.ANAC_SIROS_2023_ARCHIVE_LAST_MODIFIED_RAW,
    )


def _validate(path: Path) -> siros.AnacSirosAnnualArchiveAudit:
    return siros.validate_siros_annual_archive(
        path,
        pin=_pin(path),
        evidence_policy=siros.AnacSirosRetrospectiveEvidencePolicy(),
    )


def _audit_document(
    audit: siros.AnacSirosAnnualArchiveAudit,
) -> dict[str, object]:
    return siros.build_siros_annual_archive_audit_document(
        audit,
        validator_generation_commit=VALIDATOR_COMMIT,
        validator_source_sha256=VALIDATOR_SOURCE_SHA256,
    )


def _write_audit_document(
    path: Path,
    document: dict[str, object],
    *,
    expected_audit_sha256: str,
) -> siros.AnacSirosAnnualAuditFilePin:
    path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )
    raw = path.read_bytes()
    return siros.AnacSirosAnnualAuditFilePin(
        path=path,
        schema_version=siros.ANAC_SIROS_ANNUAL_AUDIT_SCHEMA_VERSION,
        validator_contract=siros.ANAC_SIROS_ANNUAL_VALIDATOR_CONTRACT,
        validator_generation_commit=VALIDATOR_COMMIT,
        validator_source_path=siros.ANAC_SIROS_ANNUAL_VALIDATOR_SOURCE_PATH,
        validator_source_sha256=VALIDATOR_SOURCE_SHA256,
        expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
        expected_raw_bytes=len(raw),
        expected_document_sha256=str(document["document_sha256"]),
        expected_audit_sha256=expected_audit_sha256,
    )


def _refresh_document_sha256(document: dict[str, object]) -> None:
    payload = {
        "schema_version": document["schema_version"],
        "validator_contract": document["validator_contract"],
        "audit": document["audit"],
    }
    document["document_sha256"] = siros._canonical_hash(payload)


def test_complete_archive_is_streamed_audited_and_retrospective_only() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "2023.zip"
        _write_archive(path)
        archive_size = path.stat().st_size
        audit = _validate(path)
        after_validation = sorted(entry.name for entry in Path(directory).iterdir())
        snapshot = siros.load_siros_annual_member(
            path,
            audit=audit,
            snapshot_date=date(2023, 1, 1),
        )

    assert after_validation == ["2023.zip"]
    assert audit.archive.archive_bytes == archive_size
    assert audit.archive.archive_last_modified_utc == datetime(
        2024, 7, 5, 1, 38, 23, tzinfo=timezone.utc
    )
    assert audit.expected_member_count == 365
    assert audit.actual_member_count == 365
    assert audit.first_snapshot_date == date(2023, 1, 1)
    assert audit.last_snapshot_date == date(2023, 12, 31)
    assert audit.calendar_complete
    assert audit.total_raw_row_count == 365
    assert audit.total_accepted_row_count == 365
    assert audit.total_rejected_row_count == 0
    assert not audit.point_in_time_publication_evidence
    assert audit.evidence_policy.scope == "retrospective_only"
    assert all(member.compression_method == "deflate" for member in audit.members)
    assert all(member.central_crc32 == member.computed_crc32 for member in audit.members)

    row = snapshot.rows[0]
    assert row.snapshot_date == date(2023, 1, 1)
    assert row.schedule_observed_at_utc == datetime(
        2023, 1, 2, 0, 0, tzinfo=timezone.utc
    )
    assert row.schedule_observed_at_utc != audit.archive.archive_last_modified_utc
    assert not row.public_availability_proven
    assert not row.point_in_time_eligible
    assert row.evidence_policy_id == siros.ANAC_SIROS_RETROSPECTIVE_POLICY_ID
    assert row.source_url.endswith("#member=2023/futuro_2023-01-01.csv")
    with pytest.raises(siros.AnacSirosSourceError, match="public visibility"):
        row.visible_at(datetime(2023, 1, 3, tzinfo=timezone.utc))
    with pytest.raises(siros.AnacSirosSourceError, match="point-in-time selection"):
        siros.select_services_at_t_minus_7(
            snapshot.rows,
            service_date=date(2023, 1, 10),
            target_departure_utc=datetime(
                2023, 1, 10, 12, tzinfo=timezone.utc
            ),
        )
    selected = siros.select_retrospective_services_at_t_minus_7(
        snapshot.rows,
        service_date=date(2023, 1, 10),
        target_departure_utc=datetime(2023, 1, 10, 12, tzinfo=timezone.utc),
    )
    assert len(selected) == 1
    assert not selected[0].point_in_time_eligible
    with pytest.raises(siros.AnacSirosSourceError, match="public visibility"):
        selected[0].visible_at(datetime(2023, 1, 3, tzinfo=timezone.utc))


def test_archive_and_member_audit_digests_are_deterministic() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "2023.zip"
        _write_archive(path)
        first = _validate(path)
        second = _validate(path)
    assert first.archive_content_sha256 == second.archive_content_sha256
    assert first.audit_sha256 == second.audit_sha256
    assert [row.member_content_sha256 for row in first.members] == [
        row.member_content_sha256 for row in second.members
    ]


def test_leap_year_archive_requires_all_366_daily_members() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "2020.zip"
        _write_archive(path, year=2020)
        audit = siros.validate_siros_annual_archive(
            path,
            pin=_pin(path, year=2020),
            evidence_policy=siros.AnacSirosRetrospectiveEvidencePolicy(),
        )
    assert audit.expected_member_count == 366
    assert audit.actual_member_count == 366
    assert audit.members[59].snapshot_date == date(2020, 2, 29)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"omit": date(2023, 6, 1)}, "calendar is not exact"),
        ({"extra_name": "../escape.csv"}, "unsafe member path"),
        ({"duplicate": date(2023, 1, 1)}, "duplicate member name"),
        ({"stored": date(2023, 1, 1)}, "not DEFLATE-compressed"),
        ({"wrong_schema": date(2023, 1, 1)}, "headers"),
    ],
)
def test_full_archive_validation_rejects_shape_and_schema_drift(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "2023.zip"
        _write_archive(path, **kwargs)
        with pytest.raises(siros.AnacSirosError, match=message):
            _validate(path)


def test_central_crc_mismatch_is_detected_without_extraction() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "2023.zip"
        _write_archive(path)
        raw = bytearray(path.read_bytes())
        target = b"2023/futuro_2023-01-01.csv"
        search_at = 0
        patched = False
        while True:
            central = raw.find(b"PK\x01\x02", search_at)
            if central < 0:
                break
            name_length = struct.unpack_from("<H", raw, central + 28)[0]
            extra_length = struct.unpack_from("<H", raw, central + 30)[0]
            comment_length = struct.unpack_from("<H", raw, central + 32)[0]
            name = bytes(raw[central + 46 : central + 46 + name_length])
            if name == target:
                crc = struct.unpack_from("<I", raw, central + 16)[0]
                struct.pack_into("<I", raw, central + 16, crc ^ 0xFFFFFFFF)
                patched = True
                break
            search_at = central + 46 + name_length + extra_length + comment_length
        assert patched
        path.write_bytes(raw)
        with pytest.raises(siros.AnacSirosSourceError, match="CRC"):
            _validate(path)


def test_official_2023_helper_keeps_reviewed_container_metadata_separate() -> None:
    pin = siros.official_2023_annual_archive_pin(
        expected_sha256="a" * 64,
        retrieved_at_utc=RETRIEVED,
    )
    assert pin.expected_bytes == 340_405_397
    assert pin.archive_last_modified_utc == datetime(
        2024, 7, 5, 1, 38, 23, tzinfo=timezone.utc
    )
    assert not hasattr(pin, "snapshot_observed_at_utc")


def test_full_validation_streams_audit_only_and_bounds_rejection_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "2023.zip"
        _write_archive(
            path,
            rejected_at=date(2023, 1, 1),
            rejected_count=150,
        )

        def fail_full_snapshot(*args: object, **kwargs: object) -> object:
            raise AssertionError("full snapshot construction entered validation")

        monkeypatch.setattr(
            siros,
            "_build_siros_series_snapshot",
            fail_full_snapshot,
        )
        audit = _validate(path)

    first = audit.members[0]
    assert first.raw_row_count == 151
    assert first.accepted_row_count == 1
    assert first.rejected_row_count == 150
    assert first.rejection_detail_limit == 100
    assert first.rejection_detail_count == 100
    assert first.rejection_detail_truncated_count == 50
    assert len(first.rejected_rows) == 100


def test_validation_hash_and_zip_scan_share_one_open_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "2023.zip"
        _write_archive(path)
        pin = _pin(path)
        opened_bytes = path.read_bytes()
        path.write_bytes(b"replacement path bytes are not a ZIP")
        original_open = Path.open
        open_count = 0

        def pinned_open(self: Path, mode: str = "r", *args: object, **kwargs: object):
            nonlocal open_count
            if self.resolve() == path.resolve() and mode == "rb":
                open_count += 1
                return io.BytesIO(opened_bytes)
            return original_open(self, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "open", pinned_open)
        audit = siros.validate_siros_annual_archive(
            path,
            pin=pin,
            evidence_policy=siros.AnacSirosRetrospectiveEvidencePolicy(),
        )

    assert open_count == 1
    assert audit.archive.archive_sha256 == hashlib.sha256(opened_bytes).hexdigest()


def test_selected_member_hash_and_scan_share_one_open_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "2023.zip"
        _write_archive(path)
        audit = _validate(path)
        opened_bytes = path.read_bytes()
        path.write_bytes(b"replacement path bytes are not a ZIP")
        original_open = Path.open
        open_count = 0

        def pinned_open(self: Path, mode: str = "r", *args: object, **kwargs: object):
            nonlocal open_count
            if self.resolve() == path.resolve() and mode == "rb":
                open_count += 1
                return io.BytesIO(opened_bytes)
            return original_open(self, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "open", pinned_open)
        snapshot = siros.load_siros_annual_member(
            path,
            audit=audit,
            snapshot_date=date(2023, 1, 1),
        )

    assert open_count == 1
    assert snapshot.rows[0].snapshot_date == date(2023, 1, 1)


def test_validation_postscan_rehash_detects_in_place_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "2023.zip"
        _write_archive(path)
        pin = _pin(path)
        opened_bytes = path.read_bytes()
        original_open = Path.open
        original_scan = siros._scan_annual_member_audit

        def pinned_open(self: Path, mode: str = "r", *args: object, **kwargs: object):
            if self.resolve() == path.resolve() and mode == "rb":
                return io.BytesIO(opened_bytes)
            return original_open(self, mode, *args, **kwargs)

        def mutating_scan(
            archive: zipfile.ZipFile,
            info: zipfile.ZipInfo,
            **kwargs: object,
        ) -> object:
            result = original_scan(archive, info, **kwargs)
            if info.filename.endswith("futuro_2023-12-31.csv"):
                archive.fp.seek(0, 2)
                archive.fp.write(b"mutated-after-scan")
            return result

        monkeypatch.setattr(Path, "open", pinned_open)
        monkeypatch.setattr(siros, "_scan_annual_member_audit", mutating_scan)
        with pytest.raises(siros.AnacSirosSourceError, match="changed during validation"):
            siros.validate_siros_annual_archive(
                path,
                pin=pin,
                evidence_policy=siros.AnacSirosRetrospectiveEvidencePolicy(),
            )


def test_completed_audit_wrapper_round_trips_without_rescanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        archive_path = Path(directory) / "2023.zip"
        audit_path = Path(directory) / "2023-audit.json"
        _write_archive(archive_path)
        archive_pin = _pin(archive_path)
        policy = siros.AnacSirosRetrospectiveEvidencePolicy()
        audit = siros.validate_siros_annual_archive(
            archive_path,
            pin=archive_pin,
            evidence_policy=policy,
        )
        audit_pin = _write_audit_document(
            audit_path,
            _audit_document(audit),
            expected_audit_sha256=audit.audit_sha256,
        )
        monkeypatch.setattr(
            siros,
            "_scan_annual_member_audit",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("completed audit was rescanned")
            ),
        )
        loaded = siros.load_siros_annual_archive_audit(
            audit_path,
            pin=audit_pin,
            archive_path=archive_path,
            archive_pin=archive_pin,
            evidence_policy=policy,
        )

    assert loaded == audit


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("member_digest", "member content digest"),
        ("member_order", "member date"),
        ("archive_digest", "archive-content digest"),
    ],
)
def test_semantically_repinned_audit_tampering_fails_closed(
    mutation: str,
    message: str,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        archive_path = Path(directory) / "2023.zip"
        audit_path = Path(directory) / "2023-audit.json"
        _write_archive(archive_path)
        archive_pin = _pin(archive_path)
        policy = siros.AnacSirosRetrospectiveEvidencePolicy()
        audit = siros.validate_siros_annual_archive(
            archive_path,
            pin=archive_pin,
            evidence_policy=policy,
        )
        document = _audit_document(audit)
        raw_audit = document["audit"]
        assert isinstance(raw_audit, dict)
        members = raw_audit["members"]
        assert isinstance(members, list)
        if mutation == "member_digest":
            members[0]["member_sha256"] = "f" * 64
        elif mutation == "member_order":
            members[0], members[1] = members[1], members[0]
        else:
            raw_audit["archive_content_sha256"] = "f" * 64
        _refresh_document_sha256(document)
        audit_pin = _write_audit_document(
            audit_path,
            document,
            expected_audit_sha256=audit.audit_sha256,
        )
        with pytest.raises((siros.AnacSirosError, ValueError), match=message):
            siros.load_siros_annual_archive_audit(
                audit_path,
                pin=audit_pin,
                archive_path=archive_path,
                archive_pin=archive_pin,
                evidence_policy=policy,
            )


def test_self_consistent_repinned_wrong_evidence_bound_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        archive_path = Path(directory) / "2023.zip"
        audit_path = Path(directory) / "2023-audit.json"
        _write_archive(archive_path)
        archive_pin = _pin(archive_path)
        policy = siros.AnacSirosRetrospectiveEvidencePolicy()
        audit = siros.validate_siros_annual_archive(
            archive_path,
            pin=archive_pin,
            evidence_policy=policy,
        )
        document = _audit_document(audit)
        raw_audit = document["audit"]
        assert isinstance(raw_audit, dict)
        members = raw_audit["members"]
        assert isinstance(members, list)
        wrong_bound = audit.members[0].retrospective_evidence_bound_utc + timedelta(
            hours=1
        )
        wrong_member = replace(
            audit.members[0],
            retrospective_evidence_bound_utc=wrong_bound,
            member_content_sha256="0" * 64,
        )
        wrong_member_sha256 = siros._canonical_hash(
            siros._annual_member_content_facts(
                wrong_member,
                evidence_policy_id=policy.policy_id,
            )
        )
        members[0]["retrospective_evidence_bound_utc"] = (
            wrong_bound.isoformat().replace("+00:00", "Z")
        )
        members[0]["member_content_sha256"] = wrong_member_sha256
        archive_content_sha256 = hashlib.sha256(
            "\n".join(
                str(member["member_content_sha256"]) for member in members
            ).encode("ascii")
        ).hexdigest()
        raw_audit["archive_content_sha256"] = archive_content_sha256
        audit_sha256 = siros._annual_archive_audit_digest(
            audit.archive,
            policy,
            member_count=len(audit.members),
            archive_content_sha256=archive_content_sha256,
            total_compressed_bytes=audit.total_compressed_bytes,
            total_uncompressed_bytes=audit.total_uncompressed_bytes,
            total_raw_row_count=audit.total_raw_row_count,
            total_accepted_row_count=audit.total_accepted_row_count,
            total_rejected_row_count=audit.total_rejected_row_count,
        )
        raw_audit["audit_sha256"] = audit_sha256
        _refresh_document_sha256(document)
        audit_pin = _write_audit_document(
            audit_path,
            document,
            expected_audit_sha256=audit_sha256,
        )
        with pytest.raises(siros.AnacSirosSourceError, match="evidence bound"):
            siros.load_siros_annual_archive_audit(
                audit_path,
                pin=audit_pin,
                archive_path=archive_path,
                archive_pin=archive_pin,
                evidence_policy=policy,
            )


def test_validator_contract_is_anchored_to_reviewed_commit_and_source() -> None:
    with tempfile.TemporaryDirectory() as directory:
        archive_path = Path(directory) / "2023.zip"
        audit_path = Path(directory) / "2023-audit.json"
        _write_archive(archive_path)
        archive_pin = _pin(archive_path)
        policy = siros.AnacSirosRetrospectiveEvidencePolicy()
        audit = siros.validate_siros_annual_archive(
            archive_path,
            pin=archive_pin,
            evidence_policy=policy,
        )
        audit_pin = _write_audit_document(
            audit_path,
            _audit_document(audit),
            expected_audit_sha256=audit.audit_sha256,
        )
        with pytest.raises(siros.AnacSirosSourceError, match="generation commit"):
            replace(audit_pin, validator_generation_commit="f" * 40)
        with pytest.raises(siros.AnacSirosSourceError, match="source SHA-256"):
            replace(audit_pin, validator_source_sha256="f" * 64)
        with pytest.raises(siros.AnacSirosSourceError, match="generation commit"):
            siros.build_siros_annual_archive_audit_document(
                audit,
                validator_generation_commit="f" * 40,
                validator_source_sha256=VALIDATOR_SOURCE_SHA256,
            )


def test_audit_raw_size_cap_uses_a_bounded_read() -> None:
    with tempfile.TemporaryDirectory() as directory:
        archive_path = Path(directory) / "2023.zip"
        audit_path = Path(directory) / "2023-audit.json"
        _write_archive(archive_path)
        archive_pin = _pin(archive_path)
        policy = siros.AnacSirosRetrospectiveEvidencePolicy()
        audit = siros.validate_siros_annual_archive(
            archive_path,
            pin=archive_pin,
            evidence_policy=policy,
        )
        audit_pin = _write_audit_document(
            audit_path,
            _audit_document(audit),
            expected_audit_sha256=audit.audit_sha256,
        )
        with pytest.raises(siros.AnacSirosSourceError, match="reviewed bound"):
            replace(
                audit_pin,
                expected_raw_bytes=siros.ANAC_SIROS_ANNUAL_AUDIT_MAX_RAW_BYTES + 1,
            )
        audit_path.write_bytes(
            b"x" * (siros.ANAC_SIROS_ANNUAL_AUDIT_MAX_RAW_BYTES + 1)
        )
        with pytest.raises(siros.AnacSirosSourceError, match="allocation bound"):
            siros.load_siros_annual_archive_audit(
                audit_path,
                pin=audit_pin,
                archive_path=archive_path,
                archive_pin=archive_pin,
                evidence_policy=policy,
            )


def test_audit_nested_collection_and_string_caps_fail_before_reconstruction() -> None:
    with tempfile.TemporaryDirectory() as directory:
        archive_path = Path(directory) / "2023.zip"
        audit_path = Path(directory) / "2023-audit.json"
        _write_archive(archive_path)
        archive_pin = _pin(archive_path)
        policy = siros.AnacSirosRetrospectiveEvidencePolicy()
        audit = siros.validate_siros_annual_archive(
            archive_path,
            pin=archive_pin,
            evidence_policy=policy,
        )
        base_document = _audit_document(audit)
        rejection = {
            "row_number": 3,
            "reason": "invalid row",
            "record_hint": "ROW",
            "source_values": ["x"],
        }
        for case in ("rejections", "values", "string"):
            document = json.loads(json.dumps(base_document))
            raw_audit = document["audit"]
            members = raw_audit["members"]
            first = members[0]
            if case == "rejections":
                first["rejected_rows"] = [rejection] * (
                    siros.ANAC_SIROS_ANNUAL_REJECTION_DETAIL_LIMIT + 1
                )
            elif case == "values":
                oversized = dict(rejection)
                oversized["source_values"] = ["x"] * (
                    siros.ANAC_SIROS_ANNUAL_AUDIT_MAX_SOURCE_VALUES + 1
                )
                first["rejected_rows"] = [oversized]
            else:
                oversized = dict(rejection)
                oversized["source_values"] = [
                    "x"
                    * (siros.ANAC_SIROS_ANNUAL_AUDIT_MAX_SOURCE_VALUE_CHARS + 1)
                ]
                first["rejected_rows"] = [oversized]
            _refresh_document_sha256(document)
            audit_pin = _write_audit_document(
                audit_path,
                document,
                expected_audit_sha256=audit.audit_sha256,
            )
            with pytest.raises(siros.AnacSirosUnsupportedSchemaError):
                siros.load_siros_annual_archive_audit(
                    audit_path,
                    pin=audit_pin,
                    archive_path=archive_path,
                    archive_pin=archive_pin,
                    evidence_policy=policy,
                )


def test_audit_wrapper_rejects_duplicate_nonfinite_and_unknown_json() -> None:
    with tempfile.TemporaryDirectory() as directory:
        archive_path = Path(directory) / "2023.zip"
        audit_path = Path(directory) / "2023-audit.json"
        _write_archive(archive_path)
        archive_pin = _pin(archive_path)
        policy = siros.AnacSirosRetrospectiveEvidencePolicy()
        audit = siros.validate_siros_annual_archive(
            archive_path,
            pin=archive_pin,
            evidence_policy=policy,
        )
        document = _audit_document(audit)
        valid_raw = json.dumps(
            document, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        cases = {
            "duplicate": valid_raw.replace(
                b'"schema_version":',
                (
                    b'"schema_version":"'
                    + siros.ANAC_SIROS_ANNUAL_AUDIT_SCHEMA_VERSION.encode("ascii")
                    + b'","schema_version":'
                ),
                1,
            ),
            "non-finite": valid_raw[:-1] + b',"extra":NaN}',
            "unknown": valid_raw[:-1] + b',"extra":true}',
        }
        for name, raw in cases.items():
            audit_path.write_bytes(raw)
            audit_pin = replace(
                _write_audit_document(
                    audit_path,
                    document,
                    expected_audit_sha256=audit.audit_sha256,
                ),
                expected_raw_sha256=hashlib.sha256(raw).hexdigest(),
                expected_raw_bytes=len(raw),
            )
            audit_path.write_bytes(raw)
            with pytest.raises(siros.AnacSirosError):
                siros.load_siros_annual_archive_audit(
                    audit_path,
                    pin=audit_pin,
                    archive_path=archive_path,
                    archive_pin=archive_pin,
                    evidence_policy=policy,
                )


def test_audit_archive_provenance_requires_exact_retrieval_timestamp() -> None:
    with tempfile.TemporaryDirectory() as directory:
        archive_path = Path(directory) / "2023.zip"
        audit_path = Path(directory) / "2023-audit.json"
        _write_archive(archive_path)
        archive_pin = _pin(archive_path)
        policy = siros.AnacSirosRetrospectiveEvidencePolicy()
        audit = siros.validate_siros_annual_archive(
            archive_path,
            pin=archive_pin,
            evidence_policy=policy,
        )
        audit_pin = _write_audit_document(
            audit_path,
            _audit_document(audit),
            expected_audit_sha256=audit.audit_sha256,
        )
        mismatched_archive_pin = replace(
            archive_pin,
            retrieved_at_utc=archive_pin.retrieved_at_utc + timedelta(seconds=1),
        )
        with pytest.raises(siros.AnacSirosSourceError, match="provenance"):
            siros.load_siros_annual_archive_audit(
                audit_path,
                pin=audit_pin,
                archive_path=archive_path,
                archive_pin=mismatched_archive_pin,
                evidence_policy=policy,
            )


def test_selected_snapshot_final_rehash_detects_mutation_on_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "2023.zip"
        _write_archive(path)
        audit = _validate(path)
        opened_bytes = path.read_bytes()
        original_open = Path.open
        original_load = siros._load_annual_member_snapshot

        def pinned_open(self: Path, mode: str = "r", *args: object, **kwargs: object):
            if self.resolve() == path.resolve() and mode == "rb":
                return io.BytesIO(opened_bytes)
            return original_open(self, mode, *args, **kwargs)

        def mutating_load(
            archive: zipfile.ZipFile,
            info: zipfile.ZipInfo,
            **kwargs: object,
        ) -> object:
            result = original_load(archive, info, **kwargs)
            archive.fp.seek(0, 2)
            archive.fp.write(b"mutated-after-selected-load")
            return result

        monkeypatch.setattr(Path, "open", pinned_open)
        monkeypatch.setattr(siros, "_load_annual_member_snapshot", mutating_load)
        with pytest.raises(siros.AnacSirosSourceError, match="selected members"):
            siros.load_siros_annual_member(
                path,
                audit=audit,
                snapshot_date=date(2023, 1, 1),
            )
