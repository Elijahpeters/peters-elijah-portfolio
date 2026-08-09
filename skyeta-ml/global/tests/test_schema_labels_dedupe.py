from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from itertools import permutations

import pytest

from ..dedupe import DedupeConflict, deduplicate_records
from ..labels import derive_labels
from ..schema import GlobalFlightRecord, SchemaError


def test_schema_normalizes_codes_and_requires_aware_utc(make_record):
    record = make_record(
        operating_carrier="sk",
        origin="los",
        destination="lhr",
        origin_country="ng",
    )
    assert record.operating_carrier == "SK"
    assert record.origin == "LOS"
    assert record.scheduled_departure_utc.utcoffset() == timedelta(0)
    assert record.schedule_observed_at is not None
    assert record.schedule_revision == "synthetic-v1"
    assert record.outcome_observed_at is not None

    row = record.as_dict()
    row["scheduled_departure_utc"] = record.scheduled_departure_utc.replace(
        tzinfo=None
    )
    with pytest.raises(SchemaError, match="timezone offset"):
        GlobalFlightRecord.from_mapping(row)

    row = record.as_dict()
    row["service_date"] = record.service_date + timedelta(days=1)
    with pytest.raises(SchemaError, match="origin-local"):
        GlobalFlightRecord.from_mapping(row)

    legacy_adapter_row = record.as_dict()
    for field in (
        "schedule_observed_at",
        "schedule_revision",
        "outcome_observed_at",
    ):
        legacy_adapter_row.pop(field)
    legacy = GlobalFlightRecord.from_mapping(legacy_adapter_row)
    assert legacy.schedule_observed_at is None
    assert legacy.schedule_revision is None
    assert legacy.outcome_observed_at is None


def test_schema_preserves_explicit_icao_only_airport_identity(make_record):
    record = make_record(origin=" sbeG ", destination="SBGL")

    assert record.origin == "SBEG"
    assert record.destination == "SBGL"
    assert record.origin_code_scheme == "icao"
    assert record.destination_code_scheme == "icao"

    iata_record = make_record()
    assert iata_record.origin_code_scheme == "iata"
    assert iata_record.destination_code_scheme == "iata"

    row = record.as_dict()
    row["origin"] = "ABCDE"
    with pytest.raises(SchemaError, match="invalid IATA/ICAO code"):
        GlobalFlightRecord.from_mapping(row)


def test_labels_keep_delay_and_disruption_populations_separate(make_record):
    delayed = make_record()
    delayed_labels = derive_labels(delayed)
    assert delayed_labels.arrival_delay_minutes == 20
    assert delayed_labels.arrival_15 is True
    assert delayed_labels.arrival_30 is False
    assert delayed_labels.cancelled is False
    assert delayed_labels.disrupted is False

    cancelled = make_record(status="cancelled")
    cancelled_labels = derive_labels(cancelled)
    assert cancelled_labels.arrival_15 is None
    assert cancelled_labels.arrival_30 is None
    assert cancelled_labels.arrival_60 is None
    assert cancelled_labels.cancelled is True
    assert cancelled_labels.disrupted is True

    diverted = make_record(status="diverted")
    diverted_labels = derive_labels(diverted)
    assert diverted_labels.arrival_15 is None
    assert diverted_labels.cancelled is False
    assert diverted_labels.disrupted is True


def test_codeshares_dedupe_on_operating_identity_not_marketing_code(make_record):
    first = make_record(marketing_carrier="AA", marketing_flight_number="1")
    second = replace(
        first,
        record_id="codeshare-two",
        marketing_carrier="BA",
        marketing_flight_number="22",
    )
    result = deduplicate_records([first, second])
    assert result.input_rows == 2
    assert result.duplicate_rows == 1
    assert len(result.records) == 1
    assert result.records[0].operating_carrier == "SK"


def test_conflicting_terminal_outcomes_are_rejected(make_record):
    landed = make_record()
    cancelled = replace(
        landed,
        record_id="conflict",
        status="cancelled",
        actual_departure_utc=None,
        actual_arrival_utc=None,
    )
    with pytest.raises(DedupeConflict, match="conflicting terminal outcomes"):
        deduplicate_records([landed, cancelled])

    corrected_time = replace(
        landed,
        record_id="conflicting-time",
        actual_arrival_utc=landed.actual_arrival_utc + timedelta(minutes=1),
    )
    with pytest.raises(DedupeConflict, match="actual_arrival_utc"):
        deduplicate_records([landed, corrected_time])

    conflicting_schedule = replace(
        landed,
        record_id="conflicting-scheduled-arrival",
        scheduled_arrival_utc=landed.scheduled_arrival_utc + timedelta(minutes=30),
    )
    with pytest.raises(DedupeConflict, match="scheduled_arrival_utc"):
        deduplicate_records([landed, conflicting_schedule])


