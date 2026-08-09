"""Reproducible, offline ANAC 2023 retrospective evaluation runner.

The runner binds three already-local input families by byte size and SHA-256:
the strict SIROS annual archive, a prepared airport-reference JSON file, and
the twelve monthly VRA outcome files.  It never performs network I/O.

For service date ``D`` it loads annual member ``D - 8 days``.  The reviewed
annual-member policy gives that member only a conservative next-day 00:00 UTC
*retrospective evidence bound*.  Consequently the bound is at or before the
earliest T-7 instant for every departure on ``D``.  This is deliberately not a
claim that the historical member was publicly available at that time.

Ingestion and exact SIROS-to-VRA joins are processed one UTC service month at a
time.  Only the joined records and compact, digest-bound audit summaries remain
resident after a month is reconciled.  Model preparation necessarily
materializes the complete joined corpus, but it cannot export an artifact and
keeps target-derived history disabled.
"""

from __future__ import annotations

import argparse
import heapq
import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

from .anac_siros_vra_join import (
    AnacSirosVraJoinResult,
    AnacVraOutcomeObservationProvenance,
    join_siros_schedules_to_vra_outcomes,
)
from .anac_vra_outcome_loader import (
    AnacVraOutcomeFilePin,
    AnacVraOutcomeLoadResult,
    load_anac_vra_outcome_file,
)
from .export import MODEL_HEADS
from .pipeline import (
    RetrospectiveMatrixMemoryLimits,
    prepare_retrospective_global_data,
)
from .schedule_categories import ScheduleCategoricalFeatureConfig
from .schema import GlobalFlightRecord
from .sources.anac import AirportMetadata
from .sources.anac_siros import (
    ANAC_SIROS_RETROSPECTIVE_POLICY_ID,
    AnacSirosAnnualArchiveAudit,
    AnacSirosAnnualArchivePin,
    AnacSirosRetrospectiveEvidencePolicy,
    AnacSirosServiceObservation,
    annual_zip_resource,
    iter_siros_annual_snapshots,
    select_retrospective_services_at_t_minus_7,
    validate_siros_annual_archive,
)
from .splits import ChronologicalBoundaries
from .train import (
    TrainingConfig,
    evaluate_retrospective_temporal_model,
)


ANAC_ANNUAL_RETROSPECTIVE_INPUT_SCHEMA = (
    "skyeta-anac-annual-retrospective-input-v1"
)
ANAC_ANNUAL_RETROSPECTIVE_OUTPUT_SCHEMA = (
    "skyeta-anac-annual-retrospective-evaluation-v1"
)
ANAC_REFERENCE_SCHEMA_VERSION = "skyeta-anac-reference-v1"
ANAC_ANNUAL_EVALUATION_YEAR = 2023
ANAC_ANNUAL_SERVICE_START = date(2023, 1, 9)
ANAC_ANNUAL_SERVICE_END = date(2023, 12, 31)
ANAC_ANNUAL_SNAPSHOT_OFFSET_DAYS = 8

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VRA_FILENAME = re.compile(r"^VRA_(\d{4})_(0[1-9]|1[0-2])\.csv$")

