"""Focused tests for the fail-closed SIROS T-7 to VRA outcome join."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

import pytest

from ..anac_siros_vra_join import (
    AnacSirosVraJoinError,
    AnacVraOutcomeCandidate,
    AnacVraOutcomeObservationProvenance,
    join_siros_schedules_to_vra_outcomes,
)
from ..schema import GlobalFlightRecord
from ..sources.anac import (
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
from ..sources.anac_siros import (
    ANAC_SIROS_SERIES_HEADERS,
    ANAC_SIROS_SOURCE_ID,
    AnacSirosServiceObservation,
)


UTC = timezone.utc
DEPARTURE = datetime(2025, 1, 15, 2, 0, tzinfo=UTC)
ARRIVAL = datetime(2025, 1, 15, 10, 35, tzinfo=UTC)
VRA_SOURCE = build_vra_url(2025, 1)
VRA_DIGEST = hashlib.sha256(b"reviewed VRA bytes").hexdigest()
EVIDENCE_DIGEST = hashlib.sha256(b"reviewed publication evidence").hexdigest()

ORIGIN = AirportMetadata(
    icao="SBGL",
    iata="GIG",
    latitude=-22.809999,
    longitude=-43.250557,
    country_code="BR",
    region_code="South America",
    timezone_name="America/Sao_Paulo",
)
DESTINATION = AirportMetadata(
    icao="KMIA",
    iata="MIA",
    latitude=25.7959,
    longitude=-80.287,
    country_code="US",
    region_code="Northern America",
    timezone_name="America/New_York",
)


def schedule(
    *,
    siros_id: str = "AAL-0000000000031095703",
    observed_at: datetime = datetime(2025, 1, 1, 7, 26, 25, tzinfo=UTC),
    departure: datetime = DEPARTURE,
    arrival: datetime = ARRIVAL,
    series_seed: str = "series-1",
) -> AnacSirosServiceObservation:
    stage = 1
    return AnacSirosServiceObservation(
        siros_id=siros_id,
        stage_revision_key=(
            f"{ANAC_SIROS_SOURCE_ID}:{siros_id}:stage:{stage}"
        ),
        series_facts_sha256=hashlib.sha256(series_seed.encode()).hexdigest(),
        service_date=departure.date(),
        operating_carrier="AAL",
        operating_flight_number="0904",
        stage_number=stage,
        origin_icao="SBGL",
        destination_icao="KMIA",
        scheduled_departure_utc=departure,
        scheduled_arrival_utc=arrival,
        schedule_observed_at_utc=observed_at,
        snapshot_date=observed_at.date(),
        registration_raw="26/09/2024 11:06:09",
        source_url=(
            "https://siros.anac.gov.br/siros/registros/futuro/serie/2025/"
            f"futuro_{observed_at.date().isoformat()}.csv"
        ),
        raw_file_sha256=hashlib.sha256(
            f"snapshot-{observed_at.isoformat()}".encode()
        ).hexdigest(),
        source_values=("",) * len(ANAC_SIROS_SERIES_HEADERS),
    )


def file_provenance(*, digest: str = VRA_DIGEST) -> AnacFileProvenance:
    return AnacFileProvenance(
        source_id=ANAC_SOURCE_ID,
        source_provider=ANAC_PUBLISHER,
        product_name=ANAC_DATASET_NAME,
        source_url=VRA_SOURCE,
        documentation_url="https://www.anac.gov.br/example",
        year=2025,
        month=1,
        file_path="C:/ignored/VRA_2025_01.csv",
        filename="VRA_2025_01.csv",
        retrieved_at_utc=datetime(2026, 8, 9, 12, tzinfo=UTC),
        raw_file_sha256=digest,
        raw_bytes=123456,
        reporting_timezone=ANAC_REPORTING_TIMEZONE,
        delimiter=ANAC_DELIMITER,
        encoding=ANAC_ENCODING,
    )


def evidence(
    *,
    observed_at: datetime = datetime(2025, 2, 1, 12, tzinfo=UTC),
    retrieved_at: datetime = datetime(2026, 8, 9, 12, tzinfo=UTC),
    basis: str = "official_publication_record",
    use_scope: str = "point_in_time_target_history",
    raw_digest: str = VRA_DIGEST,
) -> AnacVraOutcomeObservationProvenance:
    return AnacVraOutcomeObservationProvenance(
        vra_source_url=VRA_SOURCE,
        raw_file_sha256=raw_digest,
        outcome_observed_at_utc=observed_at,
        basis=basis,  # type: ignore[arg-type]
        evidence_url="https://www.anac.gov.br/reviewed-publication-record",
        evidence_timestamp_raw="2025-02-01T12:00:00Z",
        evidence_retrieved_at_utc=retrieved_at,
        evidence_sha256=EVIDENCE_DIGEST,
        use_scope=use_scope,  # type: ignore[arg-type]
    )


def outcome(
    *,
    record_id: str = "anac-vra-row-1",
    departure: datetime = DEPARTURE,
    arrival: datetime = ARRIVAL,
    status: str = "landed",
    observation: AnacVraOutcomeObservationProvenance | None = None,
) -> AnacVraOutcomeCandidate:
    actual_departure = (
        departure + timedelta(minutes=8) if status in {"landed", "diverted"} else None
    )
    actual_arrival = arrival + timedelta(minutes=26) if status == "landed" else None
    service_date = (departure - timedelta(hours=3)).date()
    record = GlobalFlightRecord.from_mapping(
        {
            "record_id": record_id,
            "service_date": service_date,
            "operating_carrier": "AAL",
            "operating_flight_number": "0904",
            "marketing_carrier": None,
            "marketing_flight_number": None,
            "origin": ORIGIN.training_code,
            "destination": DESTINATION.training_code,
            "scheduled_departure_utc": departure,
            "scheduled_arrival_utc": arrival,
            "schedule_observed_at": None,
            "schedule_revision": None,
            "actual_departure_utc": actual_departure,
            "actual_arrival_utc": actual_arrival,
            "outcome_observed_at": None,
            "status": status,
            "origin_latitude": ORIGIN.latitude,
            "origin_longitude": ORIGIN.longitude,
            "destination_latitude": DESTINATION.latitude,
            "destination_longitude": DESTINATION.longitude,
            "origin_country": ORIGIN.country_code,
            "destination_country": DESTINATION.country_code,
            "origin_region": ORIGIN.region_code,
            "destination_region": DESTINATION.region_code,
            "origin_timezone_offset_minutes": -180,
            "destination_timezone_offset_minutes": -300,
            "aircraft_family": "B788",
            "source": VRA_SOURCE,
        }
    )
    return AnacVraOutcomeCandidate(
        record=record,
        origin_airport=ORIGIN,
        destination_airport=DESTINATION,
        file_provenance=file_provenance(),
        observation_provenance=observation or evidence(),
    )


def decisions(result, *, side: str, disposition: str):
    return [
        item
        for item in result.audit.decisions
        if item.side == side and item.disposition == disposition
    ]


def test_exact_one_to_one_join_produces_evidence_complete_global_record() -> None:
    planned = schedule()
    terminal = outcome()

    result = join_siros_schedules_to_vra_outcomes([planned], [terminal])

    assert len(result.matches) == 1
    assert result.audit.matched_pair_count == 1
    assert result.audit.point_in_time_history_match_count == 1
    assert result.audit.retrospective_holdout_only_match_count == 0
    assert result.matches[0].to_dict()["match_method"] == (
        "exact_carrier_flight_icao_route_departure_arrival_utc"
    )
    joined = result.records[0]
    assert joined.schedule_observed_at == planned.schedule_observed_at_utc
    assert joined.schedule_revision == planned.stage_revision_key
    assert joined.outcome_observed_at == evidence().outcome_observed_at_utc
    assert joined.status == "landed"
    assert joined.source == VRA_SOURCE
    assert result.audit.facts_sha256 == result.audit.to_dict()["facts_sha256"]


def test_same_composite_uses_latest_visible_snapshot_only() -> None:
    older = schedule(
        observed_at=datetime(2024, 12, 31, 12, tzinfo=UTC),
        series_seed="old",
    )
    latest = schedule(
        observed_at=datetime(2025, 1, 1, 7, 26, 25, tzinfo=UTC),
        series_seed="new",
    )

    result = join_siros_schedules_to_vra_outcomes([latest, older], [outcome()])

    assert len(result.matches) == 1
    assert result.matches[0].schedule.schedule_observation_key == (
        latest.schedule_observation_key
    )
    rejected = decisions(result, side="schedule", disposition="rejected")
    assert len(rejected) == 1
    assert rejected[0].reason_code == "superseded_same_composite_identity"


def test_distinct_siros_ids_are_not_inferred_as_replacement_lineage() -> None:
    first = schedule(siros_id="AAL-SIROS-A", series_seed="a")
    second = schedule(siros_id="AAL-SIROS-B", series_seed="b")

    result = join_siros_schedules_to_vra_outcomes([first, second], [outcome()])

    assert not result.matches
    assert result.audit.disposition_count("schedule", "ambiguous") == 2
    assert result.audit.disposition_count("outcome", "ambiguous") == 1
    assert len(result.audit.ambiguities) == 1
    assert result.audit.ambiguities[0].reason_code == (
        "multiple_distinct_siros_ids_for_exact_key"
    )


@pytest.mark.parametrize(
    ("departure_delta", "arrival_delta", "reason"),
    [
        (timedelta(minutes=1), timedelta(minutes=1), "scheduled_departure_utc_mismatch"),
        (timedelta(0), timedelta(minutes=1), "scheduled_arrival_utc_mismatch"),
    ],
)
def test_time_mismatches_are_audited_without_fuzzy_fallback(
    departure_delta: timedelta,
    arrival_delta: timedelta,
    reason: str,
) -> None:
    terminal = outcome(
        departure=DEPARTURE + departure_delta,
        arrival=ARRIVAL + arrival_delta,
    )

    result = join_siros_schedules_to_vra_outcomes([schedule()], [terminal])

    assert not result.matches
    assert decisions(result, side="schedule", disposition="unmatched")[0].reason_code == reason
    assert decisions(result, side="outcome", disposition="unmatched")[0].reason_code == reason


def test_duplicate_vra_exact_key_is_ambiguous_not_arbitrarily_selected() -> None:
    result = join_siros_schedules_to_vra_outcomes(
        [schedule()],
        [outcome(record_id="vra-a"), outcome(record_id="vra-b")],
    )

    assert not result.matches
    assert result.audit.disposition_count("schedule", "ambiguous") == 1
    assert result.audit.disposition_count("outcome", "ambiguous") == 2
    assert result.audit.ambiguities[0].reason_code == "multiple_vra_rows_for_exact_key"


def test_non_t7_schedule_and_preknown_outcome_are_explicit_rejections() -> None:
    late_schedule = schedule(
        observed_at=DEPARTURE - timedelta(days=6, hours=23)
    )
    result = join_siros_schedules_to_vra_outcomes([late_schedule], [outcome()])
    rejected_schedule = decisions(result, side="schedule", disposition="rejected")
    assert rejected_schedule[0].reason_code == (
        "schedule_not_observed_by_prediction_horizon"
    )

    known = evidence(
        observed_at=DEPARTURE - timedelta(days=8),
        retrieved_at=datetime(2026, 8, 9, 12, tzinfo=UTC),
    )
    result = join_siros_schedules_to_vra_outcomes(
        [schedule()], [outcome(observation=known)]
    )
    rejected_outcome = decisions(result, side="outcome", disposition="rejected")
    assert rejected_outcome[0].reason_code == "outcome_observed_by_prediction_time"


def test_direct_retrieval_is_holdout_only_and_cannot_feed_target_history() -> None:
    retrieved = datetime(2026, 8, 9, 12, tzinfo=UTC)
    direct = evidence(
        observed_at=retrieved,
        retrieved_at=retrieved,
        basis="direct_retrieval_capture",
        use_scope="retrospective_holdout_only",
    )
    result = join_siros_schedules_to_vra_outcomes(
        [schedule()], [outcome(observation=direct)]
    )

    assert result.audit.retrospective_holdout_only_match_count == 1
    with pytest.raises(AnacSirosVraJoinError, match="target history"):
        _ = result.records
    assert result.retrospective_holdout_records[0].status == "landed"

    with pytest.raises(AnacSirosVraJoinError, match="target-history"):
        evidence(
            observed_at=retrieved,
            retrieved_at=retrieved,
            basis="direct_retrieval_capture",
            use_scope="point_in_time_target_history",
        )


def test_outcome_evidence_must_bind_to_the_exact_vra_file_bytes() -> None:
    wrong_digest = hashlib.sha256(b"different VRA bytes").hexdigest()
    with pytest.raises(AnacSirosVraJoinError, match="hash does not match"):
        AnacVraOutcomeCandidate(
            record=outcome().record,
            origin_airport=ORIGIN,
            destination_airport=DESTINATION,
            file_provenance=file_provenance(),
            observation_provenance=evidence(raw_digest=wrong_digest),
        )


def test_join_audit_is_stable_under_input_reordering() -> None:
    schedules = [
        schedule(siros_id="AAL-SIROS-A", series_seed="a"),
        schedule(siros_id="AAL-SIROS-B", series_seed="b"),
    ]
    outcomes = [outcome(record_id="vra-b"), outcome(record_id="vra-a")]

    forward = join_siros_schedules_to_vra_outcomes(schedules, outcomes)
    reverse = join_siros_schedules_to_vra_outcomes(
        reversed(schedules), reversed(outcomes)
    )

    assert forward.audit.facts_sha256 == reverse.audit.facts_sha256
    assert forward.to_dict() == reverse.to_dict()