def test_physical_leg_key_is_stable_across_schedule_revisions(make_record):
    initial = make_record()
    revised = replace(
        initial,
        record_id="revision-two",
        scheduled_departure_utc=initial.scheduled_departure_utc
        + timedelta(minutes=45),
        scheduled_arrival_utc=initial.scheduled_arrival_utc
        + timedelta(minutes=45),
        schedule_revision="synthetic-v2",
        schedule_observed_at=initial.scheduled_departure_utc - timedelta(days=8),
    )

    assert initial.canonical_key != revised.canonical_key
    assert initial.physical_leg_key == revised.physical_leg_key


def test_dedupe_selects_latest_revision_visible_at_prediction_horizon(make_record):
    initial = make_record(
        record_id="revision-one",
        schedule_revision="synthetic-v1",
    )
    eligible_revision = replace(
        initial,
        record_id="revision-two",
        scheduled_departure_utc=initial.scheduled_departure_utc
        + timedelta(minutes=30),
        scheduled_arrival_utc=initial.scheduled_arrival_utc
        + timedelta(minutes=30),
        schedule_revision="synthetic-v2",
        schedule_observed_at=initial.scheduled_departure_utc - timedelta(days=8),
    )

    result = deduplicate_records([initial, eligible_revision])

    assert result.duplicate_rows == 1
    assert result.records == (eligible_revision,)


def test_post_horizon_revision_cannot_hide_eligible_revision(make_record):
    initial = make_record(
        record_id="initial-eligible-revision",
        schedule_revision="synthetic-v1",
    )
    latest_eligible = replace(
        initial,
        record_id="latest-eligible-revision",
        scheduled_departure_utc=initial.scheduled_departure_utc
        + timedelta(minutes=15),
        scheduled_arrival_utc=initial.scheduled_arrival_utc
        + timedelta(minutes=15),
        schedule_revision="synthetic-v2",
        schedule_observed_at=initial.scheduled_departure_utc - timedelta(days=8),
    )
    post_horizon = replace(
        initial,
        record_id="post-horizon-richer-revision",
        scheduled_departure_utc=initial.scheduled_departure_utc
        + timedelta(minutes=30),
        scheduled_arrival_utc=initial.scheduled_arrival_utc
        + timedelta(minutes=30),
        schedule_revision="synthetic-v3",
        schedule_observed_at=initial.scheduled_departure_utc - timedelta(days=6),
    )

    for rows in permutations((post_horizon, initial, latest_eligible)):
        result = deduplicate_records(rows)
        assert result.records == (latest_eligible,)


def test_dedupe_revision_selection_uses_configured_horizon(make_record):
    initial = make_record(
        record_id="seven-day-revision",
        schedule_revision="synthetic-v1",
    )
    later_revision = replace(
        initial,
        record_id="three-day-revision",
        scheduled_departure_utc=initial.scheduled_departure_utc
        + timedelta(minutes=30),
        scheduled_arrival_utc=initial.scheduled_arrival_utc
        + timedelta(minutes=30),
        schedule_revision="synthetic-v2",
        schedule_observed_at=initial.scheduled_departure_utc - timedelta(days=5),
    )

    seven_day = deduplicate_records([initial, later_revision])
    three_day = deduplicate_records(
        [initial, later_revision], prediction_horizon=timedelta(days=3)
    )

    assert seven_day.records == (initial,)
    assert three_day.records == (later_revision,)


def test_dedupe_rejects_ambiguous_reuse_and_observation_conflicts(make_record):
    initial = replace(make_record(), schedule_revision=None)
    ambiguous_reuse = replace(
        initial,
        record_id="ambiguous-same-day-reuse",
        scheduled_departure_utc=initial.scheduled_departure_utc
        + timedelta(hours=6),
        scheduled_arrival_utc=initial.scheduled_arrival_utc
        + timedelta(hours=6),
    )
    with pytest.raises(DedupeConflict, match="scheduled_departure_utc"):
        deduplicate_records([initial, ambiguous_reuse])

    named_revision = replace(initial, schedule_revision="synthetic-v1")
    conflicting_schedule_observation = replace(
        named_revision,
        record_id="conflicting-schedule-observation",
        schedule_observed_at=named_revision.schedule_observed_at
        + timedelta(minutes=1),
    )
    with pytest.raises(DedupeConflict, match="schedule_observed_at"):
        deduplicate_records([named_revision, conflicting_schedule_observation])

    conflicting_outcome_observation = replace(
        named_revision,
        record_id="conflicting-outcome-observation",
        outcome_observed_at=named_revision.outcome_observed_at
        + timedelta(minutes=1),
    )
    with pytest.raises(DedupeConflict, match="outcome_observed_at"):
        deduplicate_records([named_revision, conflicting_outcome_observation])
