from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from .. import export
from ..corpus import (
    CorpusAuditError,
    CorpusPartition,
    PartitionProvenance,
    audit_corpus,
)
from ..export import CORPUS_BINDING_METHOD, CORPUS_COUNT_FIELDS, build_corpus_binding


REGIONS = (
    "Africa",
    "Asia",
    "Europe",
    "North America",
    "South America",
    "Oceania",
)


def _provenance(
    partition_id: str,
    *,
    source_id: str = "provider-a",
    month: str = "2025-01",
    source_url: str | None = None,
    expected_record_count: int = 1,
    ingestion_completed: bool = True,
) -> PartitionProvenance:
    return PartitionProvenance(
        partition_id=partition_id,
        source_id=source_id,
        month=month,
        source_url=source_url or f"https://records.example/{partition_id}.csv",
        retrieved_at_utc=datetime(2026, 8, 9, 2, 30, tzinfo=timezone.utc),
        raw_file_sha256=sha256(f"raw-{partition_id}".encode()).hexdigest(),
        expected_record_count=expected_record_count,
        ingestion_completed=ingestion_completed,
    )


def test_streams_partitions_into_exact_v4_binding_and_reconciled_rollups(
    make_record,
):
    january_url = "https://records.example/provider-a-2025-01.csv"
    february_url = "https://records.example/provider-b-2025-02.csv"
    landed = make_record(
        source=january_url, origin_region="Africa", status="landed"
    )
    landed = replace(
        landed,
        actual_arrival_utc=landed.scheduled_arrival_utc + timedelta(minutes=75),
        outcome_observed_at=landed.scheduled_arrival_utc + timedelta(minutes=75),
    )
    records = (
        landed,
        make_record(source=january_url, origin_region="Asia", status="cancelled"),
        make_record(
            source=february_url,
            origin_region="Europe",
            status="diverted",
            scheduled_departure_utc=datetime(
                2025, 2, 1, 8, tzinfo=timezone.utc
            ),
        ),
        make_record(
            source=february_url,
            origin_region="North America",
            status="scheduled",
            scheduled_departure_utc=datetime(
                2025, 2, 2, 8, tzinfo=timezone.utc
            ),
        ),
    )
    yielded: list[str] = []

    def one_shot(values):
        for value in values:
            yielded.append(value.record_id)
            yield value

    result = audit_corpus(
        (
            CorpusPartition(
                _provenance(
                    "provider-a-2025-01",
                    source_url=january_url,
                    expected_record_count=2,
                ),
                one_shot(records[:2]),
            ),
            CorpusPartition(
                _provenance(
                    "provider-b-2025-02",
                    source_id="provider-b",
                    month="2025-02",
                    source_url=february_url,
                    expected_record_count=2,
                ),
                one_shot(records[2:]),
            ),
        ),
        completed_months=("2025-01", "2025-02"),
        expected_source_ids=("provider-a", "provider-b"),
        expected_origin_regions=REGIONS,
    )

    assert yielded == [record.record_id for record in records]
    assert result.corpus_binding == build_corpus_binding(records)
    assert result.corpus_binding["method"] == CORPUS_BINDING_METHOD
    assert result.corpus_binding["recordCount"] == 4

    audit = result.corpus_audit
    assert set(audit) == {
        "completedMonths",
        *CORPUS_COUNT_FIELDS,
        "regions",
        "months",
        "sources",
        "partitions",
    }
    assert audit["completedMonths"] == ["2025-01", "2025-02"]
    assert {field: audit[field] for field in CORPUS_COUNT_FIELDS} == {
        "scheduledRows": 4,
        "identityCompleteRows": 4,
        "knownOutcomeRows": 3,
        "operatedRows": 2,
        "operatedRowsWithArrivalTimes": 1,
        "arrival15DelayedRows": 1,
        "cancellationRows": 1,
    }
    assert set(audit["regions"]) == set(REGIONS)
    assert audit["regions"]["Oceania"]["scheduledRows"] == 0
    assert audit["months"]["2025-01"]["scheduledRows"] == 2
    assert audit["sources"]["provider-b"]["operatedRows"] == 1
    assert all(
        set(partition) == {
            "partitionId",
            "sourceId",
            "month",
            "sourceUrl",
            "retrievedAtUtc",
            "rawFileSha256",
            "counts",
            "regions",
        }
        for partition in audit["partitions"]
    )
    assert all(
        set(partition["regions"]) == set(REGIONS)
        for partition in audit["partitions"]
    )
    assert result.data_coverage() == {"rows": 4, "corpusAudit": audit}

    operational = result.operational_audit
    assert operational["all"]["statusRows"] == {
        "cancelled": 1,
        "diverted": 1,
        "landed": 1,
        "scheduled": 1,
    }
    assert operational["all"]["arrivalDelayThresholdRows"] == {
        "arrival15DelayedRows": 1,
        "arrival30DelayedRows": 1,
        "arrival60DelayedRows": 1,
    }
    assert operational["months"]["2025-01"]["statusRows"]["cancelled"] == 1
    assert operational["sources"]["provider-b"]["statusRows"]["diverted"] == 1
    assert operational["originRegions"]["Africa"][
        "arrivalDelayThresholdRows"
    ]["arrival15DelayedRows"] == 1

    evidence = result.observation_evidence
    assert evidence["schedule"] == {
        "eligibleRows": 4,
        "timestampPresentRows": 4,
        "missingTimestampRows": 0,
        "observedBeforeDepartureRows": 4,
        "observedByPredictionTimeRows": 4,
        "completeAtPredictionTime": True,
    }
    assert evidence["terminalOutcome"] == {
        "eligibleRows": 3,
        "timestampPresentRows": 3,
        "missingTimestampRows": 0,
        "complete": True,
    }


