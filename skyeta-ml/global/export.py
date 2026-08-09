"""Versioned server artifact schema and Python parity fixtures.

The helpers can build candidate or synthetic-test artifacts, but publication is
fail-closed until an untouched-test and global-coverage release gate are
explicitly recorded.  This prevents scaffolding from being mistaken for a
trained worldwide model.
"""

from __future__ import annotations

import json
import hashlib
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from urllib.parse import urlparse

from .calibration import PlattCalibrator, calibrate_head_scores
from .coverage import CoveragePolicy, CoverageTier, assess_coverage
from .encodings import (
    HIERARCHY_LEVELS,
    Aggregate,
    EncodingSnapshot,
    PastOnlyHierarchicalEncoder,
    validate_schedule_at_prediction,
)
from .features import assemble_feature_row
from .labels import TARGET_NAMES
from .schema import GlobalFlightRecord


FORMAT_VERSION = 4
ARTIFACT_SCOPE = "global_schedule_only"
ARTIFACT_POPULATION = "scheduled commercial flight legs with valid route metadata"
MODEL_HEADS = (
    "arrival_15",
    "arrival_30",
    "arrival_60",
    "cancelled",
    "disrupted",
)
ARTIFACT_STATUSES = frozenset({"candidate", "validated", "synthetic_test_only"})
PROBABILITY_ORDERING = (
    "arrival_60 <= arrival_30 <= arrival_15 and cancelled <= disrupted "
    "after isotonic projection"
)
REQUIRED_WORLD_REGIONS = (
    "Africa",
    "Asia",
    "Europe",
    "North America",
    "South America",
    "Oceania",
)
MIN_COMPLETED_MONTHS = 24
MIN_REGION_OPERATED_LEGS = 100_000
MIN_REGION_ARRIVAL_15 = 5_000
MIN_REGION_CANCELLATIONS = 1_000
_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_PLACEHOLDER = re.compile(
    r"(?:\btest(?:ing)?\b|\bsynthetic\b|\bfixture\b|\bnot[\s_-]*real\b|"
    r"\bfake\b|\bplaceholder\b|\bdemo\b|\bsample\b|\btodo\b|\btbd\b|"
    r"\bunknown\b|\bunverified\b)",
    re.IGNORECASE,
)
CORPUS_BINDING_METHOD = "sorted_record_ids_sha256_v1"
CORPUS_COUNT_FIELDS = (
    "scheduledRows",
    "identityCompleteRows",
    "knownOutcomeRows",
    "operatedRows",
    "operatedRowsWithArrivalTimes",
    "arrival15DelayedRows",
    "cancellationRows",
)
SLICE_DIMENSIONS = (
    "region",
    "country",
    "carrier",
    "airportSize",
    "routeFrequency",
    "season",
)
RIGHTS_STATUSES = frozenset(
    {
        "approved_for_training_and_derived_publication",
        "review_pending",
        "restricted",
        "synthetic_test_only",
    }
)
PUBLISHABLE_RIGHTS_STATUS = "approved_for_training_and_derived_publication"
PUBLISHABLE_EVIDENCE_TYPES = frozenset(
    {"public_license", "written_permission", "contract", "terms_of_service"}
)


class ArtifactError(ValueError):
    """Raised when a model artifact violates the server scoring contract."""


def _tree_value(root: Mapping, features: Sequence[float]) -> float:
    node = root
    for _ in range(512):
        leaf = node.get("leaf_value")
        if isinstance(leaf, (int, float)) and math.isfinite(float(leaf)):
            return float(leaf)
        try:
            feature_index = int(node["split_feature"])
            threshold = float(node["threshold"])
            left = node["left_child"]
            right = node["right_child"]
        except (KeyError, TypeError, ValueError) as error:
            raise ArtifactError("booster contains a malformed tree node") from error
        if not 0 <= feature_index < len(features) or not math.isfinite(threshold):
            raise ArtifactError("booster tree references an invalid feature or threshold")
        value = float(features[feature_index])
        if not math.isfinite(value):
            go_left = bool(node.get("default_left", False))
        else:
            decision = node.get("decision_type", "<=")
            if decision == "<=":
                go_left = value <= threshold
            elif decision == "<":
                go_left = value < threshold
            elif decision == ">":
                go_left = value > threshold
            elif decision == ">=":
                go_left = value >= threshold
            else:
                raise ArtifactError(f"unsupported LightGBM decision type: {decision}")
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            raise ArtifactError("booster tree children must be objects")
        node = left if go_left else right
    raise ArtifactError("booster tree exceeded the traversal depth limit")


def booster_raw_score(booster: Mapping, features: Sequence[float]) -> float:
    tree_info = booster.get("tree_info")
    if not isinstance(tree_info, list) or not tree_info:
        raise ArtifactError("booster must contain at least one tree")
    total = 0.0
    for tree in tree_info:
        if not isinstance(tree, Mapping) or not isinstance(
            tree.get("tree_structure"), Mapping
        ):
            raise ArtifactError("booster tree is missing its structure")
        total += _tree_value(tree["tree_structure"], features)
    return total


def _predict_probabilities_unchecked(
    boosters: Mapping[str, Mapping],
    calibrators: Mapping[str, PlattCalibrator],
    features: Sequence[float],
) -> dict[str, float]:
    if set(boosters) != set(MODEL_HEADS) or set(calibrators) != set(MODEL_HEADS):
        raise ArtifactError("artifact must define all five SkyETA model heads")
    raw_scores = {
        head: booster_raw_score(boosters[head], features) for head in MODEL_HEADS
    }
    return calibrate_head_scores(raw_scores, calibrators)


def predict_probabilities(
    boosters: Mapping[str, Mapping],
    calibrators: Mapping[str, PlattCalibrator],
    features: Sequence[float],
    *,
    coverage_tier: CoverageTier,
    coverage_policy: CoveragePolicy = CoveragePolicy(),
) -> dict[str, float]:
    """Score a feature row while enforcing the declared cold-start policy."""

    if coverage_tier not in {"established", "partial", "cold_start"}:
        raise ArtifactError("a valid coverage tier is required for scoring")
    if (
        coverage_tier == "cold_start"
        and coverage_policy.cold_start_action == "refuse"
    ):
        raise ArtifactError("cold-start policy refuses this prediction")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in features
    ):
        raise ArtifactError("scoring features must be finite numeric values")
    return _predict_probabilities_unchecked(boosters, calibrators, features)


