"""Strict offline construction of ANAC VRA outcome candidates.

This orchestration layer deliberately delegates all CSV interpretation to
``sources.anac.iter_vra_file``.  Its responsibilities are narrower:

* require the caller to pin the exact local VRA bytes by size and SHA-256;
* require explicit, byte-bound outcome-observation evidence;
* build an unambiguous training-code reverse airport index;
* admit terminal outcomes only; and
* freeze a deterministic, fully reconciled disposition audit.

No function in this module performs network I/O.  In particular, neither a
VRA filename nor file metadata is interpreted as historical publication
evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Iterable, Literal, Mapping

from .anac_siros_vra_join import (
    AnacVraOutcomeCandidate,
    AnacVraOutcomeObservationProvenance,
)
from .schema import ALLOWED_STATUSES, TERMINAL_STATUSES, GlobalFlightRecord
from .sources.anac import (
    AirportMetadata,
    AnacPartitionAudit,
    AnacRowProvenance,
    build_vra_url,
    iter_vra_file,
)


ANAC_VRA_OUTCOME_LOAD_SCHEMA_VERSION = "skyeta-anac-vra-outcomes-v1"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OFFICIAL_FILENAME = re.compile(r"^VRA_(\d{4})_(0[1-9]|1[0-2])\.csv$")

OutcomeDisposition = Literal[
    "accepted_terminal",
    "excluded_nonterminal",
    "excluded_unplanned",
    "rejected_source",
    "rejected_normalization",
]


class AnacVraOutcomeLoadError(ValueError):
    """A pinned VRA file cannot be converted into audited outcomes."""


class AnacVraOutcomeIntegrityError(AnacVraOutcomeLoadError):
    """Local bytes or explicit evidence do not match the reviewed pin."""


class AnacVraOutcomeReconciliationError(AnacVraOutcomeLoadError):
    """Source and loader dispositions do not reconcile exactly."""


def _utc(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise AnacVraOutcomeIntegrityError(
            f"{field_name} must be a timezone-aware datetime"
        )
    return value.astimezone(timezone.utc)


def _digest(value: object, field_name: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256.fullmatch(text):
        raise AnacVraOutcomeIntegrityError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return text


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AnacVraOutcomeIntegrityError(
            f"{field_name} must be a positive integer"
        )
    return value


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: object) -> str:
    def convert(item: object) -> object:
        if isinstance(item, datetime):
            return _iso_utc(item)
        if isinstance(item, date):
            return item.isoformat()
        if isinstance(item, Mapping):
            return {
                str(key): convert(child)
                for key, child in sorted(
                    item.items(), key=lambda pair: str(pair[0])
                )
            }
        if isinstance(item, (tuple, list)):
            return [convert(child) for child in item]
        return item

    return json.dumps(
        convert(value),
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _without_local_paths(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _without_local_paths(child)
            for key, child in value.items()
            if str(key) != "file_path"
        }
    if isinstance(value, (tuple, list)):
        return [_without_local_paths(child) for child in value]
    return value


@dataclass(frozen=True, slots=True)
class AnacVraOutcomeFilePin:
    """Exact local bytes and direct retrieval time for one VRA month."""

    path: str | Path
    source_url: str
    retrieved_at_utc: datetime
    expected_sha256: str
    expected_raw_bytes: int

    def __post_init__(self) -> None:
        raw_path = str(self.path or "").strip()
        if not raw_path:
            raise AnacVraOutcomeIntegrityError("path is required")
        path = Path(raw_path).resolve()
        match = _OFFICIAL_FILENAME.fullmatch(path.name)
        if match is None:
            raise AnacVraOutcomeIntegrityError(
                "path must end with an official modern ANAC VRA filename"
            )
        expected_url = build_vra_url(int(match.group(1)), int(match.group(2)))
        source_url = str(self.source_url or "").strip()
        if source_url != expected_url:
            raise AnacVraOutcomeIntegrityError(
                "source_url does not match the official VRA filename"
            )
        object.__setattr__(self, "path", str(path))
        object.__setattr__(self, "source_url", source_url)
        object.__setattr__(
            self,
            "retrieved_at_utc",
            _utc(self.retrieved_at_utc, "retrieved_at_utc"),
        )
        object.__setattr__(
            self,
            "expected_sha256",
            _digest(self.expected_sha256, "expected_sha256"),
        )
        object.__setattr__(
            self,
            "expected_raw_bytes",
            _positive_int(self.expected_raw_bytes, "expected_raw_bytes"),
        )

    @property
    def filename(self) -> str:
        return Path(str(self.path)).name

    def stable_dict(self) -> dict[str, object]:
        """Return reproducibility facts without a machine-local path."""

        return {
            "source_url": self.source_url,
            "filename": self.filename,
            "retrieved_at_utc": _iso_utc(self.retrieved_at_utc),
            "expected_sha256": self.expected_sha256,
            "expected_raw_bytes": self.expected_raw_bytes,
        }


def build_training_code_airport_index(
    airports: Mapping[str, AirportMetadata],
) -> Mapping[str, AirportMetadata]:
    """Copy and reverse an ICAO index, failing on every ambiguous code."""

    if not isinstance(airports, Mapping) or not airports:
        raise AnacVraOutcomeIntegrityError(
            "airports must be a non-empty ICAO-to-AirportMetadata mapping"
        )
    reverse: dict[str, AirportMetadata] = {}
    for raw_icao, airport in sorted(airports.items(), key=lambda pair: str(pair[0])):
        if not isinstance(raw_icao, str) or not isinstance(airport, AirportMetadata):
            raise AnacVraOutcomeIntegrityError(
                "airport indexes must map canonical ICAO strings to AirportMetadata"
            )
        if raw_icao != airport.icao:
            raise AnacVraOutcomeIntegrityError(
                f"airport index key/code mismatch: {raw_icao!r} != {airport.icao!r}"
            )
        training_code = airport.training_code
        existing = reverse.get(training_code)
        if existing is not None and existing.icao != airport.icao:
            raise AnacVraOutcomeIntegrityError(
                "training-code collision for "
                f"{training_code}: {existing.icao} and {airport.icao}"
            )
        reverse[training_code] = airport
    return MappingProxyType(dict(sorted(reverse.items())))


@dataclass(frozen=True, slots=True)
class AnacVraOutcomeRowDecision:
    """One and only one final disposition for one source CSV row."""

    row_number: int
    disposition: OutcomeDisposition
    record_id: str | None
    record_hint: str
    status: str | None
    reason: str | None

    def __post_init__(self) -> None:
        if (
            isinstance(self.row_number, bool)
            or not isinstance(self.row_number, int)
            or self.row_number < 2
        ):
            raise AnacVraOutcomeReconciliationError(
                "row_number must identify a CSV data row"
            )
        if self.disposition not in {
            "accepted_terminal",
            "excluded_nonterminal",
            "excluded_unplanned",
            "rejected_source",
            "rejected_normalization",
        }:
            raise AnacVraOutcomeReconciliationError("unsupported row disposition")
        record_hint = str(self.record_hint or "").strip()
        if not record_hint:
            raise AnacVraOutcomeReconciliationError("record_hint is required")
        if self.disposition == "accepted_terminal":
            if not self.record_id or self.status not in TERMINAL_STATUSES or self.reason:
                raise AnacVraOutcomeReconciliationError(
                    "accepted terminal decisions require record identity and status"
                )
        elif self.disposition == "excluded_nonterminal":
            if (
                not self.record_id
                or self.status not in ALLOWED_STATUSES - TERMINAL_STATUSES
                or not self.reason
            ):
                raise AnacVraOutcomeReconciliationError(
                    "non-terminal exclusions require identity, status, and reason"
                )
        elif self.disposition == "rejected_normalization":
            if not self.record_id or not self.reason:
                raise AnacVraOutcomeReconciliationError(
                    "normalization rejections require identity and reason"
                )
        elif self.record_id is not None or not self.reason:
            raise AnacVraOutcomeReconciliationError(
                "source exclusions/rejections require a reason and no record ID"
            )
        object.__setattr__(self, "record_hint", record_hint)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AnacVraOutcomeLoadAudit:
    """Immutable counts and facts for one completed pinned-file load."""

    schema_version: str
    source_url: str
    filename: str
    retrieved_at_utc: datetime
    raw_file_sha256: str
    raw_bytes: int
    observation_provenance: AnacVraOutcomeObservationProvenance
    source_headers: tuple[str, ...]
    source_raw_row_count: int
    source_parser_accepted_row_count: int
    source_excluded_unplanned_row_count: int
    source_rejected_row_count: int
    terminal_candidate_count: int
    excluded_nonterminal_row_count: int
    normalization_rejected_row_count: int
    terminal_status_counts: Mapping[str, int]
    nonterminal_status_counts: Mapping[str, int]
    decisions: tuple[AnacVraOutcomeRowDecision, ...]
    source_parser_audit_sha256: str
    candidate_facts_sha256: str
    completed: bool = True

    def __post_init__(self) -> None:
        if self.schema_version != ANAC_VRA_OUTCOME_LOAD_SCHEMA_VERSION:
            raise AnacVraOutcomeReconciliationError(
                "unsupported VRA outcome load schema version"
            )
        retrieved = _utc(self.retrieved_at_utc, "audit.retrieved_at_utc")
        raw_digest = _digest(self.raw_file_sha256, "audit.raw_file_sha256")
        raw_bytes = _positive_int(self.raw_bytes, "audit.raw_bytes")
        if not isinstance(
            self.observation_provenance, AnacVraOutcomeObservationProvenance
        ):
            raise TypeError(
                "observation_provenance must be AnacVraOutcomeObservationProvenance"
            )
        evidence = self.observation_provenance
        source_url = str(self.source_url or "").strip()
        filename = str(self.filename or "").strip()
        if source_url != evidence.vra_source_url:
            raise AnacVraOutcomeReconciliationError(
                "audit source does not match its outcome observation evidence"
            )
        if filename != source_url.rsplit("/", 1)[-1]:
            raise AnacVraOutcomeReconciliationError(
                "audit filename does not match its official source URL"
            )
        if raw_digest != evidence.raw_file_sha256:
            raise AnacVraOutcomeReconciliationError(
                "audit bytes do not match outcome observation evidence"
            )
        if retrieved < evidence.outcome_observed_at_utc:
            raise AnacVraOutcomeReconciliationError(
                "audit retrieval cannot precede outcome observation evidence"
            )
        if evidence.basis == "direct_retrieval_capture" and (
            evidence.evidence_url != source_url
            or evidence.evidence_sha256 != raw_digest
            or evidence.evidence_retrieved_at_utc != retrieved
            or evidence.outcome_observed_at_utc != retrieved
        ):
            raise AnacVraOutcomeReconciliationError(
                "direct-retrieval audit evidence must be the exact file capture"
            )
        if not self.source_headers or any(not str(value) for value in self.source_headers):
            raise AnacVraOutcomeReconciliationError(
                "source_headers must contain the validated VRA header"
            )
        count_names = (
            "source_raw_row_count",
            "source_parser_accepted_row_count",
            "source_excluded_unplanned_row_count",
            "source_rejected_row_count",
            "terminal_candidate_count",
            "excluded_nonterminal_row_count",
            "normalization_rejected_row_count",
        )
        for name in count_names:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AnacVraOutcomeReconciliationError(
                    f"{name} must be a non-negative integer"
                )
        if self.source_raw_row_count != (
            self.source_parser_accepted_row_count
            + self.source_excluded_unplanned_row_count
            + self.source_rejected_row_count
        ):
            raise AnacVraOutcomeReconciliationError(
                "source parser counts do not reconcile to raw rows"
            )
        if self.source_parser_accepted_row_count != (
            self.terminal_candidate_count
            + self.excluded_nonterminal_row_count
            + self.normalization_rejected_row_count
        ):
            raise AnacVraOutcomeReconciliationError(
                "loader dispositions do not reconcile to parser-accepted rows"
            )

        terminal_counts = dict(self.terminal_status_counts)
        nonterminal_counts = dict(self.nonterminal_status_counts)
        if set(terminal_counts) != set(TERMINAL_STATUSES):
            raise AnacVraOutcomeReconciliationError(
                "terminal status counts must cover every terminal status"
            )
        if set(nonterminal_counts) != set(ALLOWED_STATUSES - TERMINAL_STATUSES):
            raise AnacVraOutcomeReconciliationError(
                "non-terminal status counts must cover every non-terminal status"
            )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (*terminal_counts.values(), *nonterminal_counts.values())
        ):
            raise AnacVraOutcomeReconciliationError(
                "status counts must be non-negative integers"
            )
        if sum(terminal_counts.values()) != self.terminal_candidate_count:
            raise AnacVraOutcomeReconciliationError(
                "terminal status counts do not reconcile"
            )
        if sum(nonterminal_counts.values()) != self.excluded_nonterminal_row_count:
            raise AnacVraOutcomeReconciliationError(
                "non-terminal status counts do not reconcile"
            )

        decisions = tuple(sorted(self.decisions, key=lambda item: item.row_number))
        if len(decisions) != self.source_raw_row_count:
            raise AnacVraOutcomeReconciliationError(
                "every raw VRA row must have exactly one loader decision"
            )
        if len({item.row_number for item in decisions}) != len(decisions):
            raise AnacVraOutcomeReconciliationError(
                "VRA row decisions must have unique row numbers"
            )
        disposition_counts = Counter(item.disposition for item in decisions)
        expected_dispositions = {
            "accepted_terminal": self.terminal_candidate_count,
            "excluded_nonterminal": self.excluded_nonterminal_row_count,
            "excluded_unplanned": self.source_excluded_unplanned_row_count,
            "rejected_source": self.source_rejected_row_count,
            "rejected_normalization": self.normalization_rejected_row_count,
        }
        if dict(disposition_counts) != {
            key: count for key, count in expected_dispositions.items() if count
        }:
            raise AnacVraOutcomeReconciliationError(
                "decision dispositions do not reconcile to audit counts"
            )
        if self.completed is not True:
            raise AnacVraOutcomeReconciliationError(
                "only completed VRA outcome loads may be published"
            )

        object.__setattr__(self, "retrieved_at_utc", retrieved)
        object.__setattr__(self, "source_url", source_url)
        object.__setattr__(self, "filename", filename)
        object.__setattr__(self, "raw_file_sha256", raw_digest)
        object.__setattr__(self, "raw_bytes", raw_bytes)
        object.__setattr__(self, "source_headers", tuple(self.source_headers))
        object.__setattr__(
            self,
            "terminal_status_counts",
            MappingProxyType(dict(sorted(terminal_counts.items()))),
        )
        object.__setattr__(
            self,
            "nonterminal_status_counts",
            MappingProxyType(dict(sorted(nonterminal_counts.items()))),
        )
        object.__setattr__(self, "decisions", decisions)
        object.__setattr__(
            self,
            "source_parser_audit_sha256",
            _digest(
                self.source_parser_audit_sha256,
                "source_parser_audit_sha256",
            ),
        )
        object.__setattr__(
            self,
            "candidate_facts_sha256",
            _digest(self.candidate_facts_sha256, "candidate_facts_sha256"),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_url": self.source_url,
            "filename": self.filename,
            "retrieved_at_utc": _iso_utc(self.retrieved_at_utc),
            "raw_file_sha256": self.raw_file_sha256,
            "raw_bytes": self.raw_bytes,
            "observation_provenance": self.observation_provenance.to_dict(),
            "source_headers": list(self.source_headers),
            "source_raw_row_count": self.source_raw_row_count,
            "source_parser_accepted_row_count": (
                self.source_parser_accepted_row_count
            ),
            "source_excluded_unplanned_row_count": (
                self.source_excluded_unplanned_row_count
            ),
            "source_rejected_row_count": self.source_rejected_row_count,
            "terminal_candidate_count": self.terminal_candidate_count,
            "excluded_nonterminal_row_count": (
                self.excluded_nonterminal_row_count
            ),
            "normalization_rejected_row_count": (
                self.normalization_rejected_row_count
            ),
            "terminal_status_counts": dict(self.terminal_status_counts),
            "nonterminal_status_counts": dict(self.nonterminal_status_counts),
            "decisions": [item.to_dict() for item in self.decisions],
            "source_parser_audit_sha256": self.source_parser_audit_sha256,
            "candidate_facts_sha256": self.candidate_facts_sha256,
            "completed": self.completed,
        }

    @property
    def facts_sha256(self) -> str:
        return _canonical_hash(self._payload())

    def to_dict(self) -> dict[str, object]:
        result = self._payload()
        result["facts_sha256"] = self.facts_sha256
        return result


@dataclass(frozen=True, slots=True)
class AnacVraOutcomeLoadResult:
    """Terminal candidates plus their immutable load audit."""

    candidates: tuple[AnacVraOutcomeCandidate, ...]
    audit: AnacVraOutcomeLoadAudit

    def __post_init__(self) -> None:
        candidates = tuple(
            sorted(
                self.candidates,
                key=lambda item: (
                    item.record.record_id,
                    item.candidate_facts_sha256,
                ),
            )
        )
        if not isinstance(self.audit, AnacVraOutcomeLoadAudit):
            raise TypeError("audit must be AnacVraOutcomeLoadAudit")
        if len(candidates) != self.audit.terminal_candidate_count:
            raise AnacVraOutcomeReconciliationError(
                "candidate count does not reconcile to the load audit"
            )
        for candidate in candidates:
            if not isinstance(candidate, AnacVraOutcomeCandidate):
                raise TypeError("candidates must contain AnacVraOutcomeCandidate values")
            if candidate.record.status not in TERMINAL_STATUSES:
                raise AnacVraOutcomeReconciliationError(
                    "non-terminal records cannot enter outcome candidates"
                )
            if candidate.file_provenance.source_url != self.audit.source_url:
                raise AnacVraOutcomeReconciliationError(
                    "candidate source does not match the load audit"
                )
            if (
                candidate.file_provenance.raw_file_sha256
                != self.audit.raw_file_sha256
                or candidate.file_provenance.raw_bytes != self.audit.raw_bytes
            ):
                raise AnacVraOutcomeReconciliationError(
                    "candidate bytes do not match the load audit"
                )
            if candidate.observation_provenance != self.audit.observation_provenance:
                raise AnacVraOutcomeReconciliationError(
                    "candidate observation evidence does not match the load audit"
                )
        expected_digest = _candidate_digest(candidates)
        if expected_digest != self.audit.candidate_facts_sha256:
            raise AnacVraOutcomeReconciliationError(
                "candidate facts do not match the load audit digest"
            )
        object.__setattr__(self, "candidates", candidates)

    def to_dict(self) -> dict[str, object]:
        return {
            "audit": self.audit.to_dict(),
            "candidates": [
                {
                    "record_id": item.record.record_id,
                    "status": item.record.status,
                    "candidate_facts_sha256": item.candidate_facts_sha256,
                }
                for item in self.candidates
            ],
        }


def _candidate_digest(candidates: Iterable[AnacVraOutcomeCandidate]) -> str:
    facts = sorted(candidate.candidate_facts_sha256 for candidate in candidates)
    return hashlib.sha256("\n".join(facts).encode("ascii")).hexdigest()


def _validate_evidence(
    pin: AnacVraOutcomeFilePin,
    evidence: AnacVraOutcomeObservationProvenance,
) -> None:
    if not isinstance(evidence, AnacVraOutcomeObservationProvenance):
        raise TypeError(
            "observation_provenance must be AnacVraOutcomeObservationProvenance"
        )
    if evidence.vra_source_url != pin.source_url:
        raise AnacVraOutcomeIntegrityError(
            "observation evidence source does not match the pinned VRA file"
        )
    if evidence.raw_file_sha256 != pin.expected_sha256:
        raise AnacVraOutcomeIntegrityError(
            "observation evidence hash does not match the pinned VRA file"
        )
    if pin.retrieved_at_utc < evidence.outcome_observed_at_utc:
        raise AnacVraOutcomeIntegrityError(
            "file retrieval cannot precede its claimed observation evidence"
        )
    if evidence.basis == "direct_retrieval_capture":
        if (
            evidence.evidence_url != pin.source_url
            or evidence.evidence_sha256 != pin.expected_sha256
            or evidence.evidence_retrieved_at_utc != pin.retrieved_at_utc
            or evidence.outcome_observed_at_utc != pin.retrieved_at_utc
        ):
            raise AnacVraOutcomeIntegrityError(
                "direct-retrieval evidence must be the exact pinned file capture"
            )


def _source_audit_digest(audit: AnacPartitionAudit) -> str:
    return _canonical_hash(_without_local_paths(audit.to_dict()))


def _decision_from_source_row(
    row: AnacRowProvenance,
) -> AnacVraOutcomeRowDecision:
    if row.disposition == "excluded_unplanned":
        disposition: OutcomeDisposition = "excluded_unplanned"
    elif row.disposition == "rejected":
        disposition = "rejected_source"
    else:
        raise AnacVraOutcomeReconciliationError(
            "accepted source rows require a normalized loader disposition"
        )
    return AnacVraOutcomeRowDecision(
        row_number=row.row_number,
        disposition=disposition,
        record_id=None,
        record_hint=row.record_hint,
        status=None,
        reason=row.reason,
    )


def load_anac_vra_outcome_file(
    pin: AnacVraOutcomeFilePin,
    airports: Mapping[str, AirportMetadata],
    *,
    observation_provenance: AnacVraOutcomeObservationProvenance,
) -> AnacVraOutcomeLoadResult:
    """Load one already-cached, explicitly observed ANAC VRA month.

    Parser-invalid and unplanned rows are consumed in audited non-strict mode
    so the final result accounts for the complete pinned file.  This does not
    make malformed rows acceptable: they remain explicit rejected decisions.
    """

    if not isinstance(pin, AnacVraOutcomeFilePin):
        raise TypeError("pin must be AnacVraOutcomeFilePin")
    _validate_evidence(pin, observation_provenance)
    by_training_code = build_training_code_airport_index(airports)

    path = Path(str(pin.path))
    if not path.is_file():
        raise FileNotFoundError(path)
    actual_size = path.stat().st_size
    if actual_size != pin.expected_raw_bytes:
        raise AnacVraOutcomeIntegrityError(
            "VRA byte-size mismatch: "
            f"expected {pin.expected_raw_bytes}, got {actual_size}"
        )

    source_audit = AnacPartitionAudit()
    normalized_rows = list(
        iter_vra_file(
            path,
            airports,
            retrieved_at_utc=pin.retrieved_at_utc,
            source_url=pin.source_url,
            strict=False,
            audit=source_audit,
        )
    )
    provenance = source_audit.provenance
    if provenance is None or source_audit.completed is not True:
        raise AnacVraOutcomeReconciliationError(
            "ANAC source parser did not produce a completed file audit"
        )
    if provenance.raw_file_sha256 != pin.expected_sha256:
        raise AnacVraOutcomeIntegrityError(
            "VRA SHA-256 mismatch: "
            f"expected {pin.expected_sha256}, got {provenance.raw_file_sha256}"
        )
    if provenance.raw_bytes != pin.expected_raw_bytes:
        raise AnacVraOutcomeIntegrityError(
            "source parser byte count does not match the pinned VRA file"
        )

    accepted_iter = iter(normalized_rows)
    candidates: list[AnacVraOutcomeCandidate] = []
    decisions: list[AnacVraOutcomeRowDecision] = []
    terminal_counts = Counter({status: 0 for status in TERMINAL_STATUSES})
    nonterminal_counts = Counter(
        {status: 0 for status in ALLOWED_STATUSES - TERMINAL_STATUSES}
    )
    normalization_rejected = 0

    for source_row in source_audit.row_provenance:
        if source_row.disposition != "accepted":
            decisions.append(_decision_from_source_row(source_row))
            continue
        try:
            normalized = next(accepted_iter)
        except StopIteration as error:
            raise AnacVraOutcomeReconciliationError(
                "source accepted-row provenance exceeds normalized rows"
            ) from error
        if normalized["record_id"] != source_row.record_id:
            raise AnacVraOutcomeReconciliationError(
                "source accepted-row provenance does not match normalized identity"
            )
        try:
            record = GlobalFlightRecord.from_mapping(normalized)
        except (TypeError, ValueError) as error:
            normalization_rejected += 1
            decisions.append(
                AnacVraOutcomeRowDecision(
                    row_number=source_row.row_number,
                    disposition="rejected_normalization",
                    record_id=normalized["record_id"],
                    record_hint=source_row.record_hint,
                    status=str(normalized.get("status") or "") or None,
                    reason=f"normalized schema rejection: {error}",
                )
            )
            continue

        if record.status not in TERMINAL_STATUSES:
            nonterminal_counts[record.status] += 1
            decisions.append(
                AnacVraOutcomeRowDecision(
                    row_number=source_row.row_number,
                    disposition="excluded_nonterminal",
                    record_id=record.record_id,
                    record_hint=source_row.record_hint,
                    status=record.status,
                    reason=f"non-terminal VRA status: {record.status}",
                )
            )
            continue

        origin = by_training_code.get(record.origin)
        destination = by_training_code.get(record.destination)
        if origin is None or destination is None:
            raise AnacVraOutcomeReconciliationError(
                "normalized VRA airport identity is absent from the reverse index"
            )
        candidate = AnacVraOutcomeCandidate(
            record=record,
            origin_airport=origin,
            destination_airport=destination,
            file_provenance=provenance,
            observation_provenance=observation_provenance,
        )
        candidates.append(candidate)
        terminal_counts[record.status] += 1
        decisions.append(
            AnacVraOutcomeRowDecision(
                row_number=source_row.row_number,
                disposition="accepted_terminal",
                record_id=record.record_id,
                record_hint=source_row.record_hint,
                status=record.status,
                reason=None,
            )
        )

    try:
        next(accepted_iter)
    except StopIteration:
        pass
    else:
        raise AnacVraOutcomeReconciliationError(
            "normalized rows exceed source accepted-row provenance"
        )

    ordered_candidates = tuple(
        sorted(
            candidates,
            key=lambda item: (item.record.record_id, item.candidate_facts_sha256),
        )
    )
    audit = AnacVraOutcomeLoadAudit(
        schema_version=ANAC_VRA_OUTCOME_LOAD_SCHEMA_VERSION,
        source_url=provenance.source_url,
        filename=provenance.filename,
        retrieved_at_utc=provenance.retrieved_at_utc,
        raw_file_sha256=provenance.raw_file_sha256,
        raw_bytes=provenance.raw_bytes,
        observation_provenance=observation_provenance,
        source_headers=source_audit.headers,
        source_raw_row_count=source_audit.raw_row_count,
        source_parser_accepted_row_count=source_audit.accepted_row_count,
        source_excluded_unplanned_row_count=(
            source_audit.excluded_unplanned_row_count
        ),
        source_rejected_row_count=source_audit.rejected_row_count,
        terminal_candidate_count=len(ordered_candidates),
        excluded_nonterminal_row_count=sum(nonterminal_counts.values()),
        normalization_rejected_row_count=normalization_rejected,
        terminal_status_counts=terminal_counts,
        nonterminal_status_counts=nonterminal_counts,
        decisions=tuple(decisions),
        source_parser_audit_sha256=_source_audit_digest(source_audit),
        candidate_facts_sha256=_candidate_digest(ordered_candidates),
    )
    return AnacVraOutcomeLoadResult(ordered_candidates, audit)


__all__ = [
    "ANAC_VRA_OUTCOME_LOAD_SCHEMA_VERSION",
    "AnacVraOutcomeFilePin",
    "AnacVraOutcomeIntegrityError",
    "AnacVraOutcomeLoadAudit",
    "AnacVraOutcomeLoadError",
    "AnacVraOutcomeLoadResult",
    "AnacVraOutcomeReconciliationError",
    "AnacVraOutcomeRowDecision",
    "OutcomeDisposition",
    "build_training_code_airport_index",
    "load_anac_vra_outcome_file",
]
