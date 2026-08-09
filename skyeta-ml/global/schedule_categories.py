"""Training-only categorical features derived from the published schedule.

This module deliberately has no access to outcomes or derived labels.  A
vocabulary is fitted once on the training partition and then held fixed for
tune, calibration, and test.  Unseen and deliberately truncated values share
an explicit unknown column, so evaluation categories can never expand the
feature contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Callable, Iterable

import numpy as np

from .schema import GlobalFlightRecord


SCHEDULE_CATEGORY_FEATURE_PREFIX = "schedule_category_"
_MISSING_CATEGORY = "__MISSING__"


@dataclass(frozen=True, slots=True)
class ScheduleCategoricalFeatureConfig:
    """Bounded defaults for schedule-category features.

    Each cap limits both vocabulary size and matrix width.  Categories are
    ranked by descending training count and then lexical value, making ties
    deterministic regardless of input order.
    """

    enabled: bool = True
    max_operating_carriers: int = 64
    max_origins: int = 128
    max_destinations: int = 128
    max_aircraft_families: int = 64
    max_routes: int = 128
    include_fit_frequency_features: bool = True

    def __post_init__(self) -> None:
        caps = (
            self.max_operating_carriers,
            self.max_origins,
            self.max_destinations,
            self.max_aircraft_families,
            self.max_routes,
        )
        if any(isinstance(cap, bool) or not isinstance(cap, int) for cap in caps):
            raise ValueError("schedule category caps must be integers")
        if self.enabled and any(cap <= 0 for cap in caps):
            raise ValueError("enabled schedule category caps must be positive")
        if any(cap < 0 for cap in caps):
            raise ValueError("schedule category caps cannot be negative")

    @property
    def caps(self) -> tuple[tuple[str, int], ...]:
        return (
            ("operating_carrier", self.max_operating_carriers),
            ("origin", self.max_origins),
            ("destination", self.max_destinations),
            ("aircraft_family", self.max_aircraft_families),
            ("route", self.max_routes),
        )


@dataclass(frozen=True, slots=True)
class ScheduleCategoricalVocabulary:
    """One deterministic, capped vocabulary fitted on training schedules."""

    field: str
    categories: tuple[str, ...]
    counts: tuple[int, ...]
    fit_row_count: int

    def __post_init__(self) -> None:
        if not self.field or self.field.strip() != self.field:
            raise ValueError("schedule category field must be a trimmed name")
        if len(self.categories) != len(self.counts):
            raise ValueError("schedule category values and counts must align")
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("schedule category vocabulary must be unique")
        if any(not value for value in self.categories):
            raise ValueError("schedule category values cannot be empty")
        if any(
            isinstance(count, bool) or not isinstance(count, int) or count <= 0
            for count in self.counts
        ):
            raise ValueError("schedule category counts must be positive integers")
        if self.fit_row_count <= 0:
            raise ValueError("schedule category fit row count must be positive")
        expected = tuple(
            sorted(
                zip(self.categories, self.counts, strict=True),
                key=lambda item: (-item[1], item[0]),
            )
        )
        if tuple(zip(self.categories, self.counts, strict=True)) != expected:
            raise ValueError("schedule category vocabulary order is not deterministic")


@dataclass(frozen=True, slots=True)
class ScheduleCategoricalSnapshot:
    """Immutable training vocabulary and its reproducibility digest."""

    config: ScheduleCategoricalFeatureConfig
    vocabularies: tuple[ScheduleCategoricalVocabulary, ...]
    feature_names: tuple[str, ...]
    digest: str

    def __post_init__(self) -> None:
        expected_fields = (
            tuple(field for field, _ in self.config.caps) if self.config.enabled else ()
        )
        observed_fields = tuple(vocabulary.field for vocabulary in self.vocabularies)
        if observed_fields != expected_fields:
            raise ValueError("schedule category snapshot fields are misaligned")
        if len(set(self.feature_names)) != len(self.feature_names):
            raise ValueError("schedule category feature names must be unique")
        if any(
            not name.startswith(SCHEDULE_CATEGORY_FEATURE_PREFIX)
            for name in self.feature_names
        ):
            raise ValueError("schedule category feature prefix is invalid")
        if self.digest != _snapshot_digest(
            self.config, self.vocabularies, self.feature_names
        ):
            raise ValueError("schedule category snapshot digest is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "config": asdict(self.config),
            "vocabularies": [
                {
                    "field": vocabulary.field,
                    "categories": list(vocabulary.categories),
                    "counts": list(vocabulary.counts),
                    "fit_row_count": vocabulary.fit_row_count,
                }
                for vocabulary in self.vocabularies
            ],
            "feature_names": list(self.feature_names),
            "digest": self.digest,
        }


def _normalize_category(value: str | None) -> str:
    if value is None:
        return _MISSING_CATEGORY
    normalized = unicodedata.normalize("NFKC", value)
    normalized = " ".join(normalized.strip().upper().split())
    return normalized or _MISSING_CATEGORY


def _category_value(record: GlobalFlightRecord, field: str) -> str:
    extractors: dict[str, Callable[[GlobalFlightRecord], str | None]] = {
        "operating_carrier": lambda row: row.operating_carrier,
        "origin": lambda row: row.origin,
        "destination": lambda row: row.destination,
        "aircraft_family": lambda row: row.aircraft_family,
        "route": lambda row: row.route_key,
    }
    try:
        return _normalize_category(extractors[field](record))
    except KeyError as error:
        raise ValueError(f"unsupported schedule category field: {field}") from error


def _feature_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_") or "value"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"{slug[:48]}_{digest}"


def _feature_names(
    config: ScheduleCategoricalFeatureConfig,
    vocabularies: tuple[ScheduleCategoricalVocabulary, ...],
) -> tuple[str, ...]:
    if not config.enabled:
        return ()
    names: list[str] = []
    for vocabulary in vocabularies:
        prefix = f"{SCHEDULE_CATEGORY_FEATURE_PREFIX}{vocabulary.field}"
        names.extend(
            f"{prefix}__value_{_feature_token(category)}"
            for category in vocabulary.categories
        )
        names.append(f"{prefix}__unknown")
        if config.include_fit_frequency_features:
            names.extend((f"{prefix}__fit_log_count", f"{prefix}__fit_frequency"))
    return tuple(names)


def _snapshot_digest(
    config: ScheduleCategoricalFeatureConfig,
    vocabularies: tuple[ScheduleCategoricalVocabulary, ...],
    feature_names: tuple[str, ...],
) -> str:
    document = {
        "schema": "skyeta-schedule-categories-v1",
        "config": asdict(config),
        "vocabularies": [
            {
                "field": vocabulary.field,
                "categories": list(vocabulary.categories),
                "counts": list(vocabulary.counts),
                "fit_row_count": vocabulary.fit_row_count,
            }
            for vocabulary in vocabularies
        ],
        "feature_names": list(feature_names),
    }
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class TrainingOnlyScheduleCategoricalTransformer:
    """Fit schedule vocabularies on train and reuse them without mutation."""

    def __init__(
        self,
        config: ScheduleCategoricalFeatureConfig | None = None,
    ) -> None:
        self.config = config or ScheduleCategoricalFeatureConfig()

    def fit(
        self,
        records: Iterable[GlobalFlightRecord],
    ) -> ScheduleCategoricalSnapshot:
        rows = tuple(records)
        if not rows:
            raise ValueError("schedule categorical fitting requires training rows")
        vocabularies: list[ScheduleCategoricalVocabulary] = []
        if self.config.enabled:
            for field, cap in self.config.caps:
                counts = Counter(_category_value(record, field) for record in rows)
                selected = tuple(
                    sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:cap]
                )
                vocabularies.append(
                    ScheduleCategoricalVocabulary(
                        field=field,
                        categories=tuple(value for value, _ in selected),
                        counts=tuple(count for _, count in selected),
                        fit_row_count=len(rows),
                    )
                )
        vocabulary_tuple = tuple(vocabularies)
        names = _feature_names(self.config, vocabulary_tuple)
        return ScheduleCategoricalSnapshot(
            config=self.config,
            vocabularies=vocabulary_tuple,
            feature_names=names,
            digest=_snapshot_digest(self.config, vocabulary_tuple, names),
        )

    def transform(
        self,
        records: Iterable[GlobalFlightRecord],
        snapshot: ScheduleCategoricalSnapshot,
    ) -> np.ndarray:
        """Transform schedules using only the supplied fitted snapshot."""

        if snapshot.config != self.config:
            raise ValueError("schedule category config differs from fitted snapshot")
        rows = tuple(records)
        matrix = np.zeros((len(rows), len(snapshot.feature_names)), dtype="float32")
        if not snapshot.config.enabled:
            return matrix

        offset = 0
        for vocabulary in snapshot.vocabularies:
            category_indices = {
                category: index for index, category in enumerate(vocabulary.categories)
            }
            category_counts = {
                category: count
                for category, count in zip(
                    vocabulary.categories, vocabulary.counts, strict=True
                )
            }
            unknown_index = len(vocabulary.categories)
            count_index = unknown_index + 1
            frequency_index = count_index + 1
            width = unknown_index + 1
            if snapshot.config.include_fit_frequency_features:
                width += 2

            for row_index, record in enumerate(rows):
                category = _category_value(record, vocabulary.field)
                local_index = category_indices.get(category, unknown_index)
                matrix[row_index, offset + local_index] = 1.0
                if snapshot.config.include_fit_frequency_features:
                    count = category_counts.get(category, 0)
                    matrix[row_index, offset + count_index] = math.log1p(count)
                    matrix[row_index, offset + frequency_index] = (
                        count / vocabulary.fit_row_count
                    )
            offset += width

        if offset != matrix.shape[1]:
            raise AssertionError("schedule category matrix width is misaligned")
        if not np.isfinite(matrix).all():
            raise AssertionError("schedule category matrix contains non-finite values")
        return matrix
