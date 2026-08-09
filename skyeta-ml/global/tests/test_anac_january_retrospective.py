"""Focused safety tests for the January fixed-snapshot diagnostic."""

from __future__ import annotations

import hashlib
import inspect
import json
import socket
import subprocess
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from .. import anac_january_retrospective as january_runner
from ..anac_annual_retrospective import (
    AnacAirportReferenceFilePin,
    AnacAnnualOutcomeInput,
    _load_airport_reference,
)
from ..anac_january_retrospective import (
    ANAC_JANUARY_RETROSPECTIVE_INPUT_SCHEMA,
    ANAC_JANUARY_RETROSPECTIVE_OUTPUT_SCHEMA,
    AnacJanuaryManifestError,
    AnacJanuaryReconciliationError,
    AnacJanuaryRetrospectiveConfig,
    default_january_2025_boundaries,
    load_january_retrospective_manifest,
    run_anac_january_retrospective_evaluation,
    write_january_retrospective_audit,
)
from ..anac_siros_vra_join import AnacVraOutcomeObservationProvenance
from ..anac_vra_outcome_loader import (
    AnacVraOutcomeFilePin,
    load_anac_vra_outcome_file,
)
from ..export import MODEL_HEADS
from ..pipeline import RetrospectiveMatrixMemoryLimits
from ..schedule_categories import ScheduleCategoricalFeatureConfig
from ..sources.anac import build_vra_url
from ..sources.anac_siros import (
    ANAC_SIROS_SERIES_HEADERS,
    ANAC_SIROS_UTC_NOTE,
    AnacSirosSnapshotPin,
    daily_snapshot_resource,
    load_siros_series_snapshot,
)
from ..train import (
    TrainingConfig,
    _retrospective_cold_start_evaluation,
    _retrospective_evaluation_memory_audit,
)


UTC = timezone.utc
OBSERVED = datetime(2025, 1, 1, 7, 26, 25, tzinfo=UTC)
RETRIEVED = datetime(2026, 8, 9, 12, tzinfo=UTC)
SERVICE_START = date(2025, 1, 8)
SERVICE_END = date(2025, 1, 31)
LAST_MODIFIED_RAW = "Wed, 01 Jan 2025 07:26:25 GMT"
CAPTURED_SOCKET_CLASS = socket.socket

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
    *, flight: str, siros_id: str, departure: str, arrival: str
) -> tuple[str, ...]:
    values = (
        "AAL",
        "AAL TEST AIRLINE",
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
        "01/01/2025 01:02:03",
        "2025-01-01",
        "2025-01-31",
        "NACIONAL",
        "1",
        "SBGL",
        "SBGL",
        "SBEG",
        "SBEG",
        departure,
        arrival,
        "REGULAR DE PASSAGEIROS",
        "PASSAGEIROS",
        "",
    )
    assert len(values) == len(ANAC_SIROS_SERIES_HEADERS)
    return values


def _write_snapshot(path: Path) -> tuple[str, int]:
    rows = tuple(
        _siros_row(
            flight=f"{index:02d}00",
            siros_id=f"SYNTHETIC-{index:02d}",
            departure=f"{hour:02d}:00",
            arrival=f"{hour + 2:02d}:00",
        )
        for index, hour in enumerate(range(6, 22, 2), start=1)
    )
    text = "\r\n".join(
        (
            ANAC_SIROS_UTC_NOTE,
            ";".join(ANAC_SIROS_SERIES_HEADERS),
            *(";".join(row) for row in rows),
            "",
        )
    )
    path.write_bytes(text.encode("utf-8-sig"))
    raw = path.read_bytes()
    return hashlib.sha256(raw).hexdigest(), len(raw)


