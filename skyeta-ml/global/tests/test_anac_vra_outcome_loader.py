"""Tests for strict, offline ANAC VRA outcome-file loading."""

from __future__ import annotations

import hashlib
import socket
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ..anac_siros_vra_join import AnacVraOutcomeObservationProvenance
from ..anac_vra_outcome_loader import (
    AnacVraOutcomeFilePin,
    AnacVraOutcomeIntegrityError,
    AnacVraOutcomeReconciliationError,
    build_training_code_airport_index,
    load_anac_vra_outcome_file,
)
from ..sources.anac import AirportMetadata, build_vra_url


UTC = timezone.utc
SOURCE_URL = build_vra_url(2026, 1)
RETRIEVED_AT = datetime(2026, 8, 9, 12, tzinfo=UTC)
HISTORICAL_OBSERVED_AT = datetime(2026, 2, 5, 15, tzinfo=UTC)

HEADER = (
    "Sigla ICAO Empresa Aerea;Numero Voo;Codigo DI;Codigo Tipo Linha;"
    "Modelo Equipamento;Sigla ICAO Aeroporto Origem;Partida Prevista;"
    "Partida Real;Sigla ICAO Aeroporto Destino;Chegada Prevista;"
    "Chegada Real;Situacao Voo;Referencia\n"
)


def airport(
    icao: str,
    iata: str | None,
    latitude: float,
    longitude: float,
    country: str,
    region: str,
    timezone_name: str,
) -> AirportMetadata:
    return AirportMetadata(
        icao=icao,
        iata=iata,
        latitude=latitude,
        longitude=longitude,
        country_code=country,
        region_code=region,
        timezone_name=timezone_name,
    )


AIRPORTS = {
    "SKBO": airport(
        "SKBO",
        "BOG",
        4.7016,
        -74.1469,
        "CO",
        "South America",
        "America/Bogota",
    ),
    "SBEG": airport(
        "SBEG",
        "MAO",
        -3.0386,
        -60.0497,
        "BR",
        "South America",
        "America/Manaus",
    ),
}


def line(
    flight: str,
    *,
    scheduled_departure: str = "14/01/2026 11:30",
    actual_departure: str = "14/01/2026 11:55",
    scheduled_arrival: str = "14/01/2026 14:30",
    actual_arrival: str = "14/01/2026 14:20",
    status: str = "REALIZADO",
) -> str:
    return ";".join(
        (
            "1ED",
            flight,
            "6",
            "I",
            "E145",
            "SKBO",
            scheduled_departure,
            actual_departure,
            "SBEG",
            scheduled_arrival,
            actual_arrival,
            status,
            "14/01/2026 00:00:00",
        )
    ) + "\n"


def write_vra(path: Path, rows: list[str]) -> tuple[str, int]:
    path.write_text(HEADER + "".join(rows), encoding="utf-8-sig", newline="")
    raw = path.read_bytes()
    return hashlib.sha256(raw).hexdigest(), len(raw)


def file_pin(path: Path, digest: str, raw_bytes: int) -> AnacVraOutcomeFilePin:
    return AnacVraOutcomeFilePin(
        path=path,
        source_url=SOURCE_URL,
        retrieved_at_utc=RETRIEVED_AT,
        expected_sha256=digest,
        expected_raw_bytes=raw_bytes,
    )


def direct_evidence(digest: str) -> AnacVraOutcomeObservationProvenance:
    return AnacVraOutcomeObservationProvenance(
        vra_source_url=SOURCE_URL,
        raw_file_sha256=digest,
        outcome_observed_at_utc=RETRIEVED_AT,
        basis="direct_retrieval_capture",
        evidence_url=SOURCE_URL,
        evidence_timestamp_raw="2026-08-09T12:00:00Z",
        evidence_retrieved_at_utc=RETRIEVED_AT,
        evidence_sha256=digest,
        use_scope="retrospective_holdout_only",
    )


