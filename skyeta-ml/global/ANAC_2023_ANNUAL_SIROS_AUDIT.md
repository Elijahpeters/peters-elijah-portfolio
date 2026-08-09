# ANAC 2023 annual SIROS archive audit — 2026-08-09

This document records the strict, offline validation of the complete 2023
ANAC SIROS future-schedule archive used by SkyETA's non-publishable annual
retrospective evaluation. It is source-integrity evidence only. It is not a
model-performance result, a point-in-time backtest, or permission to publish a
delay model.

## Pinned archive

- Source: `https://siros.anac.gov.br/siros/registros/futuro/serie/2023.zip`
- Bytes: `340,405,397`
- SHA-256: `d8848e74b19d0ff58dbae4bfcc2f3bcaefaed34bc67159bfd8cee9323a561e81`
- HTTP Last-Modified: `Fri, 05 Jul 2024 01:38:23 GMT`
- Retrieval captured: `2026-08-09T10:27:10.556543Z`

The archive-level Last-Modified value is container provenance only. It does
not prove when any member was publicly available. Every member therefore uses
the reviewed retrospective-only filename-date bound and is ineligible for a
point-in-time publication claim.

## Validation result

| Check | Result |
| --- | ---: |
| Expected daily snapshots | 365 |
| Validated daily snapshots | 365 |
| Calendar coverage | 2023-01-01 through 2023-12-31 |
| Calendar complete | Yes |
| Total compressed member bytes | 340,345,393 |
| Total uncompressed member bytes | 5,735,814,202 |
| Raw schedule rows | 17,278,071 |
| Accepted schedule rows | 17,277,644 |
| Rejected schedule rows | 427 |

Every member passed directory, path, encryption, compression-method, size,
schema, CRC and content-digest checks. The accepted archive-content SHA-256 is
`2840dad43241cd0217036fa86eecd1507f59cb9d0bc0e929adae007d74868e88`.
The canonical audit SHA-256 is
`3b78a225f09184d4b8260948da62d1a506b5e417dd9fc3db3bb9fe9a5f7458f5`.

The local JSON audit is `1,143,967` bytes with SHA-256
`926f84c87410a66ee201f45ffd99c600100ab8f31a3edbe7cff2d8fe32ffbe59`.
It remains under the ignored `global/data/derived/` directory because it
contains row-level source diagnostics.

## Rejected rows

| Validation reason | Rows |
| --- | ---: |
| Origin and destination are identical | 365 |
| No weekday is active | 42 |
| Equal departure and arrival clocks imply an unsupported 24-hour stage | 20 |

The rejected rows are explicit invalid schedule definitions, not silently
repaired values. Accepted plus rejected rows reconcile exactly to the raw row
count.

## Decision

The archive passes the source-integrity gate for the reviewed 2023 annual
retrospective evaluation. The next stage must still join each selected schedule
to hash-pinned VRA outcomes, report the exact-join cohort and selection rate,
evaluate seasonal and cold-start slices, and retain the hard
`publishable: false` / `point_in_time_backtest: false` boundary. Passing this
archive audit alone does not authorize artifact export or deployment.