def _vra_row(service_date: date, *, flight: str, hour: int) -> str:
    departure = datetime.combine(service_date, datetime.min.time()).replace(hour=hour)
    arrival = departure + timedelta(hours=2)
    flight_index = int(flight[:2])
    cancelled = flight_index == 5
    if cancelled:
        actual_departure = ""
        actual_arrival = ""
        status = "CANCELADO"
    else:
        delay_minutes = {
            1: 0,
            2: 20,
            3: 45,
            4: 80,
            6: 0,
            7: 45,
            8: 80,
        }[flight_index]
        actual_departure = (departure + timedelta(minutes=5)).strftime(
            "%d/%m/%Y %H:%M"
        )
        actual_arrival = (arrival + timedelta(minutes=delay_minutes)).strftime(
            "%d/%m/%Y %H:%M"
        )
        status = "REALIZADO"
    return ";".join(
        (
            "AAL",
            flight,
            "0",
            "N",
            "B788",
            "SBGL",
            departure.strftime("%d/%m/%Y %H:%M"),
            actual_departure,
            "SBEG",
            arrival.strftime("%d/%m/%Y %H:%M"),
            actual_arrival,
            status,
            service_date.strftime("%d/%m/%Y 00:00:00"),
        )
    ) + "\n"


def _write_vra(path: Path) -> tuple[str, int]:
    # Brasilia is UTC-3. Local clocks match the 06:00--20:00 SIROS UTC clocks.
    rows = [
        _vra_row(service_date, flight=flight, hour=hour)
        for service_date in _dates(SERVICE_START, SERVICE_END)
        for flight, hour in (
            (f"{index:02d}00", utc_hour - 3)
            for index, utc_hour in enumerate(range(6, 22, 2), start=1)
        )
    ]
    path.write_text(VRA_HEADER + "".join(rows), encoding="utf-8-sig", newline="")
    raw = path.read_bytes()
    return hashlib.sha256(raw).hexdigest(), len(raw)


def _write_reference(path: Path) -> tuple[str, int, str]:
    corpus_digest = hashlib.sha256(b"january airport reference").hexdigest()
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
        "audit": {"completed": True, "corpus_digest": corpus_digest},
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


def _build_config(tmp_path: Path) -> AnacJanuaryRetrospectiveConfig:
    snapshot_path = tmp_path / "futuro_2025-01-01.csv"
    snapshot_sha, snapshot_bytes = _write_snapshot(snapshot_path)
    resource = daily_snapshot_resource(date(2025, 1, 1))
    snapshot_pin = AnacSirosSnapshotPin(
        resource=resource,
        source_url=resource.url,
        availability_evidence_kind="http_last_modified",
        snapshot_observed_at_utc=OBSERVED,
        retrieved_at_utc=RETRIEVED,
        expected_sha256=snapshot_sha,
        expected_bytes=snapshot_bytes,
        http_last_modified_utc=OBSERVED,
        http_last_modified_raw=LAST_MODIFIED_RAW,
    )

    reference_path = tmp_path / "reference.json"
    reference_sha, reference_bytes, corpus_digest = _write_reference(reference_path)
    reference_pin = AnacAirportReferenceFilePin(
        path=reference_path,
        expected_sha256=reference_sha,
        expected_bytes=reference_bytes,
        expected_corpus_digest=corpus_digest,
    )

    outcome_path = tmp_path / "VRA_2025_01.csv"
    outcome_sha, outcome_bytes = _write_vra(outcome_path)
    outcome_url = build_vra_url(2025, 1)
    outcome_pin = AnacVraOutcomeFilePin(
        path=outcome_path,
        source_url=outcome_url,
        retrieved_at_utc=RETRIEVED,
        expected_sha256=outcome_sha,
        expected_raw_bytes=outcome_bytes,
    )
    outcome_evidence = AnacVraOutcomeObservationProvenance(
        vra_source_url=outcome_url,
        raw_file_sha256=outcome_sha,
        outcome_observed_at_utc=RETRIEVED,
        basis="direct_retrieval_capture",
        evidence_url=outcome_url,
        evidence_timestamp_raw="2026-08-09T12:00:00Z",
        evidence_retrieved_at_utc=RETRIEVED,
        evidence_sha256=outcome_sha,
        use_scope="retrospective_holdout_only",
    )
    return AnacJanuaryRetrospectiveConfig(
        snapshot_path=snapshot_path,
        snapshot_pin=snapshot_pin,
        airport_reference_pin=reference_pin,
        outcome_input=AnacAnnualOutcomeInput(outcome_pin, outcome_evidence),
        boundaries=default_january_2025_boundaries(),
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
        matrix_memory_limits=RetrospectiveMatrixMemoryLimits(
            max_partition_peak_bytes=16 * 1024 * 1024,
            max_total_csr_bytes=32 * 1024 * 1024,
            max_evaluation_additional_bytes=16 * 1024 * 1024,
        ),
        decision_detail_limit=5,
    )