def historical_evidence(digest: str) -> AnacVraOutcomeObservationProvenance:
    return AnacVraOutcomeObservationProvenance(
        vra_source_url=SOURCE_URL,
        raw_file_sha256=digest,
        outcome_observed_at_utc=HISTORICAL_OBSERVED_AT,
        basis="official_publication_record",
        evidence_url="https://www.anac.gov.br/reviewed-publication-record",
        evidence_timestamp_raw="2026-02-05T15:00:00Z",
        evidence_retrieved_at_utc=RETRIEVED_AT,
        evidence_sha256=hashlib.sha256(b"publication record").hexdigest(),
        use_scope="point_in_time_target_history",
    )


def representative_rows() -> list[str]:
    return [
        line("3301"),
        line(
            "3302",
            actual_departure="",
            actual_arrival="",
            status="CANCELADO",
        ),
        line(
            "3303",
            actual_departure="",
            actual_arrival="",
            status="NAO INFORMADO",
        ),
        line(
            "3304",
            scheduled_departure="",
            scheduled_arrival="",
            status="REALIZADO",
        ),
        line(
            "3305",
            scheduled_departure="bad",
            actual_departure="",
            actual_arrival="",
            status="CANCELADO",
        ),
    ]


def test_load_reconciles_every_row_and_admits_terminal_outcomes_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "VRA_2026_01.csv"
    digest, raw_bytes = write_vra(path, representative_rows())

    def block_network(*_args, **_kwargs):
        raise AssertionError("offline VRA loading attempted network I/O")

    monkeypatch.setattr(socket, "create_connection", block_network)
    result = load_anac_vra_outcome_file(
        file_pin(path, digest, raw_bytes),
        AIRPORTS,
        observation_provenance=direct_evidence(digest),
    )

    assert {candidate.record.status for candidate in result.candidates} == {
        "landed",
        "cancelled",
    }
    assert all(
        candidate.record.outcome_observed_at is None
        for candidate in result.candidates
    )
    audit = result.audit
    assert audit.source_raw_row_count == 5
    assert audit.source_parser_accepted_row_count == 3
    assert audit.source_excluded_unplanned_row_count == 1
    assert audit.source_rejected_row_count == 1
    assert audit.terminal_candidate_count == 2
    assert audit.excluded_nonterminal_row_count == 1
    assert audit.normalization_rejected_row_count == 0
    assert dict(audit.terminal_status_counts) == {
        "cancelled": 1,
        "diverted": 0,
        "landed": 1,
    }
    assert dict(audit.nonterminal_status_counts) == {"scheduled": 1}
    assert [decision.disposition for decision in audit.decisions] == [
        "accepted_terminal",
        "accepted_terminal",
        "excluded_nonterminal",
        "excluded_unplanned",
        "rejected_source",
    ]
    assert audit.facts_sha256 == audit.to_dict()["facts_sha256"]
    assert result.to_dict()["audit"]["terminal_candidate_count"] == 2


def test_historical_observation_is_explicit_and_not_inferred_from_vra_fields(
    tmp_path: Path,
) -> None:
    path = tmp_path / "VRA_2026_01.csv"
    digest, raw_bytes = write_vra(path, [line("3301")])
    evidence = historical_evidence(digest)

    result = load_anac_vra_outcome_file(
        file_pin(path, digest, raw_bytes),
        AIRPORTS,
        observation_provenance=evidence,
    )

    assert result.audit.observation_provenance is evidence
    assert (
        result.audit.observation_provenance.outcome_observed_at_utc
        == HISTORICAL_OBSERVED_AT
    )
    assert result.candidates[0].observation_provenance is evidence
    assert result.candidates[0].file_provenance.retrieved_at_utc == RETRIEVED_AT


