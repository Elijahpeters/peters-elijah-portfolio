# SkyETA weather and pre-departure context

Weather should be included, but only with a precise prediction contract. This
pipeline defines the prediction moment as **three hours before scheduled
departure**. For both the origin and destination it uses the most recent NOAA
observation timestamped at or before that cutoff, with a maximum age of three
hours. It never uses weather observed at departure or arrival after the cutoff.

## Official source

The source is NOAA NCEI's **Global Historical Climatology Network hourly
(GHCNh), Version 1**, the current successor to ISD Global Hourly. NOAA provides
station-year Parquet files over HTTPS with no account, key, or paid service.

- Product: <https://www.ncei.noaa.gov/products/global-historical-climatology-network-hourly>
- Format and quality flags: <https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh_DOCUMENTATION.pdf>
- Station metadata: <https://www.ncei.noaa.gov/oa/global-historical-climatology-network/hourly/doc/ghcnh-station-list.csv>

Run only the small metadata resolution step:

```bash
skyeta-ml/.venv/Scripts/python skyeta-ml/download_weather.py --metadata-only
```

Download the 2025 files after reviewing the manifest:

```bash
skyeta-ml/.venv/Scripts/python skyeta-ml/download_weather.py --year 2025 --workers 4
```

The configured 50 airports covered **78.98% of origin/destination endpoints** in
a January 2025 audit of 539,747 BTS flights. At least one endpoint is covered on
**98.38%** of flights and both endpoints on **59.58%**. Missingness indicators
let the model use one-endpoint weather without inventing the other endpoint.
Five sampled 2025 Parquet files were 1.04-1.15 MB each (Phoenix was 0.89 MB), so
the expected NOAA download is about **50-65 MB**. Four concurrent downloads
should take roughly 5-15 minutes on this PC and the feature join another 3-8
minutes. Allow approximately **250 MB** total disk headroom for the files plus
`pyarrow` in the Python environment. No weather download or model training
starts automatically.

## Features and leakage controls

For both origin and destination, `weather_features.py` produces temperature,
dew point, relative humidity, sea-level pressure, wind speed, wind gust,
nominal-hour precipitation, visibility, ceiling, an adverse-weather indicator,
the oldest used observation age, and the missing fraction.

- BTS local scheduled time is converted with an explicit IANA timezone and its
  historical DST rules. Ambiguous fall-DST times become missing; nonexistent
  spring-DST times shift forward.
- Every lookup is backward-only (`observation_time <= cutoff_time`).
- No report older than three hours is accepted.
- NOAA values with suspect/error/removed/missing quality codes or impossible
  physical ranges become missing.
- Missing airports and variables remain missing and get an explicit missing
  fraction; they are not silently replaced with future or network-wide values.
- The same cutoff instant is used at both endpoints. Destination observations
  therefore describe conditions already known when the prediction is issued,
  not unknowable weather at arrival.

This is a **day-of-flight** model. For a future public prediction, the same
fields must come from a forecast issued by the cutoff or be entered as a stated
scenario. Training on observed arrival-time weather and serving a forecast later
would be leakage and train/serve skew.

For live day-of-flight use, NOAA's [Aviation Weather Center Data
API](https://aviationweather.gov/data/api/) provides no-key METAR observations
and TAF forecasts. Its documented policy disallows browser CORS and applies rate
limits, so a public UI must use a small server-side cached proxy with a custom
user agent; it must not call the service directly from every visitor's browser.

## Other useful pre-departure fields

`predeparture_context.py` adds target-free schedule context fitted on the
training period only: route frequency, carrier-route frequency, origin
weekday/half-hour bank density, and a major-holiday window. For October-December
rows, reuse the January-September maps unchanged. These features use scheduled
service counts, never realized delay outcomes. Holiday definitions can be
audited against the [U.S. Office of Personnel Management schedule](https://www.opm.gov/policy-data-oversight/pay-leave/federal-holidays/).

The next safe extensions are scheduled flight number, airport-specific
departure-bank density by date, and official forecast features archived at a
fixed issue horizon. Avoid actual departure/arrival times, taxi times, delay
causes, post-cutoff weather, and full-year target-derived rates; those leak the
answer or future data.
