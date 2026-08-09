import airportSource from "../../../lib/skyeta/aviation-weather-airports.json" with {
  type: "json",
};
import {
  createQuotaKey,
  DurableRequestLimiter,
  type RateLimitResult,
} from "../../../lib/amadeus/rate-limit.ts";
import {
  isD1DatabaseLike,
  type D1DatabaseLike,
} from "../../../lib/booking/d1.ts";
import {
  BodyTooLargeError,
  readBoundedJson,
} from "../../../lib/http/bounded-json.ts";

const NOAA_API_ORIGIN = "https://aviationweather.gov";
const NOAA_DOCUMENTATION_URL =
  "https://www.connect.aviationweather.gov/data/api/";
const NOAA_CATALOGUE_URL =
  "https://www.connect.aviationweather.gov/data/cache/stations.cache.json.gz";
const NOAA_CATALOGUE_VERSION = "2026-08-09";
const NOAA_CATALOGUE_SHA256 =
  "bac107a0b678647efd8591d594ed1eb1de817d185365d0f0b8fe1f38a59a1723";
const NOAA_CATALOGUE_COMPRESSED_BYTES = 355_855;
const NOAA_CATALOGUE_UNCOMPRESSED_BYTES = 1_939_590;
const NOAA_CATALOGUE_SOURCE_RECORDS = 9_873;
const NOAA_CATALOGUE_VALIDATED_MAPPINGS = 4_719;
const AIRPORTS_DATA_SOURCE_NAME = "mborsetti/airportsdata airports.csv";
const AIRPORTS_DATA_SOURCE_COMMIT =
  "671fa36e373faa3068e15bb453dac96a41087e19";
const AIRPORTS_DATA_SOURCE_URL =
  "https://raw.githubusercontent.com/mborsetti/airportsdata/671fa36e373faa3068e15bb453dac96a41087e19/airportsdata/airports.csv";
const AIRPORTS_DATA_SOURCE_BYTES = 3_076_463;
const AIRPORTS_DATA_SOURCE_SHA256 =
  "fca6a89a336c154e86174ba933372de118d15e09a1cfa01559e0b9fd2b1e7fe0";
const DEFAULT_USER_AGENT =
  "SkyETA/1.0 (+https://peterselijah.name.ng/skyeta)";
const DEFAULT_TIMEOUT_MS = 6_000;
const DEFAULT_METAR_CACHE_TTL_MS = 60_000;
const DEFAULT_TAF_CACHE_TTL_MS = 10 * 60_000;
const AWC_MIN_REQUEST_INTERVAL_MS = 60_000;
const MAX_RESPONSE_BYTES = 256_000;
const MAX_CACHE_ENTRIES = 1_000;
const MAX_AIRPORTS = 4;
const IATA_AIRPORT = /^[A-Z]{3}$/;
const ICAO_AIRPORT = /^[A-Z0-9]{4}$/;

type DatasetKind = "metar" | "taf";
type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;
type ReserveUpstreamRequest = (
  kind: DatasetKind,
  now: number,
) => RateLimitResult | Promise<RateLimitResult>;

type HandlerOptions = {
  fetchImpl?: FetchLike;
  now?: () => number;
  timeoutMs?: number;
  metarCacheTtlMs?: number;
  tafCacheTtlMs?: number;
  maxCacheEntries?: number;
  allowLocalLimiterFallback?: boolean;
  userAgent?: string;
  getDatabase?: () => D1DatabaseLike | Promise<D1DatabaseLike>;
  reserveUpstreamRequest?: ReserveUpstreamRequest;
};

type ParsedQuery =
  | { ok: true; airports: string[] }
  | { ok: false; message: string };

type StationDefinition = {
  icao: string;
  supportsMetar: boolean;
  supportsTaf: boolean;
};

type CacheEntry = {
  expiresAt: number;
  fetchedAt: string;
  value: NoaaObservation | NoaaForecast | null;
};

type DatasetResult = {
  requested: number;
  entries: Map<string, CacheEntry>;
  unavailableReason:
    | "rate_limited"
    | "timeout"
    | "unavailable"
    | null;
  retryAfterSeconds: number;
};

