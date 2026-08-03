# SkyETA model

This directory contains the reproducible training pipeline for the interactive
SkyETA application.

The classifier uses official U.S. Bureau of Transportation Statistics
Reporting Carrier On-Time Performance records. It predicts whether
a completed domestic flight will arrive at least 15 minutes late using only
information available before departure: carrier, route, calendar, scheduled
departure time, scheduled duration, and distance.

## Data split

- Training: January–September 2025
- Validation: October–November 2025
- Test: December 2025

The chronological split prevents future months from leaking into model
selection. Categorical delay-rate features are learned from the training period
only, with Bayesian smoothing and a global fallback for unseen values.

The validation split is used for early stopping, a monotonic Platt probability
calibrator, a diagnostic F1 threshold, and (for non-core models) the feature-set
ablation decision. December is not used for any of those choices; it is reported
once as the held-out test. The diagnostic threshold is not a travel recommendation
and the public UI presents a continuous estimate rather than an on-time/delayed
label.

The browser supports the `core` contract and the target-free `context` contract.
Schedule frequency, origin-bank, and calendar features for `context` are computed
locally from exported training-only count maps. Weather/full contracts are not
served by the static demo because real inference would require timestamp-validated
pre-departure observations.

## Outputs

- `artifacts/skyeta-lightgbm.joblib`: local Python model bundle, including the
  calibrator and feature contract; ignored by Git.
- `public/assets/skyeta-model.json`: browser-safe LightGBM tree dump, feature
  metadata, route presets, and held-out metrics.
- `public/assets/skyeta-model-card.json`: compact provenance and evaluation
  record used by the portfolio.

Raw downloads and Python artifacts remain ignored so the public repository does
not carry hundreds of megabytes of source data or unsafe pickle files.

## Reproduce the model

Run these commands from the repository root:

```bash
python -m venv skyeta-ml/.venv
skyeta-ml/.venv/Scripts/python -m pip install -r skyeta-ml/requirements.txt
skyeta-ml/.venv/Scripts/python skyeta-ml/download_bts.py
skyeta-ml/.venv/Scripts/python skyeta-ml/train.py
```

To evaluate and export the browser-compatible context model, use:

```bash
skyeta-ml/.venv/Scripts/python skyeta-ml/train.py --feature-set context --ablation
```

The export is refused unless the context model clears the predeclared validation
ROC-AUC gain over the identical-row core baseline. Test-set performance is
reported but never used for that acceptance decision.

On macOS or Linux, replace `skyeta-ml/.venv/Scripts/python` with
`skyeta-ml/.venv/bin/python`.
