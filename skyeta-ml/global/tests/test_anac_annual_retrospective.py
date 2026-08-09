"""Synthetic end-to-end tests for the offline annual ANAC runner."""

from __future__ import annotations

import hashlib
import json
import socket
import zipfile
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..anac_annual_retrospective import (
    ANAC_ANNUAL_RETROSPECTIVE_INPUT_SCHEMA,
    ANAC_ANNUAL_RETROSPECTIVE_OUTPUT_SCHEMA,
    AnacAirportReferenceFilePin,
    AnacAnnualOutcomeInput,
    AnacAnnualRetrospectiveConfig,
    default_2023_boundaries,
    load_annual_retrospective_manifest,
    run_anac_annual_retrospective_evaluation,
    write_annual_retrospective_audit,
)
from ..anac_siros_vra_join import AnacVraOutcomeObservationProvenance
from ..anac_vra_outcome_loader import AnacVraOutcomeFilePin
from ..export import MODEL_HEADS
from ..schedule_categories import ScheduleCategoricalFeatureConfig
from ..sources.anac import build_vra_url
from ..sources.anac_siros import (
    ANAC_SIROS_2023_ARCHIVE_LAST_MODIFIED_RAW,
    ANAC_SIROS_2023_ARCHIVE_LAST_MODIFIED_UTC,
    ANAC_SIROS_SERIES_HEADERS,
    ANAC_SIROS_UTC_NOTE,
    AnacSirosAnnualArchivePin,
    AnacSirosRetrospectiveEvidencePolicy,
    annual_zip_resource,
)
from ..train import (
    TrainingConfig,
    _retrospective_cold_start_evaluation,
)


UTC = timezone.utc
RETRIEVED = datetime(2026, 8, 9, 12, tzinfo=UTC)
SERVICE_START = date(2023, 1, 9)
SERVICE_END = date(2023, 12, 30)

VRA_HEADER = (
    "Sigla ICAO Empresa Aerea;Numero Voo;Codigo DI;Codigo Tipo Linha;"
    "Modelo Equipamento;Sigla ICAO Aeroporto Origem;Partida Prevista;"
    "Partida Real;Sigla ICAO Aeroporto Destino;Chegada Prevista;"
    "Chegada Real;Situacao Voo;Referencia\n"
)


def _dates(start: date, end: date) -> tuple[date, ...]:
    return tuple(
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
    )


def _siros_row(
    *,
    carrier: str,
    flight: str,
    siros_id: str,
    origin: str,
    destination: str,
    operation_start: date,
) -> tuple[str, ...]:
    values = (
        carrier,
        f"{carrier} TEST AIRLINE",
        flight,
        "E195",
        "1",
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "120",
        siros_id,
        "A Operar",
        "01/01/2023 01:02:03",
        operation_start.isoformat(),
        "2023-12-31",
        "NACIONAL",
        "1",
        origin,
        origin,
        destination,
        destination,
        "12:00",
        "14:00",
        "REGULAR DE PASSAGEIROS",
        "PASSAGEIROS",
        "",
    )
    assert len(values) == len(ANAC_SIROS_SERIES_HEADERS)
    return values


def _annual_member_bytes() -> bytes:
    rows = (
        _siros_row(
            carrier="AAL",
            flight="0904",
            siros_id="AAL-PRIMARY-2023",
            origin="SBGL",
            destination="SBEG",
            operation_start=date(2023, 1, 1),
        ),
        _siros_row(
            carrier="AZU",
            flight="3302",
            siros_id="AZU-COLD-2023",
            origin="SBEG",
            destination="SBGL",
            operation_start=date(2023, 11, 8),
        ),
    )
    text = "\r\n".join(
        (
            ANAC_SIROS_UTC_NOTE,
            ";".join(ANAC_SIROS_SERIES_HEADERS),
            *(";".join(row) for row in rows),
            "",
        )
    )
    return text.encode("utf-8-sig")