def _diagnostic_evaluator(prepared, *, config: TrainingConfig):
    probabilities = np.full(
        (len(prepared.test.records), len(MODEL_HEADS)),
        0.2,
        dtype=np.float64,
    )
    return {
        "evaluation_kind": "retrospective_temporal_evaluation",
        "point_in_time_backtest": False,
        "publishable": False,
        "target_derived_history_features_used": False,
        "temporal_audit": prepared.retrospective_audit.to_dict(),
        "training_configuration": asdict(config),
        "evaluation_memory_audit": _retrospective_evaluation_memory_audit(
            prepared, config
        ),
        "cold_start_diagnostics": _retrospective_cold_start_evaluation(
            prepared, probabilities
        ),
        "runtime_provenance": {
            "deterministic": True,
            "python": "test-runtime",
            "platform": "test-platform",
            "machine": "test-machine",
            "numpy": "test-version",
            "scipy": "test-version",
            "scikit_learn": "test-version",
            "lightgbm": "test-version",
            "deterministic_parameters": {
                "random_state": config.seed,
                "bagging_seed": config.seed,
                "feature_fraction_seed": config.seed,
                "data_random_seed": config.seed,
                "deterministic": True,
                "force_col_wise": True,
                "device_type": "cpu",
                "n_jobs": config.num_threads,
            },
        },
        "feature_contract": {
            "feature_count": len(prepared.train.feature_names),
            "feature_names": list(prepared.train.feature_names),
            "precomputed_matrices_only": True,
            "target_derived_history_features": False,
            "matrix_storage": prepared.matrix_audit.to_dict(),
        },
        "test_metrics": {head: {} for head in MODEL_HEADS},
        "model_diagnostics": {head: {} for head in MODEL_HEADS},
    }


def _manifest_document(config: AnacJanuaryRetrospectiveConfig) -> dict[str, object]:
    snapshot = config.snapshot_pin
    outcome = config.outcome_input
    return {
        "schema_version": ANAC_JANUARY_RETROSPECTIVE_INPUT_SCHEMA,
        "diagnostic_month": "2025-01",
        "daily_snapshot": {
            "path": str(config.snapshot_path),
            "source_url": snapshot.source_url,
            "snapshot_date": "2025-01-01",
            "availability_evidence_kind": snapshot.availability_evidence_kind,
            "snapshot_observed_at_utc": snapshot.snapshot_observed_at_utc.isoformat(),
            "retrieved_at_utc": snapshot.retrieved_at_utc.isoformat(),
            "expected_sha256": snapshot.expected_sha256,
            "expected_bytes": snapshot.expected_bytes,
            "http_last_modified_utc": snapshot.http_last_modified_utc.isoformat(),
            "http_last_modified_raw": snapshot.http_last_modified_raw,
        },
        "airport_reference": {
            "path": str(config.airport_reference_pin.path),
            "expected_sha256": config.airport_reference_pin.expected_sha256,
            "expected_bytes": config.airport_reference_pin.expected_bytes,
            "expected_corpus_digest": (
                config.airport_reference_pin.expected_corpus_digest
            ),
        },
        "vra_outcome": {
            "path": str(outcome.pin.path),
            "source_url": outcome.pin.source_url,
            "retrieved_at_utc": outcome.pin.retrieved_at_utc.isoformat(),
            "expected_sha256": outcome.pin.expected_sha256,
            "expected_raw_bytes": outcome.pin.expected_raw_bytes,
            "observation_provenance": outcome.observation_provenance.to_dict(),
        },
        "service_start": config.service_start.isoformat(),
        "service_end": config.service_end.isoformat(),
        "minimum_schedule_age_seconds": config.minimum_schedule_age_seconds,
        "boundaries": {
            "train_end": config.boundaries.train_end.isoformat(),
            "tune_end": config.boundaries.tune_end.isoformat(),
            "calibration_end": config.boundaries.calibration_end.isoformat(),
            "test_end": config.boundaries.test_end.isoformat(),
        },
        "training_config": asdict(config.training_config),
        "schedule_categorical_config": asdict(config.schedule_categorical_config),
        "matrix_memory_limits": config.matrix_memory_limits.to_dict(),
        "decision_detail_limit": config.decision_detail_limit,
        "run_semantics": {
            "retrospective_only": True,
            "point_in_time_backtest": False,
            "publishable": False,
            "target_derived_history_features": False,
            "production_artifact_allowed": False,
            "deployment_allowed": False,
        },
    }


