# SkyETA global model: data access and governance

## Current decision

No source is currently approved for training or advertising a **worldwide**
SkyETA model. Worldwide predictions must remain disabled until the rights and
coverage gates below are satisfied. A provider API returning some international
flights is not, by itself, permission or sufficient evidence to train a global
model.

No automation may purchase a plan, accept provider terms, scrape a website, or
send a permission request. Those actions require Peters Elijah Temidayo's direct
review and approval.

## Source register

| Source | Status for model training | Permitted scope / blocking issue |
| --- | --- | --- |
| U.S. Bureau of Transportation Statistics (BTS) Reporting Carrier On-Time Performance | **Approved: regional only** | Existing U.S. domestic model. Preserve the download URL, retrieval date, file hashes and BTS field definitions. It does not support non-U.S. claims. |
| Brazil ANAC Voo Regular Ativo (VRA) open data | **Approved for acquisition and Brazil-scoped experimentation; public deployment conditional** | Provides planned/actual departure and arrival plus operated/cancelled status. Archive the applicable open-data terms before releasing a derived model. Times are reported in Brasilia time and must be retained raw and normalized explicitly. Do not describe this as worldwide coverage. |
| Brazil ANAC SIROS future planned-service snapshots | **Approved for acquisition and Brazil-scoped point-in-time schedule evidence; public deployment conditional** | The official archive contains annual daily-snapshot ZIPs for 2018–2023 and dated daily CSVs for 2024 onward. Each snapshot describes planned operations, UTC departure/arrival times, validity, weekdays, carrier/flight/route, stage and SIROS identity. Select a snapshot proven available by T−7 and join it to VRA outcomes with a complete one-to-one audit. This closes schedule-revision leakage for a Brazil/Brazil-touching model, not worldwide coverage. |
| Brazil ANAC public/private aerodrome registries | **Approved as authoritative Brazilian identity/coordinate reference** | Retain the official URL, timestamped archive URL, embedded update date, file hash and CIAD. The registries do not supply IATA codes or IANA timezones; those fields must remain absent until independently evidenced. |
| Timezone Boundary Builder 2026c | **Approved for reproducible timezone enrichment; attribution/share-alike review required before publishing the derived table** | Use the pinned comprehensive land-only asset and its published SHA-256. It is OSM-derived approximate geometry, not an aviation identity authority. Resolve official coordinates conservatively and fail closed at ambiguous/border locations. Preserve OpenStreetMap attribution and ODbL notices. |
| `mborsetti/airportsdata` | **Approved as secondary reference only** | MIT-licensed package/data, but its `icao` field may be a real ICAO or an internal pseudo-ICAO and accuracy is not guaranteed. Never override official ANAC identity/coordinates. Accept IATA enrichment only after exact-country, coordinate-distance and uniqueness checks. |
| AirLabs Historical Flight Data API | **Blocked for training** | The beta API is useful for per-flight evidence, but it is not a documented bulk training grant; coverage varies, historical depth is unspecified, and free access to actual/delay/status fields is not clearly guaranteed. Written retention, training and derived-deployment rights are required. |
| EUROCONTROL Aviation Data Repository for Research (ADRR) | **Blocked pending user access and terms review** | Europe-only R&D data, four sample months per year with a two-year release lag. Current metadata describes filed arrival, actual arrival and actual off-block time, but not a passenger-published schedule, public flight number or explicit cancellation label. Raw data cannot be redistributed. |
| OpenSky Network | **Blocked as a target-label source** | ADS-B trajectories can become contextual features only after an applicable licence is obtained. OpenSky explicitly does not provide commercial schedules or delay/cancellation labels; full free history is generally limited to eligible institutional research, and operational use requires written permission. |
| OAG Historical Flight Data / Status Direct | **Blocked pending contract** | Technically suitable global scheduled/actual/cancellation data, but bulk access, retention, ML training, trained-weight ownership and public deployment must be granted in writing. A trial alone is not approval. |
| Cirium / FlightStats Historical Flight Status | **Blocked pending contract** | Technically suitable history, but the historical API is a Premium Contract Plan product. Training, retention and derived-use rights are contract-specific. |
| FlightAware AeroAPI historical data | **Blocked pending paid licence and rights review** | Historical access is not available on the Personal tier and has a paid monthly minimum plus usage charges. Do not acquire it without explicit purchase approval. |
| ICAO performance guidance | **Reference only** | Use ICAO definitions to define punctuality labels; ICAO guidance is not a bulk per-flight training dataset. |

Official references:

- BTS: <https://www.transtats.bts.gov/>
- ANAC VRA metadata: <https://www.anac.gov.br/acesso-a-informacao/dados-abertos/areas-de-atuacao/voos-e-operacoes-aereas/voo-regular-ativo-vra/62-voo-regular-ativo-vra>
- ANAC SIROS planned-service metadata: <https://www.anac.gov.br/acesso-a-informacao/dados-abertos/areas-de-atuacao/voos-e-operacoes-aereas/registro-de-servicos-aereos/49-registro-de-servicos-aereos>
- ANAC SIROS dated snapshot archive: <https://siros.anac.gov.br/siros/registros/futuro/serie/>
- ANAC aerodrome data: <https://www.anac.gov.br/acesso-a-informacao/dados-abertos/areas-de-atuacao/aerodromos>
- Timezone Boundary Builder releases: <https://github.com/evansiroky/timezone-boundary-builder/releases>
- OpenStreetMap/ODbL attribution: <https://www.openstreetmap.org/copyright>

## ANAC VRA outcome-observation policy

ANAC's monthly filing deadlines are not public-release timestamps. The agency
validates the supplied data and warns that historical statistical records may
be revised. Current VRA files for older service months also carry later server
modification dates, so today's bytes must not be assigned the original
publication-calendar date without byte-identical historical evidence.

For each exact VRA SHA-256 used by this project:

1. Use the first trusted successful public retrieval time for those exact bytes
   as `outcome_observed_at`.
2. Mark a direct retrieval as `retrospective_holdout_only`.
3. Do not admit its labels to route, carrier, airport or other target-derived
   history features.
4. Describe a service-date temporal split as retrospective evaluation, not a
   historical point-in-time backtest.

A genuine as-of backtest requires an immutable historical CSV capture plus its
publication evidence (or an official version manifest with hashes). Filing
deadlines, filenames, the VRA `Referência` column and current
`Last-Modified` values are insufficient substitutes.

Primary ANAC references:

- VRA metadata: <https://www.anac.gov.br/acesso-a-informacao/dados-abertos/areas-de-atuacao/voos-e-operacoes-aereas/voo-regular-ativo-vra/62-voo-regular-ativo-vra>
- Statistical-data revision notice: <https://www.anac.gov.br/acesso-a-informacao/dados-abertos/areas-de-atuacao/voos-e-operacoes-aereas/dados-estatisticos-do-transporte-aereo/48-dados-estatisticos-do-transporte-aereo>
- VRA quality-check and publication workflow: <https://www.anac.gov.br/assuntos/legislacao/legislacao-1/boletim-de-pessoal/2020/52/mpr590.pdf>
- 2022 publication calendar: <https://www.anac.gov.br/assuntos/legislacao/legislacao-1/portarias/2022/portaria-8414>
- 2023 publication calendar: <https://www.anac.gov.br/assuntos/legislacao/legislacao-1/portarias/2023/portaria-11337>
- `airportsdata` documentation and licence: <https://github.com/mborsetti/airportsdata>
- AirLabs historical API: <https://airlabs.co/docs/historical>
- EUROCONTROL ADRR: <https://www.eurocontrol.int/dashboard/aviation-data-research>
- OpenSky data access: <https://opensky-network.org/data/>
- OAG historical data: <https://www.oag.com/historical-flight-data>
- Cirium historical API: <https://developer.flightstats.com/api-docs/historical-flight-status/v3>
- FlightAware AeroAPI: <https://www.flightaware.com/commercial/aeroapi/>

## Rights required before acquisition or training

Store written evidence that the provider grants all applicable rights below.
Silence, dashboard access, an API key, a free trial, or technical ability to
download data does not count as permission.

1. Automated API acquisition or delivery of a bulk export at the required scale.
2. Storage, backup, normalization, joining and retention of the returned rows.
3. Use of the data for feature engineering, model training, calibration,
   evaluation and periodic retraining.
4. Retention and use of derived artifacts: model weights, encoders, aggregate
   statistics, evaluation results and documentation.
5. Public deployment of predictions in SkyETA and the portfolio, including the
   intended non-transactional traveler-facing use.
6. The intended future commercial use, if any; non-commercial permission must
   not be silently treated as commercial permission.
7. Continued use or a defined deletion obligation after trial, subscription or
   contract termination.
8. Permission to publish aggregate metrics and provider attribution without
   redistributing source rows.
9. Clear geographic, airline, airport, historical-depth, request-volume and
   user/audience limits.