def build_parity_cases(
    boosters: Mapping[str, Mapping],
    calibrators: Mapping[str, PlattCalibrator],
    feature_rows: Iterable[Sequence[float]],
    *,
    expected_probabilities: Iterable[Mapping[str, float]] | None = None,
    tolerance: float = 1e-12,
) -> list[dict]:
    rows = tuple(feature_rows)
    expected_rows = (
        None if expected_probabilities is None else tuple(expected_probabilities)
    )
    if expected_rows is not None and len(expected_rows) != len(rows):
        raise ArtifactError("native parity outputs must align with feature rows")
    cases: list[dict] = []
    for index, row in enumerate(rows):
        features = [float(value) for value in row]
        if not features or any(not math.isfinite(value) for value in features):
            raise ArtifactError("parity features must be non-empty and finite")
        observed = _predict_probabilities_unchecked(boosters, calibrators, features)
        if expected_rows is None:
            expected = observed
        else:
            if set(expected_rows[index]) != set(MODEL_HEADS):
                raise ArtifactError("native parity probabilities are invalid")
            try:
                expected = {
                    head: float(expected_rows[index][head]) for head in MODEL_HEADS
                }
            except (TypeError, ValueError) as error:
                raise ArtifactError("native parity probabilities are invalid") from error
            if any(
                not math.isfinite(value) or not 0 <= value <= 1
                for value in expected.values()
            ):
                raise ArtifactError("native parity probabilities are invalid")
            maximum = max(abs(observed[head] - expected[head]) for head in MODEL_HEADS)
            if maximum > tolerance:
                raise ArtifactError(
                    f"native LightGBM parity error {maximum:.12g} exceeds "
                    f"{tolerance:.12g}"
                )
        cases.append(
            {
                "features": features,
                "probabilities": expected,
            }
        )
    if not cases:
        raise ArtifactError("at least one parity case is required")
    return cases


def build_corpus_binding(records: Iterable[GlobalFlightRecord]) -> dict[str, object]:
    """Bind an artifact to the normalized records used to prepare its splits.

    Only stable record identifiers enter the digest.  No provider row, secret,
    passenger information, or licensed payload is copied into the artifact.
    """

    identifiers: list[str] = []
    for record in records:
        if not isinstance(record, GlobalFlightRecord):
            raise ArtifactError("corpus binding records must satisfy the global schema")
        identifier = record.record_id.strip()
        if not identifier:
            raise ArtifactError("corpus binding record identifiers must be non-empty")
        identifiers.append(identifier)
    if not identifiers:
        raise ArtifactError("corpus binding requires at least one normalized record")
    if len(identifiers) != len(set(identifiers)):
        raise ArtifactError("corpus binding record identifiers must be unique")
    payload = "\n".join(sorted(identifiers)).encode("utf-8")
    return {
        "method": CORPUS_BINDING_METHOD,
        "recordCount": len(identifiers),
        "recordIdsSha256": hashlib.sha256(payload).hexdigest(),
    }