@pytest.fixture()
def synthetic_config(tmp_path: Path) -> AnacJanuaryRetrospectiveConfig:
    return _build_config(tmp_path)


def test_fixed_snapshot_age_denominator_aircraft_and_output_are_audited(
    synthetic_config: AnacJanuaryRetrospectiveConfig,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        january_runner,
        "evaluate_retrospective_temporal_model",
        _diagnostic_evaluator,
    )
    first = run_anac_january_retrospective_evaluation(synthetic_config)
    second = run_anac_january_retrospective_evaluation(synthetic_config)

    assert first == second
    assert first["schema_version"] == ANAC_JANUARY_RETROSPECTIVE_OUTPUT_SCHEMA
    assert first["publishable"] is False
    assert first["point_in_time_backtest"] is False
    assert first["production_artifact_created"] is False
    assert first["deployment_performed"] is False
    assert first["network_io_performed_by_runner"] is False

    ages = first["schedule_observation_age_audit"]
    assert ages["expanded_schedule_rows"] == 192
    assert ages["eligible_schedule_rows"] == 191
    assert ages["too_recent_schedule_rows"] == 1
    assert len(ages["per_service_date"]) == 24
    assert ages["per_service_date"][0]["eligible_schedule_rows"] == 7
    assert ages["per_service_date"][-1]["eligible_schedule_rows"] == 8
    assert ages["maximum_observation_age_seconds"] > ages[
        "minimum_observation_age_seconds"
    ]

    cohort = first["exact_join_cohort"]
    assert cohort["eligible_schedule_rows"] == 191
    assert cohort["metric_population_rows"] == 191
    assert cohort["fixed_snapshot_expanded_schedule_rows"] == 192
    assert cohort["minimum_age_ineligible_schedule_rows"] == 1
    assert cohort["exact_match_rate_over_eligible_schedules"] == 1.0
    assert cohort["january_population_performance_claim_allowed"] is False
    assert first["exact_join"]["input_outcome_count"] == 192
    assert first["exact_join"]["matched_pair_count"] == 191

    vocabularies = {
        row["field"]: row
        for row in first["schedule_categorical_snapshot"]["vocabularies"]
    }
    assert vocabularies["aircraft_family"]["categories"] == ["E195"]
    assert "B788" not in vocabularies["aircraft_family"]["categories"]
    assert first["feature_provenance"]["vra_equipment_used_as_feature"] is False
    assert "T-7 snapshot" not in json.dumps(first)

    output = write_january_retrospective_audit(first, tmp_path / "audit.json")
    assert json.loads(output.read_text(encoding="utf-8")) == first
    tampered = dict(first)
    tampered["publishable"] = True
    with pytest.raises(AnacJanuaryReconciliationError, match="digest"):
        write_january_retrospective_audit(tampered, tmp_path / "tampered.json")


