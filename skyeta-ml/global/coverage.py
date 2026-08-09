"""Cold-start coverage tiers derived from frozen history support."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, Mapping

from .encodings import EncodingSnapshot, hierarchy_keys
from .schema import GlobalFlightRecord


CoverageTier = Literal["established", "partial", "cold_start"]
ColdStartAction = Literal["refuse", "global_backoff"]


@dataclass(frozen=True, slots=True)
class CoveragePolicy:
    established_sample: int = 50
    partial_sample: int = 10
    cold_start_action: ColdStartAction = "refuse"

    def __post_init__(self) -> None:
        if (
            isinstance(self.established_sample, bool)
            or not isinstance(self.established_sample, int)
            or isinstance(self.partial_sample, bool)
            or not isinstance(self.partial_sample, int)
        ):
            raise ValueError("coverage thresholds must be integers")
        if self.established_sample <= self.partial_sample or self.partial_sample < 1:
            raise ValueError(
                "coverage thresholds must satisfy established > partial >= 1"
            )
        if self.cold_start_action not in {"refuse", "global_backoff"}:
            raise ValueError("unsupported cold-start action")

    def to_serializable(self) -> dict[str, int | str]:
        return {
            "establishedArrivalSample": self.established_sample,
            "partialArrivalSample": self.partial_sample,
            "coldStartAction": self.cold_start_action,
        }

    @classmethod
    def from_serializable(cls, value: object) -> "CoveragePolicy":
        if not isinstance(value, Mapping):
            raise ValueError("coverage policy must be an object")
        expected_fields = {
            "establishedArrivalSample",
            "partialArrivalSample",
            "coldStartAction",
        }
        if set(value) != expected_fields:
            raise ValueError("coverage policy fields are incomplete or unsupported")
        try:
            established = value["establishedArrivalSample"]
            partial = value["partialArrivalSample"]
            action = value["coldStartAction"]
        except KeyError as error:
            raise ValueError("coverage policy is incomplete") from error
        if (
            isinstance(established, bool)
            or not isinstance(established, int)
            or isinstance(partial, bool)
            or not isinstance(partial, int)
            or not isinstance(action, str)
        ):
            raise ValueError("coverage policy fields have invalid types")
        return cls(established, partial, action)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class CoverageAssessment:
    tier: CoverageTier
    strongest_level: str | None
    strongest_arrival_sample: int
    fallbacks: tuple[str, ...]


def assess_coverage(
    record: GlobalFlightRecord,
    snapshot: EncodingSnapshot,
    *,
    policy: CoveragePolicy = CoveragePolicy(),
    established_sample: int | None = None,
    partial_sample: int | None = None,
) -> CoverageAssessment:
    """Explain whether a score is identity-backed or geographic cold start."""

    if snapshot.prediction_horizon_seconds < 0:
        raise ValueError("history snapshot prediction horizon must not be negative")
    if snapshot.as_of is not None:
        prediction_at = record.scheduled_departure_utc - timedelta(
            seconds=snapshot.prediction_horizon_seconds
        )
        if prediction_at < snapshot.as_of:
            raise ValueError(
                f"history snapshot is newer than row {record.record_id!r} "
                "prediction timestamp"
            )

    established_sample = (
        policy.established_sample if established_sample is None else established_sample
    )
    partial_sample = policy.partial_sample if partial_sample is None else partial_sample
    if established_sample <= partial_sample or partial_sample < 1:
        raise ValueError("coverage thresholds must satisfy established > partial >= 1")
    keys = hierarchy_keys(record)
    supports = {
        level: snapshot.support(level, key, "arrival_15")
        for level, key in keys.items()
    }
    partial_levels: list[str] = []
    if supports["flight_route"] >= established_sample:
        tier: CoverageTier = "established"
        selected = "flight_route"
        selected_sample = supports[selected]
    else:
        partial_levels = [
            level
            for level in ("carrier_route", "route", "carrier")
            if supports[level] >= partial_sample
        ]
        if min(supports["origin"], supports["destination"]) >= partial_sample:
            partial_levels.extend(("origin", "destination"))
    if supports["flight_route"] < established_sample and partial_levels:
        tier = "partial"
        selected = max(
            partial_levels,
            key=lambda level: (supports[level], -list(supports).index(level)),
        )
        selected_sample = supports[selected]
    elif supports["flight_route"] < established_sample:
        tier = "cold_start"
        selected = None
        selected_sample = 0
    fallbacks = tuple(
        level for level in ("flight_route", "carrier_route", "route", "carrier")
        if supports[level] == 0
    )
    return CoverageAssessment(
        tier=tier,
        strongest_level=selected,
        strongest_arrival_sample=selected_sample,
        fallbacks=fallbacks,
    )
