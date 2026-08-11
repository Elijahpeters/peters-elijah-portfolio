"""Offline, nonpublishable January 2025 fixed-snapshot diagnostic.

This diagnostic intentionally reuses the one hash-pinned SIROS snapshot dated
1 January across service dates 8--31 January.  Each expanded schedule is
audited using its actual observation age at departure and is eligible only
when the snapshot was observed at least seven days before that departure.
The snapshot therefore is not represented as a daily prediction-time series.

The VRA file supplies retrospective labels only.  Equipment used by the model
comes exclusively from the SIROS schedule bytes.  The runner blocks network
access, exports no model, performs no deployment, and writes only an atomic,
digest-bound diagnostic audit when the CLI receives an explicit ``--execute``.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import socket
import subprocess
from collections import Counter
from collections.abc import Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from .anac_annual_retrospective import (
    AnacAirportReferenceFilePin,
    AnacAnnualManifestError,
    AnacAnnualOutcomeInput,
    _digest,
    _join_summary,
    _load_airport_reference,
    _mapping,
    _outcome_load_summary,
    _parse_date,
    _parse_datetime,
    _parse_matrix_memory_limits,
    _parse_schedule_config,
    _parse_training_config,
    _positive_int,
    _resolve_manifest_path,
    _strict_json_bytes,
)
from .anac_siros_vra_join import (
    AnacSirosVraJoinResult,
    AnacVraOutcomeObservationProvenance,
    join_siros_schedules_to_vra_outcomes,
)
from .anac_vra_outcome_loader import (
    AnacVraOutcomeFilePin,
    load_anac_vra_outcome_file,
)
from .pipeline import (
    RetrospectiveMatrixMemoryLimits,
    prepare_retrospective_global_data,
)
from .retrospective_audit_contract import (
    canonical_json,
    canonical_sha256,
    exact_join_cohort_qualification,
    source_code_provenance,
    validate_retrospective_evaluator_contract,
    write_canonical_audit,
)
from .schedule_categories import ScheduleCategoricalFeatureConfig
from .sources.anac_siros import (
    AnacSirosSeriesSnapshot,
    AnacSirosServiceObservation,
    AnacSirosSnapshotPin,
    daily_snapshot_resource,
    expand_siros_snapshot,
    load_siros_series_snapshot,
)
from .splits import ChronologicalBoundaries
from .train import TrainingConfig, evaluate_retrospective_temporal_model


ANAC_JANUARY_RETROSPECTIVE_INPUT_SCHEMA = (
    "skyeta-anac-january-fixed-snapshot-input-v1"
)
ANAC_JANUARY_RETROSPECTIVE_OUTPUT_SCHEMA = (
    "skyeta-anac-january-fixed-snapshot-evaluation-v1"
)
ANAC_JANUARY_DIAGNOSTIC_MONTH = "2025-01"
ANAC_JANUARY_SNAPSHOT_DATE = date(2025, 1, 1)
ANAC_JANUARY_SERVICE_START = date(2025, 1, 8)
ANAC_JANUARY_SERVICE_END = date(2025, 1, 31)
ANAC_JANUARY_MINIMUM_SCHEDULE_AGE_SECONDS = 7 * 24 * 60 * 60

_RUN_SEMANTICS = MappingProxyType(
    {
        "retrospective_only": True,
        "point_in_time_backtest": False,
        "publishable": False,
        "target_derived_history_features": False,
        "production_artifact_allowed": False,
        "deployment_allowed": False,
    }
)

_JANUARY_SOURCE_CONTRACT_FILES = (
    "anac_january_retrospective.py",
    "retrospective_audit_contract.py",
    "anac_annual_retrospective.py",
    "anac_siros_vra_join.py",
    "anac_vra_outcome_loader.py",
    "calibration.py",
    "coverage.py",
    "dedupe.py",
    "encodings.py",
    "export.py",
    "features.py",
    "labels.py",
    "pipeline.py",
    "schedule_categories.py",
    "schema.py",
    "splits.py",
    "train.py",
    "sources/anac.py",
    "sources/anac_siros.py",
)


class AnacJanuaryRetrospectiveError(ValueError):
    """The January diagnostic cannot be reproduced safely."""


class AnacJanuaryManifestError(AnacJanuaryRetrospectiveError):
    """The explicit fixed-snapshot manifest is incomplete or contradictory."""


class AnacJanuaryReconciliationError(AnacJanuaryRetrospectiveError):
    """The snapshot, join, model, or audit accounting failed closed."""


def default_january_2025_boundaries() -> ChronologicalBoundaries:
    """Return fixed 7/5/5/7-day windows on nominal prediction timestamps."""

    return ChronologicalBoundaries(
        train_end=datetime(2025, 1, 8, tzinfo=timezone.utc),
        tune_end=datetime(2025, 1, 13, tzinfo=timezone.utc),
        calibration_end=datetime(2025, 1, 18, tzinfo=timezone.utc),
        test_end=datetime(2025, 1, 25, tzinfo=timezone.utc),
    )


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_shape(
    value: Mapping[str, object],
    *,
    field_name: str,
    required: set[str],
    optional: set[str] = frozenset(),
) -> None:
    missing = required - set(value)
    unknown = set(value) - required - optional
    if missing:
        raise AnacJanuaryManifestError(
            f"{field_name} is missing required fields: {sorted(missing)!r}"
        )
    if unknown:
        raise AnacJanuaryManifestError(
            f"{field_name} contains unknown fields: {sorted(unknown)!r}"
        )


def _source_provenance() -> dict[str, object]:
    return source_code_provenance(
        base=Path(__file__).resolve().parent,
        relative_files=_JANUARY_SOURCE_CONTRACT_FILES,
        contract="skyeta-anac-january-fixed-snapshot-evaluator-source-v1",
        error_type=AnacJanuaryReconciliationError,
    )


def _validate_training_config(config: TrainingConfig) -> None:
    if not isinstance(config, TrainingConfig):
        raise TypeError("training_config must be TrainingConfig")
    for field_name in (
        "seed",
        "n_estimators",
        "num_leaves",
        "min_child_samples",
        "early_stopping_rounds",
        "num_threads",
    ):
        value = getattr(config, field_name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise AnacJanuaryManifestError(
                f"training_config.{field_name} must be an integer"
            )
        if field_name != "seed" and value <= 0:
            raise AnacJanuaryManifestError(
                f"training_config.{field_name} must be positive"
            )
    if (
        isinstance(config.learning_rate, bool)
        or not isinstance(config.learning_rate, (int, float))
        or not math.isfinite(float(config.learning_rate))
        or config.learning_rate <= 0
    ):
        raise AnacJanuaryManifestError(
            "training_config.learning_rate must be finite and positive"
        )


@dataclass(frozen=True, slots=True)
class AnacJanuaryRetrospectiveConfig:
    snapshot_path: str | Path
    snapshot_pin: AnacSirosSnapshotPin
    airport_reference_pin: AnacAirportReferenceFilePin
    outcome_input: AnacAnnualOutcomeInput
    boundaries: ChronologicalBoundaries
    training_config: TrainingConfig = TrainingConfig()
    schedule_categorical_config: ScheduleCategoricalFeatureConfig = (
        ScheduleCategoricalFeatureConfig()
    )
    matrix_memory_limits: RetrospectiveMatrixMemoryLimits = (
        RetrospectiveMatrixMemoryLimits()
    )
    service_start: date = ANAC_JANUARY_SERVICE_START
    service_end: date = ANAC_JANUARY_SERVICE_END
    minimum_schedule_age_seconds: int = (
        ANAC_JANUARY_MINIMUM_SCHEDULE_AGE_SECONDS
    )
    decision_detail_limit: int = 100

    def __post_init__(self) -> None:
        snapshot_path = Path(str(self.snapshot_path or "").strip()).resolve()
        resource = daily_snapshot_resource(ANAC_JANUARY_SNAPSHOT_DATE)
        if snapshot_path.name != resource.filename:
            raise AnacJanuaryManifestError(
                "snapshot path must end with futuro_2025-01-01.csv"
            )
        if not isinstance(self.snapshot_pin, AnacSirosSnapshotPin):
            raise TypeError("snapshot_pin must be AnacSirosSnapshotPin")
        if self.snapshot_pin.resource != resource:
            raise AnacJanuaryManifestError(
                "the diagnostic requires the 1 January 2025 daily snapshot"
            )
        if self.snapshot_pin.availability_evidence_kind != "http_last_modified":
            raise AnacJanuaryManifestError(
                "the reviewed snapshot requires exact HTTP Last-Modified evidence"
            )
        if not isinstance(self.airport_reference_pin, AnacAirportReferenceFilePin):
            raise TypeError("airport_reference_pin has an invalid type")
        if not isinstance(self.outcome_input, AnacAnnualOutcomeInput):
            raise TypeError("outcome_input must be AnacAnnualOutcomeInput")
        if self.outcome_input.year_month != (2025, 1):
            raise AnacJanuaryManifestError(
                "the diagnostic requires exactly VRA January 2025"
            )
        if self.service_start != ANAC_JANUARY_SERVICE_START:
            raise AnacJanuaryManifestError(
                "the diagnostic must start on 8 January 2025"
            )
        if self.service_end != ANAC_JANUARY_SERVICE_END:
            raise AnacJanuaryManifestError(
                "the diagnostic must end on 31 January 2025"
            )
        if self.boundaries != default_january_2025_boundaries():
            raise AnacJanuaryManifestError(
                "the diagnostic requires the reviewed January temporal boundaries"
            )
        _validate_training_config(self.training_config)
        if not isinstance(
            self.schedule_categorical_config, ScheduleCategoricalFeatureConfig
        ):
            raise TypeError(
                "schedule_categorical_config must be ScheduleCategoricalFeatureConfig"
            )
        if not self.schedule_categorical_config.enabled:
            raise AnacJanuaryManifestError(
                "enhanced training-only schedule categories must remain enabled"
            )
        if not isinstance(self.matrix_memory_limits, RetrospectiveMatrixMemoryLimits):
            raise TypeError(
                "matrix_memory_limits must be RetrospectiveMatrixMemoryLimits"
            )
        if (
            isinstance(self.minimum_schedule_age_seconds, bool)
            or self.minimum_schedule_age_seconds
            != ANAC_JANUARY_MINIMUM_SCHEDULE_AGE_SECONDS
        ):
            raise AnacJanuaryManifestError(
                "minimum_schedule_age_seconds must be exactly 604800"
            )
        if (
            isinstance(self.decision_detail_limit, bool)
            or not isinstance(self.decision_detail_limit, int)
            or not 0 <= self.decision_detail_limit <= 1000
        ):
            raise AnacJanuaryManifestError(
                "decision_detail_limit must be between 0 and 1000"
            )
        object.__setattr__(self, "snapshot_path", str(snapshot_path))

    def stable_input_facts(self) -> dict[str, object]:
        pin = self.snapshot_pin
        return {
            "schema_version": ANAC_JANUARY_RETROSPECTIVE_INPUT_SCHEMA,
            "diagnostic_month": ANAC_JANUARY_DIAGNOSTIC_MONTH,
            "daily_snapshot": {
                "source_url": pin.source_url,
                "filename": pin.resource.filename,
                "snapshot_date": ANAC_JANUARY_SNAPSHOT_DATE.isoformat(),
                "availability_evidence_kind": pin.availability_evidence_kind,
                "snapshot_observed_at_utc": _iso_utc(
                    pin.snapshot_observed_at_utc
                ),
                "retrieved_at_utc": _iso_utc(pin.retrieved_at_utc),
                "expected_sha256": pin.expected_sha256,
                "expected_bytes": pin.expected_bytes,
                "http_last_modified_utc": _iso_utc(
                    pin.http_last_modified_utc  # type: ignore[arg-type]
                ),
                "http_last_modified_raw": pin.http_last_modified_raw,
            },
            "airport_reference": self.airport_reference_pin.stable_dict(),
            "vra_outcome": self.outcome_input.stable_dict(),
            "service_start": self.service_start.isoformat(),
            "service_end": self.service_end.isoformat(),
            "minimum_schedule_age_seconds": self.minimum_schedule_age_seconds,
            "boundaries": {
                "train_end": _iso_utc(self.boundaries.train_end),
                "tune_end": _iso_utc(self.boundaries.tune_end),
                "calibration_end": _iso_utc(
                    self.boundaries.calibration_end
                ),
                "test_end": _iso_utc(self.boundaries.test_end),
            },
            "training_config": asdict(self.training_config),
            "schedule_categorical_config": asdict(
                self.schedule_categorical_config
            ),
            "matrix_memory_limits": self.matrix_memory_limits.to_dict(),
            "decision_detail_limit": self.decision_detail_limit,
            "run_semantics": dict(_RUN_SEMANTICS),
        }

    @property
    def protected_input_paths(self) -> tuple[Path, ...]:
        return (
            Path(str(self.snapshot_path)).resolve(),
            Path(str(self.airport_reference_pin.path)).resolve(),
            Path(str(self.outcome_input.pin.path)).resolve(),
        )


def _parse_boundaries(value: object) -> ChronologicalBoundaries:
    raw = _mapping(value, "boundaries")
    _require_shape(
        raw,
        field_name="boundaries",
        required={"train_end", "tune_end", "calibration_end", "test_end"},
    )
    return ChronologicalBoundaries(
        train_end=_parse_datetime(raw.get("train_end"), "boundaries.train_end"),
        tune_end=_parse_datetime(raw.get("tune_end"), "boundaries.tune_end"),
        calibration_end=_parse_datetime(
            raw.get("calibration_end"), "boundaries.calibration_end"
        ),
        test_end=_parse_datetime(raw.get("test_end"), "boundaries.test_end"),
    )


def _load_january_retrospective_manifest(
    manifest_path: str | Path,
) -> AnacJanuaryRetrospectiveConfig:
    """Load one strict local manifest without reading any pinned data file."""

    path = Path(manifest_path).expanduser().resolve()
    document, _, _ = _strict_json_bytes(path)
    _require_shape(
        document,
        field_name="manifest",
        required={
            "schema_version",
            "diagnostic_month",
            "daily_snapshot",
            "airport_reference",
            "vra_outcome",
            "service_start",
            "service_end",
            "minimum_schedule_age_seconds",
            "boundaries",
            "training_config",
            "schedule_categorical_config",
            "matrix_memory_limits",
            "decision_detail_limit",
            "run_semantics",
        },
    )
    if document.get("schema_version") != ANAC_JANUARY_RETROSPECTIVE_INPUT_SCHEMA:
        raise AnacJanuaryManifestError("unsupported January input schema_version")
    if document.get("diagnostic_month") != ANAC_JANUARY_DIAGNOSTIC_MONTH:
        raise AnacJanuaryManifestError("diagnostic_month must be 2025-01")
    base = path.parent

    snapshot = _mapping(document.get("daily_snapshot"), "daily_snapshot")
    _require_shape(
        snapshot,
        field_name="daily_snapshot",
        required={
            "path",
            "source_url",
            "snapshot_date",
            "availability_evidence_kind",
            "snapshot_observed_at_utc",
            "retrieved_at_utc",
            "expected_sha256",
            "expected_bytes",
            "http_last_modified_utc",
            "http_last_modified_raw",
        },
    )
    snapshot_date = _parse_date(
        snapshot.get("snapshot_date"), "daily_snapshot.snapshot_date"
    )
    if snapshot_date != ANAC_JANUARY_SNAPSHOT_DATE:
        raise AnacJanuaryManifestError(
            "daily_snapshot.snapshot_date must be 2025-01-01"
        )
    resource = daily_snapshot_resource(snapshot_date)
    snapshot_pin = AnacSirosSnapshotPin(
        resource=resource,
        source_url=str(snapshot.get("source_url") or ""),
        availability_evidence_kind=str(
            snapshot.get("availability_evidence_kind") or ""
        ),  # type: ignore[arg-type]
        snapshot_observed_at_utc=_parse_datetime(
            snapshot.get("snapshot_observed_at_utc"),
            "daily_snapshot.snapshot_observed_at_utc",
        ),
        retrieved_at_utc=_parse_datetime(
            snapshot.get("retrieved_at_utc"),
            "daily_snapshot.retrieved_at_utc",
        ),
        expected_sha256=_digest(
            snapshot.get("expected_sha256"),
            "daily_snapshot.expected_sha256",
        ),
        expected_bytes=_positive_int(
            snapshot.get("expected_bytes"), "daily_snapshot.expected_bytes"
        ),
        http_last_modified_utc=_parse_datetime(
            snapshot.get("http_last_modified_utc"),
            "daily_snapshot.http_last_modified_utc",
        ),
        http_last_modified_raw=str(
            snapshot.get("http_last_modified_raw") or ""
        ),
    )
    snapshot_path = _resolve_manifest_path(
        base, snapshot.get("path"), "daily_snapshot.path"
    )

    reference = _mapping(document.get("airport_reference"), "airport_reference")
    _require_shape(
        reference,
        field_name="airport_reference",
        required={
            "path",
            "expected_sha256",
            "expected_bytes",
            "expected_corpus_digest",
        },
    )
    reference_pin = AnacAirportReferenceFilePin(
        path=_resolve_manifest_path(
            base, reference.get("path"), "airport_reference.path"
        ),
        expected_sha256=reference.get("expected_sha256"),
        expected_bytes=reference.get("expected_bytes"),
        expected_corpus_digest=reference.get("expected_corpus_digest"),
    )

    outcome = _mapping(document.get("vra_outcome"), "vra_outcome")
    _require_shape(
        outcome,
        field_name="vra_outcome",
        required={
            "path",
            "source_url",
            "retrieved_at_utc",
            "expected_sha256",
            "expected_raw_bytes",
            "observation_provenance",
        },
    )
    outcome_pin = AnacVraOutcomeFilePin(
        path=_resolve_manifest_path(base, outcome.get("path"), "vra_outcome.path"),
        source_url=str(outcome.get("source_url") or ""),
        retrieved_at_utc=_parse_datetime(
            outcome.get("retrieved_at_utc"), "vra_outcome.retrieved_at_utc"
        ),
        expected_sha256=_digest(
            outcome.get("expected_sha256"), "vra_outcome.expected_sha256"
        ),
        expected_raw_bytes=_positive_int(
            outcome.get("expected_raw_bytes"),
            "vra_outcome.expected_raw_bytes",
        ),
    )
    evidence_raw = _mapping(
        outcome.get("observation_provenance"),
        "vra_outcome.observation_provenance",
    )
    _require_shape(
        evidence_raw,
        field_name="vra_outcome.observation_provenance",
        required={
            "vra_source_url",
            "raw_file_sha256",
            "outcome_observed_at_utc",
            "basis",
            "evidence_url",
            "evidence_timestamp_raw",
            "evidence_retrieved_at_utc",
            "evidence_sha256",
            "use_scope",
        },
    )
    evidence = AnacVraOutcomeObservationProvenance(
        vra_source_url=str(evidence_raw.get("vra_source_url") or ""),
        raw_file_sha256=_digest(
            evidence_raw.get("raw_file_sha256"),
            "vra_outcome.observation_provenance.raw_file_sha256",
        ),
        outcome_observed_at_utc=_parse_datetime(
            evidence_raw.get("outcome_observed_at_utc"),
            "vra_outcome.observation_provenance.outcome_observed_at_utc",
        ),
        basis=str(evidence_raw.get("basis") or ""),  # type: ignore[arg-type]
        evidence_url=str(evidence_raw.get("evidence_url") or ""),
        evidence_timestamp_raw=str(
            evidence_raw.get("evidence_timestamp_raw") or ""
        ),
        evidence_retrieved_at_utc=_parse_datetime(
            evidence_raw.get("evidence_retrieved_at_utc"),
            "vra_outcome.observation_provenance.evidence_retrieved_at_utc",
        ),
        evidence_sha256=_digest(
            evidence_raw.get("evidence_sha256"),
            "vra_outcome.observation_provenance.evidence_sha256",
        ),
        use_scope=str(evidence_raw.get("use_scope") or ""),  # type: ignore[arg-type]
    )
    outcome_input = AnacAnnualOutcomeInput(outcome_pin, evidence)

    semantics = _mapping(document.get("run_semantics"), "run_semantics")
    _require_shape(
        semantics,
        field_name="run_semantics",
        required=set(_RUN_SEMANTICS),
    )
    if dict(semantics) != dict(_RUN_SEMANTICS):
        raise AnacJanuaryManifestError(
            "run_semantics must preserve the fixed nonpublishable contract"
        )

    return AnacJanuaryRetrospectiveConfig(
        snapshot_path=snapshot_path,
        snapshot_pin=snapshot_pin,
        airport_reference_pin=reference_pin,
        outcome_input=outcome_input,
        boundaries=_parse_boundaries(document.get("boundaries")),
        training_config=_parse_training_config(document.get("training_config")),
        schedule_categorical_config=_parse_schedule_config(
            document.get("schedule_categorical_config")
        ),
        matrix_memory_limits=_parse_matrix_memory_limits(
            document.get("matrix_memory_limits")
        ),
        service_start=_parse_date(
            document.get("service_start"), "service_start"
        ),
        service_end=_parse_date(document.get("service_end"), "service_end"),
        minimum_schedule_age_seconds=_positive_int(
            document.get("minimum_schedule_age_seconds"),
            "minimum_schedule_age_seconds",
        ),
        decision_detail_limit=document.get("decision_detail_limit"),  # type: ignore[arg-type]
    )


def load_january_retrospective_manifest(
    manifest_path: str | Path,
) -> AnacJanuaryRetrospectiveConfig:
    """Load the strict manifest using January-specific public errors."""

    try:
        return _load_january_retrospective_manifest(manifest_path)
    except AnacAnnualManifestError as error:
        raise AnacJanuaryManifestError(str(error)) from error


@contextmanager
def _network_io_denied():
    """Fail closed if this offline runner or a dependency attempts networking."""

    def blocked(*_args, **_kwargs):
        raise AnacJanuaryReconciliationError(
            "network I/O is forbidden during the January diagnostic"
        )

    with ExitStack() as stack:
        stack.enter_context(patch.object(socket, "create_connection", blocked))
        stack.enter_context(patch.object(socket, "getaddrinfo", blocked))
        stack.enter_context(patch.object(socket, "gethostbyname", blocked))
        stack.enter_context(patch.object(socket, "gethostbyname_ex", blocked))
        stack.enter_context(patch.object(socket, "gethostbyaddr", blocked))
        stack.enter_context(patch.object(socket, "getnameinfo", blocked))
        for method_name in ("connect", "connect_ex", "sendto", "sendmsg"):
            if hasattr(socket.socket, method_name):
                stack.enter_context(
                    patch.object(socket.socket, method_name, blocked)
                )
        # Deny new sockets after patching methods on any already-imported class
        # alias, and deny child-process escape hatches for the duration of the
        # reviewed computation.
        stack.enter_context(patch.object(socket, "socket", blocked))
        stack.enter_context(patch.object(subprocess, "Popen", blocked))
        for function_name in (
            "system",
            "popen",
            "startfile",
            "spawnl",
            "spawnle",
            "spawnlp",
            "spawnlpe",
            "spawnv",
            "spawnve",
            "spawnvp",
            "spawnvpe",
        ):
            if hasattr(os, function_name):
                stack.enter_context(patch.object(os, function_name, blocked))
        yield


def _service_dates(start: date, end: date) -> tuple[date, ...]:
    return tuple(
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
    )


def _snapshot_summary(snapshot: AnacSirosSeriesSnapshot) -> dict[str, object]:
    audit = snapshot.audit
    file = audit.file
    return {
        "source_url": file.source_url,
        "filename": file.filename,
        "snapshot_date": file.snapshot_date.isoformat(),  # type: ignore[union-attr]
        "availability_evidence_kind": file.availability_evidence_kind,
        "snapshot_observed_at_utc": _iso_utc(file.snapshot_observed_at_utc),
        "retrieved_at_utc": _iso_utc(file.retrieved_at_utc),
        "http_last_modified_utc": _iso_utc(
            file.http_last_modified_utc  # type: ignore[arg-type]
        ),
        "http_last_modified_raw": file.http_last_modified_raw,
        "raw_file_sha256": file.raw_file_sha256,
        "raw_bytes": file.raw_bytes,
        "raw_row_count": audit.raw_row_count,
        "accepted_row_count": audit.accepted_row_count,
        "rejected_row_count": audit.rejected_row_count,
        "accepted_series_facts_sha256": audit.accepted_series_facts_sha256,
        "public_availability_proven": file.public_availability_proven,
        "point_in_time_eligible_source_rows": file.point_in_time_eligible,
        "completed": audit.completed,
    }


def _age_summary(
    snapshot: AnacSirosSeriesSnapshot,
    config: AnacJanuaryRetrospectiveConfig,
) -> tuple[tuple[AnacSirosServiceObservation, ...], dict[str, object]]:
    eligible: list[AnacSirosServiceObservation] = []
    per_date: list[dict[str, object]] = []
    all_ages: list[int] = []
    eligible_ages: list[int] = []
    for service_date in _service_dates(config.service_start, config.service_end):
        expanded = expand_siros_snapshot(snapshot, service_date)
        date_ages = [
            int(
                (row.scheduled_departure_utc - row.schedule_observed_at_utc)
                .total_seconds()
            )
            for row in expanded
        ]
        if any(age < 0 for age in date_ages):
            raise AnacJanuaryReconciliationError(
                "snapshot observation follows an expanded scheduled departure"
            )
        date_eligible = tuple(
            row
            for row, age in zip(expanded, date_ages, strict=True)
            if age >= config.minimum_schedule_age_seconds
        )
        date_eligible_ages = [
            int(
                (row.scheduled_departure_utc - row.schedule_observed_at_utc)
                .total_seconds()
            )
            for row in date_eligible
        ]
        eligible.extend(date_eligible)
        all_ages.extend(date_ages)
        eligible_ages.extend(date_eligible_ages)
        per_date.append(
            {
                "service_date": service_date.isoformat(),
                "expanded_schedule_rows": len(expanded),
                "eligible_schedule_rows": len(date_eligible),
                "too_recent_schedule_rows": len(expanded) - len(date_eligible),
                "minimum_observation_age_seconds": (
                    min(date_ages) if date_ages else None
                ),
                "maximum_observation_age_seconds": (
                    max(date_ages) if date_ages else None
                ),
                "minimum_eligible_observation_age_seconds": (
                    min(date_eligible_ages) if date_eligible_ages else None
                ),
                "maximum_eligible_observation_age_seconds": (
                    max(date_eligible_ages) if date_eligible_ages else None
                ),
            }
        )
    if not eligible:
        raise AnacJanuaryReconciliationError(
            "the fixed snapshot produced no schedule old enough for evaluation"
        )
    facts = {
        "selection_kind": "single_fixed_snapshot_minimum_age_filter",
        "snapshot_reused_across_service_dates": True,
        "daily_snapshot_series_used": False,
        "minimum_required_observation_age_seconds": (
            config.minimum_schedule_age_seconds
        ),
        "expanded_schedule_rows": len(all_ages),
        "eligible_schedule_rows": len(eligible),
        "too_recent_schedule_rows": len(all_ages) - len(eligible),
        "minimum_observation_age_seconds": min(all_ages) if all_ages else None,
        "maximum_observation_age_seconds": max(all_ages) if all_ages else None,
        "minimum_eligible_observation_age_seconds": min(eligible_ages),
        "maximum_eligible_observation_age_seconds": max(eligible_ages),
        "exact_minimum_age_rows": sum(
            age == config.minimum_schedule_age_seconds for age in eligible_ages
        ),
        "per_service_date": per_date,
        "interpretation": (
            "The 1 January snapshot becomes progressively older across the "
            "8--31 January service window. Eligibility proves only that its "
            "actual observation timestamp preceded a departure by at least "
            "seven days; it does not prove a fresh daily schedule view."
        ),
    }
    return tuple(eligible), facts


def _join_population_counts(
    result: AnacSirosVraJoinResult,
) -> tuple[Counter[str], int, int, int]:
    audit = result.audit
    totals = Counter(
        {
            "schedule_unmatched_count": audit.disposition_count(
                "schedule", "unmatched"
            ),
            "schedule_ambiguous_count": audit.disposition_count(
                "schedule", "ambiguous"
            ),
            "schedule_rejected_count": audit.disposition_count(
                "schedule", "rejected"
            ),
            "outcome_unmatched_count": audit.disposition_count(
                "outcome", "unmatched"
            ),
            "outcome_ambiguous_count": audit.disposition_count(
                "outcome", "ambiguous"
            ),
            "outcome_rejected_count": audit.disposition_count(
                "outcome", "rejected"
            ),
        }
    )
    matched = audit.matched_pair_count
    schedules = audit.input_schedule_count
    outcomes = audit.input_outcome_count
    if matched + sum(
        totals[key]
        for key in (
            "schedule_unmatched_count",
            "schedule_ambiguous_count",
            "schedule_rejected_count",
        )
    ) != schedules or matched + sum(
        totals[key]
        for key in (
            "outcome_unmatched_count",
            "outcome_ambiguous_count",
            "outcome_rejected_count",
        )
    ) != outcomes:
        raise AnacJanuaryReconciliationError(
            "January exact-join population accounting is inconsistent"
        )
    return totals, matched, schedules, outcomes


def _run_january_retrospective_evaluation(
    config: AnacJanuaryRetrospectiveConfig,
) -> dict[str, object]:
    source_provenance = _source_provenance()
    airports, reference_summary = _load_airport_reference(
        config.airport_reference_pin
    )
    snapshot = load_siros_series_snapshot(
        Path(str(config.snapshot_path)), pin=config.snapshot_pin
    )
    eligible_schedules, age_facts = _age_summary(snapshot, config)
    outcome_result = load_anac_vra_outcome_file(
        config.outcome_input.pin,
        airports,
        observation_provenance=config.outcome_input.observation_provenance,
    )
    outcomes = tuple(
        candidate
        for candidate in outcome_result.candidates
        if config.service_start
        <= candidate.record.scheduled_departure_utc.date()
        <= config.service_end
    )
    if not outcomes:
        raise AnacJanuaryReconciliationError(
            "VRA January produced no outcome candidates in the service window"
        )
    join = join_siros_schedules_to_vra_outcomes(
        eligible_schedules,
        outcomes,
        prediction_horizon=timedelta(
            seconds=config.minimum_schedule_age_seconds
        ),
    )
    totals, matched_count, eligible_count, outcome_count = (
        _join_population_counts(join)
    )
    if eligible_count != age_facts["eligible_schedule_rows"]:
        raise AnacJanuaryReconciliationError(
            "eligible schedule denominator changed before the exact join"
        )
    records = tuple(
        sorted(
            join.retrospective_holdout_records,
            key=lambda row: (row.scheduled_departure_utc, row.canonical_key),
        )
    )
    if not records or len(records) != matched_count:
        raise AnacJanuaryReconciliationError(
            "January exact join produced no reconciled model corpus"
        )
    if len({row.record_id for row in records}) != len(records):
        raise AnacJanuaryReconciliationError(
            "January exact join produced duplicate record identities"
        )
    schedule_aircraft = {
        match.match_id: match.schedule.aircraft_family for match in join.matches
    }
    if any(
        record.aircraft_family != schedule_aircraft[record.record_id]
        for record in records
    ):
        raise AnacJanuaryReconciliationError(
            "joined aircraft feature did not come exclusively from SIROS"
        )

    cohort = exact_join_cohort_qualification(
        matched_count=matched_count,
        eligible_schedule_count=eligible_count,
        outcome_count=outcome_count,
        schedule_dispositions={
            "matched": matched_count,
            "unmatched": totals["schedule_unmatched_count"],
            "ambiguous": totals["schedule_ambiguous_count"],
            "rejected": totals["schedule_rejected_count"],
        },
        outcome_dispositions={
            "matched": matched_count,
            "unmatched": totals["outcome_unmatched_count"],
            "ambiguous": totals["outcome_ambiguous_count"],
            "rejected": totals["outcome_rejected_count"],
        },
        interpretation=(
            "Metrics describe only fixed-snapshot schedules old enough for "
            "the seven-day minimum whose final VRA schedule remained exactly "
            "joinable. They are not January-population performance estimates; "
            "too-recent, schedule-changed, unmatched, and ambiguous services "
            "can differ systematically."
        ),
        population_claim_field="january_population_performance_claim_allowed",
    )
    cohort["fixed_snapshot_expanded_schedule_rows"] = age_facts[
        "expanded_schedule_rows"
    ]
    cohort["minimum_age_ineligible_schedule_rows"] = age_facts[
        "too_recent_schedule_rows"
    ]

    prepared = prepare_retrospective_global_data(
        records,
        config.boundaries,
        schedule_categorical_config=config.schedule_categorical_config,
        matrix_memory_limits=config.matrix_memory_limits,
    )
    if not prepared.schedule_categorical_snapshot.config.enabled:
        raise AnacJanuaryReconciliationError(
            "January preparation disabled enhanced schedule categories"
        )
    evaluation = evaluate_retrospective_temporal_model(
        prepared, config=config.training_config
    )
    evaluation = validate_retrospective_evaluator_contract(
        prepared=prepared,
        evaluation=evaluation,
        training_config=config.training_config,
        matrix_memory_limits=config.matrix_memory_limits,
        source_contract_sha256=str(source_provenance["aggregate_sha256"]),
        cohort_qualification=cohort,
        error_type=AnacJanuaryReconciliationError,
    )

    input_facts = config.stable_input_facts()
    joined_ids = sorted(record.record_id for record in records)
    payload: dict[str, object] = {
        "schema_version": ANAC_JANUARY_RETROSPECTIVE_OUTPUT_SCHEMA,
        "evaluation_kind": "retrospective_fixed_snapshot_diagnostic",
        "point_in_time_backtest": False,
        "publishable": False,
        "target_derived_history_features_used": False,
        "production_artifact_created": False,
        "deployment_performed": False,
        "network_io_performed_by_runner": False,
        "offline_execution_guard": {
            "python_socket_construction_denied": True,
            "python_socket_operations_denied": True,
            "child_process_creation_denied": True,
        },
        "scope": {
            "region": "Brazil and ANAC-recorded Brazil-touching services",
            "diagnostic_month": ANAC_JANUARY_DIAGNOSTIC_MONTH,
            "service_start": config.service_start.isoformat(),
            "service_end": config.service_end.isoformat(),
            "schedule_view": (
                "one 1 January snapshot reused with actual per-departure age"
            ),
            "minimum_schedule_age_seconds": (
                config.minimum_schedule_age_seconds
            ),
            "metric_cohort": (
                "exactly joinable minimum-age-eligible fixed-snapshot schedules only"
            ),
            "january_population_performance_claim_allowed": False,
        },
        "outcome_target_capabilities": {
            "source": "ANAC Voo Regular Ativo (VRA)",
            "terminal_statuses": ["landed", "cancelled"],
            "arrival_delay_thresholds_supported": [15, 30, 60],
            "cancellation_supported": True,
            "diversion_supported": False,
            "distinct_disruption_claim_allowed": False,
            "disrupted_head_interpretation": (
                "ANAC VRA exposes no distinct diverted status, so this corpus "
                "makes disrupted identical to cancelled."
            ),
        },
        "input_facts": input_facts,
        "input_facts_sha256": canonical_sha256(input_facts),
        "airport_reference": reference_summary,
        "siros_daily_snapshot": _snapshot_summary(snapshot),
        "schedule_observation_age_audit": age_facts,
        "vra_outcome": _outcome_load_summary(
            outcome_result,
            service_start=config.service_start,
            service_end=config.service_end,
        ),
        "exact_join": _join_summary(
            join,
            service_year=2025,
            service_month=1,
            detail_limit=config.decision_detail_limit,
        ),
        "exact_join_cohort": cohort,
        "joined_corpus": {
            "rows": len(records),
            "record_ids_sha256": hashlib.sha256(
                "\n".join(joined_ids).encode("ascii")
            ).hexdigest(),
            "dedupe_input_rows": prepared.dedupe.input_rows,
            "deduplicated_rows": len(prepared.dedupe.records),
            "duplicate_rows_removed": prepared.dedupe.duplicate_rows,
        },
        "feature_provenance": {
            "aircraft_family_source": "SIROS daily schedule only",
            "vra_equipment_used_as_feature": False,
            "target_derived_history_features": False,
        },
        "schedule_categorical_snapshot": (
            prepared.schedule_categorical_snapshot.to_dict()
        ),
        "matrix_storage_audit": prepared.matrix_audit.to_dict(),
        "model_evaluation": evaluation,
        "source_code_provenance": source_provenance,
    }
    if _source_provenance() != source_provenance:
        raise AnacJanuaryReconciliationError(
            "reviewed source contract changed during the January run"
        )
    payload["audit_sha256"] = canonical_sha256(payload)
    return payload


def run_anac_january_retrospective_evaluation(
    config: AnacJanuaryRetrospectiveConfig,
) -> dict[str, object]:
    """Run the fixed evaluator under an explicit process-local network deny."""

    if not isinstance(config, AnacJanuaryRetrospectiveConfig):
        raise TypeError("config must be AnacJanuaryRetrospectiveConfig")
    with _network_io_denied():
        return _run_january_retrospective_evaluation(config)


def write_january_retrospective_audit(
    result: Mapping[str, object], output_path: str | Path
) -> Path:
    return write_canonical_audit(
        result,
        output_path,
        expected_schema=ANAC_JANUARY_RETROSPECTIVE_OUTPUT_SCHEMA,
        error_type=AnacJanuaryReconciliationError,
    )


def _guard_output_target(
    manifest_path: Path,
    output_path: Path,
    config: AnacJanuaryRetrospectiveConfig,
) -> None:
    protected = {manifest_path.resolve(), *config.protected_input_paths}
    source_base = Path(__file__).resolve().parent
    protected.update(
        source_base.joinpath(*relative_name.split("/")).resolve()
        for relative_name in _JANUARY_SOURCE_CONTRACT_FILES
    )
    resolved_output = output_path.resolve()
    if resolved_output in protected:
        raise AnacJanuaryManifestError(
            "output must not overwrite the manifest, a pinned input, or reviewed source"
        )
    if resolved_output.exists() and resolved_output.is_dir():
        raise AnacJanuaryManifestError("output must be a file path, not a directory")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the offline, nondeployable SkyETA January 2025 fixed-snapshot "
            "diagnostic from a hash-pinned manifest."
        )
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--execute",
        required=True,
        action="store_true",
        help="explicitly authorize the local diagnostic computation",
    )
    args = parser.parse_args(argv)
    config = load_january_retrospective_manifest(args.manifest)
    _guard_output_target(args.manifest, args.output, config)
    result = run_anac_january_retrospective_evaluation(config)
    output = write_january_retrospective_audit(result, args.output)
    print(
        canonical_json(
            {
                "output": str(output),
                "audit_sha256": result["audit_sha256"],
                "publishable": False,
                "deployed": False,
            }
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through CLI tests
    raise SystemExit(main())


__all__ = [
    "ANAC_JANUARY_DIAGNOSTIC_MONTH",
    "ANAC_JANUARY_MINIMUM_SCHEDULE_AGE_SECONDS",
    "ANAC_JANUARY_RETROSPECTIVE_INPUT_SCHEMA",
    "ANAC_JANUARY_RETROSPECTIVE_OUTPUT_SCHEMA",
    "ANAC_JANUARY_SERVICE_END",
    "ANAC_JANUARY_SERVICE_START",
    "ANAC_JANUARY_SNAPSHOT_DATE",
    "AnacJanuaryManifestError",
    "AnacJanuaryReconciliationError",
    "AnacJanuaryRetrospectiveConfig",
    "AnacJanuaryRetrospectiveError",
    "default_january_2025_boundaries",
    "load_january_retrospective_manifest",
    "main",
    "run_anac_january_retrospective_evaluation",
    "write_january_retrospective_audit",
]
