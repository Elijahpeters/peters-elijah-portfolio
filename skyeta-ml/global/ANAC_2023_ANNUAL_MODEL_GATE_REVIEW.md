# SkyETA ANAC 2023 annual model gate review

## Decision

**Blocked from production.** The annual run completed successfully, but it is retrospective research evidence rather than a deployable model.

## Evaluated cohort

- Exactly joined model rows: **643,404**
- T-7 schedule rows: **723,066**
- Exact schedule-to-outcome match rate: **88.98%**
- Annual-population performance claim: **not allowed**

## Untouched chronological test results

| Head | Rows | Event rate | ROC AUC | Average precision | Brier vs constant | Log loss vs constant | Interpretation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| arrival_15 | 85,270 | 19.84% | 0.639 | 0.280 | -0.0017 | +0.0022 | Distinct evaluated target |
| arrival_30 | 85,270 | 10.21% | 0.624 | 0.145 | -0.0033 | -0.0049 | Distinct evaluated target |
| arrival_60 | 85,270 | 3.87% | 0.580 | 0.050 | +0.0000 | +0.0005 | Distinct evaluated target |
| cancelled | 87,763 | 2.84% | 0.771 | 0.145 | +0.0013 | +0.0106 | Distinct evaluated target |
| disrupted | 87,763 | 2.84% | 0.771 | 0.145 | +0.0013 | +0.0106 | Same target as cancelled for this source |

Positive Brier/log-loss differences mean the model beat the constant-rate reference; negative values mean it did worse.

## Release blockers

- The evaluation is retrospective, not a historical point-in-time backtest.
- Metrics are conditioned on final schedules remaining exactly joinable after T-7.
- The signed output intentionally contains no production model artifact.
- ANAC VRA exposes cancellation but no distinct diversion outcome.

## Next engineering actions

1. Keep this signed output as retrospective research evidence only.
2. Use a future time period for development after this test-period review.
3. Improve and recalibrate the 30- and 60-minute arrival heads before another gate review.
4. Acquire immutable point-in-time outcome evidence and archive ANAC publication rights evidence.
5. Run a new chronological regional evaluation before creating any Brazil production artifact.

Source evaluation digest: `35ad62b371acb40a5a591fc42f6c0d23c179864aff26758fabc43312b3fca847`

Gate-review digest: `3c600030f6cbd00b764c8020b3884416dc5bd2855733ef0e34cb30289754aef6`
