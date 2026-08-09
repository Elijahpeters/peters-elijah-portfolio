# ANAC January 2025 retrospective model audit — 2026-08-09

This is the first real month-scale LightGBM evaluation produced by the audited
ANAC schedule/outcome pipeline. It is a diagnostic milestone, not a production
artifact. The run used one SIROS schedule snapshot and current hash-pinned VRA
bytes, so it is explicitly retrospective and cannot be described as a
point-in-time backtest.

## Corpus and join

- Schedule source: `futuro_2025-01-01.csv`, observed from HTTP evidence at
  `2025-01-01T07:26:25Z`, SHA-256
  `3119d510da1db60c507ba4f0bf4705523a4d760a06a7358a35aad828594c95c6`.
- Outcome source: `VRA_2025_01.csv`, directly audited at
  `2026-08-09T07:58:29.186790Z`, SHA-256
  `685f8befdb548cfa53d8dee0c6bf377c2791fd6ac1590748d6c0e486bc75f562`.
- VRA source rows: 89,616; terminal candidates: 86,593; unplanned operations
  excluded: 2,253; rejected source rows: 770.
- Evaluated service dates: 2025-01-08 through 2025-01-31.
- SIROS inputs: 55,092; VRA inputs in the service window: 67,643.
- Exact one-to-one matches: 52,394.
- Ambiguities: 95, all failed closed rather than arbitrarily selected.
- Matched outcomes: 50,990 landed and 1,404 cancelled.
- Join-audit digest:
  `d775b7c4a29666ba17761a5491170b4c40fec7bb80cd493c8b23bada6b167889`.

## Temporal windows

The original baseline uses 46 schedule/geography features only. The enhanced
diagnostic adds 464 non-target categorical schedule features for carrier,
origin, destination, aircraft family and route. Its vocabularies and frequency
features are fitted on the training window only, then frozen for tune,
calibration and test; unseen values use explicit unknown buckets. No outcome or
target-derived carrier, route or airport history was admitted.

| Window | Rows |
| --- | ---: |
| Train | 14,852 |
| Tune | 11,007 |
| Calibration | 10,982 |
| Untouched test | 15,553 |

## Untouched-test results

`Average precision` should be compared with the positive share: a random or
constant ranking has average precision equal to prevalence. Lower Brier score
and log loss are better.

| Target | Rows | Positive share | ROC-AUC | Average precision | Brier | Constant-rate Brier |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Arrival delay 15+ min | 15,171 | 17.69% | 0.586 | 0.236 | 0.14470 | 0.14557 |
| Arrival delay 30+ min | 15,171 | 8.80% | 0.583 | 0.120 | 0.07981 | 0.08025 |
| Arrival delay 60+ min | 15,171 | 3.18% | 0.562 | 0.042 | 0.03087 | 0.03082 |
| Cancelled | 15,553 | 2.46% | 0.654 | 0.103 | 0.02333 | 0.02396 |
| Disrupted | 15,553 | 2.46% | 0.654 | 0.103 | 0.02333 | 0.02396 |

For this VRA slice, `disrupted` equals `cancelled` because it contains no
separately labelled diversion outcomes.

## Training-only schedule-category benchmark

The enhanced run used the identical corpus, join digest and temporal windows as
the baseline above. Its feature contract contains 510 columns: 46 base features
plus 464 training-only schedule-category features. The frozen vocabulary
snapshot digest is
`8f9a69331f604a4e697836590dac2579f5bce46869e1e91af8f524ba22912312`.

| Target | ROC-AUC | Average precision | Brier | Log loss | Constant-Brier gate |
| --- | ---: | ---: | ---: | ---: | --- |
| Arrival delay 15+ min | 0.58836 | 0.24247 | 0.14438 | 0.46480 | Pass |
| Arrival delay 30+ min | 0.61703 | 0.13200 | 0.07949 | 0.29403 | Pass |
| Arrival delay 60+ min | 0.60733 | 0.05075 | 0.03075 | 0.13990 | Pass |
| Cancelled | 0.72504 | 0.12681 | 0.02295 | 0.10609 | Pass |
| Disrupted | 0.72504 | 0.12681 | 0.02295 | 0.10609 | Pass |

Against the baseline, ROC-AUC improved by 0.00276, 0.03416, 0.04533 and
0.07139 for the 15-minute, 30-minute, 60-minute and cancellation heads
respectively. Every Brier score improved, and the 60-minute head moved from
failing to passing the constant-rate Brier gate. The only metric regression was
a 0.00024 increase in 15-minute log loss, despite improved ranking, average
precision and Brier score for that head.

## Decision

The two runs prove that the pipeline learns real ranking signal and that
training-only schedule identity materially improves the weakest heads,
especially cancellation and 60-minute delay. They also prove that the complete
ingest/join/train/calibrate/test route works on tens of thousands of official
records.

This is still not a production release. It covers one month and one schedule
snapshot, uses retrospective outcome evidence rather than a deployable
point-in-time backtest, has not yet tested seasonal stability or unseen
carrier/airport/route slices, and lacks a separately trained point-in-time
weather/operations model. The current diagnostic JSON remains in the ignored
`global/data/derived/` directory and no model was deployed.

Next work is to validate the complete annual schedule archive, join multiple
months of outcomes, repeat the temporal evaluation across seasons and cold-start
slices, and investigate the small 15-minute log-loss regression before any
release decision.
