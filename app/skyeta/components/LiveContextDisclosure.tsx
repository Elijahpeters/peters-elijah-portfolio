"use client";

import { useEffect, useId, useRef, useState } from "react";

import type { FlightSegment } from "../../types/flight-booking";
import styles from "../booking.module.css";
import {
  assessForecastCoverage,
  createLiveContextRequestCache,
  forecastCoverageCopy,
  retryCountdownLabel,
  scheduledOccurrences,
  selectLiveContextAirports,
} from "./live-context-client";

const AWC_API_ORIGIN = "https://aviationweather.gov";
const AWC_DOCUMENTATION_URL =
  "https://www.connect.aviationweather.gov/data/api/";
const AWC_CATALOGUE_URL =
  "https://www.connect.aviationweather.gov/data/cache/stations.cache.json.gz";

type Observation = {
  observedAt: string | null;
  rawText: string | null;
  flightCategory: "VFR" | "MVFR" | "IFR" | "LIFR" | null;
  temperatureC: number | null;
  dewpointC: number | null;
  windDirectionDegrees: number | null;
  windSpeedKnots: number | null;
  windGustKnots: number | null;
  visibilityMiles: string | null;
};

type Forecast = {
  issuedAt: string | null;
  validFrom: string | null;
  validTo: string | null;
  rawText: string | null;
};

type AirportContext = {
  iata: string;
  icao: string | null;
  observation: Observation | null;
  forecast: Forecast | null;
  datasetFetchedAt: {
    metar: string | null;
    taf: string | null;
  };
  sourceLinks: {
    observation: string | null;
    forecast: string | null;
  } | null;
};

type LiveContextPayload = {
  ok: true;
  partial: boolean;
  source: {
    name: "NOAA Aviation Weather Center";
    documentationUrl: typeof AWC_DOCUMENTATION_URL;
    stationCatalogue: {
      url: typeof AWC_CATALOGUE_URL;
      version: string;
      sha256: string;
    };
  };
  airports: AirportContext[];
  unavailable: Array<"metar" | "taf">;
  retryAfterSeconds: number;
};

type LoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; data: LiveContextPayload }
  | { status: "error"; message: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isNullableNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function isOfficialAwcUrl(value: unknown, pathname: string): value is string {
  if (typeof value !== "string") return false;
  try {
    const url = new URL(value);
    return url.origin === AWC_API_ORIGIN && url.pathname === pathname;
  } catch {
    return false;
  }
}

function isNullableOfficialAwcUrl(
  value: unknown,
  pathname: string,
): value is string | null {
  return value === null || isOfficialAwcUrl(value, pathname);
}

function isObservation(value: unknown): value is Observation {
  return (
    isRecord(value) &&
    isNullableString(value.observedAt) &&
    isNullableString(value.rawText) &&
    (value.flightCategory === null ||
      value.flightCategory === "VFR" ||
      value.flightCategory === "MVFR" ||
      value.flightCategory === "IFR" ||
      value.flightCategory === "LIFR") &&
    isNullableNumber(value.temperatureC) &&
    isNullableNumber(value.dewpointC) &&
    isNullableNumber(value.windDirectionDegrees) &&
    isNullableNumber(value.windSpeedKnots) &&
    isNullableNumber(value.windGustKnots) &&
    isNullableString(value.visibilityMiles)
  );
}

function isForecast(value: unknown): value is Forecast {
  return (
    isRecord(value) &&
    isNullableString(value.issuedAt) &&
    isNullableString(value.validFrom) &&
    isNullableString(value.validTo) &&
    isNullableString(value.rawText)
  );
}

function isAirportContext(value: unknown): value is AirportContext {
  return (
    isRecord(value) &&
    typeof value.iata === "string" &&
    /^[A-Z]{3}$/.test(value.iata) &&
    (value.icao === null ||
      (typeof value.icao === "string" && /^[A-Z0-9]{4}$/.test(value.icao))) &&
    (value.observation === null || isObservation(value.observation)) &&
    (value.forecast === null || isForecast(value.forecast)) &&
    isRecord(value.datasetFetchedAt) &&
    isNullableString(value.datasetFetchedAt.metar) &&
    isNullableString(value.datasetFetchedAt.taf) &&
    (value.sourceLinks === null ||
      (isRecord(value.sourceLinks) &&
        isNullableOfficialAwcUrl(
          value.sourceLinks.observation,
          "/api/data/metar",
        ) &&
        isNullableOfficialAwcUrl(value.sourceLinks.forecast, "/api/data/taf")))
  );
}

function parsePayload(value: unknown): LiveContextPayload | null {
  if (
    !isRecord(value) ||
    value.ok !== true ||
    typeof value.partial !== "boolean" ||
    !isRecord(value.source) ||
    value.source.name !== "NOAA Aviation Weather Center" ||
    value.source.documentationUrl !== AWC_DOCUMENTATION_URL ||
    !isRecord(value.source.stationCatalogue) ||
    value.source.stationCatalogue.url !== AWC_CATALOGUE_URL ||
    typeof value.source.stationCatalogue.version !== "string" ||
    !/^[a-f0-9]{64}$/.test(String(value.source.stationCatalogue.sha256)) ||
    !Array.isArray(value.airports) ||
    !value.airports.every(isAirportContext) ||
    !Array.isArray(value.unavailable) ||
    !value.unavailable.every((entry) => entry === "metar" || entry === "taf") ||
    typeof value.retryAfterSeconds !== "number" ||
    !Number.isFinite(value.retryAfterSeconds) ||
    value.retryAfterSeconds < 0
  ) {
    return null;
  }
  return value as LiveContextPayload;
}

const liveContextRequests = createLiveContextRequestCache({
  parse: parsePayload,
  timeoutMs: 8_000,
  ttlMs: 60_000,
  maxEntries: 40,
});

function utcLabel(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return (
    new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "UTC",
    }).format(date) + " UTC"
  );
}

function categoryCopy(category: Observation["flightCategory"]): string | null {
  if (category === "VFR") return "Generally good visibility and cloud ceiling";
  if (category === "MVFR") return "Reduced visibility or a lower cloud ceiling";
  if (category === "IFR") return "Low visibility or a low cloud ceiling";
  if (category === "LIFR") return "Very low visibility or cloud ceiling";
  return null;
}

function observationFacts(observation: Observation): string[] {
  const facts: string[] = [];
  if (observation.temperatureC !== null) {
    facts.push(`${Math.round(observation.temperatureC)}°C`);
  }
  if (observation.windSpeedKnots !== null) {
    const direction =
      observation.windDirectionDegrees === null
        ? "Variable wind"
        : `Wind ${Math.round(observation.windDirectionDegrees)}°`;
    const gust =
      observation.windGustKnots === null
        ? ""
        : `, gusting ${Math.round(observation.windGustKnots)} kt`;
    facts.push(
      `${direction} at ${Math.round(observation.windSpeedKnots)} kt${gust}`,
    );
  }
  if (observation.visibilityMiles !== null) {
    facts.push(`Visibility ${observation.visibilityMiles} mi`);
  }
  return facts;
}

function FeedCheckedAt({
  label,
  value,
}: {
  label: string;
  value: string | null;
}) {
  const formatted = utcLabel(value);
  return formatted ? (
    <small>
      {label} feed checked <time dateTime={value ?? undefined}>{formatted}</time>
    </small>
  ) : null;
}

