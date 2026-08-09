"""Leakage-safe, fail-closed joining of ANAC SIROS schedules to VRA outcomes.

The two ANAC products do not expose a shared row identifier.  In particular,
VRA does not publish the SIROS registration identifier or stage number.  This
module therefore never invents replacement lineage between distinct SIROS
registrations.  It uses the exact ``(SIROS ID, stage)`` identity only to select
the latest visible snapshot of that same schedule revision, then requires an
exact operating carrier, flight number, ICAO route, scheduled departure UTC,
and scheduled arrival UTC match to one VRA row.

Outcome availability is deliberately caller-supplied, byte-bound provenance.
Neither a VRA filename, its ``Referencia`` column, nor file retrieval time is
silently promoted to an historical observation timestamp.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Literal, Mapping
from urllib.parse import urlsplit

from .schema import GlobalFlightRecord, TERMINAL_STATUSES
from .sources.anac import (
    ANAC_DATASET_NAME,
    ANAC_DELIMITER,
    ANAC_ENCODING,
    ANAC_PUBLISHER,
    ANAC_REPORTING_TIMEZONE,
    ANAC_SOURCE_ID,
    AirportMetadata,
    AnacFileProvenance,
    build_vra_url,
)
from .sources.anac_siros import (
    ANAC_SIROS_SOURCE_ID,
    AnacSirosServiceObservation,
)


OutcomeEvidenceBasis = Literal[
    "official_publication_record",
    "web_archive_capture",
    "provider_manifest",
    "direct_retrieval_capture",
]
OutcomeUseScope = Literal[
    "point_in_time_target_history",
    "retrospective_holdout_only",
]
JoinSide = Literal["schedule", "outcome"]
JoinDisposition = Literal["matched", "unmatched", "ambiguous", "rejected"]
AmbiguityScope = Literal["composite_revision", "operational_match"]

_OUTCOME_EVIDENCE_BASES = frozenset(
    {
        "official_publication_record",
        "web_archive_capture",
        "provider_manifest",
        "direct_retrieval_capture",
    }
)
_OUTCOME_USE_SCOPES = frozenset(
    {"point_in_time_target_history", "retrospective_holdout_only"}
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ICAO = re.compile(r"^[A-Z0-9]{4}$")
_VRA_PATH = re.compile(
    r"^/siros/registros/diversos/vra/(\d{4})/VRA_\1_(0[1-9]|1[0-2])\.csv$"
)


class AnacSirosVraJoinError(ValueError):
    """The SIROS/VRA join contract or its provenance is invalid."""


def _utc(value: datetime, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise AnacSirosVraJoinError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return _utc(value, "datetime").isoformat().replace("+00:00", "Z")


def _required_text(value: object, name: str) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        raise AnacSirosVraJoinError(f"{name} is required")
    return text


def _digest(value: object, name: str) -> str:
    text = str(value or "").strip().lower()
    if not _DIGEST.fullmatch(text):
        raise AnacSirosVraJoinError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _https_url(value: object, name: str) -> str:
    text = _required_text(value, name)
    parsed = urlsplit(text)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise AnacSirosVraJoinError(f"{name} must be an HTTPS URL")
    return text


def _official_vra_url(value: object) -> tuple[str, int, int]:
    text = _https_url(value, "vra_source_url")
    parsed = urlsplit(text)
    match = _VRA_PATH.fullmatch(parsed.path)
    if (
        parsed.hostname != "siros.anac.gov.br"
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or match is None
    ):
        raise AnacSirosVraJoinError(
            "vra_source_url must be an official modern monthly ANAC VRA URL"
        )
    year, month = int(match.group(1)), int(match.group(2))
    try:
        expected = build_vra_url(year, month)
    except ValueError as error:
        raise AnacSirosVraJoinError(str(error)) from error
    if text != expected:
        raise AnacSirosVraJoinError("vra_source_url is not canonical")
    return text, year, month


def _canonical_json(value: object) -> str:
    def convert(item: object) -> object:
        if isinstance(item, datetime):
            return _iso_utc(item)
        if isinstance(item, date):
            return item.isoformat()
        if isinstance(item, Mapping):
            return {
                str(key): convert(child)
                for key, child in sorted(item.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(item, (tuple, list)):
            return [convert(child) for child in item]
        return item

    return json.dumps(
        convert(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AnacVraOutcomeObservationProvenance:
    """External proof of when one exact VRA file was observable.

    ``outcome_observed_at_utc`` is the earliest instant justified by the named
    evidence.  For a direct retrieval capture it must equal retrieval time;
    callers cannot backdate a freshly downloaded file using Last-Modified.
    """

    vra_source_url: str
    raw_file_sha256: str
    outcome_observed_at_utc: datetime
    basis: OutcomeEvidenceBasis
    evidence_url: str
    evidence_timestamp_raw: str
    evidence_retrieved_at_utc: datetime
    evidence_sha256: str
    use_scope: OutcomeUseScope

    def __post_init__(self) -> None:
        source, _, _ = _official_vra_url(self.vra_source_url)
        raw_digest = _digest(self.raw_file_sha256, "raw_file_sha256")
        observed = _utc(self.outcome_observed_at_utc, "outcome_observed_at_utc")
        retrieved = _utc(
            self.evidence_retrieved_at_utc, "evidence_retrieved_at_utc"
        )
        basis = str(self.basis)
        if basis not in _OUTCOME_EVIDENCE_BASES:
            raise AnacSirosVraJoinError("unsupported outcome observation basis")
        evidence_url = _https_url(self.evidence_url, "evidence_url")
        timestamp_raw = _required_text(
            self.evidence_timestamp_raw, "evidence_timestamp_raw"
        )
        evidence_digest = _digest(self.evidence_sha256, "evidence_sha256")
        use_scope = str(self.use_scope)
        if use_scope not in _OUTCOME_USE_SCOPES:
            raise AnacSirosVraJoinError("unsupported outcome evidence use scope")
        if retrieved < observed:
            raise AnacSirosVraJoinError(
                "evidence cannot be retrieved before the availability it proves"
            )
        if basis == "direct_retrieval_capture" and observed != retrieved:
            raise AnacSirosVraJoinError(
                "direct retrieval proves availability only at retrieval time"
            )
        if (
            basis == "direct_retrieval_capture"
            and use_scope != "retrospective_holdout_only"
        ):
            raise AnacSirosVraJoinError(
                "directly retrieved retrospective bytes cannot feed target-history features"
            )
        object.__setattr__(self, "vra_source_url", source)
        object.__setattr__(self, "raw_file_sha256", raw_digest)
        object.__setattr__(self, "outcome_observed_at_utc", observed)
        object.__setattr__(self, "basis", basis)
        object.__setattr__(self, "evidence_url", evidence_url)
        object.__setattr__(self, "evidence_timestamp_raw", timestamp_raw)
        object.__setattr__(self, "evidence_retrieved_at_utc", retrieved)
        object.__setattr__(self, "evidence_sha256", evidence_digest)
        object.__setattr__(self, "use_scope", use_scope)

    @property
    def facts_sha256(self) -> str:
        return _canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "vra_source_url": self.vra_source_url,
            "raw_file_sha256": self.raw_file_sha256,
            "outcome_observed_at_utc": _iso_utc(self.outcome_observed_at_utc),
            "basis": self.basis,
            "evidence_url": self.evidence_url,
            "evidence_timestamp_raw": self.evidence_timestamp_raw,
            "evidence_retrieved_at_utc": _iso_utc(
                self.evidence_retrieved_at_utc
            ),
            "evidence_sha256": self.evidence_sha256,
            "use_scope": self.use_scope,
        }


def _validate_file_provenance(value: AnacFileProvenance) -> AnacFileProvenance:
    if not isinstance(value, AnacFileProvenance):
        raise TypeError("file_provenance must be AnacFileProvenance")
    source, year, month = _official_vra_url(value.source_url)
    expected_filename = f"VRA_{year}_{month:02d}.csv"
    expected = {
        "source_id": ANAC_SOURCE_ID,
        "source_provider": ANAC_PUBLISHER,
        "product_name": ANAC_DATASET_NAME,
        "source_url": source,
        "year": year,
        "month": month,
        "filename": expected_filename,
        "reporting_timezone": ANAC_REPORTING_TIMEZONE,
        "delimiter": ANAC_DELIMITER,
        "encoding": ANAC_ENCODING,
    }
    for field, wanted in expected.items():
        if getattr(value, field) != wanted:
            raise AnacSirosVraJoinError(
                f"VRA file provenance {field} does not match official metadata"
            )
    _utc(value.retrieved_at_utc, "file_provenance.retrieved_at_utc")
    _digest(value.raw_file_sha256, "file_provenance.raw_file_sha256")
    if (
        isinstance(value.raw_bytes, bool)
        or not isinstance(value.raw_bytes, int)
        or value.raw_bytes <= 0
    ):
        raise AnacSirosVraJoinError(
            "file_provenance.raw_bytes must be a positive integer"
        )
    return value


@dataclass(frozen=True, slots=True)
class AnacVraOutcomeCandidate:
    """One validated VRA record with ICAO identity and observation evidence."""

    record: GlobalFlightRecord
    origin_airport: AirportMetadata
    destination_airport: AirportMetadata
    file_provenance: AnacFileProvenance
    observation_provenance: AnacVraOutcomeObservationProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.record, GlobalFlightRecord):
            raise TypeError("record must be GlobalFlightRecord")
        if not isinstance(self.origin_airport, AirportMetadata) or not isinstance(
            self.destination_airport, AirportMetadata
        ):
            raise TypeError("origin_airport and destination_airport must be AirportMetadata")
        file = _validate_file_provenance(self.file_provenance)
        if not isinstance(
            self.observation_provenance, AnacVraOutcomeObservationProvenance
        ):
            raise TypeError(
                "observation_provenance must be AnacVraOutcomeObservationProvenance"
            )
        evidence = self.observation_provenance
        if self.record.source != file.source_url:
            raise AnacSirosVraJoinError(
                "VRA record source does not match its file provenance"
            )
        if evidence.vra_source_url != file.source_url:
            raise AnacSirosVraJoinError(
                "outcome evidence source does not match VRA file provenance"
            )
        if evidence.raw_file_sha256 != file.raw_file_sha256:
            raise AnacSirosVraJoinError(
                "outcome evidence hash does not match VRA file provenance"
            )
        if self.origin_airport.training_code != self.record.origin:
            raise AnacSirosVraJoinError(
                "origin airport identity does not match the normalized VRA record"
            )
        if self.destination_airport.training_code != self.record.destination:
            raise AnacSirosVraJoinError(
                "destination airport identity does not match the normalized VRA record"
            )
        if self.origin_airport.icao == self.destination_airport.icao:
            raise AnacSirosVraJoinError("VRA ICAO origin and destination must differ")
        if self.record.schedule_observed_at is not None:
            raise AnacSirosVraJoinError(
                "raw VRA candidates must not claim schedule observation evidence"
            )
        if self.record.schedule_revision is not None:
            raise AnacSirosVraJoinError(
                "raw VRA candidates must not claim a schedule revision"
            )
        if (
            self.record.outcome_observed_at is not None
            and self.record.outcome_observed_at
            != evidence.outcome_observed_at_utc
        ):
            raise AnacSirosVraJoinError(
                "record outcome_observed_at contradicts supplied provenance"
            )

    @property
    def candidate_facts_sha256(self) -> str:
        return _canonical_hash(
            {
                "record": self.record.as_dict(),
                "originIcao": self.origin_airport.icao,
                "destinationIcao": self.destination_airport.icao,
                "fileSha256": self.file_provenance.raw_file_sha256,
                "observationEvidence": self.observation_provenance.to_dict(),
            }
        )


@dataclass(frozen=True, slots=True, order=True)
class AnacSirosVraMatchKey:
    """The only cross-product match key admitted by this implementation."""

    operating_carrier: str
    operating_flight_number: str
    origin_icao: str
    destination_icao: str
    scheduled_departure_utc: datetime
    scheduled_arrival_utc: datetime

    def __post_init__(self) -> None:
        carrier = _required_text(self.operating_carrier, "operating_carrier").upper()
        flight = _required_text(
            self.operating_flight_number, "operating_flight_number"
        ).upper()
        origin = _required_text(self.origin_icao, "origin_icao").upper()
        destination = _required_text(self.destination_icao, "destination_icao").upper()
        departure = _utc(self.scheduled_departure_utc, "scheduled_departure_utc")
        arrival = _utc(self.scheduled_arrival_utc, "scheduled_arrival_utc")
        if not re.fullmatch(r"[A-Z0-9]{3}", carrier):
            raise AnacSirosVraJoinError(
                "ANAC operating_carrier must be a three-character ICAO designator"
            )
        if not re.fullmatch(r"[A-Z0-9]{1,6}", flight):
            raise AnacSirosVraJoinError("invalid ANAC operating flight number")
        if not _ICAO.fullmatch(origin) or not _ICAO.fullmatch(destination):
            raise AnacSirosVraJoinError("ANAC route keys require exact ICAO codes")
        if origin == destination:
            raise AnacSirosVraJoinError("origin and destination must differ")
        if arrival <= departure:
            raise AnacSirosVraJoinError("scheduled arrival must follow departure")
        object.__setattr__(self, "operating_carrier", carrier)
        object.__setattr__(self, "operating_flight_number", flight)
        object.__setattr__(self, "origin_icao", origin)
        object.__setattr__(self, "destination_icao", destination)
        object.__setattr__(self, "scheduled_departure_utc", departure)
        object.__setattr__(self, "scheduled_arrival_utc", arrival)

    @classmethod
    def from_schedule(
        cls, schedule: AnacSirosServiceObservation
    ) -> "AnacSirosVraMatchKey":
        return cls(
            schedule.operating_carrier,
            schedule.operating_flight_number,
            schedule.origin_icao,
            schedule.destination_icao,
            schedule.scheduled_departure_utc,
            schedule.scheduled_arrival_utc,
        )

    @classmethod
    def from_outcome(
        cls, outcome: AnacVraOutcomeCandidate
    ) -> "AnacSirosVraMatchKey":
        return cls(
            outcome.record.operating_carrier,
            outcome.record.operating_flight_number,
            outcome.origin_airport.icao,
            outcome.destination_airport.icao,
            outcome.record.scheduled_departure_utc,
            outcome.record.scheduled_arrival_utc,
        )

    @property
    def operational_identity(self) -> tuple[str, str, str, str]:
        return (
            self.operating_carrier,
            self.operating_flight_number,
            self.origin_icao,
            self.destination_icao,
        )

    @property
    def canonical(self) -> str:
        return "|".join(
            (
                self.operating_carrier,
                self.operating_flight_number,
                f"{self.origin_icao}>{self.destination_icao}",
                _iso_utc(self.scheduled_departure_utc),
                _iso_utc(self.scheduled_arrival_utc),
            )
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "operating_carrier": self.operating_carrier,
            "operating_flight_number": self.operating_flight_number,
            "origin_icao": self.origin_icao,
            "destination_icao": self.destination_icao,
            "scheduled_departure_utc": _iso_utc(self.scheduled_departure_utc),
            "scheduled_arrival_utc": _iso_utc(self.scheduled_arrival_utc),
        }


def _validate_schedule(
    schedule: AnacSirosServiceObservation,
) -> AnacSirosServiceObservation:
    if not isinstance(schedule, AnacSirosServiceObservation):
        raise TypeError("schedules must contain AnacSirosServiceObservation values")
    expected_stage_key = (
        f"{ANAC_SIROS_SOURCE_ID}:{schedule.siros_id}:stage:{schedule.stage_number}"
    )
    if schedule.stage_revision_key != expected_stage_key:
        raise AnacSirosVraJoinError(
            "SIROS stage_revision_key does not match its exact ID/stage composite"
        )
    _digest(schedule.series_facts_sha256, "schedule.series_facts_sha256")
    _digest(schedule.raw_file_sha256, "schedule.raw_file_sha256")
    AnacSirosVraMatchKey.from_schedule(schedule)
    return schedule


@dataclass(frozen=True, slots=True)
class AnacSirosVraMatch:
    schedule: AnacSirosServiceObservation
    outcome: AnacVraOutcomeCandidate
    key: AnacSirosVraMatchKey

    def __post_init__(self) -> None:
        if self.key != AnacSirosVraMatchKey.from_schedule(self.schedule):
            raise AnacSirosVraJoinError("match key does not describe the SIROS row")
        if self.key != AnacSirosVraMatchKey.from_outcome(self.outcome):
            raise AnacSirosVraJoinError("match key does not describe the VRA row")

    @property
    def match_id(self) -> str:
        digest = _canonical_hash(
            {
                "scheduleObservationKey": self.schedule.schedule_observation_key,
                "vraRecordId": self.outcome.record.record_id,
                "outcomeEvidence": self.outcome.observation_provenance.facts_sha256,
                "matchKey": self.key.to_dict(),
            }
        )
        return f"anac-siros-vra-{digest[:24]}"

    def to_global_record(
        self, *, allow_retrospective_holdout: bool = False
    ) -> GlobalFlightRecord:
        """Return a schema-valid evidence row.

        Directly retrieved retrospective bytes are blocked by default so they
        cannot accidentally enter target-history encoders.  Holdout code must
        opt in explicitly and keep those records out of historical aggregates.
        """

        if (
            self.outcome.observation_provenance.use_scope
            == "retrospective_holdout_only"
            and not allow_retrospective_holdout
        ):
            raise AnacSirosVraJoinError(
                "retrospective-holdout outcome cannot enter point-in-time target history"
            )

        values = self.outcome.record.as_dict()
        values.update(
            {
                "record_id": self.match_id,
                "scheduled_departure_utc": self.schedule.scheduled_departure_utc,
                "scheduled_arrival_utc": self.schedule.scheduled_arrival_utc,
                "schedule_observed_at": self.schedule.schedule_observed_at_utc,
                "schedule_revision": self.schedule.stage_revision_key,
                "outcome_observed_at": (
                    self.outcome.observation_provenance.outcome_observed_at_utc
                ),
            }
        )
        return GlobalFlightRecord.from_mapping(values)

    def to_retrospective_holdout_record(self) -> GlobalFlightRecord:
        return self.to_global_record(allow_retrospective_holdout=True)

    def to_dict(self) -> dict[str, object]:
        return {
            "match_id": self.match_id,
            "match_method": "exact_carrier_flight_icao_route_departure_arrival_utc",
            "match_key": self.key.to_dict(),
            "siros_id": self.schedule.siros_id,
            "siros_stage_number": self.schedule.stage_number,
            "siros_stage_revision_key": self.schedule.stage_revision_key,
            "siros_schedule_observation_key": (
                self.schedule.schedule_observation_key
            ),
            "vra_record_id": self.outcome.record.record_id,
            "vra_file_sha256": self.outcome.file_provenance.raw_file_sha256,
            "outcome_observation": (
                self.outcome.observation_provenance.to_dict()
            ),
        }


@dataclass(frozen=True, slots=True)
class AnacSirosVraJoinDecision:
    candidate_id: str
    side: JoinSide
    source_identity: str
    disposition: JoinDisposition
    match_key: str | None
    counterpart_candidate_ids: tuple[str, ...]
    reason_code: str | None
    detail: str | None

    def __post_init__(self) -> None:
        _required_text(self.candidate_id, "candidate_id")
        _required_text(self.source_identity, "source_identity")
        if self.side not in {"schedule", "outcome"}:
            raise AnacSirosVraJoinError("invalid join-decision side")
        if self.disposition not in {"matched", "unmatched", "ambiguous", "rejected"}:
            raise AnacSirosVraJoinError("invalid join-decision disposition")
        counterparts = tuple(self.counterpart_candidate_ids)
        if self.disposition == "matched":
            if len(counterparts) != 1 or self.reason_code is not None:
                raise AnacSirosVraJoinError(
                    "matched decisions require one counterpart and no reason"
                )
        elif self.disposition == "ambiguous":
            if not counterparts or not self.reason_code:
                raise AnacSirosVraJoinError(
                    "ambiguous decisions require candidates and a reason"
                )
        elif counterparts or not self.reason_code:
            raise AnacSirosVraJoinError(
                "unmatched/rejected decisions require a reason and no counterpart"
            )
        object.__setattr__(self, "counterpart_candidate_ids", counterparts)

    def to_dict(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "side": self.side,
            "source_identity": self.source_identity,
            "disposition": self.disposition,
            "match_key": self.match_key,
            "counterpart_candidate_ids": list(self.counterpart_candidate_ids),
            "reason_code": self.reason_code,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class AnacSirosVraJoinAmbiguity:
    scope: AmbiguityScope
    identity: str
    schedule_candidate_ids: tuple[str, ...]
    outcome_candidate_ids: tuple[str, ...]
    reason_code: str

    def __post_init__(self) -> None:
        if self.scope not in {"composite_revision", "operational_match"}:
            raise AnacSirosVraJoinError("invalid ambiguity scope")
        _required_text(self.identity, "ambiguity.identity")
        _required_text(self.reason_code, "ambiguity.reason_code")
        schedules = tuple(self.schedule_candidate_ids)
        outcomes = tuple(self.outcome_candidate_ids)
        if len(schedules) + len(outcomes) < 2:
            raise AnacSirosVraJoinError(
                "an ambiguity must identify at least two candidates"
            )
        object.__setattr__(self, "schedule_candidate_ids", schedules)
        object.__setattr__(self, "outcome_candidate_ids", outcomes)

    def to_dict(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "identity": self.identity,
            "schedule_candidate_ids": list(self.schedule_candidate_ids),
            "outcome_candidate_ids": list(self.outcome_candidate_ids),
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True, slots=True)
class AnacSirosVraJoinAudit:
    prediction_horizon_seconds: int
    input_schedule_count: int
    input_outcome_count: int
    matched_pair_count: int
    point_in_time_history_match_count: int
    retrospective_holdout_only_match_count: int
    decisions: tuple[AnacSirosVraJoinDecision, ...]
    ambiguities: tuple[AnacSirosVraJoinAmbiguity, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.prediction_horizon_seconds, bool)
            or not isinstance(self.prediction_horizon_seconds, int)
            or self.prediction_horizon_seconds <= 0
        ):
            raise AnacSirosVraJoinError(
                "prediction_horizon_seconds must be a positive integer"
            )
        decisions = tuple(self.decisions)
        ambiguities = tuple(self.ambiguities)
        ids = [decision.candidate_id for decision in decisions]
        if len(ids) != len(set(ids)):
            raise AnacSirosVraJoinError("join audit candidate IDs must be unique")
        schedule_count = sum(decision.side == "schedule" for decision in decisions)
        outcome_count = sum(decision.side == "outcome" for decision in decisions)
        if schedule_count != self.input_schedule_count:
            raise AnacSirosVraJoinError("schedule decisions do not reconcile")
        if outcome_count != self.input_outcome_count:
            raise AnacSirosVraJoinError("outcome decisions do not reconcile")
        matched_schedules = sum(
            decision.side == "schedule" and decision.disposition == "matched"
            for decision in decisions
        )
        matched_outcomes = sum(
            decision.side == "outcome" and decision.disposition == "matched"
            for decision in decisions
        )
        if not matched_schedules == matched_outcomes == self.matched_pair_count:
            raise AnacSirosVraJoinError("matched decision counts do not reconcile")
        if (
            self.point_in_time_history_match_count
            + self.retrospective_holdout_only_match_count
            != self.matched_pair_count
        ):
            raise AnacSirosVraJoinError("matched outcome use scopes do not reconcile")
        object.__setattr__(self, "decisions", decisions)
        object.__setattr__(self, "ambiguities", ambiguities)

    def disposition_count(self, side: JoinSide, disposition: JoinDisposition) -> int:
        return sum(
            decision.side == side and decision.disposition == disposition
            for decision in self.decisions
        )

    @property
    def facts_sha256(self) -> str:
        return _canonical_hash(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, object]:
        counts = {
            side: {
                disposition: self.disposition_count(side, disposition)
                for disposition in ("matched", "unmatched", "ambiguous", "rejected")
            }
            for side in ("schedule", "outcome")
        }
        result: dict[str, object] = {
            "prediction_horizon_seconds": self.prediction_horizon_seconds,
            "input_schedule_count": self.input_schedule_count,
            "input_outcome_count": self.input_outcome_count,
            "matched_pair_count": self.matched_pair_count,
            "point_in_time_history_match_count": (
                self.point_in_time_history_match_count
            ),
            "retrospective_holdout_only_match_count": (
                self.retrospective_holdout_only_match_count
            ),
            "counts": counts,
            "decisions": [decision.to_dict() for decision in self.decisions],
            "ambiguities": [ambiguity.to_dict() for ambiguity in self.ambiguities],
        }
        if include_digest:
            result["facts_sha256"] = self.facts_sha256
        return result


@dataclass(frozen=True, slots=True)
class AnacSirosVraJoinResult:
    matches: tuple[AnacSirosVraMatch, ...]
    audit: AnacSirosVraJoinAudit

    def __post_init__(self) -> None:
        matches = tuple(self.matches)
        if len(matches) != self.audit.matched_pair_count:
            raise AnacSirosVraJoinError("matches do not reconcile with the join audit")
        ids = [match.match_id for match in matches]
        if len(ids) != len(set(ids)):
            raise AnacSirosVraJoinError("joined match IDs must be unique")
        object.__setattr__(self, "matches", matches)

    @property
    def records(self) -> tuple[GlobalFlightRecord, ...]:
        return tuple(match.to_global_record() for match in self.matches)

    @property
    def retrospective_holdout_records(self) -> tuple[GlobalFlightRecord, ...]:
        """Materialize labels for evaluation without admitting target history."""

        return tuple(match.to_retrospective_holdout_record() for match in self.matches)

    def to_dict(self) -> dict[str, object]:
        return {
            "matches": [match.to_dict() for match in self.matches],
            "audit": self.audit.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class _ScheduleRef:
    candidate_id: str
    schedule: AnacSirosServiceObservation
    key: AnacSirosVraMatchKey


@dataclass(frozen=True, slots=True)
class _OutcomeRef:
    candidate_id: str
    outcome: AnacVraOutcomeCandidate
    key: AnacSirosVraMatchKey


def _indexed_schedules(
    values: Iterable[AnacSirosServiceObservation],
) -> tuple[_ScheduleRef, ...]:
    schedules = [_validate_schedule(value) for value in values]
    schedules.sort(
        key=lambda row: (
            row.schedule_observation_key,
            row.stage_revision_key,
            row.scheduled_departure_utc,
            row.scheduled_arrival_utc,
        )
    )
    occurrences: dict[str, int] = {}
    result: list[_ScheduleRef] = []
    for row in schedules:
        identity = row.schedule_observation_key
        occurrences[identity] = occurrences.get(identity, 0) + 1
        candidate_id = f"schedule:{identity}:{occurrences[identity]}"
        result.append(
            _ScheduleRef(candidate_id, row, AnacSirosVraMatchKey.from_schedule(row))
        )
    return tuple(result)


def _indexed_outcomes(
    values: Iterable[AnacVraOutcomeCandidate],
) -> tuple[_OutcomeRef, ...]:
    outcomes = list(values)
    for value in outcomes:
        if not isinstance(value, AnacVraOutcomeCandidate):
            raise TypeError("outcomes must contain AnacVraOutcomeCandidate values")
    outcomes.sort(key=lambda row: (row.record.record_id, row.candidate_facts_sha256))
    occurrences: dict[str, int] = {}
    result: list[_OutcomeRef] = []
    for row in outcomes:
        identity = row.record.record_id
        occurrences[identity] = occurrences.get(identity, 0) + 1
        candidate_id = f"outcome:{identity}:{occurrences[identity]}"
        result.append(
            _OutcomeRef(candidate_id, row, AnacSirosVraMatchKey.from_outcome(row))
        )
    return tuple(result)


def _decision(
    ref: _ScheduleRef | _OutcomeRef,
    *,
    disposition: JoinDisposition,
    counterparts: Iterable[str] = (),
    reason_code: str | None = None,
    detail: str | None = None,
) -> AnacSirosVraJoinDecision:
    if isinstance(ref, _ScheduleRef):
        side: JoinSide = "schedule"
        identity = ref.schedule.schedule_observation_key
    else:
        side = "outcome"
        identity = ref.outcome.record.record_id
    return AnacSirosVraJoinDecision(
        candidate_id=ref.candidate_id,
        side=side,
        source_identity=identity,
        disposition=disposition,
        match_key=ref.key.canonical,
        counterpart_candidate_ids=tuple(sorted(counterparts)),
        reason_code=reason_code,
        detail=detail,
    )


def _unmatched_reason(
    key: AnacSirosVraMatchKey,
    counterpart_keys: Iterable[AnacSirosVraMatchKey],
) -> tuple[str, str]:
    same_identity = [
        candidate
        for candidate in counterpart_keys
        if candidate.operational_identity == key.operational_identity
    ]
    if not same_identity:
        return (
            "no_exact_operational_identity",
            "No eligible row has the same carrier, flight number, and ICAO route.",
        )
    same_departure = [
        candidate
        for candidate in same_identity
        if candidate.scheduled_departure_utc == key.scheduled_departure_utc
    ]
    if same_departure:
        return (
            "scheduled_arrival_utc_mismatch",
            "Carrier, flight, route, and departure match, but arrival UTC differs.",
        )
    return (
        "scheduled_departure_utc_mismatch",
        "Carrier, flight, and route match, but exact departure UTC differs.",
    )


def join_siros_schedules_to_vra_outcomes(
    schedules: Iterable[AnacSirosServiceObservation],
    outcomes: Iterable[AnacVraOutcomeCandidate],
    *,
    prediction_horizon: timedelta = timedelta(days=7),
) -> AnacSirosVraJoinResult:
    """Join point-in-time SIROS schedules to VRA outcomes without fuzzy fallback.

    Repeated observations of the same exact SIROS ID/stage/service-date identity
    are ordered by their independently pinned snapshot timestamp.  Distinct
    SIROS IDs are never treated as revisions of one another.  All inputs receive
    one terminal audit decision.
    """

    if not isinstance(prediction_horizon, timedelta):
        raise TypeError("prediction_horizon must be a timedelta")
    seconds = prediction_horizon.total_seconds()
    if not math.isfinite(seconds) or seconds <= 0 or not seconds.is_integer():
        raise AnacSirosVraJoinError(
            "prediction_horizon must be a finite positive whole number of seconds"
        )
    schedule_refs = _indexed_schedules(schedules)
    outcome_refs = _indexed_outcomes(outcomes)
    decisions: dict[str, AnacSirosVraJoinDecision] = {}
    ambiguities: list[AnacSirosVraJoinAmbiguity] = []

    visible: list[_ScheduleRef] = []
    for ref in schedule_refs:
        cutoff = ref.schedule.scheduled_departure_utc - prediction_horizon
        if ref.schedule.schedule_observed_at_utc > cutoff:
            decisions[ref.candidate_id] = _decision(
                ref,
                disposition="rejected",
                reason_code="schedule_not_observed_by_prediction_horizon",
                detail=(
                    f"Observed {_iso_utc(ref.schedule.schedule_observed_at_utc)}; "
                    f"required by {_iso_utc(cutoff)}."
                ),
            )
        else:
            visible.append(ref)

    # Exact SIROS ID/stage/service-date is a genuine revision identity.  Only
    # within that identity may a newer visible snapshot supersede an older one.
    by_composite: dict[str, list[_ScheduleRef]] = {}
    for ref in visible:
        by_composite.setdefault(ref.schedule.service_identity_key, []).append(ref)
    selected_schedules: list[_ScheduleRef] = []
    for identity in sorted(by_composite):
        group = by_composite[identity]
        latest_at = max(row.schedule.schedule_observed_at_utc for row in group)
        latest = [
            row for row in group if row.schedule.schedule_observed_at_utc == latest_at
        ]
        older = [row for row in group if row not in latest]
        for ref in older:
            decisions[ref.candidate_id] = _decision(
                ref,
                disposition="rejected",
                reason_code="superseded_same_composite_identity",
                detail=(
                    "A later T-7-visible snapshot exists for this exact SIROS "
                    "ID, stage, and service date."
                ),
            )
        if len(latest) > 1:
            candidate_ids = tuple(sorted(row.candidate_id for row in latest))
            ambiguities.append(
                AnacSirosVraJoinAmbiguity(
                    scope="composite_revision",
                    identity=identity,
                    schedule_candidate_ids=candidate_ids,
                    outcome_candidate_ids=(),
                    reason_code="simultaneous_latest_composite_observations",
                )
            )
            for ref in latest:
                decisions[ref.candidate_id] = _decision(
                    ref,
                    disposition="ambiguous",
                    counterparts=(
                        candidate
                        for candidate in candidate_ids
                        if candidate != ref.candidate_id
                    ),
                    reason_code="simultaneous_latest_composite_observations",
                    detail=(
                        "More than one latest observation claims the same exact "
                        "SIROS ID/stage/service-date identity."
                    ),
                )
        else:
            selected_schedules.append(latest[0])

    eligible_outcomes: list[_OutcomeRef] = []
    for ref in outcome_refs:
        record = ref.outcome.record
        observed = ref.outcome.observation_provenance.outcome_observed_at_utc
        prediction_at = record.scheduled_departure_utc - prediction_horizon
        if record.status not in TERMINAL_STATUSES:
            decisions[ref.candidate_id] = _decision(
                ref,
                disposition="rejected",
                reason_code="non_terminal_vra_status",
                detail="A training outcome must be landed, cancelled, or diverted.",
            )
        elif observed <= prediction_at:
            decisions[ref.candidate_id] = _decision(
                ref,
                disposition="rejected",
                reason_code="outcome_observed_by_prediction_time",
                detail=(
                    f"Outcome was observable {_iso_utc(observed)}, at or before "
                    f"the prediction time {_iso_utc(prediction_at)}."
                ),
            )
        else:
            eligible_outcomes.append(ref)

    schedule_by_key: dict[AnacSirosVraMatchKey, list[_ScheduleRef]] = {}
    outcome_by_key: dict[AnacSirosVraMatchKey, list[_OutcomeRef]] = {}
    for ref in selected_schedules:
        schedule_by_key.setdefault(ref.key, []).append(ref)
    for ref in eligible_outcomes:
        outcome_by_key.setdefault(ref.key, []).append(ref)

    matches: list[AnacSirosVraMatch] = []
    all_keys = sorted(set(schedule_by_key) | set(outcome_by_key))
    for key in all_keys:
        schedule_group = schedule_by_key.get(key, [])
        outcome_group = outcome_by_key.get(key, [])
        if len(schedule_group) > 1 or len(outcome_group) > 1:
            schedule_ids = tuple(sorted(row.candidate_id for row in schedule_group))
            outcome_ids = tuple(sorted(row.candidate_id for row in outcome_group))
            if len(schedule_group) > 1 and len(outcome_group) > 1:
                reason = "multiple_schedules_and_outcomes_for_exact_key"
            elif len(schedule_group) > 1:
                reason = "multiple_distinct_siros_ids_for_exact_key"
            else:
                reason = "multiple_vra_rows_for_exact_key"
            ambiguities.append(
                AnacSirosVraJoinAmbiguity(
                    scope="operational_match",
                    identity=key.canonical,
                    schedule_candidate_ids=schedule_ids,
                    outcome_candidate_ids=outcome_ids,
                    reason_code=reason,
                )
            )
            all_candidates = schedule_ids + outcome_ids
            for ref in (*schedule_group, *outcome_group):
                decisions[ref.candidate_id] = _decision(
                    ref,
                    disposition="ambiguous",
                    counterparts=(
                        candidate
                        for candidate in all_candidates
                        if candidate != ref.candidate_id
                    ),
                    reason_code=reason,
                    detail="The exact operational key is not one-to-one.",
                )
        elif len(schedule_group) == 1 and len(outcome_group) == 1:
            schedule_ref = schedule_group[0]
            outcome_ref = outcome_group[0]
            match = AnacSirosVraMatch(
                schedule_ref.schedule,
                outcome_ref.outcome,
                key,
            )
            matches.append(match)
            decisions[schedule_ref.candidate_id] = _decision(
                schedule_ref,
                disposition="matched",
                counterparts=(outcome_ref.candidate_id,),
            )
            decisions[outcome_ref.candidate_id] = _decision(
                outcome_ref,
                disposition="matched",
                counterparts=(schedule_ref.candidate_id,),
            )
        elif schedule_group:
            ref = schedule_group[0]
            reason, detail = _unmatched_reason(
                ref.key, (candidate.key for candidate in eligible_outcomes)
            )
            decisions[ref.candidate_id] = _decision(
                ref,
                disposition="unmatched",
                reason_code=reason,
                detail=detail,
            )
        elif outcome_group:
            ref = outcome_group[0]
            reason, detail = _unmatched_reason(
                ref.key, (candidate.key for candidate in selected_schedules)
            )
            decisions[ref.candidate_id] = _decision(
                ref,
                disposition="unmatched",
                reason_code=reason,
                detail=detail,
            )

    if len(decisions) != len(schedule_refs) + len(outcome_refs):
        missing = sorted(
            {ref.candidate_id for ref in (*schedule_refs, *outcome_refs)}
            - set(decisions)
        )
        raise RuntimeError("join failed to audit candidates: " + ", ".join(missing))

    ordered_matches = tuple(
        sorted(matches, key=lambda match: (match.key, match.match_id))
    )
    audit = AnacSirosVraJoinAudit(
        prediction_horizon_seconds=int(seconds),
        input_schedule_count=len(schedule_refs),
        input_outcome_count=len(outcome_refs),
        matched_pair_count=len(ordered_matches),
        point_in_time_history_match_count=sum(
            match.outcome.observation_provenance.use_scope
            == "point_in_time_target_history"
            for match in ordered_matches
        ),
        retrospective_holdout_only_match_count=sum(
            match.outcome.observation_provenance.use_scope
            == "retrospective_holdout_only"
            for match in ordered_matches
        ),
        decisions=tuple(decisions[key] for key in sorted(decisions)),
        ambiguities=tuple(
            sorted(
                ambiguities,
                key=lambda item: (item.scope, item.identity, item.reason_code),
            )
        ),
    )
    return AnacSirosVraJoinResult(ordered_matches, audit)


__all__ = [
    "AmbiguityScope",
    "AnacSirosVraJoinAmbiguity",
    "AnacSirosVraJoinAudit",
    "AnacSirosVraJoinDecision",
    "AnacSirosVraJoinError",
    "AnacSirosVraJoinResult",
    "AnacSirosVraMatch",
    "AnacSirosVraMatchKey",
    "AnacVraOutcomeCandidate",
    "AnacVraOutcomeObservationProvenance",
    "JoinDisposition",
    "JoinSide",
    "OutcomeEvidenceBasis",
    "OutcomeUseScope",
    "join_siros_schedules_to_vra_outcomes",
]