def _write_annual_archive(path: Path) -> tuple[str, int]:
    member = _annual_member_bytes()
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("2023/", b"")
        for snapshot_date in _dates(date(2023, 1, 1), date(2023, 12, 31)):
            archive.writestr(
                f"2023/futuro_{snapshot_date.isoformat()}.csv",
                member,
                compress_type=zipfile.ZIP_DEFLATED,
            )
    raw = path.read_bytes()
    return hashlib.sha256(raw).hexdigest(), len(raw)


def _vra_row(
    service_date: date,
    *,
    carrier: str,
    flight: str,
    origin: str,
    destination: str,
    sequence: int,
) -> str:
    # ANAC's VRA clocks are interpreted in Brasilia time.  09:00/11:00 local
    # is exactly 12:00/14:00 UTC in 2023 and therefore matches the SIROS row.
    scheduled_departure = datetime.combine(
        service_date, datetime.min.time()
    ).replace(hour=9)
    scheduled_arrival = scheduled_departure + timedelta(hours=2)
    cancelled = sequence % 11 == 0
    if cancelled:
        actual_departure = ""
        actual_arrival = ""
        status = "CANCELADO"
    else:
        delay = (0, 20, 40, 70)[sequence % 4]
        actual_departure = (scheduled_departure + timedelta(minutes=5)).strftime(
            "%d/%m/%Y %H:%M"
        )
        actual_arrival = (scheduled_arrival + timedelta(minutes=delay)).strftime(
            "%d/%m/%Y %H:%M"
        )
        status = "REALIZADO"
    return ";".join(
        (
            carrier,
            flight,
            "0",
            "N",
            "E195",
            origin,
            scheduled_departure.strftime("%d/%m/%Y %H:%M"),
            actual_departure,
            destination,
            scheduled_arrival.strftime("%d/%m/%Y %H:%M"),
            actual_arrival,
            status,
            service_date.strftime("%d/%m/%Y 00:00:00"),
        )
    ) + "\n"


def _write_vra_month(path: Path, month: int) -> tuple[str, int]:
    rows: list[str] = []
    sequence = 0
    for service_date in _dates(SERVICE_START, SERVICE_END):
        if service_date.month != month:
            continue
        sequence += 1
        rows.append(
            _vra_row(
                service_date,
                carrier="AAL",
                flight="0904",
                origin="SBGL",
                destination="SBEG",
                sequence=sequence,
            )
        )
        if service_date >= date(2023, 11, 8):
            rows.append(
                _vra_row(
                    service_date,
                    carrier="AZU",
                    flight="3302",
                    origin="SBEG",
                    destination="SBGL",
                    sequence=sequence + 3,
                )
            )
    path.write_text(VRA_HEADER + "".join(rows), encoding="utf-8-sig", newline="")
    raw = path.read_bytes()
    return hashlib.sha256(raw).hexdigest(), len(raw)


def _write_reference(path: Path) -> tuple[str, int, str]:
    corpus_digest = hashlib.sha256(b"synthetic airport reference corpus").hexdigest()
    airports = {
        "SBGL": {
            "icao": "SBGL",
            "iata": None,
            "latitude": -22.81,
            "longitude": -43.25,
            "country_code": "BR",
            "region_code": "South America",
            "timezone_name": "America/Sao_Paulo",
        },
        "SBEG": {
            "icao": "SBEG",
            "iata": None,
            "latitude": -3.0386,
            "longitude": -60.0497,
            "country_code": "BR",
            "region_code": "South America",
            "timezone_name": "America/Manaus",
        },
    }
    document = {
        "schema_version": "skyeta-anac-reference-v1",
        "corpus_digest": corpus_digest,
        "audit": {
            "completed": True,
            "corpus_digest": corpus_digest,
        },
        "airport_index": {
            "by_icao": airports,
            "audit": {"indexed_record_count": len(airports)},
        },
    }
    path.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )
    raw = path.read_bytes()
    return hashlib.sha256(raw).hexdigest(), len(raw), corpus_digest