export type NoaaObservation = {
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

export type NoaaForecast = {
  issuedAt: string | null;
  validFrom: string | null;
  validTo: string | null;
  rawText: string | null;
};

export type LiveAirportContext = {
  iata: string;
  icao: string | null;
  observation: NoaaObservation | null;
  forecast: NoaaForecast | null;
  datasetFetchedAt: {
    metar: string | null;
    taf: string | null;
  };
  sourceLinks: {
    observation: string | null;
    forecast: string | null;
  } | null;
};

export const NOAA_LIVE_CONTEXT_SOURCE = {
  name: "NOAA Aviation Weather Center",
  documentationUrl: NOAA_DOCUMENTATION_URL,
  stationCatalogue: {
    url: NOAA_CATALOGUE_URL,
    version: NOAA_CATALOGUE_VERSION,
    sha256: NOAA_CATALOGUE_SHA256,
  },
} as const;

class NoaaProviderError extends Error {
  readonly kind: "timeout" | "unavailable";

  constructor(kind: "timeout" | "unavailable") {
    super(kind);
    this.name = "NoaaProviderError";
    this.kind = kind;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStationTuple(
  value: unknown,
): value is readonly [string, string, boolean, boolean] {
  return (
    Array.isArray(value) &&
    value.length === 4 &&
    typeof value[0] === "string" &&
    IATA_AIRPORT.test(value[0]) &&
    typeof value[1] === "string" &&
    ICAO_AIRPORT.test(value[1]) &&
    typeof value[2] === "boolean" &&
    typeof value[3] === "boolean" &&
    (value[2] || value[3])
  );
}

function validCatalogue(value: unknown): value is {
  airports: Array<readonly [string, string, boolean, boolean]>;
} {
  if (
    !isRecord(value) ||
    value.schemaVersion !== 1 ||
    !isRecord(value.provenance) ||
    value.provenance.sourceName !==
      "NOAA Aviation Weather Center station catalogue" ||
    value.provenance.sourceUrl !== NOAA_CATALOGUE_URL ||
    value.provenance.catalogueVersion !== NOAA_CATALOGUE_VERSION ||
    value.provenance.compressedBytes !== NOAA_CATALOGUE_COMPRESSED_BYTES ||
    value.provenance.compressedSha256 !== NOAA_CATALOGUE_SHA256 ||
    value.provenance.uncompressedBytes !== NOAA_CATALOGUE_UNCOMPRESSED_BYTES ||
    value.provenance.sourceRecords !== NOAA_CATALOGUE_SOURCE_RECORDS ||
    !isRecord(value.provenance.airportIdentitySource) ||
    value.provenance.airportIdentitySource.name !==
      AIRPORTS_DATA_SOURCE_NAME ||
    value.provenance.airportIdentitySource.url !== AIRPORTS_DATA_SOURCE_URL ||
    value.provenance.airportIdentitySource.commit !==
      AIRPORTS_DATA_SOURCE_COMMIT ||
    value.provenance.airportIdentitySource.bytes !==
      AIRPORTS_DATA_SOURCE_BYTES ||
    value.provenance.airportIdentitySource.sha256 !==
      AIRPORTS_DATA_SOURCE_SHA256 ||
    value.provenance.validatedMappings !==
      NOAA_CATALOGUE_VALIDATED_MAPPINGS ||
    !Array.isArray(value.airports) ||
    value.airports.length !== NOAA_CATALOGUE_VALIDATED_MAPPINGS ||
    !value.airports.every(isStationTuple)
  ) {
    return false;
  }
  return true;
}

const STATIONS_BY_IATA = new Map<string, StationDefinition>();
if (validCatalogue(airportSource)) {
  for (const [iata, icao, supportsMetar, supportsTaf] of airportSource.airports) {
    if (!STATIONS_BY_IATA.has(iata)) {
      STATIONS_BY_IATA.set(iata, { icao, supportsMetar, supportsTaf });
    }
  }
}

function safeText(value: unknown, maxLength: number): string | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  return text.length > 0 && text.length <= maxLength ? text : null;
}

function safeNumber(
  value: unknown,
  minimum: number,
  maximum: number,
): number | null {
  return typeof value === "number" &&
    Number.isFinite(value) &&
    value >= minimum &&
    value <= maximum
    ? value
    : null;
}

function safeIsoTime(value: unknown): string | null {
  let timestamp: number;
  if (typeof value === "number" && Number.isFinite(value)) {
    timestamp = value < 10_000_000_000 ? value * 1_000 : value;
  } else if (typeof value === "string" && value.length <= 80) {
    timestamp = Date.parse(value);
  } else {
    return null;
  }
  if (!Number.isFinite(timestamp)) return null;
  const date = new Date(timestamp);
  const year = date.getUTCFullYear();
  return year >= 2000 && year <= 2100 ? date.toISOString() : null;
}

function safeVisibility(value: unknown): string | null {
  if (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= 200
  ) {
    return String(value);
  }
  if (typeof value !== "string") return null;
  const visibility = value.trim();
  return /^\d{1,3}(?:\.\d{1,3})?\+?$/.test(visibility)
    ? visibility
    : null;
}

function safeFlightCategory(
  value: unknown,
): NoaaObservation["flightCategory"] {
  return value === "VFR" ||
    value === "MVFR" ||
    value === "IFR" ||
    value === "LIFR"
    ? value
    : null;
}

function rowIcao(value: Record<string, unknown>): string | null {
  const code = safeText(value.icaoId, 4);
  return code && ICAO_AIRPORT.test(code) ? code : null;
}

function sanitizeObservations(
  rows: unknown[],
  expectedIcaos: Set<string>,
): Map<string, NoaaObservation> {
  const observations = new Map<string, NoaaObservation>();
  for (const candidate of rows) {
    if (!isRecord(candidate)) continue;
    const icao = rowIcao(candidate);
    if (!icao || !expectedIcaos.has(icao)) continue;
    const observation: NoaaObservation = {
      observedAt:
        safeIsoTime(candidate.obsTime) ??
        safeIsoTime(candidate.reportTime) ??
        safeIsoTime(candidate.receiptTime),
      rawText: safeText(candidate.rawOb, 2_000),
      flightCategory: safeFlightCategory(candidate.fltCat),
      temperatureC: safeNumber(candidate.temp, -100, 70),
      dewpointC: safeNumber(candidate.dewp, -100, 70),
      windDirectionDegrees: safeNumber(candidate.wdir, 0, 360),
      windSpeedKnots: safeNumber(candidate.wspd, 0, 300),
      windGustKnots: safeNumber(candidate.wgst, 0, 400),
      visibilityMiles: safeVisibility(candidate.visib),
    };
    if (!observation.observedAt && !observation.rawText) continue;
    const current = observations.get(icao);
    if (
      !current ||
      (observation.observedAt ?? "") > (current.observedAt ?? "")
    ) {
      observations.set(icao, observation);
    }
  }
  return observations;
}

function sanitizeForecasts(
  rows: unknown[],
  expectedIcaos: Set<string>,
): Map<string, NoaaForecast> {
  const forecasts = new Map<string, NoaaForecast>();
  for (const candidate of rows) {
    if (!isRecord(candidate)) continue;
    const icao = rowIcao(candidate);
    if (!icao || !expectedIcaos.has(icao)) continue;
    const forecast: NoaaForecast = {
      issuedAt:
        safeIsoTime(candidate.issueTime) ??
        safeIsoTime(candidate.bulletinTime) ??
        safeIsoTime(candidate.dbPopTime),
      validFrom: safeIsoTime(candidate.validTimeFrom),
      validTo: safeIsoTime(candidate.validTimeTo),
      rawText: safeText(candidate.rawTAF, 4_000),
    };
    if (!forecast.issuedAt && !forecast.validFrom && !forecast.rawText) continue;
    const current = forecasts.get(icao);
    if (!current || (forecast.issuedAt ?? "") > (current.issuedAt ?? "")) {
      forecasts.set(icao, forecast);
    }
  }
  return forecasts;
}

export function parseLiveContextQuery(url: URL): ParsedQuery {
  const airportValues = url.searchParams.getAll("airports");
  const hasUnknownParameter = [...url.searchParams.keys()].some(
    (key) => key !== "airports",
  );
  if (airportValues.length !== 1 || hasUnknownParameter) {
    return {
      ok: false,
      message: "Provide exactly one airports parameter and no other parameters.",
    };
  }

  const airports = airportValues[0].split(",");
  if (
    airports.length < 1 ||
    airports.length > MAX_AIRPORTS ||
    airports.some((airport) => !IATA_AIRPORT.test(airport)) ||
    new Set(airports).size !== airports.length
  ) {
    return {
      ok: false,
      message: "Airports must contain one to four unique uppercase IATA codes.",
    };
  }
  return { ok: true, airports };
}

export function buildNoaaUrl(kind: DatasetKind, icaos: string[]): URL {
  const url = new URL(`/api/data/${kind}`, NOAA_API_ORIGIN);
  url.searchParams.set("ids", [...icaos].sort().join(","));
  url.searchParams.set("format", "json");
  if (kind === "metar") url.searchParams.set("hours", "2");
  return url;
}

function json(
  body: unknown,
  status: number,
  cacheControl: string,
  headers: Record<string, string> = {},
): Response {
  return Response.json(body, {
    status,
    headers: {
      "Cache-Control": cacheControl,
      "Content-Type": "application/json; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
      ...headers,
    },
  });
}

async function fetchDataset(options: {
  kind: DatasetKind;
  icaos: string[];
  fetchImpl: FetchLike;
  timeoutMs: number;
  userAgent: string;
  now: () => number;
}): Promise<{ rows: unknown[]; fetchedAt: string }> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs);
  try {
    const response = await options.fetchImpl(
      buildNoaaUrl(options.kind, options.icaos),
      {
        method: "GET",
        headers: {
          Accept: "application/json",
          "User-Agent": options.userAgent,
        },
        cache: "no-store",
        redirect: "error",
        signal: controller.signal,
      },
    );
    if (response.status === 204) {
      return { rows: [], fetchedAt: new Date(options.now()).toISOString() };
    }
    if (!response.ok) throw new Error("noaa_rejected");
    const payload = await readBoundedJson(response, MAX_RESPONSE_BYTES);
    if (!Array.isArray(payload)) throw new Error("invalid_noaa_response");
    return {
      rows: payload,
      fetchedAt: new Date(options.now()).toISOString(),
    };
  } catch (error) {
    throw new NoaaProviderError(
      controller.signal.aborted
        ? "timeout"
        : error instanceof BodyTooLargeError
          ? "unavailable"
          : "unavailable",
    );
  } finally {
    clearTimeout(timeout);
  }
}