10. A statement of whether provider data may be combined with BTS, ANAC,
    EUROCONTROL, weather and airport reference data.

Archive the signed contract, permission email or terms snapshot with provider,
version/date, permitted purpose, expiry, attribution and deletion requirements.
Raw vendor rows must never be committed to Git or exposed through a public API.

## Minimum coverage gates for a worldwide label

All gates are mandatory. If any fails, release only the explicitly validated
regional model or show historical evidence without calling it a global model.

- **Time:** at least 24 consecutive months of completed operations, covering two
  full seasonal cycles; the newest chronological holdout must remain untouched
  until final evaluation.
- **Geography:** meaningful test coverage in Africa, Asia, Europe, North America,
  South America and Oceania. Each region needs at least 100,000 operated legs,
  5,000 arrivals delayed by at least 15 minutes and 1,000 cancellations, or the
  worldwide claim is withheld for that region.
- **Identity:** operating carrier, flight number, origin, destination and service
  date present on at least 98% of scheduled records. Marketing codeshares must
  not be counted as separate physical flights.
- **Outcome completeness:** known operated/cancelled status on at least 95% of
  the scheduled universe and both scheduled and actual arrival times on at
  least 90% of operated legs. A disappeared schedule row must not be assumed to
  be a cancellation unless the provider documents that rule.
- **Timestamp quality:** raw local timestamp, source timezone/offset and UTC
  normalization retained. DST, midnight crossing and dateline tests must pass.
- **Label consistency:** the primary delay label is actual in-block/gate arrival
  minus scheduled in-block/gate arrival. Runway time must not be mixed with gate
  time without a declared mapping. Report 15+, 30+ and 60+ minute outcomes and
  cancellations separately.
- **Inference parity:** every feature used in training must be available before
  departure in production. Estimated/actual times, final status and post-event
  weather are forbidden training features for a pre-departure prediction.
- **Slice validation:** publish discrimination and calibration by region,
  country, carrier, airport-size band, route-frequency band and season. Refuse
  or back off predictions for unsupported slices rather than applying a global
  average silently.
- **Provenance:** every raw partition and produced artifact must be reproducible
  from the provenance record below.

### Artifact coverage-audit contract

A `validated` artifact is still not publishable merely because
`globalReleaseGatePassed` was set to `true`. Its model card must carry
`dataCoverage.corpusAudit` with all of the following machine-checked evidence:

- `completedMonths`: at least 24 unique, chronological, consecutive `YYYY-MM`
  values;
- `scheduledRows`, `identityCompleteRows`, `knownOutcomeRows`, `operatedRows`,
  `operatedRowsWithArrivalTimes`, `arrival15DelayedRows`, and
  `cancellationRows`, with `dataCoverage.rows` equal to `scheduledRows`;
- `regions`: entries for Africa, Asia, Europe, North America, South America and
  Oceania using the same complete count vocabulary;
- `months` and `sources`: exact count rollups for every completed month and
  every model-card source;
- `partitions`: normalized-corpus partitions with a stable ID, source ID,
  month, HTTPS source URL, retrieval time, raw-file SHA-256, complete counts,
  and the exact region breakdown. Partition totals must reproduce the month,
  source, region, and global rollups exactly.

Publication validation checks the 98%, 95%, and 90% completeness thresholds
and every per-region minimum above. It also binds `scheduledRows` to a digest
and count of the normalized record IDs used to prepare the model. The boolean
remains a human review signal; it is not a substitute for the structured audit.

Every model-card source must have a unique `sourceId`, an explicit
`rightsStatus`, and structured evidence containing its type, human-reviewable
reference, HTTPS URL, review time, and SHA-256. Publication accepts only
sources explicitly approved for training and derived-model publication;
placeholder evidence containing terms such as test, synthetic, fixture,
not-real, fake, demo, or unknown is rejected.

Untouched-test evaluation must include exhaustive, disjoint slice reports for
origin region, origin country, operating carrier, airport-history size,
route-history frequency, and origin-local season. Every slice reports its
population and all five heads' sample counts, positive counts, ROC AUC,
average precision, Brier score, and log loss. Slice populations and head
populations must aggregate exactly to the untouched-test totals. No
slice-performance acceptance threshold is inferred by this structural check.

## Required provenance record

Record these fields for every raw partition and propagate their identifiers into
the trained model card:

- `source_provider`, `product_name`, `endpoint_or_export`, `api_version`
- `licence_or_contract_id`, `terms_version`, `permission_evidence`,
  `rights_expiry`, `retention_or_deletion_rule`