def test_manifest_is_strict_round_trips_and_preserves_semantics(
    synthetic_config: AnacJanuaryRetrospectiveConfig, tmp_path: Path
) -> None:
    document = _manifest_document(synthetic_config)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(document, sort_keys=True, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    loaded = load_january_retrospective_manifest(manifest)
    assert loaded.stable_input_facts() == synthetic_config.stable_input_facts()
    assert loaded.outcome_input.observation_provenance.use_scope == (
        "retrospective_holdout_only"
    )

    unknown = dict(document)
    unknown["surprise"] = True
    unknown_path = tmp_path / "unknown.json"
    unknown_path.write_text(json.dumps(unknown), encoding="utf-8")
    with pytest.raises(AnacJanuaryManifestError, match="unknown"):
        load_january_retrospective_manifest(unknown_path)

    changed_semantics = json.loads(json.dumps(document))
    changed_semantics["run_semantics"]["publishable"] = True
    semantics_path = tmp_path / "semantics.json"
    semantics_path.write_text(json.dumps(changed_semantics), encoding="utf-8")
    with pytest.raises(AnacJanuaryManifestError, match="nonpublishable"):
        load_january_retrospective_manifest(semantics_path)

    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(
        '{"schema_version":"x","schema_version":"y"}',
        encoding="utf-8",
    )
    with pytest.raises(AnacJanuaryManifestError, match="duplicate JSON key"):
        load_january_retrospective_manifest(duplicate_path)

    nonfinite_path = tmp_path / "nonfinite.json"
    nonfinite_path.write_text('{"value":NaN}', encoding="utf-8")
    with pytest.raises(AnacJanuaryManifestError, match="non-finite"):
        load_january_retrospective_manifest(nonfinite_path)


def test_daily_snapshot_hash_and_parser_share_one_byte_buffer(
    synthetic_config: AnacJanuaryRetrospectiveConfig, monkeypatch
) -> None:
    snapshot_path = Path(str(synthetic_config.snapshot_path)).resolve()
    original = Path.read_bytes
    snapshot_reads = 0

    def counted_read_bytes(path: Path) -> bytes:
        nonlocal snapshot_reads
        if path.resolve() == snapshot_path:
            snapshot_reads += 1
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    snapshot = load_siros_series_snapshot(
        snapshot_path, pin=synthetic_config.snapshot_pin
    )
    assert snapshot.audit.completed is True
    assert snapshot_reads == 1


def test_runner_blocks_network_even_inside_fixed_evaluator(
    synthetic_config: AnacJanuaryRetrospectiveConfig, monkeypatch
) -> None:
    def network_evaluator(_prepared, *, config):
        del config
        socket.create_connection(("example.com", 443))

    monkeypatch.setattr(
        january_runner,
        "evaluate_retrospective_temporal_model",
        network_evaluator,
    )
    with pytest.raises(AnacJanuaryReconciliationError, match="network I/O"):
        run_anac_january_retrospective_evaluation(synthetic_config)

    def udp_evaluator(_prepared, *, config):
        del config
        udp = CAPTURED_SOCKET_CLASS(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            udp.sendto(b"blocked", ("127.0.0.1", 9))
        finally:
            udp.close()

    monkeypatch.setattr(
        january_runner,
        "evaluate_retrospective_temporal_model",
        udp_evaluator,
    )
    with pytest.raises(AnacJanuaryReconciliationError, match="network I/O"):
        run_anac_january_retrospective_evaluation(synthetic_config)

    def process_evaluator(_prepared, *, config):
        del config
        subprocess.run(["should-not-execute"], check=False)

    monkeypatch.setattr(
        january_runner,
        "evaluate_retrospective_temporal_model",
        process_evaluator,
    )
    with pytest.raises(AnacJanuaryReconciliationError, match="network I/O"):
        run_anac_january_retrospective_evaluation(synthetic_config)


def test_source_contract_change_during_run_fails_closed(
    synthetic_config: AnacJanuaryRetrospectiveConfig, monkeypatch
) -> None:
    monkeypatch.setattr(
        january_runner,
        "evaluate_retrospective_temporal_model",
        _diagnostic_evaluator,
    )
    original = january_runner._source_provenance
    calls = 0

    def changed_source():
        nonlocal calls
        calls += 1
        result = original()
        if calls > 1:
            result = dict(result)
            result["aggregate_sha256"] = "0" * 64
        return result

    monkeypatch.setattr(january_runner, "_source_provenance", changed_source)
    with pytest.raises(AnacJanuaryReconciliationError, match="changed"):
        run_anac_january_retrospective_evaluation(synthetic_config)


def test_snapshot_hash_tampering_is_rejected_before_evaluation(
    synthetic_config: AnacJanuaryRetrospectiveConfig, monkeypatch
) -> None:
    Path(str(synthetic_config.snapshot_path)).write_bytes(b"tampered")
    called = False

    def evaluator(_prepared, *, config):
        nonlocal called
        del config
        called = True

    monkeypatch.setattr(
        january_runner, "evaluate_retrospective_temporal_model", evaluator
    )
    with pytest.raises(ValueError, match="byte count mismatch|SHA-256 mismatch"):
        run_anac_january_retrospective_evaluation(synthetic_config)
    assert called is False


def test_vra_hash_and_parser_share_one_buffer_despite_path_swap(
    synthetic_config: AnacJanuaryRetrospectiveConfig, monkeypatch
) -> None:
    outcome_path = Path(str(synthetic_config.outcome_input.pin.path)).resolve()
    original_read = Path.read_bytes
    swaps = 0

    def swap_after_read(path: Path) -> bytes:
        nonlocal swaps
        raw = original_read(path)
        if path.resolve() == outcome_path:
            replacement = raw.replace(b"B788", b"B739")
            assert len(replacement) == len(raw)
            path.write_bytes(replacement)
            swaps += 1
        return raw

    airports, _ = _load_airport_reference(
        synthetic_config.airport_reference_pin
    )
    monkeypatch.setattr(Path, "read_bytes", swap_after_read)
    result = load_anac_vra_outcome_file(
        synthetic_config.outcome_input.pin,
        airports,
        observation_provenance=(
            synthetic_config.outcome_input.observation_provenance
        ),
    )

    assert swaps == 1
    assert b"B739" in original_read(outcome_path)
    assert {candidate.record.aircraft_family for candidate in result.candidates} == {
        "B788"
    }
    assert result.audit.raw_file_sha256 == (
        synthetic_config.outcome_input.pin.expected_sha256
    )


def test_source_contract_binds_transitive_encoding_dependency(monkeypatch) -> None:
    baseline = january_runner._source_provenance()
    original_read = Path.read_bytes

    def changed_dependency(path: Path) -> bytes:
        raw = original_read(path)
        if path.name == "encodings.py" and path.parent.name == "global":
            return raw + b"\n# simulated reviewed dependency change\n"
        return raw

    monkeypatch.setattr(Path, "read_bytes", changed_dependency)
    changed = january_runner._source_provenance()
    assert changed["aggregate_sha256"] != baseline["aggregate_sha256"]
    bound_paths = {row["path"] for row in baseline["files"]}
    assert {"encodings.py", "coverage.py"} <= bound_paths


def test_cli_requires_execute_and_refuses_input_overwrite(
    synthetic_config: AnacJanuaryRetrospectiveConfig, tmp_path: Path
) -> None:
    document = _manifest_document(synthetic_config)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SystemExit) as missing_execute:
        january_runner.main(
            ["--manifest", str(manifest), "--output", str(tmp_path / "out.json")]
        )
    assert missing_execute.value.code == 2

    with pytest.raises(AnacJanuaryManifestError, match="must not overwrite"):
        january_runner.main(
            [
                "--manifest",
                str(manifest),
                "--output",
                str(synthetic_config.snapshot_path),
                "--execute",
            ]
        )


def test_public_runner_has_no_arbitrary_evaluator_callback() -> None:
    assert tuple(
        inspect.signature(run_anac_january_retrospective_evaluation).parameters
    ) == ("config",)


def test_default_lightgbm_evaluator_is_deterministic(
    synthetic_config: AnacJanuaryRetrospectiveConfig,
) -> None:
    first = run_anac_january_retrospective_evaluation(synthetic_config)
    second = run_anac_january_retrospective_evaluation(synthetic_config)

    assert second == first
    evaluation = first["model_evaluation"]
    assert set(evaluation["test_metrics"]) == set(MODEL_HEADS)
    assert set(evaluation["model_diagnostics"]) == set(MODEL_HEADS)
    assert evaluation["runtime_provenance"]["deterministic"] is True
    assert evaluation["publishable"] is False
    assert evaluation["point_in_time_backtest"] is False