def test_reports_missing_and_late_observation_evidence_without_inventing_it(
    make_record,
):
    source_url = "https://records.example/evidence-2025-01.csv"
    missing = make_record(
        source=source_url,
        schedule_observed_at=None,
        outcome_observed_at=None,
        status="landed",
    )
    late = make_record(source=source_url, status="cancelled")
    late = replace(
        late,
        schedule_observed_at=late.scheduled_departure_utc - timedelta(days=1),
    )

    result = audit_corpus(
        (
            CorpusPartition(
                _provenance(
                    "evidence-2025-01",
                    source_url=source_url,
                    expected_record_count=2,
                ),
                iter((missing, late)),
            ),
        ),
        completed_months=("2025-01",),
    )

    assert result.observation_evidence["schedule"] == {
        "eligibleRows": 2,
        "timestampPresentRows": 1,
        "missingTimestampRows": 1,
        "observedBeforeDepartureRows": 1,
        "observedByPredictionTimeRows": 0,
        "completeAtPredictionTime": False,
    }
    assert result.observation_evidence["terminalOutcome"] == {
        "eligibleRows": 2,
        "timestampPresentRows": 1,
        "missingTimestampRows": 1,
        "complete": False,
    }


def test_v4_export_validator_accepts_runner_structures_without_translation(
    make_record, monkeypatch
):
    january_url = "https://records.example/global-2025-01.csv"
    february_url = "https://records.example/global-2025-02.csv"

    def monthly_records(month: int, source_url: str):
        return tuple(
            make_record(
                source=source_url,
                origin_region=region,
                scheduled_departure_utc=datetime(
                    2025, month, index + 1, 8, tzinfo=timezone.utc
                ),
            )
            for index, region in enumerate(REGIONS)
        )

    january = monthly_records(1, january_url)
    february = monthly_records(2, february_url)
    result = audit_corpus(
        (
            CorpusPartition(
                _provenance(
                    "global-2025-01",
                    source_url=january_url,
                    expected_record_count=len(january),
                ),
                iter(january),
            ),
            CorpusPartition(
                _provenance(
                    "global-2025-02",
                    month="2025-02",
                    source_url=february_url,
                    expected_record_count=len(february),
                ),
                iter(february),
            ),
        ),
        completed_months=("2025-01", "2025-02"),
        expected_source_ids=("provider-a",),
        expected_origin_regions=REGIONS,
    )

    # This test lowers only publication-scale minima. The v4 validator still
    # checks every exact field, population identity, and partition aggregation.
    monkeypatch.setattr(export, "MIN_COMPLETED_MONTHS", 2)
    monkeypatch.setattr(export, "MIN_REGION_OPERATED_LEGS", 1)
    monkeypatch.setattr(export, "MIN_REGION_ARRIVAL_15", 1)
    monkeypatch.setattr(export, "MIN_REGION_CANCELLATIONS", 0)
    export._validate_global_corpus_audit(
        result.data_coverage(),
        source_ids={"provider-a"},
        corpus_binding=result.corpus_binding,
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"ingestion_completed": False}, "completed ingestion audit"),
        ({"source_url": "http://records.example/a.csv"}, "absolute HTTPS"),
        (
            {"source_url": "https://records.example/a.csv?token=secret"},
            "without credentials, query",
        ),
        ({"month": "2025-13"}, "YYYY-MM"),
        ({"source_id": "Provider A"}, "stable lowercase"),
        ({"partition_id": "sample-partition"}, "placeholder"),
    ),
)
def test_partition_provenance_is_immutable_complete_and_export_safe(
    changes, message
):
    partition_id = changes.get("partition_id", "provider-a-2025-01")
    arguments = {key: value for key, value in changes.items() if key != "partition_id"}
    with pytest.raises(CorpusAuditError, match=message):
        _provenance(partition_id, **arguments)