- `source_url`, `request_or_export_parameters`, `retrieved_at_utc`
- `raw_file_sha256`, `raw_bytes`, `raw_row_count`, `accepted_row_count`,
  `rejected_row_count`
- `coverage_start_utc`, `coverage_end_utc`, `countries`, `airports`, `carriers`
- operating and marketing carrier identifiers, flight number, service date,
  origin, destination, aircraft/equipment identifier where licensed
- raw scheduled/estimated/actual timestamps, their event type (gate or runway),
  supplied timezone/offset, normalized UTC value and `observed_or_inferred`
- final status, cancellation/diversion flag, delay minutes and label version
- provider record ID, source update/correction time, deduplication key and
  codeshare-resolution rule
- ingestion pipeline version/commit, schema version, quality report ID,
  train/validation/test split assignment and model artifact ID

## Permission request templates

Send each request manually from Peters Elijah Temidayo's account. Do not include
API keys, passwords or other secrets.

### AirLabs

**Subject:** Written permission for AirLabs historical data in the SkyETA ML model

> Hello AirLabs team,
>
> My name is Peters Elijah Temidayo. I am developing SkyETA, an engineering
> portfolio project that estimates pre-departure flight-delay risk and explains
> the result to travelers. I am evaluating the AirLabs Historical Flight Data
> API (currently documented as beta) as a source for a worldwide model.
>
> Please confirm in writing whether I may: (1) acquire historical records at
> bulk/model-training scale; (2) retain and normalize scheduled/actual departure
> and arrival times, delays, cancellations and diversions; (3) combine them with
> weather and public airport/carrier data; (4) train, calibrate and periodically
> retrain ML models; (5) retain model weights and aggregate statistics after a
> trial or plan ends; and (6) deploy those derived predictions publicly in a
> non-transactional portfolio/travel-assistance website without exposing or
> redistributing raw AirLabs rows.
>
> Please also state the available history depth, regional/airline coverage,
> cancellation completeness, whether missing flights remain represented,
> timestamp semantics/timezones, bulk delivery or pagination options, request
> quota, attribution requirement, retention/deletion requirement, and whether a
> free student/research allocation is available. If future commercial use needs
> separate permission, please distinguish it from the portfolio permission.
>
> Thank you,
> Peters Elijah Temidayo

### OAG

**Subject:** Student/research access and ML derived-use rights for SkyETA

> Hello OAG team,
>
> My name is Peters Elijah Temidayo. I am developing SkyETA, an engineering
> portfolio project that estimates pre-departure flight-delay and cancellation
> risk. I am evaluating OAG Historical Flight Data and Status Direct for a
> worldwide model.
>
> Please confirm whether a student/research trial or data extract is available
> and whether its licence permits me to: retain and normalize historical
> scheduled/actual gate times and status rows; combine them with weather and
> public reference data; train, calibrate and retrain ML models; retain and own
> the resulting weights and aggregate metrics; and deploy predictions publicly
> in a non-transactional portfolio/travel-assistance website without exposing or
> redistributing OAG source records.
>
> Please specify the available history, countries/airlines/airports covered,
> cancellation and codeshare treatment, bulk file/Snowflake/API options,
> timestamp semantics, corrections, volume limits, attribution, retention after
> trial/contract end, deletion obligations, and any separate terms for future
> commercial deployment.
>
> Thank you,
> Peters Elijah Temidayo

### Cirium / FlightStats

**Subject:** Research access and model-training rights for Cirium historical flight status

> Hello Cirium team,
>
> My name is Peters Elijah Temidayo. I am developing SkyETA, an engineering
> portfolio project that estimates pre-departure flight-delay and cancellation
> risk. I am evaluating the Historical Flight Status product, which the developer
> documentation lists under the Premium Contract Plan.
>
> Please advise whether student/research evaluation access or a suitable bulk
> extract is available. I need written confirmation that the licence permits
> retention and normalization of historical scheduled/actual gate times, delays,
> cancellations and diversions; combination with weather and public reference
> data; ML training, calibration and retraining; retention and public use of
> derived model weights and aggregate metrics; and deployment of predictions in
> a non-transactional portfolio/travel-assistance website without redistributing
> raw Cirium records.
>
> Please specify history depth, worldwide coverage, cancellation/codeshare
> semantics, API or bulk-delivery limits, timestamp definitions, attribution,
> retention after access ends, deletion obligations, and whether future
> commercial use requires a separate agreement.
>
> Thank you,
> Peters Elijah Temidayo