def _build_config(tmp_path: Path) -> AnacAnnualRetrospectiveConfig:
    archive_path = tmp_path / "2023.zip"
    archive_sha, archive_bytes = _write_annual_archive(archive_path)
    archive_resource = annual_zip_resource(2023)
    archive_pin = AnacSirosAnnualArchivePin(
        resource=archive_resource,
        source_url=archive_resource.url,
        retrieved_at_utc=RETRIEVED,
        expected_sha256=archive_sha,
        expected_bytes=archive_bytes,
        archive_last_modified_utc=ANAC_SIROS_2023_ARCHIVE_LAST_MODIFIED_UTC,
        archive_last_modified_raw=ANAC_SIROS_2023_ARCHIVE_LAST_MODIFIED_RAW,
    )

    reference_path = tmp_path / "anac-reference.json"
    reference_sha, reference_bytes, corpus_digest = _write_reference(reference_path)
    reference_pin = AnacAirportReferenceFilePin(
        path=reference_path,
        expected_sha256=reference_sha,
        expected_bytes=reference_bytes,
        expected_corpus_digest=corpus_digest,
    )

    outcomes: list[AnacAnnualOutcomeInput] = []
    for month in range(1, 13):
        path = tmp_path / f"VRA_2023_{month:02d}.csv"
        digest, raw_bytes = _write_vra_month(path, month)
        source_url = build_vra_url(2023, month)
        pin = AnacVraOutcomeFilePin(
            path=path,
            source_url=source_url,
            retrieved_at_utc=RETRIEVED,
            expected_sha256=digest,
            expected_raw_bytes=raw_bytes,
        )
        evidence = AnacVraOutcomeObservationProvenance(
            vra_source_url=source_url,
            raw_file_sha256=digest,
            outcome_observed_at_utc=RETRIEVED,
            basis="direct_retrieval_capture",
            evidence_url=source_url,
            evidence_timestamp_raw="2026-08-09T12:00:00Z",
            evidence_retrieved_at_utc=RETRIEVED,
            evidence_sha256=digest,
            use_scope="retrospective_holdout_only",
        )
        outcomes.append(AnacAnnualOutcomeInput(pin, evidence))

    return AnacAnnualRetrospectiveConfig(
        year=2023,
        annual_archive_path=archive_path,
        annual_archive_pin=archive_pin,
        evidence_policy=AnacSirosRetrospectiveEvidencePolicy(),
        airport_reference_pin=reference_pin,
        outcome_inputs=tuple(outcomes),
        boundaries=default_2023_boundaries(),
        training_config=TrainingConfig(
            seed=7,
            n_estimators=20,
            learning_rate=0.1,
            num_leaves=7,
            min_child_samples=2,
            early_stopping_rounds=5,
        ),
        schedule_categorical_config=ScheduleCategoricalFeatureConfig(
            max_operating_carriers=8,
            max_origins=8,
            max_destinations=8,
            max_aircraft_families=8,
            max_routes=8,
        ),
        decision_detail_limit=5,
    )


def _diagnostic_evaluator(prepared, *, config: TrainingConfig):
    assert config.seed == 7
    probabilities = [
        {head: 0.2 for head in MODEL_HEADS}
        for _ in prepared.test.records
    ]
    return {
        "evaluation_kind": "retrospective_temporal_evaluation",
        "point_in_time_backtest": False,
        "publishable": False,
        "target_derived_history_features_used": False,
        "cold_start_diagnostics": _retrospective_cold_start_evaluation(
            prepared, probabilities
        ),
        "test_metrics": {},
    }