def test_partition_provenance_cannot_be_mutated_after_validation():
    provenance = _provenance("provider-a-2025-01")
    with pytest.raises(FrozenInstanceError):
        provenance.month = "2025-02"


def test_fails_closed_on_partition_count_source_and_identifier_mismatches(
    make_record,
):
    source_url = "https://records.example/provider-a-2025-01.csv"
    record = make_record(source=source_url)
    with pytest.raises(CorpusAuditError, match="expected 2"):
        audit_corpus(
            (
                CorpusPartition(
                    _provenance(
                        "provider-a-2025-01",
                        source_url=source_url,
                        expected_record_count=2,
                    ),
                    iter((record,)),
                ),
            ),
            completed_months=("2025-01",),
        )

    wrong_source = make_record(source="https://records.example/other.csv")
    with pytest.raises(CorpusAuditError, match="record source"):
        audit_corpus(
            (
                CorpusPartition(
                    _provenance(
                        "provider-a-2025-01",
                        source_url=source_url,
                    ),
                    iter((wrong_source,)),
                ),
            ),
            completed_months=("2025-01",),
        )

    with pytest.raises(CorpusAuditError, match="duplicate normalized record_id"):
        audit_corpus(
            (
                CorpusPartition(
                    _provenance(
                        "provider-a-2025-01-a",
                        source_url=source_url,
                    ),
                    iter((record,)),
                ),
                CorpusPartition(
                    _provenance(
                        "provider-a-2025-01-b",
                        source_url=source_url,
                    ),
                    iter((record,)),
                ),
            ),
            completed_months=("2025-01",),
        )


def test_fails_closed_on_month_source_region_and_schema_gaps(make_record):
    source_url = "https://records.example/provider-a-2025-01.csv"
    record = make_record(source=source_url, origin_region="Africa")
    partition = CorpusPartition(
        _provenance("provider-a-2025-01", source_url=source_url),
        iter((record,)),
    )
    with pytest.raises(CorpusAuditError, match="lacks partition provenance"):
        audit_corpus(
            (partition,),
            completed_months=("2025-01", "2025-02"),
        )

    with pytest.raises(CorpusAuditError, match="expected_source_ids lacks"):
        audit_corpus(
            (
                CorpusPartition(
                    _provenance("provider-a-2025-01-x", source_url=source_url),
                    iter((record,)),
                ),
            ),
            completed_months=("2025-01",),
            expected_source_ids=("provider-a", "provider-b"),
        )

    with pytest.raises(CorpusAuditError, match="unexpected origin region"):
        audit_corpus(
            (
                CorpusPartition(
                    _provenance("provider-a-2025-01-y", source_url=source_url),
                    iter((record,)),
                ),
            ),
            completed_months=("2025-01",),
            expected_origin_regions=("Europe",),
        )

    february_record = make_record(
        source=source_url,
        scheduled_departure_utc=datetime(2025, 2, 1, 8, tzinfo=timezone.utc),
    )
    with pytest.raises(CorpusAuditError, match="record service month"):
        audit_corpus(
            (
                CorpusPartition(
                    _provenance("provider-a-2025-01-month", source_url=source_url),
                    iter((february_record,)),
                ),
            ),
            completed_months=("2025-01",),
        )

    invalid = replace(record, status="teleported")
    with pytest.raises(CorpusAuditError, match="invalid normalized record"):
        audit_corpus(
            (
                CorpusPartition(
                    _provenance("provider-a-2025-01-z", source_url=source_url),
                    iter((invalid,)),
                ),
            ),
            completed_months=("2025-01",),
        )


def test_completed_months_must_be_explicit_chronological_and_consecutive():
    with pytest.raises(CorpusAuditError, match="chronological and consecutive"):
        audit_corpus((), completed_months=("2025-01", "2025-03"))
    with pytest.raises(CorpusAuditError, match="unique"):
        audit_corpus((), completed_months=("2025-01", "2025-01"))
