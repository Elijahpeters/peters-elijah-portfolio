# SkyETA web intelligence boundary

SkyETA remains free to travelers and does not collect payment. Its web layer is
a cited **Live Context** service, not a substitute for the trained reliability
model and not an excuse to invent worldwide coverage.

## Three separate products in one interface

| Object | Purpose | Required evidence |
| --- | --- | --- |
| Historical prediction | Estimate delay/cancellation probability for a stated model horizon and coverage area | Model version, calibration, data coverage and training provenance |
| Live fact | Report current weather, airport disruption or an official airline/airport notice | Authority, source URL, published/valid/retrieved times, freshness and content digest |
| Explanation | Translate the prediction and live facts into clear traveler language | Exact prediction/fact IDs supporting each sentence |

A live fact never silently adds or subtracts percentage points from the model.
For example, a current TAF may justify “thunderstorms may affect operations,”
but not “risk increased by 12%” until a separate weather-nowcast model has been
trained, calibrated and backtested.

## Stage 1: no paid account

1. Add a server-side adapter for the official
   [AviationWeather.gov Data API](https://connect.aviationweather.gov/data/api/):
   METAR, TAF and international SIGMET results, each with source and freshness.
   The API has no key, but browser CORS is disabled, so clients must call a
   SkyETA server endpoint. Respect the documented 100-request/minute ceiling,
   avoid polling a thread more than once per minute, and cap every response.
2. Add the official FAA airport-status feed for U.S. airport-level delays. It
   is general airport context, not flight-specific status and not worldwide
   NOTAM coverage.
3. Maintain a reviewed registry of official airline and airport alert pages or
   RSS/Atom feeds. Each registry entry records its allowed domain, review date,
   retrieval method and cache policy.
4. Display a separate “Live context” panel with “Sources checked,” retrieved
   time, stale/unavailable states and direct links.

Suggested operational caches are 60 seconds for METAR/SIGMET and 10 minutes
for TAF, subject to the provider's current terms and headers.

## General web search

There is no genuinely free, anonymous, production-grade worldwide search API.
Do not scrape consumer search pages or ship a private key to the browser.

- Tavily's free development allowance is suitable for bounded testing, not an
  unrestricted public deployment.
- Brave Search is a later production option with a hard quota and budget; its
  default terms restrict storage and prohibit training on search results.
- SerpAPI's free allowance is suitable only for low-volume experiments.
- Google Custom Search is closed to new customers and Bing Search API has been
  retired, so neither is a new foundation.

When account approval and a budget exist, add a server-side
`WebSearchProvider` interface. Query only route/airport/airline operational
topics, prefer audited official domains, store citations rather than
provider-generated answers, and fail visibly when quota is exhausted.

## NOTAM boundary

SkyETA must not claim machine-readable worldwide NOTAM coverage today. FAA NMS
API access requires approval; EUROCONTROL machine access requires an agreement
and may carry royalties/insurance obligations. Public/manual portals do not
grant automated redistribution rights.

Until licensed access exists, call available material “airport/airspace live
context,” state its geography and freshness, and show `Unknown` when no
authoritative feed is available.

## Security and trust gates

- Keep provider keys server-side and out of client bundles and Git.
- Allow only reviewed HTTPS domains; block private IPs, localhost and unsafe
  redirects to prevent SSRF.
- Revalidate every redirect, cap response bytes and time, sanitize HTML, and
  isolate retrieved text from system/tool instructions.
- Rate-limit by client and route; use conditional requests and provider-specific
  caches.
- Never treat a search snippet as an official source merely because it says so.
- Preserve source URL, timestamps and digest for every displayed fact.
- Do not train on retrieved results unless a separate rights review approves it.

Booking remains an outbound handoff to an approved airline/provider in a new
tab. That provider—not SkyETA—handles payment, refunds and booking support.
