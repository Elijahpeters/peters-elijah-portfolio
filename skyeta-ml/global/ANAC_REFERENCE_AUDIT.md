# ANAC airport reference audit — 2026-08-09

This is the reproducibility summary for the first full offline preparation of
SkyETA's Brazilian aerodrome reference. The 31.8 MB derived JSON remains under
the ignored `global/data/derived/` directory; raw source files are not committed.

## Bound source files

| Source | Snapshot / release | SHA-256 |
| --- | --- | --- |
| ANAC public aerodromes | Wayback capture `2025-04-18T15:32:53Z`; source updated `2025-04-15` | `43c33fc83f3ae1377dd9dd8cee99c8f1f555c1737590745b053ca1cc4dfd1775` |
| ANAC private aerodromes | Wayback capture `2024-11-02T01:44:36Z`; source updated `2024-11-01` | `0fb904d1381a214fe4de441306ee41f1577f5f917d9c65e13781c49c169f56e4` |
| Timezone Boundary Builder | comprehensive land-only release `2026c`, commit `7c04f5c` | `7d3f0c5a33b6acd891335c0ad5ba767736b6914cb1a1d68c71921c17ce358948` |
| `airportsdata` | package data dated `2026-08-03` | `fca6a89a336c154e86174ba933372de118d15e09a1cfa01559e0b9fd2b1e7fe0` |

## Reconciled results

- ANAC source rows: 3,875.
- Official ICAO/CIAD records accepted: 3,775.
- Source rows rejected with explicit reasons: 100 (one public row missing the
  required state and 99 private rows without a usable official ICAO identity).
- Unique timezone assignments accepted after the centre plus 1 km/16-bearing
  guard check: 3,729.
- Timezone assignments rejected near a boundary: 46.
- Safe IATA enrichments: 268.
- Official ICAO-only identities retained: 3,461.
- Secondary-coordinate manual-review decisions: 77.
- Secondary identity/coordinate conflicts: 869 (835 more than 5 km from the
  official ANAC coordinate and 34 country mismatches). None supplied an IATA
  value to the accepted reference.
- Official aerodromes with no exact secondary ICAO row: 1,605.
- Exact secondary rows without an IATA code: 910.

The path-independent prepared-reference digest is:

`f3534c1099975d8a6de84dc8915fa94ae84541962df4096d0072378632e1dffe`

## Interpretation

ANAC identity and coordinates remain authoritative. `airportsdata` is only a
secondary IATA/quality signal; its pseudo-ICAO and stale-coordinate collisions
are not allowed to overwrite an ANAC fact. An aerodrome rejected by the
timezone guard has no fallback timezone in the artifact. This reference is an
input to a Brazil/Brazil-touching model and is not evidence of worldwide flight
outcome coverage.
