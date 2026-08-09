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
  genuine unseen-region diagnostics. It also exposes a separately named
  retrospective T−7 evaluation split for hash-pinned labels first seen only
  after the complete service period; that split explicitly forbids
  target-derived history and never calls itself a point-in-time backtest.
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
  windows to the training-boundary history snapshot. Its separate
  retrospective preparation path exposes no history encoder or snapshot and
  produces schedule/geography-only matrices that are structurally
  non-publishable.
- `train.py` can fit five LightGBM candidate heads from an authorized normalized
  corpus. It always exports a non-publishable candidate. A separate
  retrospective evaluator can fit, tune and calibrate the same five heads for
  diagnostics only; it returns metrics rather than a model artifact.
- `corpus.py` streams completed normalized partitions into an immutable
  record-ID binding, exact artifact-v4 month/source/origin-region rollups, and
  separate status, 15/30/60-minute delay, and observation-evidence diagnostics.
  Raw-partition count, source, month and provenance mismatches fail closed.
- `sources/anac_aerodromes.py` loads archived official ANAC public/private
  aerodrome registries with byte hashes, memento timestamps, embedded update
  dates and row-complete audits. It retains official ICAO/CIAD identity and
  never invents IATA codes or timezones.
- `sources/timezone_boundaries.py` resolves coordinates from the checksum-pinned
  Timezone Boundary Builder 2026c land polygons. A point and a 1 km guard ring
  must resolve uniquely to the same IANA zone; uncovered or boundary-adjacent
  locations are rejected without a nearest-zone/default fallback.
- `sources/anac_airport_index.py` combines official ANAC identity with the
  independently resolved timezone and uses `airportsdata` only for tightly
  checked secondary IATA enrichment. Official coordinates are never replaced,
  ICAO-only aerodromes remain first-class schema identities, and every merge
  conflict remains visible in the audit.
- `anac_reference.py` runs those reference stages offline as one hash-checked,
  reconciled preparation job and can atomically write a deterministic local
  artifact containing every accepted and rejected timezone/identity decision.
- `sources/anac_siros.py` validates dated ANAC future-schedule snapshots,
  preserves byte and availability evidence, expands recurring series into UTC
  service instances and selects only schedules visible by T−7.
- `anac_siros_vra_join.py` joins those schedule instances to terminal VRA rows
  only on an exact carrier/flight/ICAO-route/departure/arrival key. It audits
  every unmatched, ambiguous and rejected input and requires hash-bound outcome
  availability evidence supplied by the caller. Its unmatched diagnostics use
  pre-indexed operational keys so a month- or year-scale audit remains linear.
- `anac_vra_outcome_loader.py` converts one pinned monthly VRA file into
  terminal join candidates without duplicating source parsing. It reconciles
  every raw row, verifies file bytes and explicit observation evidence, and
  fails on ambiguous airport training codes.
- `anac_annual_retrospective.py` is the offline 2023 evaluation runner. It
  validates the complete annual SIROS ZIP, selects member `D-8` for each
  service date `D`, loads hash-pinned VRA months through a bounded rolling
  cache, performs exact month-scoped joins, and emits a deterministic audit
  rather than a model artifact. Its untouched-test report includes true
  train-versus-test cold starts for carrier, origin, destination and route.
- `anac_january_retrospective.py` is the guarded January 2025 correction
  runner. It treats `futuro_2025-01-01.csv` as one fixed snapshot, reports its
  actual age for every 8--31 January service date, excludes schedules observed
  less than seven days before departure, and uses the resulting eligible-row
  count as the exact-join denominator. It never describes that one file as a
  fresh daily snapshot series; VRA equipment cannot enter model features.
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

The separate cited live-research architecture and its strict boundary from
trained probabilities are documented in `WEB_INTELLIGENCE.md`. SkyETA remains
free to travelers and does not collect payment.

## Tests

Tests use synthetic fixtures only. From the repository root:

```powershell
skyeta-ml/.venv/Scripts/python -m pip install -r skyeta-ml/global/requirements-dev.txt
skyeta-ml/.venv/Scripts/python -m pytest skyeta-ml/global/tests -q
```

No test writes a public model artifact.