function AirportWeatherCard({
  airport,
  segments,
}: {
  airport: AirportContext;
  segments: FlightSegment[];
}) {
  const occurrences = scheduledOccurrences(segments, airport.iata);
  const coverage = airport.forecast
    ? assessForecastCoverage(
        airport.forecast.validFrom,
        airport.forecast.validTo,
        occurrences,
      )
    : null;
  const facts = airport.observation
    ? observationFacts(airport.observation)
    : [];
  const category = airport.observation
    ? categoryCopy(airport.observation.flightCategory)
    : null;

  return (
    <article>
      <span>
        {airport.iata}
        {airport.icao
          ? ` · AWC-listed weather station ${airport.icao}`
          : " · Weather-station match unavailable"}
      </span>
      {!airport.icao ? (
        <>
          <strong>No validated AWC weather-station match</strong>
          <p>SkyETA will not guess a weather station for this airport.</p>
        </>
      ) : !airport.observation && !airport.forecast ? (
        <>
          <strong>No current terminal report returned</strong>
          <p>
            The Aviation Weather Center feed returned no recent observation or
            forecast for this weather station.
          </p>
          <FeedCheckedAt
            label="Observation"
            value={airport.datasetFetchedAt.metar}
          />
          <FeedCheckedAt label="Forecast" value={airport.datasetFetchedAt.taf} />
        </>
      ) : (
        <>
          <strong>
            {airport.observation?.flightCategory ?? "Current airport weather"}
          </strong>
          {category ? <p>{category}.</p> : null}
          {facts.length ? <p>{facts.join(" · ")}</p> : null}
          {airport.observation?.observedAt ? (
            <small>
              Weather observed {utcLabel(airport.observation.observedAt)}
            </small>
          ) : null}
          <FeedCheckedAt
            label="Observation"
            value={airport.datasetFetchedAt.metar}
          />
          {airport.forecast ? (
            <p>
              Terminal forecast
              {airport.forecast.validFrom && airport.forecast.validTo
                ? ` valid ${utcLabel(airport.forecast.validFrom)} to ${utcLabel(airport.forecast.validTo)}`
                : " available"}
              . {coverage ? forecastCoverageCopy(coverage) : null}
            </p>
          ) : null}
          <FeedCheckedAt label="Forecast" value={airport.datasetFetchedAt.taf} />
          {airport.observation?.rawText || airport.forecast?.rawText ? (
            <details className={styles.liveContextRaw}>
              <summary>Read raw AWC report</summary>
              {airport.observation?.rawText ? (
                <code>{airport.observation.rawText}</code>
              ) : null}
              {airport.forecast?.rawText ? (
                <code>{airport.forecast.rawText}</code>
              ) : null}
            </details>
          ) : null}
        </>
      )}
      {airport.sourceLinks ? (
        <div className={styles.liveContextLinks}>
          {airport.sourceLinks.observation ? (
            <a
              href={airport.sourceLinks.observation}
              target="_blank"
              rel="noopener noreferrer"
            >
              AWC observation data ↗
            </a>
          ) : null}
          {airport.sourceLinks.forecast ? (
            <a
              href={airport.sourceLinks.forecast}
              target="_blank"
              rel="noopener noreferrer"
            >
              AWC forecast data ↗
            </a>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

export default function LiveContextDisclosure({
  segments,
}: {
  segments: FlightSegment[];
}) {
  const lookup = selectLiveContextAirports(segments);
  const [state, setState] = useState<LoadState>({ status: "idle" });
  const [retryDeadline, setRetryDeadline] = useState<number | null>(null);
  const [retryRemaining, setRetryRemaining] = useState(0);
  const requestSequence = useRef(0);
  const retryStatusId = useId();

  useEffect(
    () => () => {
      // Shared requests remain reusable by other cards, but this card must not
      // update state after it has unmounted.
      requestSequence.current += 1;
    },
    [],
  );

  useEffect(() => {
    if (retryDeadline === null) return;
    const timer = window.setInterval(() => {
      const remaining = Math.max(
        0,
        Math.ceil((retryDeadline - Date.now()) / 1_000),
      );
      setRetryRemaining(remaining);
      if (remaining === 0) window.clearInterval(timer);
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [retryDeadline]);

  async function load(force = false) {
    if (lookup.codes.length === 0 || state.status === "loading") return;
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    setRetryDeadline(null);
    setRetryRemaining(0);
    setState({ status: "loading" });
    try {
      const data = await liveContextRequests.load(lookup.codes, { force });
      if (data.partial) liveContextRequests.invalidate(lookup.codes);
      if (requestSequence.current !== sequence) return;
      const retrySeconds = Math.max(
        0,
        Math.min(3_600, Math.ceil(data.retryAfterSeconds)),
      );
      if (retrySeconds > 0) {
        setRetryDeadline(Date.now() + retrySeconds * 1_000);
        setRetryRemaining(retrySeconds);
      }
      setState({ status: "ready", data });
    } catch {
      if (requestSequence.current !== sequence) return;
      setState({
        status: "error",
        message:
          "Current airport reports are unavailable. Your fare and SkyETA delay estimate are unaffected.",
      });
    }
  }

  if (lookup.codes.length === 0) return null;

  return (
    <details
      className={`${styles.intelligenceDisclosure} ${styles.liveContextDisclosure}`}
      onToggle={(event) => {
        if (event.currentTarget.open && state.status === "idle") void load();
      }}
    >
      <summary>
        <span>Live airport context</span>
        <em>Not included in the delay percentage</em>
      </summary>
      <div className={`${styles.intelligencePanel} ${styles.liveContextPanel}`}>
        <div className={styles.intelligenceHeading}>
          <span>Current AWC feed</span>
          <strong>
            Weather reports carried by the Aviation Weather Center feed
          </strong>
          <p>
            These time-sensitive observations and terminal forecasts are shown
            separately. They do not change SkyETA&apos;s trained delay percentage.
          </p>
        </div>

        {state.status === "idle" ? (
          <p className={styles.liveContextStatus} role="status">
            Open this panel to request current airport conditions.
          </p>
        ) : state.status === "loading" ? (
          <p className={styles.liveContextStatus} role="status">
            Checking the current Aviation Weather Center feed…
          </p>
        ) : state.status === "error" ? (
          <div className={styles.intelligenceError} role="status">
            <p className={styles.liveContextStatus}>{state.message}</p>
            <button type="button" onClick={() => void load(true)}>
              Try again
            </button>
          </div>
        ) : (
          <>
            <div className={styles.liveContextGrid}>
              {state.data.airports.map((airport) => (
                <AirportWeatherCard
                  key={airport.iata}
                  airport={airport}
                  segments={segments}
                />
              ))}
            </div>
            {lookup.limited ? (
              <p className={styles.liveContextStatus}>
                This itinerary uses {lookup.totalUnique} airports. SkyETA shows
                the first origin, final destination and up to two connection
                airports here.
              </p>
            ) : null}
            {state.data.partial ? (
              <p className={styles.liveContextStatus} role="status">
                Part of the Aviation Weather Center feed was unavailable, so only
                facts that were returned are shown.
              </p>
            ) : null}
            {state.data.partial ? (
              <div className={styles.liveContextRetry}>
                <p
                  id={retryStatusId}
                  role="status"
                  aria-live="polite"
                  aria-atomic="true"
                >
                  {retryCountdownLabel(retryRemaining)}
                </p>
                <button
                  type="button"
                  disabled={retryRemaining > 0}
                  aria-describedby={retryStatusId}
                  onClick={() => void load(true)}
                >
                  Refresh live airport context
                </button>
              </div>
            ) : null}
            <p className={styles.intelligenceNote}>
              Source: {state.data.source.name}. Weather-station identifiers were
              validated against AWC catalogue snapshot {" "}
              {state.data.source.stationCatalogue.version}. Dataset check times
              are shown per airport above. Reports may be unavailable at some
              airports. Read the {" "}
              <a
                href={state.data.source.documentationUrl}
                target="_blank"
                rel="noopener noreferrer"
              >
                official AWC data documentation
              </a>
              .
            </p>
          </>
        )}
      </div>
    </details>
  );
}