def _manifest_document(config: AnacAnnualRetrospectiveConfig) -> dict[str, object]:
    archive = config.annual_archive_pin
    return {
        "schema_version": ANAC_ANNUAL_RETROSPECTIVE_INPUT_SCHEMA,
        "year": 2023,
        "annual_archive": {
            "path": str(config.annual_archive_path),
            "source_url": archive.source_url,
            "retrieved_at_utc": archive.retrieved_at_utc.isoformat(),
            "expected_sha256": archive.expected_sha256,
            "expected_bytes": archive.expected_bytes,
            "archive_last_modified_utc": (
                archive.archive_last_modified_utc.isoformat()
            ),
            "archive_last_modified_raw": archive.archive_last_modified_raw,
        },
        "annual_member_evidence_policy": config.evidence_policy.to_dict(),
        "airport_reference": {
            "path": str(config.airport_reference_pin.path),
            "expected_sha256": config.airport_reference_pin.expected_sha256,
            "expected_bytes": config.airport_reference_pin.expected_bytes,
            "expected_corpus_digest": (
                config.airport_reference_pin.expected_corpus_digest
            ),
        },
        "vra_months": [
            {
                "path": str(item.pin.path),
                "source_url": item.pin.source_url,
                "retrieved_at_utc": item.pin.retrieved_at_utc.isoformat(),
                "expected_sha256": item.pin.expected_sha256,
                "expected_raw_bytes": item.pin.expected_raw_bytes,
                "observation_provenance": (
                    item.observation_provenance.to_dict()
                ),
            }
            for item in config.outcome_inputs
        ],
        "service_start": config.service_start.isoformat(),
        "service_end": config.service_end.isoformat(),
        "boundaries": {
            "train_end": config.boundaries.train_end.isoformat(),
            "tune_end": config.boundaries.tune_end.isoformat(),
            "calibration_end": config.boundaries.calibration_end.isoformat(),
            "test_end": config.boundaries.test_end.isoformat(),
        },
        "training_config": asdict(config.training_config),
        "schedule_categorical_config": asdict(
            config.schedule_categorical_config
        ),
        "decision_detail_limit": config.decision_detail_limit,
    }


def test_synthetic_annual_runner_is_offline_exact_and_deterministic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _build_config(tmp_path)

    def block_network(*_args, **_kwargs):
        raise AssertionError("annual retrospective runner attempted network I/O")

    monkeypatch.setattr(socket, "create_connection", block_network)
    first = run_anac_annual_retrospective_evaluation(
        config,
        evaluation_function=_diagnostic_evaluator,
    )
    second = run_anac_annual_retrospective_evaluation(
        config,
        evaluation_function=_diagnostic_evaluator,
    )

    assert first == second
    assert first["schema_version"] == ANAC_ANNUAL_RETROSPECTIVE_OUTPUT_SCHEMA
    assert first["publishable"] is False
    assert first["point_in_time_backtest"] is False
    assert first["production_artifact_created"] is False
    assert first["deployment_performed"] is False
    assert len(first["selected_t7_members"]) == 356
    selection = first["selected_t7_members"][0]
    assert selection["service_date"] == "2023-01-09"
    assert selection["snapshot_date"] == "2023-01-01"
    assert selection["retrospective_evidence_bound_utc"] == (
        "2023-01-02T00:00:00Z"
    )
    assert selection["public_availability_proven"] is False

    joins = first["monthly_exact_joins"]
    assert len(joins) == 12
    assert all(row["complete_decision_accounting"] for row in joins)
    assert all(row["nonmatched_decision_count"] == 0 for row in joins)
    assert sum(row["matched_pair_count"] for row in joins) == 409
    assert first["joined_corpus"]["rows"] == 409
    assert first["joined_corpus"]["duplicate_rows_removed"] == 0

    cold = first["model_evaluation"]["cold_start_diagnostics"]
    for field in ("operatingCarrier", "origin", "destination", "route"):
        assert cold["fields"][field]["unseen"]["populationRows"] == 53
        assert cold["fields"][field]["unseenDistinctValueCount"] == 1
    assert cold["combined"]["anyUnseen"]["populationRows"] == 53

    output = write_annual_retrospective_audit(first, tmp_path / "audit.json")
    rendered = json.loads(output.read_text(encoding="utf-8"))
    assert rendered["audit_sha256"] == first["audit_sha256"]


def test_manifest_round_trip_preserves_explicit_input_facts(tmp_path: Path) -> None:
    config = _build_config(tmp_path)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(_manifest_document(config), sort_keys=True, indent=2),
        encoding="utf-8",
        newline="\n",
    )

    loaded = load_annual_retrospective_manifest(manifest)

    assert loaded.stable_input_facts() == config.stable_input_facts()
    assert loaded.evidence_policy.public_availability_proven is False
    assert loaded.evidence_policy.point_in_time_eligible is False
    assert all(
        item.observation_provenance.use_scope == "retrospective_holdout_only"
        for item in loaded.outcome_inputs
    )