## Offline annual evaluation CLI

The annual runner accepts one explicit JSON manifest and never downloads a
missing input:

```powershell
Push-Location skyeta-ml
.venv/Scripts/python -m global.anac_annual_retrospective `
  --manifest C:/path/to/anac-2023-manifest.json `
  --output C:/path/to/anac-2023-retrospective-audit.json
Pop-Location
```

The manifest schema is `skyeta-anac-annual-retrospective-input-v1`. It pins the
annual archive, prepared airport-reference JSON and every January-December VRA
file by exact byte count and SHA-256; it also preserves each VRA file's explicit
outcome-observation provenance, the reviewed non-public annual-member evidence
policy, chronological boundaries and training configuration. Paths may be
absolute or relative to the manifest. The manifest also pins explicit sparse
matrix and evaluation-working-set limits; unsafe estimates fail before model
evaluation. The reviewed run covers 9 January
through 31 December; earlier dates have no same-archive `D-8` member. December
31 remains inside the December VRA partition because ANAC evaluates partition
membership using the scheduled departure in its Brasilia reporting timezone.

The output always states `publishable: false`, `point_in_time_backtest: false`,
`production_artifact_created: false`, and `deployment_performed: false`.
Complete row/join decisions are reconciled and digest-bound; only bounded
non-match examples are embedded so a year-scale audit remains practical.
Features remain in CSR storage, and LightGBM runs with fixed seeds, fixed CPU
thread count and deterministic column-wise training. Runtime library versions,
the exact deterministic parameters and SHA-256 digests of the reviewed source
files are recorded in every output.

Metrics are explicitly qualified as an **exact-join-conditioned cohort**. A
row enters evaluation only when carrier, flight, route, departure and arrival
from the T-7 SIROS schedule exactly match the final VRA schedule. The audit
reports the schedule match rate and every non-match disposition beside the
metrics. Because unchanged schedule identity is known only after T-7 and may
be related to disruption, these metrics must not be presented as performance
for all annual flights.

## Offline January fixed-snapshot diagnostic CLI

The January correction has a separate strict manifest and an additional
execution acknowledgement. Omitting any of `--manifest`, `--output`, or
`--execute` fails before an input is loaded:

```powershell
Push-Location skyeta-ml
.venv/Scripts/python -m global.anac_january_retrospective `
  --manifest C:/path/to/anac-january-2025-manifest.json `
  --output C:/path/to/anac-january-2025-diagnostic.json `
  --execute
Pop-Location
```

Schema `skyeta-anac-january-fixed-snapshot-input-v1` pins the daily SIROS
file, airport reference and January VRA file by byte count and SHA-256, plus
the exact HTTP availability evidence, retrospective outcome provenance,
fixed chronological windows, deterministic training configuration and memory
limits. Unknown or duplicate fields fail closed. Network access is denied for
the entire run, output cannot overwrite a pinned input or reviewed source, and
the only permitted result is an atomic, digest-bound, nonpublishable audit.
This diagnostic exports no model and makes no January-population performance
claim.

The large raw reference files and derived airport-timezone artifacts belong
under `skyeta-ml/global/data/`, which is intentionally ignored by Git. Only
loader code, fixed source pins, tests and reproducibility documentation are
committed.

The first full real-file airport-reference run is recorded in
`ANAC_REFERENCE_AUDIT.md`. It is reference-data validation, not a trained model
or a worldwide-release claim.

The first full real-file daily-schedule parse is recorded in
`ANAC_SIROS_AUDIT.md`. It proves the reviewed source shape and schedule
observation handling, but does not by itself prove a VRA outcome join or a
deployable model.

The first real one-day schedule-to-outcome smoke audit is recorded in
`ANAC_SIROS_VRA_JOIN_AUDIT.md`. Its labels are retrospective-holdout-only and
its results must not be presented as a trained or released model.

The first real month-scale five-head evaluation is recorded in
`ANAC_JANUARY_2025_MODEL_AUDIT.md`. Its original and enhanced metrics are
explicitly invalidated after review found that aircraft type crossed the
schedule/outcome feature boundary. The document remains as a transparent audit
trail; a corrected join and rerun are required before any model-performance
claim.
