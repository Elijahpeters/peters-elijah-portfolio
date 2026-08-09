"""Dedicated-split calibration and ordered cumulative delay probabilities."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np
from sklearn.linear_model import LogisticRegression


ARRIVAL_HEADS = ("arrival_15", "arrival_30", "arrival_60")
DISRUPTION_HEADS = ("disrupted", "cancelled")


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


@dataclass(frozen=True, slots=True)
class PlattCalibrator:
    slope: float
    intercept: float
    fitted_rows: int

    def __post_init__(self) -> None:
        if not math.isfinite(self.slope) or self.slope <= 0:
            raise ValueError("calibration slope must be finite and positive")
        if not math.isfinite(self.intercept) or self.fitted_rows < 1:
            raise ValueError("calibration metadata is invalid")

    def apply(self, raw_score: float) -> float:
        if not math.isfinite(raw_score):
            raise ValueError("raw score must be finite")
        return _sigmoid(self.slope * raw_score + self.intercept)

    def as_dict(self) -> dict[str, float | int | str]:
        return {
            "method": "platt_sigmoid",
            "input": "lightgbm_raw_score",
            "slope": self.slope,
            "intercept": self.intercept,
            "fittedRows": self.fitted_rows,
            "fittedOn": "dedicated_calibration_split",
        }


def fit_platt_calibrator(
    raw_scores: Sequence[float],
    labels: Sequence[bool | int],
) -> PlattCalibrator:
    """Fit a monotonic sigmoid; callers must pass only the calibration split."""

    scores = np.asarray(raw_scores, dtype="float64")
    target = np.asarray(labels, dtype="int8")
    if scores.ndim != 1 or target.ndim != 1 or len(scores) != len(target):
        raise ValueError("calibration scores and labels must be aligned vectors")
    if len(scores) < 2 or not np.isfinite(scores).all():
        raise ValueError("calibration requires at least two finite scores")
    if set(np.unique(target)) != {0, 1}:
        raise ValueError("calibration requires both target classes")
    model = LogisticRegression(C=1_000_000.0, solver="lbfgs", max_iter=1_000)
    model.fit(scores.reshape(-1, 1), target)
    return PlattCalibrator(
        slope=float(model.coef_[0, 0]),
        intercept=float(model.intercept_[0]),
        fitted_rows=len(scores),
    )


def project_nonincreasing(values: Iterable[float]) -> tuple[float, ...]:
    """Least-squares isotonic projection for a non-increasing sequence."""

    raw = [float(value) for value in values]
    if not raw or any(not math.isfinite(value) or not 0 <= value <= 1 for value in raw):
        raise ValueError("probabilities must be finite values between 0 and 1")
    blocks: list[dict[str, float | int]] = []
    for index, value in enumerate(raw):
        blocks.append({"start": index, "end": index, "weight": 1, "mean": value})
        while len(blocks) >= 2 and float(blocks[-2]["mean"]) < float(blocks[-1]["mean"]):
            right = blocks.pop()
            left = blocks.pop()
            weight = int(left["weight"]) + int(right["weight"])
            mean = (
                float(left["mean"]) * int(left["weight"])
                + float(right["mean"]) * int(right["weight"])
            ) / weight
            blocks.append(
                {
                    "start": int(left["start"]),
                    "end": int(right["end"]),
                    "weight": weight,
                    "mean": mean,
                }
            )
    projected = [0.0] * len(raw)
    for block in blocks:
        for index in range(int(block["start"]), int(block["end"]) + 1):
            projected[index] = float(block["mean"])
    return tuple(projected)


def project_cumulative_probabilities(
    probabilities: Mapping[str, float],
) -> dict[str, float]:
    missing = [head for head in ARRIVAL_HEADS if head not in probabilities]
    if missing:
        raise ValueError(f"missing cumulative probabilities: {', '.join(missing)}")
    projected = project_nonincreasing(probabilities[head] for head in ARRIVAL_HEADS)
    result = dict(probabilities)
    result.update(zip(ARRIVAL_HEADS, projected, strict=True))
    return result


def calibrate_head_scores(
    raw_scores: Mapping[str, float],
    calibrators: Mapping[str, PlattCalibrator],
) -> dict[str, float]:
    if set(raw_scores) != set(calibrators):
        raise ValueError("raw scores and calibrators must define the same heads")
    calibrated = {
        head: calibrators[head].apply(score) for head, score in raw_scores.items()
    }
    calibrated = project_cumulative_probabilities(calibrated)
    disruption, cancelled = project_nonincreasing(
        calibrated[head] for head in DISRUPTION_HEADS
    )
    calibrated["disrupted"] = disruption
    calibrated["cancelled"] = cancelled
    return calibrated