_ANNUAL_SOURCE_CONTRACT_FILES = (
    "anac_annual_retrospective.py",
    "anac_siros_vra_join.py",
    "anac_vra_outcome_loader.py",
    "calibration.py",
    "dedupe.py",
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


class AnacAnnualRetrospectiveError(ValueError):
    """The annual retrospective run cannot be reproduced safely."""


class AnacAnnualManifestError(AnacAnnualRetrospectiveError):
    """The explicit local-input manifest is incomplete or contradictory."""


class AnacAnnualReconciliationError(AnacAnnualRetrospectiveError):
    """Monthly selection, join, or corpus accounting failed closed."""


def _utc(value: datetime, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise AnacAnnualManifestError(
            f"{field_name} must be a timezone-aware datetime"
        )
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: object, field_name: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise AnacAnnualManifestError(f"{field_name} is required")
    rendered = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(rendered)
    except ValueError as error:
        raise AnacAnnualManifestError(
            f"{field_name} must be an ISO-8601 datetime"
        ) from error
    return _utc(parsed, field_name)


def _parse_date(value: object, field_name: str) -> date:
    text = str(value or "").strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as error:
        raise AnacAnnualManifestError(
            f"{field_name} must be an ISO-8601 date"
        ) from error
    return parsed


def _digest(value: object, field_name: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256.fullmatch(text):
        raise AnacAnnualManifestError(
            f"{field_name} must contain one lowercase SHA-256 digest"
        )
    return text


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AnacAnnualManifestError(f"{field_name} must be a positive integer")
    return value


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise AnacAnnualManifestError(f"{field_name} must be boolean")
    return value


def _canonical_json(value: object, *, indent: int | None = None) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        indent=indent,
        separators=(",", ":") if indent is None else None,
    )


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _source_code_provenance() -> dict[str, object]:
    """Bind an audit to the exact reviewed ingestion/evaluation source bytes."""

    base = Path(__file__).resolve().parent
    files: list[dict[str, object]] = []
    for relative_name in _ANNUAL_SOURCE_CONTRACT_FILES:
        path = base.joinpath(*relative_name.split("/"))
        if not path.is_file():
            raise AnacAnnualReconciliationError(
                f"reviewed source-contract file is missing: {relative_name}"
            )
        raw = path.read_bytes()
        files.append(
            {
                "path": relative_name,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return {
        "contract": "skyeta-anac-annual-evaluator-source-v1",
        "files": files,
        "aggregate_sha256": _canonical_sha256(files),
    }


def _strict_json_bytes(path: Path) -> tuple[dict[str, object], str, int]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    raw = resolved.read_bytes()

    def reject_constant(value: str) -> object:
        raise AnacAnnualManifestError(f"non-finite JSON value is forbidden: {value}")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise AnacAnnualManifestError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AnacAnnualManifestError(f"invalid UTF-8 JSON file: {resolved}") from error
    if not isinstance(value, dict):
        raise AnacAnnualManifestError("JSON root must be an object")
    return value, hashlib.sha256(raw).hexdigest(), len(raw)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AnacAnnualManifestError(f"{field_name} must be an object")
    return value


def _sequence(value: object, field_name: str) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise AnacAnnualManifestError(f"{field_name} must be an array")
    return tuple(value)


def _resolve_manifest_path(base: Path, value: object, field_name: str) -> Path:
    text = str(value or "").strip()
    if not text:
        raise AnacAnnualManifestError(f"{field_name} is required")
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def default_2023_boundaries() -> ChronologicalBoundaries:
    """Return fixed prediction-time windows spanning the 2023 seasons."""

    return ChronologicalBoundaries(
        train_end=datetime(2023, 7, 1, tzinfo=timezone.utc),
        tune_end=datetime(2023, 9, 1, tzinfo=timezone.utc),
        calibration_end=datetime(2023, 11, 1, tzinfo=timezone.utc),
        test_end=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


@dataclass(frozen=True, slots=True)
class AnacAirportReferenceFilePin:
    """Byte pin for a prepared, already-local airport-reference JSON file."""

    path: str | Path
    expected_sha256: str
    expected_bytes: int
    expected_corpus_digest: str

    def __post_init__(self) -> None:
        path = Path(str(self.path or "").strip()).resolve()
        object.__setattr__(self, "path", str(path))
        object.__setattr__(
            self,
            "expected_sha256",
            _digest(self.expected_sha256, "airport reference expected_sha256"),
        )
        object.__setattr__(
            self,
            "expected_bytes",
            _positive_int(self.expected_bytes, "airport reference expected_bytes"),
        )
        object.__setattr__(
            self,
            "expected_corpus_digest",
            _digest(
                self.expected_corpus_digest,
                "airport reference expected_corpus_digest",
            ),
        )

    def stable_dict(self) -> dict[str, object]:
        return {
            "filename": Path(str(self.path)).name,
            "expected_sha256": self.expected_sha256,
            "expected_bytes": self.expected_bytes,
            "expected_corpus_digest": self.expected_corpus_digest,
        }


@dataclass(frozen=True, slots=True)
class AnacAnnualOutcomeInput:
    pin: AnacVraOutcomeFilePin
    observation_provenance: AnacVraOutcomeObservationProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.pin, AnacVraOutcomeFilePin):
            raise TypeError("pin must be AnacVraOutcomeFilePin")
        if not isinstance(
            self.observation_provenance, AnacVraOutcomeObservationProvenance
        ):
            raise TypeError(
                "observation_provenance must be AnacVraOutcomeObservationProvenance"
            )
        evidence = self.observation_provenance
        if evidence.use_scope != "retrospective_holdout_only":
            raise AnacAnnualManifestError(
                "annual outcomes must remain retrospective_holdout_only"
            )
        if evidence.vra_source_url != self.pin.source_url:
            raise AnacAnnualManifestError(
                "outcome evidence source does not match its pinned VRA file"
            )
        if evidence.raw_file_sha256 != self.pin.expected_sha256:
            raise AnacAnnualManifestError(
                "outcome evidence digest does not match its pinned VRA file"
            )

    @property
    def year_month(self) -> tuple[int, int]:
        match = _VRA_FILENAME.fullmatch(self.pin.filename)
        if match is None:  # already guarded by AnacVraOutcomeFilePin
            raise AnacAnnualManifestError("invalid VRA filename")
        return int(match.group(1)), int(match.group(2))

    def stable_dict(self) -> dict[str, object]:
        return {
            "file": self.pin.stable_dict(),
            "observation_provenance": self.observation_provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class AnacAnnualRetrospectiveConfig:
    year: int
    annual_archive_path: str | Path
    annual_archive_pin: AnacSirosAnnualArchivePin
    evidence_policy: AnacSirosRetrospectiveEvidencePolicy
    airport_reference_pin: AnacAirportReferenceFilePin
    outcome_inputs: tuple[AnacAnnualOutcomeInput, ...]
    boundaries: ChronologicalBoundaries
    training_config: TrainingConfig = TrainingConfig()
    schedule_categorical_config: ScheduleCategoricalFeatureConfig = (
        ScheduleCategoricalFeatureConfig()
    )
    matrix_memory_limits: RetrospectiveMatrixMemoryLimits = (
        RetrospectiveMatrixMemoryLimits()
    )
    service_start: date = ANAC_ANNUAL_SERVICE_START
    service_end: date = ANAC_ANNUAL_SERVICE_END
    decision_detail_limit: int = 100

    def __post_init__(self) -> None:
        if self.year != ANAC_ANNUAL_EVALUATION_YEAR:
            raise AnacAnnualManifestError("this reviewed runner is fixed to 2023")
        archive_path = Path(str(self.annual_archive_path or "").strip()).resolve()
        if archive_path.name != f"{self.year}.zip":
            raise AnacAnnualManifestError(
                "annual archive path must end with the reviewed year ZIP filename"
            )
        if self.annual_archive_pin.resource != annual_zip_resource(self.year):
            raise AnacAnnualManifestError("annual archive pin year is inconsistent")
        if not isinstance(
            self.evidence_policy, AnacSirosRetrospectiveEvidencePolicy
        ):
            raise TypeError(
                "evidence_policy must be AnacSirosRetrospectiveEvidencePolicy"
            )
        if self.evidence_policy.policy_id != ANAC_SIROS_RETROSPECTIVE_POLICY_ID:
            raise AnacAnnualManifestError(
                "annual schedule evidence must use the reviewed retrospective policy"
            )
        if not isinstance(self.airport_reference_pin, AnacAirportReferenceFilePin):
            raise TypeError("airport_reference_pin has an invalid type")
        inputs = tuple(self.outcome_inputs)
        expected = {(self.year, month) for month in range(1, 13)}
        observed = [item.year_month for item in inputs]
        if set(observed) != expected or len(observed) != 12:
            raise AnacAnnualManifestError(
                "annual evaluation requires exactly VRA January through December 2023"
            )
        inputs = tuple(sorted(inputs, key=lambda item: item.year_month))
        if not isinstance(self.boundaries, ChronologicalBoundaries):
            raise TypeError("boundaries must be ChronologicalBoundaries")
        if not isinstance(self.training_config, TrainingConfig):
            raise TypeError("training_config must be TrainingConfig")
        for field_name in (
            "seed",
            "n_estimators",
            "num_leaves",
            "min_child_samples",
            "early_stopping_rounds",
            "num_threads",
        ):
            value = getattr(self.training_config, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise AnacAnnualManifestError(
                    f"training_config.{field_name} must be an integer"
                )
            if field_name != "seed" and value <= 0:
                raise AnacAnnualManifestError(
                    f"training_config.{field_name} must be positive"
                )
        if (
            isinstance(self.training_config.learning_rate, bool)
            or not isinstance(self.training_config.learning_rate, (int, float))
            or not math.isfinite(float(self.training_config.learning_rate))
            or self.training_config.learning_rate <= 0
        ):
            raise AnacAnnualManifestError(
                "training_config.learning_rate must be finite and positive"
            )
        if not isinstance(
            self.schedule_categorical_config,
            ScheduleCategoricalFeatureConfig,
        ):
            raise TypeError(
                "schedule_categorical_config must be ScheduleCategoricalFeatureConfig"
            )
        if not self.schedule_categorical_config.enabled:
            raise AnacAnnualManifestError(
                "enhanced training-only schedule categories must remain enabled"
            )
        if not isinstance(
            self.matrix_memory_limits,
            RetrospectiveMatrixMemoryLimits,
        ):
            raise TypeError(
                "matrix_memory_limits must be RetrospectiveMatrixMemoryLimits"
            )
        if self.service_start != ANAC_ANNUAL_SERVICE_START:
            raise AnacAnnualManifestError(
                "2023 evaluation must start 9 January so D-8 stays inside the archive"
            )
        if self.service_end != ANAC_ANNUAL_SERVICE_END:
            raise AnacAnnualManifestError(
                "2023 evaluation must end 31 December"
            )
        if (
            isinstance(self.decision_detail_limit, bool)
            or not isinstance(self.decision_detail_limit, int)
            or not 0 <= self.decision_detail_limit <= 1000
        ):
            raise AnacAnnualManifestError(
                "decision_detail_limit must be between 0 and 1000"
            )
        object.__setattr__(self, "annual_archive_path", str(archive_path))
        object.__setattr__(self, "outcome_inputs", inputs)

    @property
    def outcome_by_month(self) -> Mapping[int, AnacAnnualOutcomeInput]:
        return MappingProxyType(
            {item.year_month[1]: item for item in self.outcome_inputs}
        )

    def stable_input_facts(self) -> dict[str, object]:
        annual = self.annual_archive_pin
        return {
            "schema_version": ANAC_ANNUAL_RETROSPECTIVE_INPUT_SCHEMA,
            "year": self.year,
            "annual_archive": {
                "source_url": annual.source_url,
                "filename": annual.resource.filename,
                "retrieved_at_utc": _iso_utc(annual.retrieved_at_utc),
                "expected_sha256": annual.expected_sha256,
                "expected_bytes": annual.expected_bytes,
                "archive_last_modified_utc": _iso_utc(
                    annual.archive_last_modified_utc
                ),
                "archive_last_modified_raw": annual.archive_last_modified_raw,
            },
            "annual_member_evidence_policy": self.evidence_policy.to_dict(),
            "airport_reference": self.airport_reference_pin.stable_dict(),
            "vra_months": [item.stable_dict() for item in self.outcome_inputs],
            "service_start": self.service_start.isoformat(),
            "service_end": self.service_end.isoformat(),
            "boundaries": {
                "train_end": _iso_utc(self.boundaries.train_end),
                "tune_end": _iso_utc(self.boundaries.tune_end),
                "calibration_end": _iso_utc(self.boundaries.calibration_end),
                "test_end": _iso_utc(self.boundaries.test_end),
            },
            "training_config": asdict(self.training_config),
            "schedule_categorical_config": asdict(
                self.schedule_categorical_config
            ),
            "matrix_memory_limits": self.matrix_memory_limits.to_dict(),
            "decision_detail_limit": self.decision_detail_limit,
        }


def _parse_training_config(value: object) -> TrainingConfig:
    if value is None:
        return TrainingConfig()
    raw = _mapping(value, "training_config")
    allowed = {
        "seed",
        "n_estimators",
        "learning_rate",
        "num_leaves",
        "min_child_samples",
        "early_stopping_rounds",
        "num_threads",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise AnacAnnualManifestError(
            f"unknown training_config fields: {sorted(unknown)!r}"
        )
    try:
        return TrainingConfig(**raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise AnacAnnualManifestError("invalid training_config") from error


def _parse_schedule_config(value: object) -> ScheduleCategoricalFeatureConfig:
    if value is None:
        return ScheduleCategoricalFeatureConfig()
    raw = _mapping(value, "schedule_categorical_config")
    allowed = {
        "enabled",
        "max_operating_carriers",
        "max_origins",
        "max_destinations",
        "max_aircraft_families",
        "max_routes",
        "include_fit_frequency_features",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise AnacAnnualManifestError(
            f"unknown schedule_categorical_config fields: {sorted(unknown)!r}"
        )
    try:
        return ScheduleCategoricalFeatureConfig(**raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise AnacAnnualManifestError(
            "invalid schedule_categorical_config"
        ) from error


def _parse_matrix_memory_limits(
    value: object,
) -> RetrospectiveMatrixMemoryLimits:
    if value is None:
        return RetrospectiveMatrixMemoryLimits()
    raw = _mapping(value, "matrix_memory_limits")
    allowed = {
        "max_partition_peak_bytes",
        "max_total_csr_bytes",
        "max_evaluation_additional_bytes",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise AnacAnnualManifestError(
            f"unknown matrix_memory_limits fields: {sorted(unknown)!r}"
        )
    try:
        return RetrospectiveMatrixMemoryLimits(**raw)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise AnacAnnualManifestError(
            "invalid matrix_memory_limits"
        ) from error


def load_annual_retrospective_manifest(
    manifest_path: str | Path,
) -> AnacAnnualRetrospectiveConfig:
    """Load a strict local-only manifest without touching any data source."""

    path = Path(manifest_path).expanduser().resolve()
    document, _, _ = _strict_json_bytes(path)
    if document.get("schema_version") != ANAC_ANNUAL_RETROSPECTIVE_INPUT_SCHEMA:
        raise AnacAnnualManifestError("unsupported annual input schema_version")
    year = document.get("year")
    if year != ANAC_ANNUAL_EVALUATION_YEAR:
        raise AnacAnnualManifestError("annual input year must be 2023")
    base = path.parent

    archive = _mapping(document.get("annual_archive"), "annual_archive")
    archive_path = _resolve_manifest_path(
        base, archive.get("path"), "annual_archive.path"
    )
    resource = annual_zip_resource(year)
    archive_pin = AnacSirosAnnualArchivePin(
        resource=resource,
        source_url=str(archive.get("source_url") or ""),
        retrieved_at_utc=_parse_datetime(
            archive.get("retrieved_at_utc"),
            "annual_archive.retrieved_at_utc",
        ),
        expected_sha256=_digest(
            archive.get("expected_sha256"),
            "annual_archive.expected_sha256",
        ),
        expected_bytes=_positive_int(
            archive.get("expected_bytes"),
            "annual_archive.expected_bytes",
        ),
        archive_last_modified_utc=_parse_datetime(
            archive.get("archive_last_modified_utc"),
            "annual_archive.archive_last_modified_utc",
        ),
        archive_last_modified_raw=str(
            archive.get("archive_last_modified_raw") or ""
        ),
    )

    policy_raw = _mapping(
        document.get("annual_member_evidence_policy"),
        "annual_member_evidence_policy",
    )
    evidence_policy = AnacSirosRetrospectiveEvidencePolicy(
        policy_id=str(policy_raw.get("policy_id") or ""),
        scope=str(policy_raw.get("scope") or ""),  # type: ignore[arg-type]
        bound_rule=str(
            policy_raw.get("bound_rule") or ""
        ),  # type: ignore[arg-type]
        public_availability_proven=_boolean(
            policy_raw.get("public_availability_proven"),
            "annual_member_evidence_policy.public_availability_proven",
        ),
        point_in_time_eligible=_boolean(
            policy_raw.get("point_in_time_eligible"),
            "annual_member_evidence_policy.point_in_time_eligible",
        ),
    )

    reference = _mapping(
        document.get("airport_reference"), "airport_reference"
    )
    reference_pin = AnacAirportReferenceFilePin(
        path=_resolve_manifest_path(
            base, reference.get("path"), "airport_reference.path"
        ),
        expected_sha256=reference.get("expected_sha256"),
        expected_bytes=reference.get("expected_bytes"),
        expected_corpus_digest=reference.get("expected_corpus_digest"),
    )

    outcomes: list[AnacAnnualOutcomeInput] = []
    for index, raw_item in enumerate(
        _sequence(document.get("vra_months"), "vra_months")
    ):
        item = _mapping(raw_item, f"vra_months[{index}]")
        pin = AnacVraOutcomeFilePin(
            path=_resolve_manifest_path(
                base, item.get("path"), f"vra_months[{index}].path"
            ),
            source_url=str(item.get("source_url") or ""),
            retrieved_at_utc=_parse_datetime(
                item.get("retrieved_at_utc"),
                f"vra_months[{index}].retrieved_at_utc",
            ),
            expected_sha256=_digest(
                item.get("expected_sha256"),
                f"vra_months[{index}].expected_sha256",
            ),
            expected_raw_bytes=_positive_int(
                item.get("expected_raw_bytes"),
                f"vra_months[{index}].expected_raw_bytes",
            ),
        )
        evidence_raw = _mapping(
            item.get("observation_provenance"),
            f"vra_months[{index}].observation_provenance",
        )
        evidence = AnacVraOutcomeObservationProvenance(
            vra_source_url=str(evidence_raw.get("vra_source_url") or ""),
            raw_file_sha256=_digest(
                evidence_raw.get("raw_file_sha256"),
                f"vra_months[{index}].observation.raw_file_sha256",
            ),
            outcome_observed_at_utc=_parse_datetime(
                evidence_raw.get("outcome_observed_at_utc"),
                f"vra_months[{index}].observation.outcome_observed_at_utc",
            ),
            basis=str(evidence_raw.get("basis") or ""),  # type: ignore[arg-type]
            evidence_url=str(evidence_raw.get("evidence_url") or ""),
            evidence_timestamp_raw=str(
                evidence_raw.get("evidence_timestamp_raw") or ""
            ),
            evidence_retrieved_at_utc=_parse_datetime(
                evidence_raw.get("evidence_retrieved_at_utc"),
                f"vra_months[{index}].observation.evidence_retrieved_at_utc",
            ),
            evidence_sha256=_digest(
                evidence_raw.get("evidence_sha256"),
                f"vra_months[{index}].observation.evidence_sha256",
            ),
            use_scope=str(
                evidence_raw.get("use_scope") or ""
            ),  # type: ignore[arg-type]
        )
        outcomes.append(AnacAnnualOutcomeInput(pin, evidence))

    boundaries_raw = document.get("boundaries")
    if boundaries_raw is None:
        boundaries = default_2023_boundaries()
    else:
        values = _mapping(boundaries_raw, "boundaries")
        boundaries = ChronologicalBoundaries(
            train_end=_parse_datetime(values.get("train_end"), "train_end"),
            tune_end=_parse_datetime(values.get("tune_end"), "tune_end"),
            calibration_end=_parse_datetime(
                values.get("calibration_end"), "calibration_end"
            ),
            test_end=_parse_datetime(values.get("test_end"), "test_end"),
        )

    service_start = _parse_date(
        document.get("service_start", ANAC_ANNUAL_SERVICE_START.isoformat()),
        "service_start",
    )
    service_end = _parse_date(
        document.get("service_end", ANAC_ANNUAL_SERVICE_END.isoformat()),
        "service_end",
    )
    detail_limit = document.get("decision_detail_limit", 100)
    return AnacAnnualRetrospectiveConfig(
        year=year,
        annual_archive_path=archive_path,
        annual_archive_pin=archive_pin,
        evidence_policy=evidence_policy,
        airport_reference_pin=reference_pin,
        outcome_inputs=tuple(outcomes),
        boundaries=boundaries,
        training_config=_parse_training_config(document.get("training_config")),
        schedule_categorical_config=_parse_schedule_config(
            document.get("schedule_categorical_config")
        ),
        matrix_memory_limits=_parse_matrix_memory_limits(
            document.get("matrix_memory_limits")
        ),
        service_start=service_start,
        service_end=service_end,
        decision_detail_limit=detail_limit,  # type: ignore[arg-type]
    )


def _load_airport_reference(
    pin: AnacAirportReferenceFilePin,
) -> tuple[Mapping[str, AirportMetadata], dict[str, object]]:
    path = Path(str(pin.path))
    document, actual_sha256, actual_bytes = _strict_json_bytes(path)
    if actual_sha256 != pin.expected_sha256:
        raise AnacAnnualManifestError(
            "airport reference SHA-256 differs from its explicit pin"
        )
    if actual_bytes != pin.expected_bytes:
        raise AnacAnnualManifestError(
            "airport reference byte count differs from its explicit pin"
        )
    if document.get("schema_version") != ANAC_REFERENCE_SCHEMA_VERSION:
        raise AnacAnnualManifestError("unsupported airport reference schema")
    corpus_digest = _digest(
        document.get("corpus_digest"), "airport reference corpus_digest"
    )
    if corpus_digest != pin.expected_corpus_digest:
        raise AnacAnnualManifestError(
            "airport reference corpus digest differs from its explicit pin"
        )
    audit = _mapping(document.get("audit"), "airport reference audit")
    if audit.get("completed") is not True or audit.get("corpus_digest") != corpus_digest:
        raise AnacAnnualManifestError(
            "airport reference does not carry a completed matching audit"
        )
    index = _mapping(document.get("airport_index"), "airport_index")
    by_icao = _mapping(index.get("by_icao"), "airport_index.by_icao")
    airports: dict[str, AirportMetadata] = {}
    for raw_icao, raw_value in sorted(by_icao.items()):
        values = _mapping(raw_value, f"airport_index.by_icao.{raw_icao}")
        airport = AirportMetadata(
            icao=str(values.get("icao") or ""),
            iata=(str(values["iata"]) if values.get("iata") is not None else None),
            latitude=float(values.get("latitude")),
            longitude=float(values.get("longitude")),
            country_code=str(values.get("country_code") or ""),
            region_code=str(values.get("region_code") or ""),
            timezone_name=str(values.get("timezone_name") or ""),
        )
        if raw_icao != airport.icao:
            raise AnacAnnualManifestError(
                "airport reference index key does not match its ICAO identity"
            )
        airports[airport.icao] = airport
    if not airports:
        raise AnacAnnualManifestError("airport reference index is empty")
    index_audit = _mapping(index.get("audit"), "airport_index.audit")
    if index_audit.get("indexed_record_count") != len(airports):
        raise AnacAnnualManifestError(
            "airport reference indexed-record count does not reconcile"
        )
    return MappingProxyType(airports), {
        "schema_version": ANAC_REFERENCE_SCHEMA_VERSION,
        "filename": path.name,
        "file_sha256": actual_sha256,
        "file_bytes": actual_bytes,
        "corpus_digest": corpus_digest,
        "airport_count": len(airports),
        "completed": True,
    }


def _archive_summary(audit: AnacSirosAnnualArchiveAudit) -> dict[str, object]:
    return {
        "source_url": audit.archive.source_url,
        "filename": audit.archive.filename,
        "retrieved_at_utc": _iso_utc(audit.archive.retrieved_at_utc),
        "archive_last_modified_utc": _iso_utc(
            audit.archive.archive_last_modified_utc
        ),
        "archive_last_modified_raw": audit.archive.archive_last_modified_raw,
        "archive_sha256": audit.archive.archive_sha256,
        "archive_bytes": audit.archive.archive_bytes,
        "evidence_policy": audit.evidence_policy.to_dict(),
        "member_count": audit.actual_member_count,
        "calendar_complete": audit.calendar_complete,
        "total_raw_row_count": audit.total_raw_row_count,
        "total_accepted_row_count": audit.total_accepted_row_count,
        "total_rejected_row_count": audit.total_rejected_row_count,
        "archive_content_sha256": audit.archive_content_sha256,
        "archive_audit_sha256": audit.audit_sha256,
        "point_in_time_publication_evidence": False,
        "members": [
            {
                "snapshot_date": member.snapshot_date.isoformat(),
                "member_name": member.member_name,
                "member_sha256": member.member_sha256,
                "member_content_sha256": member.member_content_sha256,
                "raw_row_count": member.raw_row_count,
                "accepted_row_count": member.accepted_row_count,
                "rejected_row_count": member.rejected_row_count,
                "row_audit_sha256": member.row_audit_sha256,
                "retrospective_evidence_bound_utc": _iso_utc(
                    member.retrospective_evidence_bound_utc
                ),
                "public_availability_proven": False,
            }
            for member in audit.members
        ],
        "completed": audit.completed,
    }


def _outcome_load_summary(
    result: AnacVraOutcomeLoadResult,
    *,
    service_start: date,
    service_end: date,
) -> dict[str, object]:
    audit = result.audit
    scope_counts = Counter()
    for candidate in result.candidates:
        service_date = candidate.record.scheduled_departure_utc.date()
        if service_date < service_start:
            scope_counts["before_evaluation_service_window"] += 1
        elif service_date > service_end:
            scope_counts["after_evaluation_service_window"] += 1
        else:
            scope_counts["inside_evaluation_service_window"] += 1
    return {
        "source_url": audit.source_url,
        "filename": audit.filename,
        "retrieved_at_utc": _iso_utc(audit.retrieved_at_utc),
        "raw_file_sha256": audit.raw_file_sha256,
        "raw_bytes": audit.raw_bytes,
        "observation_provenance": audit.observation_provenance.to_dict(),
        "source_raw_row_count": audit.source_raw_row_count,
        "source_parser_accepted_row_count": audit.source_parser_accepted_row_count,
        "source_excluded_unplanned_row_count": (
            audit.source_excluded_unplanned_row_count
        ),
        "source_rejected_row_count": audit.source_rejected_row_count,
        "terminal_candidate_count": audit.terminal_candidate_count,
        "excluded_nonterminal_row_count": audit.excluded_nonterminal_row_count,
        "normalization_rejected_row_count": (
            audit.normalization_rejected_row_count
        ),
        "terminal_status_counts": dict(audit.terminal_status_counts),
        "nonterminal_status_counts": dict(audit.nonterminal_status_counts),
        "candidate_scope_counts": {
            key: scope_counts.get(key, 0)
            for key in (
                "before_evaluation_service_window",
                "inside_evaluation_service_window",
                "after_evaluation_service_window",
            )
        },
        "source_parser_audit_sha256": audit.source_parser_audit_sha256,
        "candidate_facts_sha256": audit.candidate_facts_sha256,
        "load_audit_sha256": audit.facts_sha256,
        "complete_row_accounting": True,
        "completed": audit.completed,
    }


def _join_summary(
    result: AnacSirosVraJoinResult,
    *,
    service_month: int,
    detail_limit: int,
) -> dict[str, object]:
    audit = result.audit
    reason_counts = Counter(
        (
            decision.side,
            decision.disposition,
            decision.reason_code or "matched",
        )
        for decision in audit.decisions
    )
    nonmatched_count = sum(
        decision.disposition != "matched" for decision in audit.decisions
    )
    detail_rows = heapq.nsmallest(
        detail_limit,
        (
            decision
            for decision in audit.decisions
            if decision.disposition != "matched"
        ),
        key=lambda item: (item.side, item.disposition, item.candidate_id),
    )
    details = [decision.to_dict() for decision in detail_rows]
    status_counts = Counter(match.outcome.record.status for match in result.matches)
    match_ids = sorted(match.match_id for match in result.matches)
    return {
        "service_month": f"2023-{service_month:02d}",
        "prediction_horizon_seconds": audit.prediction_horizon_seconds,
        "input_schedule_count": audit.input_schedule_count,
        "input_outcome_count": audit.input_outcome_count,
        "matched_pair_count": audit.matched_pair_count,
        "point_in_time_history_match_count": (
            audit.point_in_time_history_match_count
        ),
        "retrospective_holdout_only_match_count": (
            audit.retrospective_holdout_only_match_count
        ),
        "disposition_counts": {
            side: {
                disposition: audit.disposition_count(side, disposition)
                for disposition in (
                    "matched",
                    "unmatched",
                    "ambiguous",
                    "rejected",
                )
            }
            for side in ("schedule", "outcome")
        },
        "reason_counts": [
            {
                "side": side,
                "disposition": disposition,
                "reason_code": reason,
                "count": count,
            }
            for (side, disposition, reason), count in sorted(reason_counts.items())
        ],
        "ambiguities": [
            value.to_dict()
            for value in sorted(
                audit.ambiguities,
                key=lambda item: (item.scope, item.identity, item.reason_code),
            )
        ],
        "nonmatched_decision_count": nonmatched_count,
        "nonmatched_decision_examples": details,
        "nonmatched_decision_examples_limit": detail_limit,
        "nonmatched_decision_examples_truncated_count": max(
            0, nonmatched_count - len(details)
        ),
        "complete_decision_accounting": True,
        "join_audit_sha256": audit.facts_sha256,
        "matched_status_counts": dict(sorted(status_counts.items())),
        "matched_facts_sha256": hashlib.sha256(
            "\n".join(match_ids).encode("ascii")
        ).hexdigest(),
    }


def _service_dates(start: date, end: date) -> tuple[date, ...]:
    return tuple(
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
    )


def _selected_snapshot_date(service_date: date) -> date:
    return service_date - timedelta(days=ANAC_ANNUAL_SNAPSHOT_OFFSET_DAYS)


def _partition_season_coverage(records: tuple[GlobalFlightRecord, ...]) -> dict[str, object]:
    counts = Counter()
    months = Counter()
    for record in records:
        month = record.service_date.month
        months[f"{record.service_date.year:04d}-{month:02d}"] += 1
        if record.origin_latitude >= 0:
            season = (
                "winter" if month in {12, 1, 2}
                else "spring" if month in {3, 4, 5}
                else "summer" if month in {6, 7, 8}
                else "autumn"
            )
        else:
            season = (
                "summer" if month in {12, 1, 2}
                else "autumn" if month in {3, 4, 5}
                else "winter" if month in {6, 7, 8}
                else "spring"
            )
        counts[season] += 1
    return {
        "rows": len(records),
        "service_month_counts": dict(sorted(months.items())),
        "origin_local_season_counts": {
            season: counts.get(season, 0)
            for season in ("summer", "autumn", "winter", "spring")
        },
    }


def run_anac_annual_retrospective_evaluation(
    config: AnacAnnualRetrospectiveConfig,
) -> dict[str, object]:
    """Run the audited annual ingest/join/evaluation path without exporting."""

    if not isinstance(config, AnacAnnualRetrospectiveConfig):
        raise TypeError("config must be AnacAnnualRetrospectiveConfig")
    source_code_provenance = _source_code_provenance()
    airports, reference_summary = _load_airport_reference(
        config.airport_reference_pin
    )
    archive_audit = validate_siros_annual_archive(
        Path(str(config.annual_archive_path)),
        pin=config.annual_archive_pin,
        evidence_policy=config.evidence_policy,
    )

    service_dates = _service_dates(config.service_start, config.service_end)
    snapshot_dates = tuple(_selected_snapshot_date(value) for value in service_dates)
    outcome_inputs = config.outcome_by_month
    outcome_cache: dict[int, AnacVraOutcomeLoadResult] = {}
    outcome_summaries: dict[int, dict[str, object]] = {}
    joined_records: list[GlobalFlightRecord] = []
    monthly_join_summaries: list[dict[str, object]] = []
    join_population_totals: Counter[str] = Counter()
    selected_member_facts: list[dict[str, object]] = []
    current_month: int | None = None
    monthly_schedules: list[AnacSirosServiceObservation] = []

    def load_outcome_month(month: int) -> AnacVraOutcomeLoadResult:
        result = outcome_cache.get(month)
        if result is not None:
            return result
        source = outcome_inputs[month]
        result = load_anac_vra_outcome_file(
            source.pin,
            airports,
            observation_provenance=source.observation_provenance,
        )
        outcome_cache[month] = result
        outcome_summaries[month] = _outcome_load_summary(
            result,
            service_start=config.service_start,
            service_end=config.service_end,
        )
        return result

    def flush_month(month: int, schedules: list[AnacSirosServiceObservation]) -> None:
        # VRA source clocks are reported in Brasilia time.  A target UTC month
        # can therefore receive records from that source month or its immediate
        # predecessor.  The Jan-9 lower bound avoids needing an unpinned
        # Dec-2022 boundary file.  A 31 December UTC departure still belongs
        # to December in the source's Brasilia reporting timezone, so no
        # January 2024 VRA partition is required.
        source_months = tuple(
            candidate for candidate in (month - 1, month) if 1 <= candidate <= 12
        )
        outcomes = tuple(
            candidate
            for source_month in source_months
            for candidate in load_outcome_month(source_month).candidates
            if (
                candidate.record.scheduled_departure_utc.year == config.year
                and candidate.record.scheduled_departure_utc.month == month
                and config.service_start
                <= candidate.record.scheduled_departure_utc.date()
                <= config.service_end
            )
        )
        result = join_siros_schedules_to_vra_outcomes(schedules, outcomes)
        join_population_totals.update(
            {
                "input_schedule_count": result.audit.input_schedule_count,
                "input_outcome_count": result.audit.input_outcome_count,
                "matched_pair_count": result.audit.matched_pair_count,
                "schedule_unmatched_count": result.audit.disposition_count(
                    "schedule", "unmatched"
                ),
                "schedule_ambiguous_count": result.audit.disposition_count(
                    "schedule", "ambiguous"
                ),
                "schedule_rejected_count": result.audit.disposition_count(
                    "schedule", "rejected"
                ),
                "outcome_unmatched_count": result.audit.disposition_count(
                    "outcome", "unmatched"
                ),
                "outcome_ambiguous_count": result.audit.disposition_count(
                    "outcome", "ambiguous"
                ),
                "outcome_rejected_count": result.audit.disposition_count(
                    "outcome", "rejected"
                ),
            }
        )
        monthly_join_summaries.append(
            _join_summary(
                result,
                service_month=month,
                detail_limit=config.decision_detail_limit,
            )
        )
        joined_records.extend(result.retrospective_holdout_records)
        for source_month in tuple(outcome_cache):
            if source_month < month:
                del outcome_cache[source_month]

    snapshots_seen = 0
    for snapshot in iter_siros_annual_snapshots(
        Path(str(config.annual_archive_path)),
        audit=archive_audit,
        snapshot_dates=snapshot_dates,
    ):
        if snapshot.audit.file.snapshot_date is None:
            raise AnacAnnualReconciliationError(
                "selected annual member is missing its snapshot date"
            )
        service_date = snapshot.audit.file.snapshot_date + timedelta(
            days=ANAC_ANNUAL_SNAPSHOT_OFFSET_DAYS
        )
        if not config.service_start <= service_date <= config.service_end:
            raise AnacAnnualReconciliationError(
                "selected annual member mapped outside the evaluation service window"
            )
        month = service_date.month
        if current_month is not None and month != current_month:
            flush_month(current_month, monthly_schedules)
            monthly_schedules = []
        current_month = month
        target_floor = datetime.combine(service_date, time.min, tzinfo=timezone.utc)
        selected = select_retrospective_services_at_t_minus_7(
            snapshot.rows,
            service_date=service_date,
            target_departure_utc=target_floor,
        )
        if any(
            row.schedule_observed_at_utc
            > row.scheduled_departure_utc - timedelta(days=7)
            for row in selected
        ):
            raise AnacAnnualReconciliationError(
                "annual member admitted a schedule after its row-level T-7 instant"
            )
        monthly_schedules.extend(selected)
        selected_member_facts.append(
            {
                "service_date": service_date.isoformat(),
                "snapshot_date": snapshot.audit.file.snapshot_date.isoformat(),
                "retrospective_evidence_bound_utc": _iso_utc(
                    snapshot.audit.file.snapshot_observed_at_utc
                ),
                "member_sha256": snapshot.audit.file.raw_file_sha256,
                "accepted_series_row_count": snapshot.audit.accepted_row_count,
                "selected_service_count": len(selected),
                "public_availability_proven": False,
            }
        )
        snapshots_seen += 1
    if current_month is not None:
        flush_month(current_month, monthly_schedules)

    if snapshots_seen != len(snapshot_dates):
        raise AnacAnnualReconciliationError(
            "selected annual member count does not match the service calendar"
        )
    # December is first needed for the December UTC service partition and may
    # not have been loaded before the last flush if no schedules survived.
    for month in range(1, 13):
        if month not in outcome_summaries:
            load_outcome_month(month)

    records = tuple(
        sorted(
            joined_records,
            key=lambda row: (row.scheduled_departure_utc, row.canonical_key),
        )
    )
    if not records:
        raise AnacAnnualReconciliationError("annual exact join produced no records")
    if len({row.record_id for row in records}) != len(records):
        raise AnacAnnualReconciliationError(
            "annual month joins produced duplicate joined record identities"
        )
    matched_count = join_population_totals["matched_pair_count"]
    schedule_count = join_population_totals["input_schedule_count"]
    schedule_nonmatched_count = sum(
        join_population_totals[key]
        for key in (
            "schedule_unmatched_count",
            "schedule_ambiguous_count",
            "schedule_rejected_count",
        )
    )
    outcome_count = join_population_totals["input_outcome_count"]
    outcome_nonmatched_count = sum(
        join_population_totals[key]
        for key in (
            "outcome_unmatched_count",
            "outcome_ambiguous_count",
            "outcome_rejected_count",
        )
    )
    if (
        matched_count != len(records)
        or matched_count + schedule_nonmatched_count != schedule_count
        or matched_count + outcome_nonmatched_count != outcome_count
    ):
        raise AnacAnnualReconciliationError(
            "annual exact-join population accounting is inconsistent"
        )
    exact_join_cohort = {
        "join_conditioned_cohort": True,
        "conditioning_uses_post_t7_schedule_stability": True,
        "metric_population_rows": matched_count,
        "t7_schedule_rows": schedule_count,
        "final_vra_candidate_rows": outcome_count,
        "exact_match_rate_over_t7_schedules": matched_count / schedule_count,
        "schedule_dispositions": {
            "matched": matched_count,
            "unmatched": join_population_totals["schedule_unmatched_count"],
            "ambiguous": join_population_totals["schedule_ambiguous_count"],
            "rejected": join_population_totals["schedule_rejected_count"],
        },
        "outcome_dispositions": {
            "matched": matched_count,
            "unmatched": join_population_totals["outcome_unmatched_count"],
            "ambiguous": join_population_totals["outcome_ambiguous_count"],
            "rejected": join_population_totals["outcome_rejected_count"],
        },
        "required_exact_identity": (
            "carrier, flight number, ICAO route, scheduled departure UTC, "
            "and scheduled arrival UTC"
        ),
        "interpretation": (
            "Metrics describe only T-7 SIROS schedules whose final VRA "
            "scheduled departure and arrival remained exactly joinable. "
            "They are not annual-population performance estimates; excluded "
            "or schedule-changed services can differ systematically."
        ),
        "annual_population_performance_claim_allowed": False,
    }
    prepared = prepare_retrospective_global_data(
        records,
        config.boundaries,
        schedule_categorical_config=config.schedule_categorical_config,
        matrix_memory_limits=config.matrix_memory_limits,
    )
    if not prepared.schedule_categorical_snapshot.config.enabled:
        raise AnacAnnualReconciliationError(
            "annual model preparation disabled enhanced schedule categories"
        )
    evaluation = evaluate_retrospective_temporal_model(
        prepared,
        config=config.training_config,
    )
    if (
        evaluation.get("evaluation_kind") != "retrospective_temporal_evaluation"
        or evaluation.get("publishable") is not False
        or evaluation.get("point_in_time_backtest") is not False
        or evaluation.get("target_derived_history_features_used") is not False
    ):
        raise AnacAnnualReconciliationError(
            "annual evaluator violated the retrospective non-publication contract"
        )
    if evaluation.get("training_configuration") != asdict(
        config.training_config
    ):
        raise AnacAnnualReconciliationError(
            "annual evaluator training configuration is inconsistent"
        )
    if evaluation.get("temporal_audit") != prepared.retrospective_audit.to_dict():
        raise AnacAnnualReconciliationError(
            "annual evaluator temporal audit is inconsistent"
        )
    runtime_provenance = evaluation.get("runtime_provenance")
    if not isinstance(runtime_provenance, Mapping):
        raise AnacAnnualReconciliationError(
            "annual evaluator must disclose its runtime provenance"
        )
    deterministic_parameters = runtime_provenance.get(
        "deterministic_parameters"
    )
    if not isinstance(deterministic_parameters, Mapping):
        raise AnacAnnualReconciliationError(
            "annual evaluator must disclose its deterministic parameters"
        )
    expected_deterministic_parameters = {
        "random_state": config.training_config.seed,
        "bagging_seed": config.training_config.seed,
        "feature_fraction_seed": config.training_config.seed,
        "data_random_seed": config.training_config.seed,
        "deterministic": True,
        "force_col_wise": True,
        "device_type": "cpu",
        "n_jobs": config.training_config.num_threads,
    }
    if (
        runtime_provenance.get("deterministic") is not True
        or dict(deterministic_parameters) != expected_deterministic_parameters
    ):
        raise AnacAnnualReconciliationError(
            "annual evaluator must disclose the exact deterministic runtime contract"
        )
    feature_contract = evaluation.get("feature_contract")
    if not isinstance(feature_contract, Mapping):
        raise AnacAnnualReconciliationError(
            "annual evaluator must disclose its feature contract"
        )
    matrix_storage_audit = prepared.matrix_audit.to_dict()
    if (
        feature_contract.get("feature_count")
        != len(prepared.train.feature_names)
        or feature_contract.get("feature_names")
        != list(prepared.train.feature_names)
        or feature_contract.get("precomputed_matrices_only") is not True
        or feature_contract.get("target_derived_history_features") is not False
        or feature_contract.get("matrix_storage") != matrix_storage_audit
    ):
        raise AnacAnnualReconciliationError(
            "annual evaluator feature contract is inconsistent"
        )
    evaluation_memory_audit = evaluation.get("evaluation_memory_audit")
    if not isinstance(evaluation_memory_audit, Mapping):
        raise AnacAnnualReconciliationError(
            "annual evaluator must disclose its evaluation memory audit"
        )
    stage_estimates = evaluation_memory_audit.get(
        "stage_estimated_additional_bytes"
    )
    target_selections = evaluation_memory_audit.get("target_selections")
    if not isinstance(stage_estimates, Mapping) or set(stage_estimates) != {
        "model_fit",
        "calibration",
        "test_probability_generation",
        "test_metrics",
        "cold_start_diagnostics",
    }:
        raise AnacAnnualReconciliationError(
            "annual evaluator memory stages are inconsistent"
        )
    if not isinstance(target_selections, Mapping) or set(target_selections) != {
        "train",
        "tune",
        "calibration",
        "test",
    } or any(
        not isinstance(selection, Mapping)
        or set(selection) != set(MODEL_HEADS)
        for selection in target_selections.values()
    ):
        raise AnacAnnualReconciliationError(
            "annual evaluator target-selection memory audit is inconsistent"
        )
    estimated_peak = evaluation_memory_audit.get(
        "estimated_peak_additional_bytes"
    )
    memory_limit = config.matrix_memory_limits.max_evaluation_additional_bytes
    stage_values = tuple(stage_estimates.values())
    lightgbm_reserves = evaluation_memory_audit.get("lightgbm_reserves")
    if not isinstance(lightgbm_reserves, Mapping) or set(lightgbm_reserves) != {
        "dataset_bytes",
        "histogram_bytes",
        "tree_structure_bytes",
    } or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in lightgbm_reserves.values()
    ):
        raise AnacAnnualReconciliationError(
            "annual evaluator LightGBM memory reserves are inconsistent"
        )
    model_reserve = sum(lightgbm_reserves.values())
    raw_score_bytes = evaluation_memory_audit.get(
        "maximum_raw_score_vector_bytes"
    )
    raw_overlap_reserve = evaluation_memory_audit.get(
        "raw_score_overlap_reserve_bytes"
    )
    fit_subset_peak = evaluation_memory_audit.get(
        "maximum_fit_subset_peak_bytes"
    )
    calibration_overlap_reserve = evaluation_memory_audit.get(
        "cross_iteration_calibration_overlap_reserve_bytes"
    )
    projection_workspace = evaluation_memory_audit.get(
        "projection_workspace_bytes"
    )
    probability_bytes = evaluation_memory_audit.get("probability_matrix_bytes")
    if (
        evaluation_memory_audit.get("guard_applied_before_model_fit") is not True
        or evaluation_memory_audit.get("scope")
        != "additional_retrospective_evaluator_working_memory"
        or evaluation_memory_audit.get("estimate_kind")
        != "conservative_preflight_estimate_not_native_allocator_hard_cap"
        or evaluation_memory_audit.get("lightgbm_native_allocator_hard_cap")
        is not False
        or evaluation_memory_audit.get("head_order") != list(MODEL_HEADS)
        or evaluation_memory_audit.get("test_rows")
        != prepared.test.matrix.shape[0]
        or evaluation_memory_audit.get("head_count") != len(MODEL_HEADS)
        or evaluation_memory_audit.get("probability_storage")
        != "numpy_float64_matrix"
        or evaluation_memory_audit.get("probability_matrix_bytes")
        != prepared.test.matrix.shape[0] * len(MODEL_HEADS) * 8
        or isinstance(raw_score_bytes, bool)
        or not isinstance(raw_score_bytes, int)
        or raw_overlap_reserve != 2 * raw_score_bytes
        or isinstance(fit_subset_peak, bool)
        or not isinstance(fit_subset_peak, int)
        or isinstance(calibration_overlap_reserve, bool)
        or not isinstance(calibration_overlap_reserve, int)
        or stage_estimates["model_fit"]
        != model_reserve + fit_subset_peak + calibration_overlap_reserve
        or isinstance(projection_workspace, bool)
        or not isinstance(projection_workspace, int)
        or stage_estimates["test_probability_generation"]
        != (
            model_reserve
            + probability_bytes
            + raw_overlap_reserve
            + projection_workspace
        )
        or evaluation_memory_audit.get("limit_bytes") != memory_limit
        or isinstance(estimated_peak, bool)
        or not isinstance(estimated_peak, int)
        or not stage_values
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in stage_values
        )
        or estimated_peak != max(stage_values)
        or estimated_peak > memory_limit
    ):
        raise AnacAnnualReconciliationError(
            "annual evaluator memory contract is inconsistent"
        )
    for field_name in (
        "python",
        "platform",
        "machine",
        "numpy",
        "scipy",
        "scikit_learn",
        "lightgbm",
    ):
        value = runtime_provenance.get(field_name)
        if not isinstance(value, str) or not value.strip():
            raise AnacAnnualReconciliationError(
                f"annual evaluator runtime provenance lacks {field_name}"
            )
    test_metrics = evaluation.get("test_metrics")
    model_diagnostics = evaluation.get("model_diagnostics")
    if (
        not isinstance(test_metrics, Mapping)
        or set(test_metrics) != set(MODEL_HEADS)
        or not isinstance(model_diagnostics, Mapping)
        or set(model_diagnostics) != set(MODEL_HEADS)
    ):
        raise AnacAnnualReconciliationError(
            "annual evaluator must report every reviewed model head"
        )
    cold_start = evaluation.get("cold_start_diagnostics")
    cold_fields = cold_start.get("fields") if isinstance(cold_start, Mapping) else None
    if not isinstance(cold_fields, Mapping) or set(cold_fields) != {
        "operatingCarrier",
        "origin",
        "destination",
        "aircraftFamily",
        "route",
    }:
        raise AnacAnnualReconciliationError(
            "annual evaluator must report all required cold-start fields"
        )

    evaluation = dict(evaluation)
    evaluation["cohort_qualification"] = exact_join_cohort
    evaluation["source_contract_sha256"] = source_code_provenance[
        "aggregate_sha256"
    ]

    partition_coverage = {
        name: _partition_season_coverage(partition.records)
        for name, partition in (
            ("train", prepared.train),
            ("tune", prepared.tune),
            ("calibration", prepared.calibration),
            ("test", prepared.test),
        )
    }
    if any(not value["rows"] for value in partition_coverage.values()):
        raise AnacAnnualReconciliationError(
            "annual chronological evaluation contains an empty window"
        )

    joined_ids = sorted(row.record_id for row in records)
    input_facts = config.stable_input_facts()
    payload: dict[str, object] = {
        "schema_version": ANAC_ANNUAL_RETROSPECTIVE_OUTPUT_SCHEMA,
        "evaluation_kind": "retrospective_temporal_evaluation",
        "point_in_time_backtest": False,
        "publishable": False,
        "production_artifact_created": False,
        "deployment_performed": False,
        "network_io_performed_by_runner": False,
        "scope": {
            "region": "Brazil and ANAC-recorded Brazil-touching services",
            "year": config.year,
            "service_start": config.service_start.isoformat(),
            "service_end": config.service_end.isoformat(),
            "excluded_boundary_service_dates": [
                "2023-01-01/2023-01-08: no same-archive D-8 member",
            ],
            "prediction_horizon": "T-7 days",
            "schedule_member_rule": "service date D uses annual member D-8",
            "schedule_evidence_interpretation": (
                "retrospective filename-date next-day bound only; not historical "
                "public availability"
            ),
            "vra_source_month_alignment": (
                "target UTC month consumes Brasilia-time VRA source month and "
                "its immediate predecessor"
            ),
            "metric_cohort": "exactly joinable T-7 SIROS schedules only",
            "annual_population_performance_claim_allowed": False,
        },
        "input_facts": input_facts,
        "input_facts_sha256": _canonical_sha256(input_facts),
        "airport_reference": reference_summary,
        "siros_annual_archive": _archive_summary(archive_audit),
        "selected_t7_members": selected_member_facts,
        "selected_t7_members_sha256": _canonical_sha256(selected_member_facts),
        "vra_months": [outcome_summaries[month] for month in range(1, 13)],
        "monthly_exact_joins": monthly_join_summaries,
        "exact_join_cohort": exact_join_cohort,
        "joined_corpus": {
            "rows": len(records),
            "record_ids_sha256": hashlib.sha256(
                "\n".join(joined_ids).encode("ascii")
            ).hexdigest(),
            "dedupe_input_rows": prepared.dedupe.input_rows,
            "deduplicated_rows": len(prepared.dedupe.records),
            "duplicate_rows_removed": prepared.dedupe.duplicate_rows,
        },
        "chronological_season_coverage": partition_coverage,
        "schedule_categorical_snapshot": (
            prepared.schedule_categorical_snapshot.to_dict()
        ),
        "matrix_storage_audit": matrix_storage_audit,
        "model_evaluation": evaluation,
        "source_code_provenance": source_code_provenance,
    }
    if _source_code_provenance() != source_code_provenance:
        raise AnacAnnualReconciliationError(
            "reviewed source contract changed during the annual run"
        )
    payload["audit_sha256"] = _canonical_sha256(payload)
    return payload


def write_annual_retrospective_audit(
    result: Mapping[str, object],
    output_path: str | Path,
) -> Path:
    """Atomically write canonical, deterministic audit JSON."""

    if result.get("schema_version") != ANAC_ANNUAL_RETROSPECTIVE_OUTPUT_SCHEMA:
        raise AnacAnnualReconciliationError("result schema is not an annual audit")
    expected = result.get("audit_sha256")
    without_digest = dict(result)
    without_digest.pop("audit_sha256", None)
    if expected != _canonical_sha256(without_digest):
        raise AnacAnnualReconciliationError("annual audit digest is inconsistent")
    target = Path(output_path).expanduser().resolve()
    if target.exists() and target.is_dir():
        raise IsADirectoryError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json(dict(result), indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the offline, non-deployable SkyETA ANAC 2023 retrospective "
            "evaluation from a hash-pinned manifest."
        )
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    config = load_annual_retrospective_manifest(args.manifest)
    result = run_anac_annual_retrospective_evaluation(config)
    output = write_annual_retrospective_audit(result, args.output)
    print(
        _canonical_json(
            {
                "output": str(output),
                "audit_sha256": result["audit_sha256"],
                "publishable": False,
                "deployed": False,
            }
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())


__all__ = [
    "ANAC_ANNUAL_EVALUATION_YEAR",
    "ANAC_ANNUAL_RETROSPECTIVE_INPUT_SCHEMA",
    "ANAC_ANNUAL_RETROSPECTIVE_OUTPUT_SCHEMA",
    "ANAC_ANNUAL_SERVICE_END",
    "ANAC_ANNUAL_SERVICE_START",
    "AnacAirportReferenceFilePin",
    "AnacAnnualManifestError",
    "AnacAnnualOutcomeInput",
    "AnacAnnualReconciliationError",
    "AnacAnnualRetrospectiveConfig",
    "AnacAnnualRetrospectiveError",
    "default_2023_boundaries",
    "load_annual_retrospective_manifest",
    "main",
    "run_anac_annual_retrospective_evaluation",
    "write_annual_retrospective_audit",
]
