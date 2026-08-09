# ANAC SIROS daily-snapshot audit — 2026-08-09

This is the reproducibility summary for the first full offline parse of a real
ANAC SIROS future-schedule snapshot. It validates the source adapter and its
point-in-time schedule evidence; it is not a trained-model result or a claim of
worldwide prediction coverage.

## Bound source file

| Field | Value |
| --- | --- |
| Official resource | `futuro_2025-01-01.csv` |
| Source URL | `https://siros.anac.gov.br/siros/registros/futuro/serie/2025/futuro_2025-01-01.csv` |
| HTTP `Last-Modified` | `Wed, 01 Jan 2025 07:26:25 GMT` |
| Bytes | `16,227,522` |
| SHA-256 | `3119d510da1db60c507ba4f0bf4705523a4d760a06a7358a35aad828594c95c6` |

The file has a UTF-8 BOM, the exact first-line statement `Importante: Horários
em UTC`, and the reviewed 28-column Portuguese SIROS schema. The loader treats
the HTTP timestamp as the schedule observation time. The filename date alone
is never converted into an availability timestamp.

## Reconciled results

- Raw series rows: 44,888.
- Accepted rows: 44,888.
- Rejected rows: 0.
- Unique SIROS registration IDs: 43,997.
- Unique `(SIROS ID, stage)` identities: 44,888.
- Services expanded for 2025-01-02: 1,316.
- Deterministic service-observation digest for that date:
  `9556337b64cf9fad050ad418e275d0c6040f834099a5cf5f64cf402dee4b4a15`.

## Interpretation

A SIROS source row is a recurring schedule series rather than one operated
flight. Service instances are expanded only when the requested UTC date falls
inside the validity interval and matches the weekday mask. The identity is the
official SIROS ID plus stage number because multi-stage registrations are
legitimate. `Data Registro` is preserved raw because its timezone is not
documented, and distinct SIROS IDs are never inferred to replace one another.

The next gate is a fully audited, one-to-one join from a schedule snapshot
visible at T−7 to the later ANAC VRA outcome. Until that gate and model
evaluation pass, no public delay estimate should claim this coverage.
