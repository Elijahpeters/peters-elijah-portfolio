# SkyETA global model pipeline

This package is the provider-neutral, leakage-safe foundation for a future
worldwide SkyETA schedule model. It does **not** contain a trained global model,
provider credentials, or fabricated international outcomes. The existing U.S.
BTS pipeline in `skyeta-ml/train.py` remains unchanged.

## Contracts implemented

- `schema.py` normalizes one operating flight leg with aware UTC timestamps,
  airport geography, local timezone offsets, operating identity, schedule
  revision/observation metadata and terminal-outcome observation time.
- `dedupe.py` resolves marketing codeshares and schedule snapshots to one
  revision-independent physical-leg key, selects the latest schedule revision
  visible at the configured prediction horizon, and rejects contradictory or
  insufficiently identified revisions.
- `labels.py` derives 15+, 30+ and 60+ minute arrival labels only for landed
  flights, with cancellation and disruption kept as separate targets.
- `splits.py` creates exclusive prediction-time train/tune/calibration/test
  windows, purges labels not observed before the next cutoff and supports
  genuine unseen-region diagnostics.
- `encodings.py` computes hierarchical empirical-Bayes history rates using only
  outcomes available before each prediction timestamp. The default contract is
  seven days before scheduled departure, and the horizon is exported with the
  snapshot. A row must prove that its schedule was observed by that timestamp;
  every terminal row must carry an outcome-observation timestamp, and rows
  sharing a timestamp cannot observe one another. Frozen snapshots carry an
  explicit information cutoff and cannot score an earlier prediction.
- `features.py` creates schedule and geographic features that are available
  before departure and therefore work for unseen route/airline cold starts.
- `coverage.py` labels identity support as established, partial or cold start;
  the exported default policy refuses cold-start scores.
- `calibration.py` fits dedicated-split Platt calibrators and projects cumulative
  delay probabilities so `P(60+) <= P(30+) <= P(15+)` and
  `P(cancelled) <= P(disrupted)`.
- `pipeline.py` prepares aligned numeric matrices while freezing all later
  windows to the training-boundary history snapshot.
- `train.py` can fit five LightGBM candidate heads from an authorized normalized
  corpus. It always exports a non-publishable candidate.
- `export.py` defines the server artifact v4 schema, native-LightGBM parity
  fixtures, full structural validation and fail-closed publication/scoring
  gates. V4 binds the model to its normalized record-ID digest, requires
  source-rights evidence, checks every source/month/region total against
  per-partition provenance, and requires exhaustive untouched-test slices for
  region, country, carrier, airport-history size, route-history frequency and
  season. Production scoring derives the coverage tier from the serialized
  history and flight identity; a caller cannot claim that a cold route is
  established.

The source rights and worldwide data coverage requirements are documented in
`DATA_ACCESS.md`. Publication requires its structured 24-month audit,
partition-provenance rollups, rights evidence, untouched-test slices and
completeness gates; flipping a boolean or pasting unbound counts is
insufficient. A provider API key or trial access is not permission to retain
rows, train a model, or deploy derived predictions.

## Tests

Tests use synthetic fixtures only. From the repository root:

```powershell
skyeta-ml/.venv/Scripts/python -m pip install -r skyeta-ml/global/requirements-dev.txt
skyeta-ml/.venv/Scripts/python -m pytest skyeta-ml/global/tests -q
```

No test writes a public model artifact.
