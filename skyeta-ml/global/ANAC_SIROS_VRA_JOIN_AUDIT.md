# ANAC SIROS-to-VRA join audit — 2026-08-09

This is a production-style smoke audit of the exact schedule-to-outcome join on
real ANAC files. It is deliberately a one-day retrospective evaluation, not a
trained model, a historical point-in-time backtest, or evidence of worldwide
coverage.

## Bound inputs

| Input | Observation evidence | SHA-256 |
| --- | --- | --- |
| SIROS `futuro_2025-01-01.csv` | HTTP `Last-Modified`: `Wed, 01 Jan 2025 07:26:25 GMT` | `3119d510da1db60c507ba4f0bf4705523a4d760a06a7358a35aad828594c95c6` |
| VRA `VRA_2025_01.csv` | Direct byte audit at `2026-08-09T07:58:29.186790Z` | `685f8befdb548cfa53d8dee0c6bf377c2791fd6ac1590748d6c0e486bc75f562` |

The current VRA bytes cannot be backdated to the original monthly publication:
ANAC may revise historical files, and no immutable historical byte capture was
found for this hash. The matched labels are therefore marked
`retrospective_holdout_only` and cannot enter target-derived history features.

## Exact join results for 2025-01-08 UTC

- Expanded SIROS schedule inputs: 2,033.
- Terminal VRA outcome inputs: 2,864.
- Exact one-to-one matches: 1,558.
- Ambiguous matches: 0.
- Matched outcomes: 1,516 landed and 42 cancelled.
- Eligible schedule rows with no exact VRA counterpart: 21.
- Outcome rows with no exact SIROS counterpart from this one snapshot: 1,306.
- Schedule rows rejected by the T−7 gate: 454.
- Reconciled join-audit digest:
  `0cec6420d6e6dc08e041fc606c247258472a7382b00f6553b9747e2a44e13f55`.

The cross-product key is exact operating carrier, flight number, ICAO origin,
ICAO destination, scheduled departure UTC, and scheduled arrival UTC. There is
no fuzzy time window and no inferred relationship between distinct SIROS IDs.

## Interpretation

This one-snapshot test intentionally rejects early-morning 8 January services
whose T−7 instant precedes the 1 January snapshot's proven availability time.
The complete archive runner must select the preceding daily snapshot for those
services. The join is ready for that archive; the archive coverage and model
evaluation gates remain open.
