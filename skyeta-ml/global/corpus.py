"""Provider-neutral normalized-corpus accounting for artifact v4.

This module starts *after* a provider adapter has normalized raw rows into
``GlobalFlightRecord`` objects.  It deliberately does not download data,
interpret provider-specific columns, deduplicate rows, or decide whether a
corpus is publishable.  Its job is narrower: bind accepted normalized record
identifiers to immutable raw-partition provenance and build reconciled audit
rollups for the artifact-v4 contract.

The returned ``corpusBinding`` and ``corpusAudit`` mappings contain exactly the
fields consumed by :mod:`global.export`.  More detailed status, delay-threshold,
and observation-evidence accounting is kept beside those mappings so adding
useful diagnostics cannot silently change the versioned artifact contract.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence
from urllib.parse import urlparse

from .export import (
    CORPUS_BINDING_METHOD,
    CORPUS_COUNT_FIELDS,
    ArtifactError,
)
from .schema import ALLOWED_STATUSES, TERMINAL_STATUSES, GlobalFlightRecord


_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_PLACEHOLDER = re.compile(
    r"(?:\btest(?:ing)?\b|\bsynthetic\b|\bfixture\b|\bnot[\s_-]*real\b|"
    r"\bfake\b|\bplaceholder\b|\bdemo\b|\bsample\b|\btodo\b|\btbd\b|"
    r"\bunknown\b|\bunverified\b)",
    re.IGNORECASE,
)
_DELAY_THRESHOLDS = (15, 30, 60)


class CorpusAuditError(ArtifactError):
    """Raised when a normalized corpus cannot be reconciled to provenance."""


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CorpusAuditError(f"{name} must be a non-empty string")
    return value.strip()


def _validate_https_url(value: object, name: str) -> str:
    text = _required_text(value, name)
    parsed = urlparse(text)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise CorpusAuditError(
            f"{name} must be an absolute HTTPS URL without credentials, "
            "query, or fragment"
        )
    return text


def _validate_aware_datetime(value: object, name: str) -> datetime:
    if not isinstance(value, datetime):
        raise CorpusAuditError(f"{name} must be an aware datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise CorpusAuditError(f"{name} must include a timezone offset")
    return value.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CorpusAuditError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class PartitionProvenance:
    """Immutable facts binding one normalized partition to one raw resource.

    ``expected_record_count`` must come from the caller's completed manifest
    for this *final accepted* partition, not from this runner.  If deduplication
    or another declared acceptance policy is applied before training, the
    manifest and stream must both describe that post-policy corpus.  Requiring
    an independent count makes a truncated or accidentally duplicated iterator
    fail rather than produce plausible rollups.
    """

    partition_id: str
    source_id: str
    month: str
    source_url: str
    retrieved_at_utc: datetime
    raw_file_sha256: str
    expected_record_count: int
    ingestion_completed: bool

    def __post_init__(self) -> None:
        partition_id = _required_text(self.partition_id, "partition_id")
        if _PLACEHOLDER.search(partition_id):
            raise CorpusAuditError("partition_id must not contain placeholder text")
        source_id = _required_text(self.source_id, "source_id")
        if _SOURCE_ID.fullmatch(source_id) is None:
            raise CorpusAuditError("source_id must use a stable lowercase identifier")
        if _MONTH.fullmatch(self.month) is None:
            raise CorpusAuditError("month must use YYYY-MM")
        _validate_https_url(self.source_url, "source_url")
        _validate_aware_datetime(self.retrieved_at_utc, "retrieved_at_utc")
        if not isinstance(self.raw_file_sha256, str) or _SHA256.fullmatch(
            self.raw_file_sha256
        ) is None:
            raise CorpusAuditError("raw_file_sha256 must be a lowercase SHA-256")
        _validate_nonnegative_int(
            self.expected_record_count, "expected_record_count"
        )
        if self.ingestion_completed is not True:
            raise CorpusAuditError(
                "partition provenance requires a completed ingestion audit"
            )


@dataclass(frozen=True, slots=True)
class CorpusPartition:
    """A one-shot normalized record stream and its immutable provenance."""

    provenance: PartitionProvenance
    records: Iterable[GlobalFlightRecord]

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, PartitionProvenance):
            raise CorpusAuditError(
                "corpus partition provenance must be PartitionProvenance"
            )
        try:
            iter(self.records)
        except TypeError as error:
            raise CorpusAuditError(
                "corpus partition records must be iterable"
            ) from error


@dataclass(frozen=True, slots=True)
class CorpusAuditResult:
    """JSON-compatible artifact inputs plus non-contract diagnostics."""

    corpus_binding: Mapping[str, object]
    corpus_audit: Mapping[str, object]
    operational_audit: Mapping[str, object]
    observation_evidence: Mapping[str, object]

    def data_coverage(self) -> dict[str, object]:
        """Return the exact model-card fragment consumed by artifact v4."""

        return {
            "rows": int(self.corpus_binding["recordCount"]),
            "corpusAudit": dict(self.corpus_audit),
        }


def _empty_counts() -> dict[str, int]:
    return {field: 0 for field in CORPUS_COUNT_FIELDS}


def _add_counts(target: dict[str, int], values: Mapping[str, int]) -> None:
    for field in CORPUS_COUNT_FIELDS:
        target[field] += values[field]


def _record_counts(record: GlobalFlightRecord) -> dict[str, int]:
    terminal = record.status in TERMINAL_STATUSES
    operated = record.status in {"landed", "diverted"}
    arrival_time = operated and record.actual_arrival_utc is not None
    delayed_15 = False
    if record.status == "landed" and record.actual_arrival_utc is not None:
        delayed_15 = (
            record.actual_arrival_utc - record.scheduled_arrival_utc
        ).total_seconds() >= 15 * 60
    return {
        "scheduledRows": 1,
        # A record is counted only after a schema round-trip below, so every
        # accepted normalized row has the complete identity contract.
        "identityCompleteRows": 1,
        "knownOutcomeRows": int(terminal),
        "operatedRows": int(operated),
        "operatedRowsWithArrivalTimes": int(arrival_time),
        "arrival15DelayedRows": int(delayed_15),
        "cancellationRows": int(record.status == "cancelled"),
    }


def _empty_operational() -> dict[str, object]:
    return {
        "scheduledRows": 0,
        "statusRows": {status: 0 for status in sorted(ALLOWED_STATUSES)},
        "operatedRowsWithArrivalTimes": 0,
        "arrivalDelayThresholdRows": {
            f"arrival{threshold}DelayedRows": 0
            for threshold in _DELAY_THRESHOLDS
        },
    }


def _add_operational(target: dict[str, object], record: GlobalFlightRecord) -> None:
    target["scheduledRows"] = int(target["scheduledRows"]) + 1
    status_rows = target["statusRows"]
    assert isinstance(status_rows, dict)
    status_rows[record.status] += 1
    if (
        record.status in {"landed", "diverted"}
        and record.actual_arrival_utc is not None
    ):
        target["operatedRowsWithArrivalTimes"] = (
            int(target["operatedRowsWithArrivalTimes"]) + 1
        )
    if record.status != "landed" or record.actual_arrival_utc is None:
        return
    delay_minutes = (
        record.actual_arrival_utc - record.scheduled_arrival_utc
    ).total_seconds() / 60.0
    thresholds = target["arrivalDelayThresholdRows"]
    assert isinstance(thresholds, dict)
    for threshold in _DELAY_THRESHOLDS:
        if delay_minutes >= threshold:
            thresholds[f"arrival{threshold}DelayedRows"] += 1


def _validate_completed_months(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise CorpusAuditError("completed_months must be a sequence of YYYY-MM values")
    months = tuple(values)
    if not months:
        raise CorpusAuditError("completed_months must not be empty")
    parsed: list[tuple[int, int]] = []
    for value in months:
        if not isinstance(value, str) or (match := _MONTH.fullmatch(value)) is None:
            raise CorpusAuditError("completed_months values must use YYYY-MM")
        parsed.append((int(match.group(1)), int(match.group(2))))
    if len(set(months)) != len(months):
        raise CorpusAuditError("completed_months must be unique")
    for previous, current in zip(parsed, parsed[1:], strict=False):
        expected = (
            (previous[0] + 1, 1)
            if previous[1] == 12
            else (previous[0], previous[1] + 1)
        )
        if current != expected:
            raise CorpusAuditError(
                "completed_months must be chronological and consecutive"
            )
    return months


def _validate_expected_values(
    values: Iterable[str] | None,
    name: str,
    *,
    pattern: re.Pattern[str] | None = None,
) -> tuple[str, ...] | None:
    if values is None:
        return None
    if isinstance(values, (str, bytes)):
        raise CorpusAuditError(f"{name} must be an iterable of identifiers")
    result = tuple(values)
    if not result:
        raise CorpusAuditError(f"{name} must not be empty when supplied")
    if len(set(result)) != len(result):
        raise CorpusAuditError(f"{name} must be unique")
    for value in result:
        text = _required_text(value, name)
        if text != value:
            raise CorpusAuditError(f"{name} values must be canonical")
        if pattern is not None and pattern.fullmatch(text) is None:
            raise CorpusAuditError(f"{name} contains an invalid identifier")
    return result


def _canonical_record(record: object, partition_id: str) -> GlobalFlightRecord:
    if not isinstance(record, GlobalFlightRecord):
        raise CorpusAuditError(
            f"partition {partition_id} contains a non-GlobalFlightRecord value"
        )
    try:
        normalized = GlobalFlightRecord.from_mapping(record.as_dict())
    except (TypeError, ValueError) as error:
        raise CorpusAuditError(
            f"partition {partition_id} contains an invalid normalized record"
        ) from error
    if normalized != record:
        raise CorpusAuditError(
            f"partition {partition_id} contains a non-canonical normalized record"
        )
    return record


def _sum_count_maps(values: Iterable[Mapping[str, int]]) -> dict[str, int]:
    total = _empty_counts()
    for value in values:
        _add_counts(total, value)
    return total


def _require_counts_equal(
    observed: Mapping[str, int], expected: Mapping[str, int], name: str
) -> None:
    if any(observed[field] != expected[field] for field in CORPUS_COUNT_FIELDS):
        raise CorpusAuditError(f"{name} failed exact count reconciliation")


def _validate_operational_block(value: Mapping[str, object], name: str) -> None:
    scheduled = _validate_nonnegative_int(value.get("scheduledRows"), name)
    statuses = value.get("statusRows")
    if not isinstance(statuses, Mapping) or set(statuses) != set(ALLOWED_STATUSES):
        raise CorpusAuditError(f"{name} has incomplete status counts")
    status_total = sum(
        _validate_nonnegative_int(count, f"{name}.{status}")
        for status, count in statuses.items()
    )
    if status_total != scheduled:
        raise CorpusAuditError(f"{name} status counts do not reconcile")
    arrivals = _validate_nonnegative_int(
        value.get("operatedRowsWithArrivalTimes"), name
    )
    if arrivals > int(statuses["landed"]) + int(statuses["diverted"]):
        raise CorpusAuditError(f"{name} contains impossible arrival-time counts")
    thresholds = value.get("arrivalDelayThresholdRows")
    threshold_fields = {
        f"arrival{threshold}DelayedRows" for threshold in _DELAY_THRESHOLDS
    }
    if not isinstance(thresholds, Mapping) or set(thresholds) != threshold_fields:
        raise CorpusAuditError(f"{name} has incomplete delay-threshold counts")
    delayed = [
        _validate_nonnegative_int(
            thresholds[f"arrival{threshold}DelayedRows"], name
        )
        for threshold in _DELAY_THRESHOLDS
    ]
    if not delayed[2] <= delayed[1] <= delayed[0] <= arrivals:
        raise CorpusAuditError(f"{name} contains impossible delay-threshold counts")


def audit_corpus(
    partitions: Iterable[CorpusPartition],
    *,
    completed_months: Sequence[str],
    expected_source_ids: Iterable[str] | None = None,
    expected_origin_regions: Iterable[str] | None = None,
    prediction_horizon: timedelta = timedelta(days=7),
) -> CorpusAuditResult:
    """Consume normalized partitions once and construct reconciled v4 evidence.

    ``completed_months`` is an explicit caller assertion because seeing records
    from a month does not prove that the raw monthly delivery was complete.
    Optional expected source/region universes make missing partitions or region
    mappings fail immediately; otherwise those universes are derived from the
    completed input.
    """

    months = _validate_completed_months(completed_months)
    expected_sources = _validate_expected_values(
        expected_source_ids, "expected_source_ids", pattern=_SOURCE_ID
    )
    expected_regions = _validate_expected_values(
        expected_origin_regions, "expected_origin_regions"
    )
    if not isinstance(prediction_horizon, timedelta):
        raise CorpusAuditError("prediction_horizon must be a timedelta")
    horizon_seconds = prediction_horizon.total_seconds()
    if not math.isfinite(horizon_seconds) or horizon_seconds <= 0:
        raise CorpusAuditError("prediction_horizon must be finite and positive")

    month_set = set(months)
    expected_source_set = set(expected_sources or ())
    expected_region_set = set(expected_regions or ())
    partition_ids: set[str] = set()
    seen_partition_months: set[str] = set()
    seen_partition_sources: set[str] = set()
    seen_record_ids: set[str] = set()

    top_counts = _empty_counts()
    month_counts = {month: _empty_counts() for month in months}
    source_counts: dict[str, dict[str, int]] = {}
    region_counts: dict[str, dict[str, int]] = {}
    partition_rows: list[dict[str, object]] = []

    operational_all = _empty_operational()
    operational_months = {month: _empty_operational() for month in months}
    operational_sources: dict[str, dict[str, object]] = {}
    operational_regions: dict[str, dict[str, object]] = {}

    schedule_present = 0
    schedule_before_departure = 0
    schedule_by_prediction_time = 0
    terminal_rows = 0
    terminal_outcome_present = 0

    partition_count = 0
    for raw_partition in partitions:
        partition_count += 1
        if not isinstance(raw_partition, CorpusPartition):
            raise CorpusAuditError("partitions must contain CorpusPartition values")
        provenance = raw_partition.provenance
        if provenance.partition_id in partition_ids:
            raise CorpusAuditError("partition identifiers must be globally unique")
        partition_ids.add(provenance.partition_id)
        if provenance.month not in month_set:
            raise CorpusAuditError(
                f"partition {provenance.partition_id} is outside completed_months"
            )
        if (
            expected_sources is not None
            and provenance.source_id not in expected_source_set
        ):
            raise CorpusAuditError(
                f"partition {provenance.partition_id} references an unexpected source"
            )
        seen_partition_months.add(provenance.month)
        seen_partition_sources.add(provenance.source_id)
        source_counts.setdefault(provenance.source_id, _empty_counts())
        operational_sources.setdefault(provenance.source_id, _empty_operational())

        counts = _empty_counts()
        sparse_regions: dict[str, dict[str, int]] = {}
        accepted = 0
        for raw_record in raw_partition.records:
            record = _canonical_record(raw_record, provenance.partition_id)
            if record.source != provenance.source_url:
                raise CorpusAuditError(
                    f"partition {provenance.partition_id} record source does not "
                    "match immutable source_url provenance"
                )
            record_month = record.service_date.strftime("%Y-%m")
            if record_month != provenance.month:
                raise CorpusAuditError(
                    f"partition {provenance.partition_id} record service month "
                    f"{record_month} does not match provenance month "
                    f"{provenance.month}"
                )
            if record.record_id in seen_record_ids:
                raise CorpusAuditError(
                    f"duplicate normalized record_id: {record.record_id}"
                )
            seen_record_ids.add(record.record_id)
            if (
                expected_regions is not None
                and record.origin_region not in expected_region_set
            ):
                raise CorpusAuditError(
                    f"partition {provenance.partition_id} contains an unexpected "
                    f"origin region: {record.origin_region}"
                )

            accepted += 1
            values = _record_counts(record)
            _add_counts(counts, values)
            sparse_regions.setdefault(record.origin_region, _empty_counts())
            _add_counts(sparse_regions[record.origin_region], values)
            region_counts.setdefault(record.origin_region, _empty_counts())
            _add_counts(region_counts[record.origin_region], values)

            _add_operational(operational_all, record)
            _add_operational(operational_months[provenance.month], record)
            _add_operational(operational_sources[provenance.source_id], record)
            operational_regions.setdefault(record.origin_region, _empty_operational())
            _add_operational(operational_regions[record.origin_region], record)

            if record.schedule_observed_at is not None:
                schedule_present += 1
                if record.schedule_observed_at <= record.scheduled_departure_utc:
                    schedule_before_departure += 1
                prediction_time = record.scheduled_departure_utc - prediction_horizon
                if record.schedule_observed_at <= prediction_time:
                    schedule_by_prediction_time += 1
            if record.status in TERMINAL_STATUSES:
                terminal_rows += 1
                if record.outcome_observed_at is not None:
                    terminal_outcome_present += 1

        if accepted != provenance.expected_record_count:
            raise CorpusAuditError(
                f"partition {provenance.partition_id} accepted {accepted} records; "
                f"completed ingestion audit expected {provenance.expected_record_count}"
            )

        _add_counts(top_counts, counts)
        _add_counts(month_counts[provenance.month], counts)
        _add_counts(source_counts[provenance.source_id], counts)
        partition_rows.append(
            {
                "partitionId": provenance.partition_id,
                "sourceId": provenance.source_id,
                "month": provenance.month,
                "sourceUrl": provenance.source_url,
                "retrievedAtUtc": _utc_text(provenance.retrieved_at_utc),
                "rawFileSha256": provenance.raw_file_sha256,
                "counts": counts,
                # Zero-filled after the complete origin-region universe is known.
                "regions": sparse_regions,
            }
        )

    if partition_count == 0:
        raise CorpusAuditError("at least one completed corpus partition is required")
    missing_months = [month for month in months if month not in seen_partition_months]
    if missing_months:
        raise CorpusAuditError(
            "completed_months lacks partition provenance for: "
            + ", ".join(missing_months)
        )
    if expected_sources is not None:
        missing_sources = [
            source
            for source in expected_sources
            if source not in seen_partition_sources
        ]
        if missing_sources:
            raise CorpusAuditError(
                "expected_source_ids lacks partition provenance for: "
                + ", ".join(missing_sources)
            )
    if not seen_record_ids:
        raise CorpusAuditError("corpus binding requires at least one accepted record")

    source_universe = tuple(expected_sources or sorted(source_counts))
    region_universe = tuple(expected_regions or sorted(region_counts))
    if not region_universe:
        raise CorpusAuditError("at least one origin region is required")
    for source_id in source_universe:
        source_counts.setdefault(source_id, _empty_counts())
        operational_sources.setdefault(source_id, _empty_operational())
    for region in region_universe:
        region_counts.setdefault(region, _empty_counts())
        operational_regions.setdefault(region, _empty_operational())
    for partition in partition_rows:
        sparse = partition["regions"]
        assert isinstance(sparse, dict)
        partition["regions"] = {
            region: sparse.get(region, _empty_counts()) for region in region_universe
        }
        _require_counts_equal(
            _sum_count_maps(partition["regions"].values()),
            partition["counts"],
            f"partition {partition['partitionId']} regions",
        )
    partition_rows.sort(
        key=lambda partition: (
            partition["month"],
            partition["sourceId"],
            partition["partitionId"],
        )
    )

    _require_counts_equal(
        _sum_count_maps(month_counts.values()), top_counts, "month rollups"
    )
    _require_counts_equal(
        _sum_count_maps(source_counts.values()), top_counts, "source rollups"
    )
    _require_counts_equal(
        _sum_count_maps(region_counts.values()), top_counts, "origin-region rollups"
    )
    _require_counts_equal(
        _sum_count_maps(
            partition["counts"] for partition in partition_rows  # type: ignore[misc]
        ),
        top_counts,
        "partition rollups",
    )

    binding_payload = "\n".join(sorted(seen_record_ids)).encode("utf-8")
    corpus_binding: dict[str, object] = {
        "method": CORPUS_BINDING_METHOD,
        "recordCount": len(seen_record_ids),
        "recordIdsSha256": hashlib.sha256(binding_payload).hexdigest(),
    }
    corpus_audit: dict[str, object] = {
        "completedMonths": list(months),
        **top_counts,
        "regions": {region: region_counts[region] for region in region_universe},
        "months": {month: month_counts[month] for month in months},
        "sources": {source: source_counts[source] for source in source_universe},
        "partitions": partition_rows,
    }
    operational_audit: dict[str, object] = {
        "all": operational_all,
        "months": {month: operational_months[month] for month in months},
        "sources": {
            source: operational_sources[source] for source in source_universe
        },
        "originRegions": {
            region: operational_regions[region] for region in region_universe
        },
    }
    _validate_operational_block(operational_all, "global operational audit")
    for month, values in operational_months.items():
        _validate_operational_block(values, f"operational month {month}")
    for source, values in operational_sources.items():
        _validate_operational_block(values, f"operational source {source}")
    for region, values in operational_regions.items():
        _validate_operational_block(values, f"operational origin region {region}")
    scheduled_rows = top_counts["scheduledRows"]
    observation_evidence: dict[str, object] = {
        "predictionHorizonSeconds": int(horizon_seconds),
        "schedule": {
            "eligibleRows": scheduled_rows,
            "timestampPresentRows": schedule_present,
            "missingTimestampRows": scheduled_rows - schedule_present,
            "observedBeforeDepartureRows": schedule_before_departure,
            "observedByPredictionTimeRows": schedule_by_prediction_time,
            "completeAtPredictionTime": schedule_by_prediction_time == scheduled_rows,
        },
        "terminalOutcome": {
            "eligibleRows": terminal_rows,
            "timestampPresentRows": terminal_outcome_present,
            "missingTimestampRows": terminal_rows - terminal_outcome_present,
            "complete": terminal_outcome_present == terminal_rows,
        },
    }
    return CorpusAuditResult(
        corpus_binding=corpus_binding,
        corpus_audit=corpus_audit,
        operational_audit=operational_audit,
        observation_evidence=observation_evidence,
    )