def test_direct_capture_must_be_the_exact_pinned_file_evidence(tmp_path: Path) -> None:
    path = tmp_path / "VRA_2026_01.csv"
    digest, raw_bytes = write_vra(path, [line("3301")])
    evidence = AnacVraOutcomeObservationProvenance(
        vra_source_url=SOURCE_URL,
        raw_file_sha256=digest,
        outcome_observed_at_utc=RETRIEVED_AT,
        basis="direct_retrieval_capture",
        evidence_url=SOURCE_URL,
        evidence_timestamp_raw="2026-08-09T12:00:00Z",
        evidence_retrieved_at_utc=RETRIEVED_AT,
        evidence_sha256=hashlib.sha256(b"not the VRA bytes").hexdigest(),
        use_scope="retrospective_holdout_only",
    )

    with pytest.raises(AnacVraOutcomeIntegrityError, match="exact pinned"):
        load_anac_vra_outcome_file(
            file_pin(path, digest, raw_bytes),
            AIRPORTS,
            observation_provenance=evidence,
        )


@pytest.mark.parametrize("tamper", ["size", "hash"])
def test_size_and_hash_pins_fail_closed(tmp_path: Path, tamper: str) -> None:
    path = tmp_path / "VRA_2026_01.csv"
    digest, raw_bytes = write_vra(path, [line("3301")])
    if tamper == "size":
        pin = file_pin(path, digest, raw_bytes + 1)
        evidence = direct_evidence(digest)
        message = "byte-size mismatch"
    else:
        wrong = hashlib.sha256(b"wrong pinned bytes").hexdigest()
        pin = file_pin(path, wrong, raw_bytes)
        evidence = direct_evidence(wrong)
        message = "SHA-256 mismatch"

    with pytest.raises(AnacVraOutcomeIntegrityError, match=message):
        load_anac_vra_outcome_file(
            pin,
            AIRPORTS,
            observation_provenance=evidence,
        )


def test_training_code_reverse_index_fails_on_collision(tmp_path: Path) -> None:
    path = tmp_path / "VRA_2026_01.csv"
    digest, raw_bytes = write_vra(path, [line("3301")])
    colliding = dict(AIRPORTS)
    colliding["SKBX"] = airport(
        "SKBX",
        "BOG",
        4.8,
        -74.2,
        "CO",
        "South America",
        "America/Bogota",
    )

    with pytest.raises(AnacVraOutcomeIntegrityError, match="collision"):
        load_anac_vra_outcome_file(
            file_pin(path, digest, raw_bytes),
            colliding,
            observation_provenance=direct_evidence(digest),
        )


def test_reverse_index_and_result_audit_are_immutable_and_path_stable(
    tmp_path: Path,
) -> None:
    reverse = build_training_code_airport_index(AIRPORTS)
    with pytest.raises(TypeError):
        reverse["NEW"] = AIRPORTS["SKBO"]  # type: ignore[index]

    paths = [
        tmp_path / "first" / "VRA_2026_01.csv",
        tmp_path / "second" / "VRA_2026_01.csv",
    ]
    results = []
    for path in paths:
        path.parent.mkdir()
        digest, raw_bytes = write_vra(path, representative_rows())
        results.append(
            load_anac_vra_outcome_file(
                file_pin(path, digest, raw_bytes),
                AIRPORTS,
                observation_provenance=direct_evidence(digest),
            )
        )

    assert results[0].audit.facts_sha256 == results[1].audit.facts_sha256
    assert results[0].audit.to_dict() == results[1].audit.to_dict()
    with pytest.raises(TypeError):
        results[0].audit.terminal_status_counts["landed"] = 99  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        results[0].audit.completed = False  # type: ignore[misc]

    with pytest.raises(AnacVraOutcomeReconciliationError, match="match outcome"):
        replace(
            results[0].audit,
            observation_provenance=direct_evidence(
                hashlib.sha256(b"different VRA bytes").hexdigest()
            ),
        )


def test_pin_requires_explicit_official_source_identity(tmp_path: Path) -> None:
    path = tmp_path / "VRA_2026_01.csv"
    digest, raw_bytes = write_vra(path, [line("3301")])
    with pytest.raises(AnacVraOutcomeIntegrityError, match="does not match"):
        AnacVraOutcomeFilePin(
            path=path,
            source_url=build_vra_url(2026, 2),
            retrieved_at_utc=RETRIEVED_AT,
            expected_sha256=digest,
            expected_raw_bytes=raw_bytes,
        )
