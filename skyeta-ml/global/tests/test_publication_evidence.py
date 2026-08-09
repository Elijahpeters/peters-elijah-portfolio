from __future__ import annotations

import copy
from hashlib import sha256

import pytest

from ..export import (
    CORPUS_BINDING_METHOD,
    CORPUS_COUNT_FIELDS,
    ArtifactError,
    _validate_global_corpus_audit,
)


REGIONS = (
    "Africa",
    "Asia",
    "Europe",
    "North America",
    "South America",
    "Oceania",
)


def _add(left: dict[str, int], right: dict[str, int]) -> None:
    for field in CORPUS_COUNT_FIELDS:
        left[field] += right[field]


def _evidence_contract():
    months = [
        f"{year}-{month:02d}"
        for year in (2024, 2025)
        for month in range(1, 13)
    ]
    per_region = {
        "scheduledRows": 120_000,
        "identityCompleteRows": 118_000,
        "knownOutcomeRows": 116_000,
        "operatedRows": 100_000,
        "operatedRowsWithArrivalTimes": 90_000,
        "arrival15DelayedRows": 5_000,
        "cancellationRows": 1_000,
    }
    regions = {region: dict(per_region) for region in REGIONS}
    top = {field: per_region[field] * len(REGIONS) for field in CORPUS_COUNT_FIELDS}
    month_rollups: dict[str, dict[str, int]] = {}
    partitions = []
    for index, month in enumerate(months):
        partition_regions: dict[str, dict[str, int]] = {}
        partition_counts = {field: 0 for field in CORPUS_COUNT_FIELDS}
        for region in REGIONS:
            values = {
                field: per_region[field] // len(months)
                + int(index < per_region[field] % len(months))
                for field in CORPUS_COUNT_FIELDS
            }
            partition_regions[region] = values
            _add(partition_counts, values)
        month_rollups[month] = dict(partition_counts)
        partitions.append(
            {
                "partitionId": f"provider-records-{month}",
                "sourceId": "provider-records",
                "month": month,
                "sourceUrl": f"https://example.invalid/provider/{month}.csv",
                "retrievedAtUtc": "2026-08-09T00:00:00Z",
                "rawFileSha256": sha256(f"raw-{month}".encode()).hexdigest(),
                "counts": partition_counts,
                "regions": partition_regions,
            }
        )
    audit = {
        "completedMonths": months,
        **top,
        "regions": regions,
        "months": month_rollups,
        "sources": {"provider-records": dict(top)},
        "partitions": partitions,
    }
    coverage = {"rows": top["scheduledRows"], "corpusAudit": audit}
    binding = {
        "method": CORPUS_BINDING_METHOD,
        "recordCount": top["scheduledRows"],
        "recordIdsSha256": sha256(b"normalized-record-identifiers").hexdigest(),
    }
    return coverage, binding


def test_partition_provenance_aggregates_exactly_by_month_source_and_region():
    coverage, binding = _evidence_contract()
    _validate_global_corpus_audit(
        coverage,
        source_ids={"provider-records"},
        corpus_binding=binding,
    )

    bad_month = copy.deepcopy(coverage)
    bad_month["corpusAudit"]["months"]["2024-01"]["scheduledRows"] += 1
    with pytest.raises(ArtifactError, match="global month counts"):
        _validate_global_corpus_audit(
            bad_month,
            source_ids={"provider-records"},
            corpus_binding=binding,
        )

    bad_source = copy.deepcopy(coverage)
    bad_source["corpusAudit"]["sources"]["provider-records"][
        "cancellationRows"
    ] += 1
    with pytest.raises(ArtifactError, match="global source counts"):
        _validate_global_corpus_audit(
            bad_source,
            source_ids={"provider-records"},
            corpus_binding=binding,
        )

    bad_partition_region = copy.deepcopy(coverage)
    bad_partition_region["corpusAudit"]["partitions"][0]["regions"]["Africa"][
        "scheduledRows"
    ] += 1
    with pytest.raises(ArtifactError, match="partition 0 region counts"):
        _validate_global_corpus_audit(
            bad_partition_region,
            source_ids={"provider-records"},
            corpus_binding=binding,
        )

    query_bearing_url = copy.deepcopy(coverage)
    query_bearing_url["corpusAudit"]["partitions"][0]["sourceUrl"] += (
        "?token=redacted"
    )
    with pytest.raises(ArtifactError, match="without credentials, query"):
        _validate_global_corpus_audit(
            query_bearing_url,
            source_ids={"provider-records"},
            corpus_binding=binding,
        )


def test_corpus_binding_prevents_pasted_rollups_from_relabelling_a_small_corpus():
    coverage, binding = _evidence_contract()
    small_binding = dict(binding, recordCount=72)
    with pytest.raises(ArtifactError, match="bound normalized record count"):
        _validate_global_corpus_audit(
            coverage,
            source_ids={"provider-records"},
            corpus_binding=small_binding,
        )
