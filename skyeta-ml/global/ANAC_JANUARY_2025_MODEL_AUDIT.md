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

The model uses schedule/geography features only. No target-derived carrier,
route or airport history was admitted.

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

## Decision

The run proves that the pipeline learns real ranking signal, especially for
cancellation, and that the full ingest/join/train/calibrate/test route works on
tens of thousands of official records. It does not meet a production release
gate: the 60-minute Brier score is slightly worse than the constant-rate
baseline, delay discrimination is modest, only one month and one schedule
snapshot are represented, and carrier/route identity plus weather/live context
are absent.

Next work is to ingest the complete daily archive, broaden seasons and routes,
add training-only non-target categorical schedule features, and test a separate
near-departure weather/operations model. The current diagnostic JSON remains in
the ignored `global/data/derived/` directory and no model was deployed.