def build_artifact(
    *,
    feature_names: Sequence[str],
    boosters: Mapping[str, Mapping],
    calibrators: Mapping[str, PlattCalibrator],
    history_snapshot: EncodingSnapshot,
    model_card: Mapping,
    parity_feature_rows: Iterable[Sequence[float]],
    native_parity_probabilities: Iterable[Mapping[str, float]] | None = None,
    coverage_policy: CoveragePolicy = CoveragePolicy(),
    artifact_status: str = "candidate",
    corpus_binding: Mapping[str, object] | None = None,
) -> dict:
    """Build a JSON-compatible v4 artifact without asserting publication."""

    if artifact_status not in ARTIFACT_STATUSES:
        raise ArtifactError(f"unsupported artifact status: {artifact_status}")
    names = tuple(feature_names)
    if not names or len(names) != len(set(names)) or any(not name for name in names):
        raise ArtifactError("feature names must be non-empty and unique")
    if set(boosters) != set(MODEL_HEADS) or set(calibrators) != set(MODEL_HEADS):
        raise ArtifactError("all five model heads are required")
    for head, booster in boosters.items():
        _validate_booster_structure(booster, len(names), head)
        # Exercise one complete scoring path in addition to validating every
        # branch structurally.
        booster_raw_score(booster, [0.0] * len(names))
    card = dict(model_card)
    if not isinstance(card.get("dataSources"), list) or not card["dataSources"]:
        raise ArtifactError("model card must list its data sources")
    if artifact_status != "synthetic_test_only" and native_parity_probabilities is None:
        raise ArtifactError(
            "candidate and validated artifacts require native LightGBM parity outputs"
        )
    parity_cases = build_parity_cases(
        boosters,
        calibrators,
        parity_feature_rows,
        expected_probabilities=native_parity_probabilities,
    )
    if any(len(case["features"]) != len(names) for case in parity_cases):
        raise ArtifactError("parity rows must match the feature contract")

    artifact = {
        "formatVersion": FORMAT_VERSION,
        "artifactStatus": artifact_status,
        "scope": ARTIFACT_SCOPE,
        "population": ARTIFACT_POPULATION,
        "featureNames": list(names),
        "heads": {
            "arrival_15": "arrival at least 15 minutes late among landed legs",
            "arrival_30": "arrival at least 30 minutes late among landed legs",
            "arrival_60": "arrival at least 60 minutes late among landed legs",
            "cancelled": "scheduled leg cancelled",
            "disrupted": "scheduled leg cancelled or diverted",
        },
        "boosters": {head: boosters[head] for head in MODEL_HEADS},
        "calibration": {
            head: calibrators[head].as_dict() for head in MODEL_HEADS
        },
        "history": history_snapshot.to_serializable(),
        "coveragePolicy": coverage_policy.to_serializable(),
        "probabilityOrdering": PROBABILITY_ORDERING,
        "paritySource": (
            "native_lightgbm"
            if native_parity_probabilities is not None
            else "python_reference"
        ),
        "parityCases": parity_cases,
        "modelCard": card,
    }
    if corpus_binding is not None:
        artifact["corpusBinding"] = dict(corpus_binding)
    validate_artifact(artifact)
    return artifact


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ArtifactError(f"{name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ArtifactError(f"{name} must be finite")
    return parsed


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ArtifactError(f"{name} must be a non-negative integer")
    return value


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactError(f"{name} must be a non-empty string")
    return value.strip()


def _aware_datetime_text(value: object, name: str) -> datetime:
    text = _required_text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ArtifactError(f"{name} must be an ISO datetime") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ArtifactError(f"{name} must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def _https_url(value: object, name: str) -> str:
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
        raise ArtifactError(
            f"{name} must be an absolute HTTPS URL without credentials, "
            "query, or fragment"
        )
    return text


def _sha256(value: object, name: str) -> str:
    text = _required_text(value, name).lower()
    if _SHA256.fullmatch(text) is None:
        raise ArtifactError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _contains_placeholder(value: str) -> bool:
    return _PLACEHOLDER.search(value) is not None


def _validate_corpus_binding(value: object, *, required: bool) -> Mapping | None:
    if value is None and not required:
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "method",
        "recordCount",
        "recordIdsSha256",
    }:
        raise ArtifactError(
            "candidate and validated artifacts require an exact corpus binding"
        )
    if value.get("method") != CORPUS_BINDING_METHOD:
        raise ArtifactError("corpus binding method is invalid")
    if _nonnegative_int(value.get("recordCount"), "corpus binding recordCount") < 1:
        raise ArtifactError("corpus binding recordCount must be positive")
    _sha256(value.get("recordIdsSha256"), "corpus binding recordIdsSha256")
    return value


def _validate_data_sources(
    value: object, *, require_publishable: bool
) -> dict[str, Mapping]:
    if not isinstance(value, list) or not value:
        raise ArtifactError("model card must list structured data sources")
    indexed: dict[str, Mapping] = {}
    source_fields = {"sourceId", "name", "rightsStatus", "rightsEvidence"}
    evidence_fields = {"type", "reference", "url", "reviewedAtUtc", "sha256"}
    for index, source in enumerate(value):
        name = f"data source {index}"
        if not isinstance(source, Mapping) or set(source) != source_fields:
            raise ArtifactError(f"{name} fields are incomplete or unsupported")
        source_id = _required_text(source.get("sourceId"), f"{name} sourceId")
        if _SOURCE_ID.fullmatch(source_id) is None:
            raise ArtifactError(
                f"{name} sourceId must be a lowercase stable identifier"
            )
        if source_id in indexed:
            raise ArtifactError("data source identifiers must be unique")
        display_name = _required_text(source.get("name"), f"{name} name")
        rights_status = _required_text(
            source.get("rightsStatus"), f"{name} rightsStatus"
        )
        if rights_status not in RIGHTS_STATUSES:
            raise ArtifactError(f"{name} rightsStatus is unsupported")
        evidence = source.get("rightsEvidence")
        if not isinstance(evidence, Mapping) or set(evidence) != evidence_fields:
            raise ArtifactError(f"{name} rightsEvidence fields are incomplete")
        evidence_type = _required_text(evidence.get("type"), f"{name} evidence type")
        reference = _required_text(
            evidence.get("reference"), f"{name} evidence reference"
        )
        evidence_url = _required_text(evidence.get("url"), f"{name} evidence URL")
        _aware_datetime_text(
            evidence.get("reviewedAtUtc"), f"{name} evidence reviewedAtUtc"
        )
        _sha256(evidence.get("sha256"), f"{name} evidence sha256")
        if require_publishable:
            if rights_status != PUBLISHABLE_RIGHTS_STATUS:
                raise ArtifactError(
                    f"{name} is not approved for training and derived publication"
                )
            if evidence_type not in PUBLISHABLE_EVIDENCE_TYPES:
                raise ArtifactError(f"{name} rights evidence type is not publishable")
            _https_url(evidence_url, f"{name} evidence URL")
            for field, text in (
                ("sourceId", source_id),
                ("name", display_name),
                ("reference", reference),
                ("url", evidence_url),
            ):
                if _contains_placeholder(text):
                    raise ArtifactError(
                        f"{name} {field} contains placeholder or synthetic evidence"
                    )
        indexed[source_id] = source
    return indexed


def _validate_probability_map(value: object, name: str) -> None:
    if not isinstance(value, Mapping) or set(value) != set(MODEL_HEADS):
        raise ArtifactError(f"{name} must define all five model heads")
    probabilities = {
        head: _finite_number(value[head], f"{name}.{head}") for head in MODEL_HEADS
    }
    if any(not 0 <= probability <= 1 for probability in probabilities.values()):
        raise ArtifactError(f"{name} probabilities must lie between 0 and 1")
    if not (
        probabilities["arrival_60"]
        <= probabilities["arrival_30"]
        <= probabilities["arrival_15"]
    ):
        raise ArtifactError(f"{name} violates cumulative arrival ordering")
    if probabilities["cancelled"] > probabilities["disrupted"]:
        raise ArtifactError(f"{name} violates cancellation/disruption ordering")


def _validate_tree_structure(root: object, feature_count: int) -> int:
    if not isinstance(root, Mapping):
        raise ArtifactError("booster tree root must be an object")
    stack: list[tuple[Mapping, int]] = [(root, 0)]
    seen: set[int] = set()
    leaf_count = 0
    while stack:
        node, depth = stack.pop()
        if depth >= 512:
            raise ArtifactError("booster tree exceeded the traversal depth limit")
        identity = id(node)
        if identity in seen:
            raise ArtifactError("booster tree contains a cycle or shared node")
        seen.add(identity)
        if "leaf_value" in node:
            _finite_number(node["leaf_value"], "booster leaf value")
            if any(
                field in node
                for field in (
                    "split_feature",
                    "threshold",
                    "decision_type",
                    "default_left",
                    "missing_type",
                    "left_child",
                    "right_child",
                )
            ):
                raise ArtifactError("booster leaf cannot contain split children")
            leaf_count += 1
            continue
        try:
            raw_feature_index = node["split_feature"]
            raw_threshold = node["threshold"]
            if (
                isinstance(raw_feature_index, bool)
                or not isinstance(raw_feature_index, int)
                or isinstance(raw_threshold, bool)
                or not isinstance(raw_threshold, (int, float))
            ):
                raise ArtifactError(
                    "booster tree references an invalid feature or threshold"
                )
            feature_index = raw_feature_index
            threshold = float(raw_threshold)
            decision = node.get("decision_type", "<=")
            left = node["left_child"]
            right = node["right_child"]
        except (KeyError, TypeError, ValueError) as error:
            raise ArtifactError("booster contains a malformed tree node") from error
        if not 0 <= feature_index < feature_count or not math.isfinite(threshold):
            raise ArtifactError("booster tree references an invalid feature or threshold")
        if decision not in {"<=", "<", ">", ">="}:
            raise ArtifactError(f"unsupported LightGBM decision type: {decision}")
        default_left = node.get("default_left", False)
        if not isinstance(default_left, bool):
            raise ArtifactError("booster default_left must be boolean")
        missing_type = node.get("missing_type", "None")
        # The scorer's feature contract is finite numeric input and does not
        # implement LightGBM's optional zero-as-missing traversal semantics.
        if missing_type not in {"None", "NaN"}:
            raise ArtifactError("booster missing_type is unsupported")
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            raise ArtifactError("booster tree children must be objects")
        stack.append((right, depth + 1))
        stack.append((left, depth + 1))
    return leaf_count


def _validate_booster_structure(
    booster: object,
    feature_count: int,
    head: str,
) -> None:
    """Validate every supported LightGBM field and every reachable branch."""

    if not isinstance(booster, Mapping):
        raise ArtifactError(f"{head} booster must be an object")
    objective = booster.get("objective")
    if not isinstance(objective, str) or re.match(r"^binary(?:\s|$)", objective) is None:
        raise ArtifactError(f"{head} booster must use a binary objective")
    if booster.get("average_output") is not False:
        raise ArtifactError(f"{head} booster average_output must be false")

    optional_unit_fields = ("num_class", "num_tree_per_iteration")
    for field in optional_unit_fields:
        if field in booster and (
            isinstance(booster[field], bool)
            or not isinstance(booster[field], int)
            or booster[field] != 1
        ):
            raise ArtifactError(f"{head} booster {field} must equal 1")
    if "max_feature_idx" in booster and (
        isinstance(booster["max_feature_idx"], bool)
        or not isinstance(booster["max_feature_idx"], int)
        or booster["max_feature_idx"] != feature_count - 1
    ):
        raise ArtifactError(f"{head} booster feature count does not match the contract")
    if "feature_names" in booster:
        feature_names = booster["feature_names"]
        if (
            not isinstance(feature_names, list)
            or len(feature_names) != feature_count
            or any(not isinstance(name, str) or not name for name in feature_names)
        ):
            raise ArtifactError(
                f"{head} booster feature names do not match the contract"
            )

    tree_info = booster.get("tree_info")
    if not isinstance(tree_info, list) or not tree_info:
        raise ArtifactError(f"{head} booster must contain at least one tree")
    for index, tree in enumerate(tree_info):
        if not isinstance(tree, Mapping):
            raise ArtifactError(f"{head} booster tree must be an object")
        if "tree_index" in tree and (
            isinstance(tree["tree_index"], bool)
            or not isinstance(tree["tree_index"], int)
            or tree["tree_index"] != index
        ):
            raise ArtifactError(f"{head} booster tree index is invalid")
        if "num_cat" in tree and (
            isinstance(tree["num_cat"], bool)
            or not isinstance(tree["num_cat"], int)
            or tree["num_cat"] != 0
        ):
            raise ArtifactError(f"{head} booster categorical trees are unsupported")
        if "shrinkage" in tree and _finite_number(
            tree["shrinkage"], f"{head} booster tree shrinkage"
        ) <= 0:
            raise ArtifactError(f"{head} booster tree shrinkage must be positive")
        leaves = _validate_tree_structure(tree.get("tree_structure"), feature_count)
        if "num_leaves" in tree and (
            isinstance(tree["num_leaves"], bool)
            or not isinstance(tree["num_leaves"], int)
            or tree["num_leaves"] != leaves
        ):
            raise ArtifactError(f"{head} booster leaf count is invalid")


def _deserialize_calibrators(value: object) -> dict[str, PlattCalibrator]:
    if not isinstance(value, Mapping) or set(value) != set(MODEL_HEADS):
        raise ArtifactError("calibration must define all five model heads")
    calibrators: dict[str, PlattCalibrator] = {}
    for head in MODEL_HEADS:
        entry = value[head]
        if not isinstance(entry, Mapping):
            raise ArtifactError(f"{head} calibration must be an object")
        if (
            entry.get("method") != "platt_sigmoid"
            or entry.get("input") != "lightgbm_raw_score"
            or entry.get("fittedOn") != "dedicated_calibration_split"
        ):
            raise ArtifactError(f"{head} calibration metadata is invalid")
        try:
            fitted_rows = _nonnegative_int(
                entry["fittedRows"], f"{head} calibration fitted rows"
            )
            if fitted_rows < 1:
                raise ArtifactError(f"{head} calibration fitted rows must be positive")
            calibrators[head] = PlattCalibrator(
                slope=_finite_number(entry["slope"], f"{head} calibration slope"),
                intercept=_finite_number(
                    entry["intercept"], f"{head} calibration intercept"
                ),
                fitted_rows=fitted_rows,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ArtifactError(f"{head} calibration parameters are invalid") from error
    return calibrators


def _validate_history(value: object, *, require_as_of: bool) -> None:
    if not isinstance(value, Mapping):
        raise ArtifactError("history snapshot must be an object")
    as_of = value.get("asOf")
    if as_of is None:
        if require_as_of:
            raise ArtifactError("candidate and validated history require an asOf cutoff")
    elif not isinstance(as_of, str):
        raise ArtifactError("history asOf must be an ISO timestamp")
    else:
        try:
            parsed_as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except ValueError as error:
            raise ArtifactError("history asOf must be an ISO timestamp") from error
        if parsed_as_of.tzinfo is None or parsed_as_of.utcoffset() is None:
            raise ArtifactError("history asOf must be timezone-aware")

    _nonnegative_int(
        value.get("predictionHorizonSeconds"), "history prediction horizon"
    )
    priors = value.get("priors")
    if not isinstance(priors, Mapping) or set(priors) != set(TARGET_NAMES):
        raise ArtifactError("history priors must define every target")
    if any(
        not 0 < _finite_number(priors[target], f"history prior {target}") < 1
        for target in TARGET_NAMES
    ):
        raise ArtifactError("history priors must lie strictly between 0 and 1")
    strengths = value.get("priorStrength")
    if not isinstance(strengths, Mapping) or set(strengths) != set(HIERARCHY_LEVELS):
        raise ArtifactError("history prior strengths must define every hierarchy level")
    if any(
        _finite_number(strengths[level], f"history prior strength {level}") <= 0
        for level in HIERARCHY_LEVELS
    ):
        raise ArtifactError("history prior strengths must be positive")

    schedule_counts = value.get("scheduleCounts")
    if not isinstance(schedule_counts, Mapping) or set(schedule_counts) != set(
        HIERARCHY_LEVELS
    ):
        raise ArtifactError("history schedule counts are incomplete")
    validated_schedule_counts: dict[str, dict[str, int]] = {}
    for level in HIERARCHY_LEVELS:
        counts = schedule_counts[level]
        if not isinstance(counts, Mapping) or any(
            not isinstance(key, str)
            or not key
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
            for key, count in counts.items()
        ):
            raise ArtifactError(f"history schedule counts for {level} are invalid")
        validated_schedule_counts[level] = dict(counts)
    schedule_totals = {
        level: sum(counts.values())
        for level, counts in validated_schedule_counts.items()
    }
    if len(set(schedule_totals.values())) != 1:
        raise ArtifactError("history schedule counts disagree across hierarchy levels")
    scheduled_rows = next(iter(schedule_totals.values()))

    targets = value.get("targets")
    if not isinstance(targets, Mapping) or set(targets) != set(TARGET_NAMES):
        raise ArtifactError("history targets are incomplete")
    validated_targets: dict[
        str, dict[str, dict[str, tuple[int, int]]]
    ] = {}
    for target in TARGET_NAMES:
        levels = targets[target]
        if not isinstance(levels, Mapping) or set(levels) != set(HIERARCHY_LEVELS):
            raise ArtifactError(f"history target {target} levels are incomplete")
        validated_targets[target] = {}
        for level in HIERARCHY_LEVELS:
            aggregates = levels[level]
            if not isinstance(aggregates, Mapping):
                raise ArtifactError(f"history target {target}/{level} is invalid")
            validated_targets[target][level] = {}
            for key, pair in aggregates.items():
                if (
                    not isinstance(key, str)
                    or not key
                    or not isinstance(pair, (list, tuple))
                    or len(pair) != 2
                ):
                    raise ArtifactError(f"history target {target}/{level} is invalid")
                count = _nonnegative_int(pair[0], "history aggregate count")
                positives = _nonnegative_int(pair[1], "history aggregate positives")
                if positives > count:
                    raise ArtifactError("history positives cannot exceed count")
                if (
                    key not in validated_schedule_counts[level]
                    or count > validated_schedule_counts[level][key]
                ):
                    raise ArtifactError(
                        "history target counts cannot exceed schedule support"
                    )
                validated_targets[target][level][key] = (count, positives)

    global_targets = value.get("globalTargets")
    if not isinstance(global_targets, Mapping) or set(global_targets) != set(
        TARGET_NAMES
    ):
        raise ArtifactError("history global targets are incomplete")
    validated_global_targets: dict[str, tuple[int, int]] = {}
    for target in TARGET_NAMES:
        pair = global_targets[target]
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ArtifactError(f"history global target {target} is invalid")
        count = _nonnegative_int(pair[0], "history global count")
        positives = _nonnegative_int(pair[1], "history global positives")
        if positives > count:
            raise ArtifactError("history global positives cannot exceed count")
        if count > scheduled_rows:
            raise ArtifactError("history global target count exceeds scheduled rows")
        validated_global_targets[target] = (count, positives)
        for level in HIERARCHY_LEVELS:
            aggregate_count = sum(
                aggregate[0]
                for aggregate in validated_targets[target][level].values()
            )
            aggregate_positives = sum(
                aggregate[1]
                for aggregate in validated_targets[target][level].values()
            )
            if (aggregate_count, aggregate_positives) != (count, positives):
                raise ArtifactError(
                    f"history target {target} disagrees across hierarchy levels"
                )

    arrival_counts = {
        validated_global_targets[target][0]
        for target in ("arrival_15", "arrival_30", "arrival_60")
    }
    if len(arrival_counts) != 1:
        raise ArtifactError("history arrival target populations must match")
    if not (
        validated_global_targets["arrival_60"][1]
        <= validated_global_targets["arrival_30"][1]
        <= validated_global_targets["arrival_15"][1]
    ):
        raise ArtifactError("history arrival positives violate cumulative ordering")
    if (
        validated_global_targets["cancelled"][0]
        != validated_global_targets["disrupted"][0]
        or validated_global_targets["cancelled"][1]
        > validated_global_targets["disrupted"][1]
    ):
        raise ArtifactError("history cancellation/disruption aggregates are inconsistent")

    for level in HIERARCHY_LEVELS:
        arrival_keys = set().union(
            *(
                validated_targets[target][level]
                for target in ("arrival_15", "arrival_30", "arrival_60")
            )
        )
        for key in arrival_keys:
            arrival = [
                validated_targets[target][level].get(key, (0, 0))
                for target in ("arrival_15", "arrival_30", "arrival_60")
            ]
            if len({pair[0] for pair in arrival}) != 1 or not (
                arrival[2][1] <= arrival[1][1] <= arrival[0][1]
            ):
                raise ArtifactError(
                    "history per-key arrival aggregates are inconsistent"
                )
        disruption_keys = set(validated_targets["cancelled"][level]) | set(
            validated_targets["disrupted"][level]
        )
        for key in disruption_keys:
            cancelled = validated_targets["cancelled"][level].get(key, (0, 0))
            disrupted = validated_targets["disrupted"][level].get(key, (0, 0))
            if cancelled[0] != disrupted[0] or cancelled[1] > disrupted[1]:
                raise ArtifactError(
                    "history per-key cancellation/disruption aggregates are inconsistent"
                )


def validate_artifact(artifact: Mapping) -> None:
    """Fully validate a serialized scoring artifact, including every tree path."""

    if not isinstance(artifact, Mapping):
        raise ArtifactError("artifact must be an object")
    if artifact.get("formatVersion") != FORMAT_VERSION:
        raise ArtifactError("only the current v4 artifact is supported")
    status = artifact.get("artifactStatus")
    if status not in ARTIFACT_STATUSES:
        raise ArtifactError("artifact status is invalid")
    if (
        artifact.get("scope") != ARTIFACT_SCOPE
        or artifact.get("population") != ARTIFACT_POPULATION
    ):
        raise ArtifactError("artifact scope and population are invalid")
    if artifact.get("probabilityOrdering") != PROBABILITY_ORDERING:
        raise ArtifactError("artifact probability ordering contract is invalid")

    names = artifact.get("featureNames")
    if (
        not isinstance(names, list)
        or not names
        or any(not isinstance(name, str) or not name for name in names)
        or len(names) != len(set(names))
    ):
        raise ArtifactError("feature names must be non-empty and unique")
    heads = artifact.get("heads")
    if not isinstance(heads, Mapping) or set(heads) != set(MODEL_HEADS) or any(
        not isinstance(heads[head], str) or not heads[head] for head in MODEL_HEADS
    ):
        raise ArtifactError("artifact heads are incomplete")

    boosters = artifact.get("boosters")
    if not isinstance(boosters, Mapping) or set(boosters) != set(MODEL_HEADS):
        raise ArtifactError("boosters must define all five model heads")
    for head in MODEL_HEADS:
        _validate_booster_structure(boosters[head], len(names), head)

    _deserialize_calibrators(artifact.get("calibration"))
    _validate_history(
        artifact.get("history"), require_as_of=status in {"candidate", "validated"}
    )
    try:
        CoveragePolicy.from_serializable(artifact.get("coveragePolicy"))
    except ValueError as error:
        raise ArtifactError(str(error)) from error

    source = artifact.get("paritySource")
    if source not in {"native_lightgbm", "python_reference"}:
        raise ArtifactError("artifact parity source is invalid")
    if status in {"candidate", "validated"} and source != "native_lightgbm":
        raise ArtifactError("candidate and validated artifacts require native parity")
    cases = artifact.get("parityCases")
    if not isinstance(cases, list) or not cases:
        raise ArtifactError("artifact is missing parity cases")
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise ArtifactError("parity cases must be objects")
        features = case.get("features")
        if (
            not isinstance(features, list)
            or len(features) != len(names)
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                for value in features
            )
        ):
            raise ArtifactError("parity rows must match the finite feature contract")
        _validate_probability_map(
            case.get("probabilities"), f"parity case {index}"
        )

    corpus_binding = _validate_corpus_binding(
        artifact.get("corpusBinding"),
        required=status in {"candidate", "validated"},
    )

    card = artifact.get("modelCard")
    if not isinstance(card, Mapping):
        raise ArtifactError("artifact is missing its model card")
    data_sources = _validate_data_sources(
        card.get("dataSources"), require_publishable=status == "validated"
    )
    evaluation = card.get("evaluation")
    coverage = card.get("dataCoverage")
    if not isinstance(evaluation, Mapping) or not isinstance(coverage, Mapping):
        raise ArtifactError("model card evaluation and data coverage are required")
    if not isinstance(evaluation.get("untouchedTest"), bool):
        raise ArtifactError("model card untouchedTest flag must be boolean")
    if not isinstance(coverage.get("globalReleaseGatePassed"), bool):
        raise ArtifactError("model card global release gate flag must be boolean")
    if evaluation["untouchedTest"]:
        test_metrics = _validate_untouched_test_metrics(
            evaluation.get("testMetrics")
        )
        _validate_slice_evaluation(evaluation, test_metrics)
    if status == "validated":
        assert corpus_binding is not None
        _validate_global_corpus_audit(
            coverage,
            source_ids=set(data_sources),
            corpus_binding=corpus_binding,
        )
    verify_parity_cases(artifact)


def _deserialize_history_snapshot(value: Mapping) -> EncodingSnapshot:
    as_of_text = value.get("asOf")
    as_of = (
        None
        if as_of_text is None
        else datetime.fromisoformat(as_of_text.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    )
    return EncodingSnapshot(
        schedule_counts={
            level: dict(value["scheduleCounts"][level])
            for level in HIERARCHY_LEVELS
        },
        target_aggregates={
            target: {
                level: {
                    key: Aggregate(int(pair[0]), int(pair[1]))
                    for key, pair in value["targets"][target][level].items()
                }
                for level in HIERARCHY_LEVELS
            }
            for target in TARGET_NAMES
        },
        global_aggregates={
            target: Aggregate(
                int(value["globalTargets"][target][0]),
                int(value["globalTargets"][target][1]),
            )
            for target in TARGET_NAMES
        },
        as_of=as_of,
        priors={target: float(value["priors"][target]) for target in TARGET_NAMES},
        prior_strength={
            level: float(value["priorStrength"][level])
            for level in HIERARCHY_LEVELS
        },
        prediction_horizon_seconds=int(value["predictionHorizonSeconds"]),
    )


def predict_artifact_probabilities(
    artifact: Mapping,
    features: Sequence[float] | None = None,
    *,
    record: GlobalFlightRecord | None = None,
    coverage_tier: CoverageTier | None = None,
    allow_unvalidated: bool = False,
) -> dict[str, float]:
    """Score safely through the serialized contract.

    Production scoring accepts only a publishable artifact and derives coverage
    from the record plus its frozen history. ``allow_unvalidated`` exists only
    for candidate/synthetic parity tests; in that mode a trusted tier may be
    supplied when no record is available.
    """

    if not isinstance(allow_unvalidated, bool):
        raise ArtifactError("allow_unvalidated must be boolean")
    if allow_unvalidated:
        validate_artifact(artifact)
    else:
        assert_publishable(artifact)
    names = artifact["featureNames"]
    calibrators = _deserialize_calibrators(artifact["calibration"])
    try:
        policy = CoveragePolicy.from_serializable(artifact["coveragePolicy"])
    except ValueError as error:
        raise ArtifactError(str(error)) from error
    if record is not None:
        if not isinstance(record, GlobalFlightRecord):
            raise ArtifactError("record must satisfy the global flight schema")
        snapshot = _deserialize_history_snapshot(artifact["history"])
        horizon = timedelta(seconds=snapshot.prediction_horizon_seconds)
        try:
            validate_schedule_at_prediction(record, horizon)
            derived_tier = assess_coverage(record, snapshot, policy=policy).tier
        except ValueError as error:
            raise ArtifactError(str(error)) from error
        if coverage_tier is not None and coverage_tier != derived_tier:
            raise ArtifactError("caller coverage tier disagrees with frozen history")
        coverage_tier = derived_tier
        try:
            encoder = PastOnlyHierarchicalEncoder(
                priors=snapshot.priors,
                prior_strength=snapshot.prior_strength,
                prediction_horizon=horizon,
            )
            history_row = encoder.transform((record,), snapshot)[0]
            assembled = assemble_feature_row(record, history_row).values
        except ValueError as error:
            raise ArtifactError(str(error)) from error
        if set(assembled) != set(names):
            if not allow_unvalidated:
                raise ArtifactError(
                    "artifact feature contract cannot be assembled from the record"
                )
            # Synthetic parity fixtures may deliberately use tiny arbitrary
            # feature vectors. Their record still derives the trusted coverage
            # tier, while the explicitly supplied vector remains test-only.
        else:
            bound_features = tuple(float(assembled[name]) for name in names)
            if features is not None:
                try:
                    supplied_features = tuple(float(value) for value in features)
                except (TypeError, ValueError) as error:
                    raise ArtifactError(
                        "feature row does not match the record-derived contract"
                    ) from error
                if supplied_features != bound_features:
                    raise ArtifactError(
                        "feature row does not match the record-derived contract"
                    )
            features = bound_features
    elif not allow_unvalidated:
        raise ArtifactError(
            "production scoring requires a record to derive its coverage tier"
        )
    elif coverage_tier is None:
        raise ArtifactError(
            "test scoring requires a record or an explicit trusted coverage tier"
        )
    if features is None or len(features) != len(names):
        raise ArtifactError("feature row does not match the artifact contract")
    return predict_probabilities(
        artifact["boosters"],
        calibrators,
        features,
        coverage_tier=coverage_tier,
        coverage_policy=policy,
    )


def _validate_count_map(value: object, name: str) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != set(CORPUS_COUNT_FIELDS):
        raise ArtifactError(f"{name} must define the exact corpus count fields")
    counts = {
        field: _nonnegative_int(value[field], f"{name}.{field}")
        for field in CORPUS_COUNT_FIELDS
    }
    scheduled = counts["scheduledRows"]
    identity = counts["identityCompleteRows"]
    outcomes = counts["knownOutcomeRows"]
    operated = counts["operatedRows"]
    arrivals = counts["operatedRowsWithArrivalTimes"]
    delayed = counts["arrival15DelayedRows"]
    cancelled = counts["cancellationRows"]
    if not (
        identity <= scheduled
        and outcomes <= scheduled
        and operated <= outcomes
        and arrivals <= operated
        and delayed <= arrivals
        and cancelled <= outcomes
        and operated + cancelled <= outcomes
    ):
        raise ArtifactError(f"{name} contains impossible populations")
    return counts


def _empty_counts() -> dict[str, int]:
    return {field: 0 for field in CORPUS_COUNT_FIELDS}


def _add_counts(total: dict[str, int], values: Mapping[str, int]) -> None:
    for field in CORPUS_COUNT_FIELDS:
        total[field] += values[field]


def _require_equal_counts(
    observed: Mapping[str, int], expected: Mapping[str, int], name: str
) -> None:
    if any(observed[field] != expected[field] for field in CORPUS_COUNT_FIELDS):
        raise ArtifactError(f"{name} does not aggregate exactly into corpusAudit")


def _validate_region_counts(
    value: object,
    name: str,
    *,
    expected_regions: set[str] | None = None,
) -> dict[str, dict[str, int]]:
    if not isinstance(value, Mapping) or not value:
        raise ArtifactError(f"{name} requires per-region count objects")
    regions: dict[str, dict[str, int]] = {}
    for raw_region, raw_counts in value.items():
        region = _required_text(raw_region, f"{name} region")
        if region in regions:
            raise ArtifactError(f"{name} region names must be unique")
        regions[region] = _validate_count_map(raw_counts, f"{name}.{region}")
    if expected_regions is not None and set(regions) != expected_regions:
        raise ArtifactError(f"{name} must define the exact corpus region set")
    return regions


def _validate_global_corpus_audit(
    coverage: Mapping,
    *,
    source_ids: set[str],
    corpus_binding: Mapping,
) -> None:
    """Validate totals against immutable per-partition provenance rollups."""

    audit = coverage.get("corpusAudit")
    if not isinstance(audit, Mapping):
        raise ArtifactError(
            "validated artifact requires a structured global corpus coverage audit"
        )

    completed_months = audit.get("completedMonths")
    if (
        not isinstance(completed_months, list)
        or len(completed_months) < MIN_COMPLETED_MONTHS
    ):
        raise ArtifactError(
            "global corpus audit requires at least "
            f"{MIN_COMPLETED_MONTHS} completed months"
        )
    parsed_months: list[tuple[int, int]] = []
    for value in completed_months:
        if not isinstance(value, str) or (match := _MONTH.fullmatch(value)) is None:
            raise ArtifactError("global corpus completedMonths must use YYYY-MM")
        parsed_months.append((int(match.group(1)), int(match.group(2))))
    if len(set(parsed_months)) != len(parsed_months):
        raise ArtifactError("global corpus completedMonths must be unique")
    for previous, current in zip(parsed_months, parsed_months[1:], strict=False):
        expected = (
            (previous[0] + 1, 1)
            if previous[1] == 12
            else (previous[0], previous[1] + 1)
        )
        if current != expected:
            raise ArtifactError(
                "global corpus completedMonths must be chronological and consecutive"
            )
    month_names = [f"{year:04d}-{month:02d}" for year, month in parsed_months]

    top_counts = _validate_count_map(
        {field: audit.get(field) for field in CORPUS_COUNT_FIELDS},
        "global corpus",
    )
    if top_counts["scheduledRows"] < 1 or top_counts["operatedRows"] < 1:
        raise ArtifactError(
            "global corpus scheduled and operated rows must be positive"
        )
    reported_rows = _nonnegative_int(coverage.get("rows"), "coverage rows")
    if reported_rows != top_counts["scheduledRows"]:
        raise ArtifactError("coverage rows must equal global corpus scheduledRows")
    if top_counts["scheduledRows"] != corpus_binding["recordCount"]:
        raise ArtifactError(
            "global corpus scheduledRows must equal the bound normalized record count"
        )
    if top_counts["identityCompleteRows"] * 100 < top_counts["scheduledRows"] * 98:
        raise ArtifactError("global corpus identity completeness is below 98%")
    if top_counts["knownOutcomeRows"] * 100 < top_counts["scheduledRows"] * 95:
        raise ArtifactError("global corpus outcome completeness is below 95%")
    if (
        top_counts["operatedRowsWithArrivalTimes"] * 100
        < top_counts["operatedRows"] * 90
    ):
        raise ArtifactError("global corpus operated-arrival completeness is below 90%")

    regions = _validate_region_counts(audit.get("regions"), "global corpus regions")
    missing_regions = [
        region for region in REQUIRED_WORLD_REGIONS if region not in regions
    ]
    if missing_regions:
        raise ArtifactError(
            "global corpus audit is missing required regions: "
            + ", ".join(missing_regions)
        )
    region_total = _empty_counts()
    for region, counts in regions.items():
        _add_counts(region_total, counts)
        if region in REQUIRED_WORLD_REGIONS:
            if counts["operatedRows"] < MIN_REGION_OPERATED_LEGS:
                raise ArtifactError(
                    f"global corpus region {region} has fewer than "
                    f"{MIN_REGION_OPERATED_LEGS} operated legs"
                )
            if counts["arrival15DelayedRows"] < MIN_REGION_ARRIVAL_15:
                raise ArtifactError(
                    f"global corpus region {region} has fewer than "
                    f"{MIN_REGION_ARRIVAL_15} delayed arrivals"
                )
            if counts["cancellationRows"] < MIN_REGION_CANCELLATIONS:
                raise ArtifactError(
                    f"global corpus region {region} has fewer than "
                    f"{MIN_REGION_CANCELLATIONS} cancellations"
                )
    _require_equal_counts(region_total, top_counts, "global region counts")

    months_value = audit.get("months")
    if not isinstance(months_value, Mapping) or set(months_value) != set(month_names):
        raise ArtifactError("global corpus month rollups must match completedMonths")
    month_rollups = {
        month: _validate_count_map(months_value[month], f"global corpus month {month}")
        for month in month_names
    }
    month_total = _empty_counts()
    for counts in month_rollups.values():
        _add_counts(month_total, counts)
    _require_equal_counts(month_total, top_counts, "global month counts")

    sources_value = audit.get("sources")
    if not isinstance(sources_value, Mapping) or set(sources_value) != source_ids:
        raise ArtifactError(
            "global corpus source rollups must match model-card sources"
        )
    source_rollups = {
        source_id: _validate_count_map(
            sources_value[source_id], f"global corpus source {source_id}"
        )
        for source_id in sorted(source_ids)
    }
    source_total = _empty_counts()
    for counts in source_rollups.values():
        _add_counts(source_total, counts)
    _require_equal_counts(source_total, top_counts, "global source counts")

    partitions = audit.get("partitions")
    partition_fields = {
        "partitionId",
        "sourceId",
        "month",
        "sourceUrl",
        "retrievedAtUtc",
        "rawFileSha256",
        "counts",
        "regions",
    }
    if not isinstance(partitions, list) or not partitions:
        raise ArtifactError("global corpus audit requires partition provenance")
    partition_ids: set[str] = set()
    aggregate = _empty_counts()
    partition_months = {month: _empty_counts() for month in month_names}
    partition_sources = {source_id: _empty_counts() for source_id in source_ids}
    partition_regions = {region: _empty_counts() for region in regions}
    for index, partition in enumerate(partitions):
        name = f"global corpus partition {index}"
        if not isinstance(partition, Mapping) or set(partition) != partition_fields:
            raise ArtifactError(f"{name} fields are incomplete or unsupported")
        partition_id = _required_text(partition.get("partitionId"), f"{name} id")
        if partition_id in partition_ids or _contains_placeholder(partition_id):
            raise ArtifactError(f"{name} id must be unique and non-placeholder")
        partition_ids.add(partition_id)
        source_id = _required_text(partition.get("sourceId"), f"{name} sourceId")
        month = _required_text(partition.get("month"), f"{name} month")
        if source_id not in source_ids:
            raise ArtifactError(f"{name} references an unknown source")
        if month not in partition_months:
            raise ArtifactError(f"{name} is outside completedMonths")
        _https_url(partition.get("sourceUrl"), f"{name} sourceUrl")
        _aware_datetime_text(
            partition.get("retrievedAtUtc"), f"{name} retrievedAtUtc"
        )
        _sha256(partition.get("rawFileSha256"), f"{name} rawFileSha256")
        counts = _validate_count_map(partition.get("counts"), f"{name} counts")
        region_counts = _validate_region_counts(
            partition.get("regions"),
            f"{name} regions",
            expected_regions=set(regions),
        )
        partition_region_total = _empty_counts()
        for region, values in region_counts.items():
            _add_counts(partition_region_total, values)
            _add_counts(partition_regions[region], values)
        _require_equal_counts(partition_region_total, counts, f"{name} region counts")
        _add_counts(aggregate, counts)
        _add_counts(partition_months[month], counts)
        _add_counts(partition_sources[source_id], counts)

    _require_equal_counts(aggregate, top_counts, "partition counts")
    for month, counts in partition_months.items():
        _require_equal_counts(counts, month_rollups[month], f"partition month {month}")
    for source_id, counts in partition_sources.items():
        _require_equal_counts(
            counts, source_rollups[source_id], f"partition source {source_id}"
        )
    for region, counts in partition_regions.items():
        _require_equal_counts(counts, regions[region], f"partition region {region}")


def _validate_metric_block(
    value: object,
    name: str,
    *,
    require_both_classes: bool,
) -> tuple[int, int]:
    fields = {
        "rocAuc",
        "averagePrecision",
        "brierScore",
        "logLoss",
        "rows",
        "positives",
        "positiveShare",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ArtifactError(f"{name} metrics are incomplete")
    rows = _nonnegative_int(value["rows"], f"{name} rows")
    positives = _nonnegative_int(value["positives"], f"{name} positives")
    if positives > rows:
        raise ArtifactError(f"{name} metrics contain an impossible population")
    if rows == 0:
        if require_both_classes or positives != 0 or any(
            value[field] is not None
            for field in (
                "rocAuc",
                "averagePrecision",
                "brierScore",
                "logLoss",
                "positiveShare",
            )
        ):
            raise ArtifactError(f"{name} empty population metrics must be null")
        return 0, 0
    if require_both_classes and not 0 < positives < rows:
        raise ArtifactError(f"{name} requires both outcome classes")
    share = _finite_number(value["positiveShare"], f"{name} positiveShare")
    if not 0 <= share <= 1 or not math.isclose(
        share, positives / rows, rel_tol=0, abs_tol=1e-12
    ):
        raise ArtifactError(f"{name} positiveShare must equal positives / rows")
    brier = _finite_number(value["brierScore"], f"{name} brierScore")
    if not 0 <= brier <= 1:
        raise ArtifactError(f"{name} brierScore must lie in [0, 1]")
    if _finite_number(value["logLoss"], f"{name} logLoss") < 0:
        raise ArtifactError(f"{name} logLoss must be non-negative")
    has_both_classes = 0 < positives < rows
    for metric_name in ("rocAuc", "averagePrecision"):
        metric = value[metric_name]
        if not has_both_classes:
            if metric is not None:
                raise ArtifactError(
                    f"{name} {metric_name} must be null for a single-class slice"
                )
            continue
        parsed = _finite_number(metric, f"{name} {metric_name}")
        if not 0 <= parsed <= 1:
            raise ArtifactError(f"{name} {metric_name} must lie in [0, 1]")
    return rows, positives


def _validate_untouched_test_metrics(
    value: object,
) -> dict[str, tuple[int, int]]:
    if not isinstance(value, Mapping) or set(value) != set(MODEL_HEADS):
        raise ArtifactError(
            "validated artifact requires untouched-test metrics for every model head"
        )
    populations: dict[str, tuple[int, int]] = {}
    for head in MODEL_HEADS:
        populations[head] = _validate_metric_block(
            value[head],
            f"validated artifact {head} untouched-test",
            require_both_classes=True,
        )
    arrival_rows = {populations[head][0] for head in MODEL_HEADS[:3]}
    if len(arrival_rows) != 1 or not (
        populations["arrival_60"][1]
        <= populations["arrival_30"][1]
        <= populations["arrival_15"][1]
    ):
        raise ArtifactError("untouched-test arrival populations are inconsistent")
    if (
        populations["cancelled"][0] != populations["disrupted"][0]
        or populations["cancelled"][1] > populations["disrupted"][1]
    ):
        raise ArtifactError("untouched-test disruption populations are inconsistent")
    return populations


def _validate_slice_evaluation(
    evaluation: Mapping,
    test_populations: Mapping[str, tuple[int, int]],
) -> None:
    population_rows = _nonnegative_int(
        evaluation.get("testPopulationRows"), "untouched-test population rows"
    )
    if population_rows < 1:
        raise ArtifactError("untouched-test population rows must be positive")
    if any(rows > population_rows for rows, _ in test_populations.values()):
        raise ArtifactError("untouched-test head rows exceed the test population")
    slices = evaluation.get("sliceMetrics")
    if not isinstance(slices, Mapping) or set(slices) != set(SLICE_DIMENSIONS):
        raise ArtifactError(
            "validated artifact requires region, country, carrier, airport-size, "
            "route-frequency, and season slice evaluation"
        )
    slice_fields = {"value", "populationRows", "metrics"}
    for dimension in SLICE_DIMENSIONS:
        entries = slices[dimension]
        if not isinstance(entries, list) or not entries:
            raise ArtifactError(f"{dimension} slice evaluation must be non-empty")
        seen: set[str] = set()
        dimension_population = 0
        dimension_heads = {head: [0, 0] for head in MODEL_HEADS}
        for index, entry in enumerate(entries):
            name = f"{dimension} slice {index}"
            if not isinstance(entry, Mapping) or set(entry) != slice_fields:
                raise ArtifactError(f"{name} fields are incomplete or unsupported")
            label = _required_text(entry.get("value"), f"{name} value")
            if label in seen:
                raise ArtifactError(f"{dimension} slice values must be unique")
            seen.add(label)
            rows = _nonnegative_int(
                entry.get("populationRows"), f"{name} populationRows"
            )
            if rows < 1:
                raise ArtifactError(f"{name} populationRows must be positive")
            dimension_population += rows
            metrics = entry.get("metrics")
            if not isinstance(metrics, Mapping) or set(metrics) != set(MODEL_HEADS):
                raise ArtifactError(f"{name} must define metrics for every model head")
            for head in MODEL_HEADS:
                head_rows, positives = _validate_metric_block(
                    metrics[head], f"{name} {head}", require_both_classes=False
                )
                if head_rows > rows:
                    raise ArtifactError(f"{name} {head} rows exceed its population")
                dimension_heads[head][0] += head_rows
                dimension_heads[head][1] += positives
            if not (
                metrics["arrival_60"]["rows"]
                == metrics["arrival_30"]["rows"]
                == metrics["arrival_15"]["rows"]
                and metrics["arrival_60"]["positives"]
                <= metrics["arrival_30"]["positives"]
                <= metrics["arrival_15"]["positives"]
            ):
                raise ArtifactError(f"{name} arrival populations are inconsistent")
            if not (
                metrics["cancelled"]["rows"] == metrics["disrupted"]["rows"]
                and metrics["cancelled"]["positives"]
                <= metrics["disrupted"]["positives"]
            ):
                raise ArtifactError(f"{name} disruption populations are inconsistent")
        if dimension_population != population_rows:
            raise ArtifactError(
                f"{dimension} slice populations must exhaust the untouched test"
            )
        for head in MODEL_HEADS:
            if tuple(dimension_heads[head]) != test_populations[head]:
                raise ArtifactError(
                    f"{dimension} {head} slice populations do not aggregate to "
                    "untouched-test metrics"
                )


def assert_publishable(artifact: Mapping) -> None:
    """Fail closed unless independent release gates are recorded."""

    validate_artifact(artifact)
    if artifact.get("artifactStatus") != "validated":
        raise ArtifactError("candidate or synthetic artifacts cannot be published")
    card = artifact.get("modelCard")
    if not isinstance(card, Mapping):
        raise ArtifactError("validated artifact is missing its model card")
    evaluation = card.get("evaluation")
    coverage = card.get("dataCoverage")
    if not isinstance(evaluation, Mapping) or evaluation.get("untouchedTest") is not True:
        raise ArtifactError("validated artifact requires an untouched test result")
    if (
        not isinstance(coverage, Mapping)
        or coverage.get("globalReleaseGatePassed") is not True
    ):
        raise ArtifactError("validated artifact requires the global coverage gate")
    if coverage.get("synthetic") is True:
        raise ArtifactError("synthetic coverage cannot pass the publication gate")
    rows = coverage.get("rows")
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
        raise ArtifactError("validated artifact requires a positive coverage row count")


def write_artifact(
    path: Path,
    artifact: Mapping,
    *,
    allow_unvalidated: bool = False,
) -> None:
    validate_artifact(artifact)
    if not allow_unvalidated:
        assert_publishable(artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(artifact, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )


def verify_parity_cases(artifact: Mapping, tolerance: float = 1e-12) -> float:
    """Re-evaluate serialized parity rows and return the maximum error."""

    if tolerance < 0:
        raise ValueError("tolerance must not be negative")
    boosters = artifact.get("boosters")
    calibration = artifact.get("calibration")
    cases = artifact.get("parityCases")
    if not isinstance(boosters, Mapping) or not isinstance(calibration, Mapping):
        raise ArtifactError("artifact is missing model components")
    if not isinstance(cases, list) or not cases:
        raise ArtifactError("artifact is missing parity cases")
    calibrators = _deserialize_calibrators(calibration)
    maximum = 0.0
    for case in cases:
        expected = case["probabilities"]
        observed = _predict_probabilities_unchecked(
            boosters, calibrators, case["features"]
        )
        for head in MODEL_HEADS:
            maximum = max(maximum, abs(observed[head] - expected[head]))
    if maximum > tolerance:
        raise ArtifactError(f"parity error {maximum:.12g} exceeds {tolerance:.12g}")
    return maximum