async function environmentDatabase(): Promise<D1DatabaseLike> {
  const workers = await import("cloudflare:workers");
  if (!isD1DatabaseLike(workers.env.DB)) {
    throw new Error("NOAA request quota storage is unavailable.");
  }
  return workers.env.DB;
}

export function createLiveContextHandler(options: HandlerOptions = {}) {
  const fetchImpl = options.fetchImpl ?? globalThis.fetch;
  const now = options.now ?? Date.now;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const metarCacheTtlMs =
    options.metarCacheTtlMs ?? DEFAULT_METAR_CACHE_TTL_MS;
  const tafCacheTtlMs = options.tafCacheTtlMs ?? DEFAULT_TAF_CACHE_TTL_MS;
  const maxCacheEntries = Number.isSafeInteger(options.maxCacheEntries)
    ? Math.max(
        1,
        Math.min(MAX_CACHE_ENTRIES, Math.trunc(options.maxCacheEntries!)),
      )
    : MAX_CACHE_ENTRIES;
  const userAgent = options.userAgent ?? DEFAULT_USER_AGENT;
  const getDatabase = options.getDatabase ?? environmentDatabase;
  const allowLocalLimiterFallback =
    options.allowLocalLimiterFallback === true;
  const cache = new Map<string, CacheEntry>();
  const datasetInFlight = new Map<DatasetKind, Promise<void>>();
  const localNextAllowedAt = new Map<DatasetKind, number>();
  let durableLimiter: Promise<DurableRequestLimiter> | null = null;
  let durableUnavailable = false;
  let durableReady = false;

  function localReserve(kind: DatasetKind, current: number): RateLimitResult {
    const nextAllowed = localNextAllowedAt.get(kind) ?? 0;
    if (current < nextAllowed) {
      return {
        allowed: false,
        retryAfterSeconds: Math.max(1, Math.ceil((nextAllowed - current) / 1_000)),
      };
    }
    localNextAllowedAt.set(kind, current + AWC_MIN_REQUEST_INTERVAL_MS);
    return { allowed: true, retryAfterSeconds: 0 };
  }

  async function defaultReserve(
    kind: DatasetKind,
    current: number,
  ): Promise<RateLimitResult> {
    if (!durableUnavailable) {
      try {
        durableLimiter ??= Promise.resolve(getDatabase()).then(
          (database) => {
            durableReady = true;
            return new DurableRequestLimiter(database);
          },
        );
        const limiter = await durableLimiter;
        const result = await limiter.consume({
          key: await createQuotaKey("noaa-awc-dataset", kind),
          now: current,
          windowMs: AWC_MIN_REQUEST_INTERVAL_MS,
          limit: 1,
        });
        const shadowUntil =
          current +
          (result.allowed
            ? AWC_MIN_REQUEST_INTERVAL_MS
            : Math.max(1, result.retryAfterSeconds) * 1_000);
        localNextAllowedAt.set(
          kind,
          Math.max(localNextAllowedAt.get(kind) ?? 0, shadowUntil),
        );
        return result;
      } catch {
        // Once durable quota storage has been reached, an operational D1
        // failure must fail closed. Falling back to an isolate-local allowance
        // here could violate AWC's cross-instance request interval.
        if (durableReady) {
          return {
            allowed: false,
            retryAfterSeconds: Math.max(
              60,
              Math.ceil(
                ((localNextAllowedAt.get(kind) ?? current) - current) / 1_000,
              ),
            ),
          };
        }
        durableLimiter = null;
        if (!allowLocalLimiterFallback) {
          // A production handler with no durable quota binding cannot safely
          // coordinate AWC requests across isolates, so it must fail closed.
          return { allowed: false, retryAfterSeconds: 60 };
        }
        // Explicit local/test mode uses the conservative in-handler limiter.
        durableUnavailable = true;
      }
    }
    return localReserve(kind, current);
  }

  const reserveUpstreamRequest =
    options.reserveUpstreamRequest ?? defaultReserve;

  function cacheKey(kind: DatasetKind, icao: string): string {
    return `${kind}:${icao}`;
  }

  function pruneCache(current: number): void {
    for (const [key, entry] of cache) {
      if (entry.expiresAt <= current) cache.delete(key);
    }
    while (cache.size >= maxCacheEntries) {
      const oldest = cache.keys().next().value;
      if (oldest === undefined) break;
      cache.delete(oldest);
    }
  }

  function readEntries(
    kind: DatasetKind,
    icaos: string[],
    current: number,
  ): Map<string, CacheEntry> {
    const entries = new Map<string, CacheEntry>();
    for (const icao of icaos) {
      const key = cacheKey(kind, icao);
      const entry = cache.get(key);
      if (entry && entry.expiresAt > current) entries.set(icao, entry);
      else if (entry) cache.delete(key);
    }
    return entries;
  }

  async function fetchAndCache(
    kind: DatasetKind,
    icaos: string[],
  ): Promise<void> {
    const result = await fetchDataset({
      kind,
      icaos,
      fetchImpl,
      timeoutMs,
      userAgent,
      now,
    });
    const expected = new Set(icaos);
    const sanitized =
      kind === "metar"
        ? sanitizeObservations(result.rows, expected)
        : sanitizeForecasts(result.rows, expected);
    const current = now();
    for (const icao of icaos) {
      const key = cacheKey(kind, icao);
      if (!cache.has(key)) pruneCache(current);
      cache.set(key, {
        expiresAt:
          current + (kind === "metar" ? metarCacheTtlMs : tafCacheTtlMs),
        fetchedAt: result.fetchedAt,
        value: sanitized.get(icao) ?? null,
      });
    }
  }

  async function getDataset(
    kind: DatasetKind,
    requestedIcaos: string[],
  ): Promise<DatasetResult> {
    const icaos = [...new Set(requestedIcaos)].sort();
    if (icaos.length === 0) {
      return {
        requested: 0,
        entries: new Map(),
        unavailableReason: null,
        retryAfterSeconds: 0,
      };
    }

    let entries = readEntries(kind, icaos, now());
    let missing = icaos.filter((icao) => !entries.has(icao));
    if (missing.length === 0) {
      return {
        requested: icaos.length,
        entries,
        unavailableReason: null,
        retryAfterSeconds: 0,
      };
    }

    const pending = datasetInFlight.get(kind);
    if (pending) {
      try {
        await pending;
      } catch {
        // The initiating request reports the upstream error. Recheck the
        // per-station cache before deciding whether this request needs a slot.
      }
      entries = readEntries(kind, icaos, now());
      missing = icaos.filter((icao) => !entries.has(icao));
      if (missing.length === 0) {
        return {
          requested: icaos.length,
          entries,
          unavailableReason: null,
          retryAfterSeconds: 0,
        };
      }
    }

    let reservation: RateLimitResult;
    try {
      reservation = await reserveUpstreamRequest(kind, now());
    } catch {
      reservation = localReserve(kind, now());
    }
    if (!reservation.allowed) {
      const newlyPending = datasetInFlight.get(kind);
      if (newlyPending) {
        try {
          await newlyPending;
        } catch {
          // The initiating request reports the upstream error. This request
          // can still reuse any station entries that were successfully cached.
        }
        entries = readEntries(kind, icaos, now());
        missing = icaos.filter((icao) => !entries.has(icao));
        if (missing.length === 0) {
          return {
            requested: icaos.length,
            entries,
            unavailableReason: null,
            retryAfterSeconds: 0,
          };
        }
      }
      return {
        requested: icaos.length,
        entries,
        unavailableReason: "rate_limited",
        retryAfterSeconds: reservation.retryAfterSeconds,
      };
    }

    // Another request can acquire the shared dataset slot while this request
    // is awaiting durable quota storage. Never issue a second same-dataset
    // upstream request in that race; reuse what the first request fetched.
    const newlyPending = datasetInFlight.get(kind);
    if (newlyPending) {
      try {
        await newlyPending;
      } catch {
        // Re-read the cache below. The initiating request owns its error.
      }
      entries = readEntries(kind, icaos, now());
      missing = icaos.filter((icao) => !entries.has(icao));
      if (missing.length === 0) {
        return {
          requested: icaos.length,
          entries,
          unavailableReason: null,
          retryAfterSeconds: 0,
        };
      }
      return {
        requested: icaos.length,
        entries,
        unavailableReason: "rate_limited",
        retryAfterSeconds: Math.ceil(AWC_MIN_REQUEST_INTERVAL_MS / 1_000),
      };
    }

    const request = fetchAndCache(kind, missing);
    datasetInFlight.set(kind, request);
    try {
      await request;
    } catch (error) {
      return {
        requested: icaos.length,
        entries,
        unavailableReason:
          error instanceof NoaaProviderError && error.kind === "timeout"
            ? "timeout"
            : "unavailable",
        retryAfterSeconds: 0,
      };
    } finally {
      if (datasetInFlight.get(kind) === request) datasetInFlight.delete(kind);
    }

    entries = readEntries(kind, icaos, now());
    return {
      requested: icaos.length,
      entries,
      unavailableReason: null,
      retryAfterSeconds: 0,
    };
  }

  return async function GET(request: Request): Promise<Response> {
    const parsed = parseLiveContextQuery(new URL(request.url));
    if (parsed.ok === false) {
      return json(
        {
          ok: false,
          error: { code: "invalid_query", message: parsed.message },
        },
        400,
        "no-store",
      );
    }

    const mappings = parsed.airports.map((iata) => ({
      iata,
      station: STATIONS_BY_IATA.get(iata) ?? null,
    }));
    const metarIcaos = mappings
      .filter(({ station }) => station?.supportsMetar)
      .map(({ station }) => station!.icao);
    const tafIcaos = mappings
      .filter(({ station }) => station?.supportsTaf)
      .map(({ station }) => station!.icao);

    const [metar, taf] = await Promise.all([
      getDataset("metar", metarIcaos),
      getDataset("taf", tafIcaos),
    ]);
    const relevant = [metar, taf].filter((result) => result.requested > 0);
    const failed = relevant.filter((result) => result.unavailableReason !== null);
    const noUsableEntries = failed.every((result) => result.entries.size === 0);
    if (
      relevant.length > 0 &&
      failed.length === relevant.length &&
      noUsableEntries
    ) {
      const onlyRateLimited = failed.every(
        (result) => result.unavailableReason === "rate_limited",
      );
      const onlyTimedOut = failed.every(
        (result) => result.unavailableReason === "timeout",
      );
      const retryAfterSeconds = Math.max(
        1,
        ...failed.map((result) => result.retryAfterSeconds),
      );
      return json(
        {
          ok: false,
          error: {
            code: onlyRateLimited
              ? "upstream_rate_limited"
              : onlyTimedOut
                ? "upstream_timeout"
                : "upstream_unavailable",
            message: onlyRateLimited
              ? "Live airport conditions were checked recently. Please wait before requesting a different set of airports."
              : onlyTimedOut
                ? "Live airport conditions took too long to respond."
                : "Live airport conditions are temporarily unavailable.",
          },
        },
        onlyRateLimited ? 429 : onlyTimedOut ? 504 : 502,
        "no-store",
        onlyRateLimited ? { "Retry-After": String(retryAfterSeconds) } : {},
      );
    }

    const unavailable: DatasetKind[] = [];
    if (metar.unavailableReason) unavailable.push("metar");
    if (taf.unavailableReason) unavailable.push("taf");
    const retryAfterSeconds = Math.max(
      0,
      metar.retryAfterSeconds,
      taf.retryAfterSeconds,
    );
    const airports = mappings.map(
      ({ iata, station }): LiveAirportContext => {
        const observationEntry = station
          ? metar.entries.get(station.icao)
          : undefined;
        const forecastEntry = station
          ? taf.entries.get(station.icao)
          : undefined;
        return {
          iata,
          icao: station?.icao ?? null,
          observation:
            observationEntry?.value && station?.supportsMetar
              ? (observationEntry.value as NoaaObservation)
              : null,
          forecast:
            forecastEntry?.value && station?.supportsTaf
              ? (forecastEntry.value as NoaaForecast)
              : null,
          datasetFetchedAt: {
            metar: observationEntry?.fetchedAt ?? null,
            taf: forecastEntry?.fetchedAt ?? null,
          },
          sourceLinks: station
            ? {
                observation: station.supportsMetar
                  ? buildNoaaUrl("metar", [station.icao]).toString()
                  : null,
                forecast: station.supportsTaf
                  ? buildNoaaUrl("taf", [station.icao]).toString()
                  : null,
              }
            : null,
        };
      },
    );

    const partial = unavailable.length > 0;
    return json(
      {
        ok: true,
        partial,
        source: NOAA_LIVE_CONTEXT_SOURCE,
        airports,
        unavailable,
        retryAfterSeconds,
      },
      200,
      partial
        ? "no-store"
        : "public, max-age=30, s-maxage=60, stale-while-revalidate=300",
      partial && retryAfterSeconds > 0
        ? { "Retry-After": String(retryAfterSeconds) }
        : {},
    );
  };
}
