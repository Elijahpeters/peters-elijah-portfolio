import {
  BodyTooLargeError,
  readBoundedJson,
} from "../../../lib/http/bounded-json.ts";
import {
  cloudflareClientAddress,
  createQuotaKey,
  DurableRequestLimiter,
  type RateLimitResult,
} from "../../../lib/amadeus/rate-limit.ts";
import {
  isD1DatabaseLike,
  type D1DatabaseLike,
} from "../../../lib/booking/d1.ts";

const AIRLABS_HISTORICAL_ENDPOINT =
  "https://airlabs.co/api/v10/historical";
const AIRLABS_DOCUMENTATION_URL = "https://airlabs.co/docs/historical";
const DEFAULT_TIMEOUT_MS = 8_000;
const DEFAULT_CACHE_TTL_MS = 6 * 60 * 60 * 1_000;
const MAX_CACHE_ENTRIES = 100;
const MAX_RESPONSE_BYTES = 256_000;
const MAX_FLIGHTS = 3;
const FLIGHT_IATA = /^[A-Z0-9]{2}[0-9]{1,4}$/;
const AIRPORT_IATA = /^[A-Z]{3}$/;
const CLIENT_RATE_LIMIT = 6;
const CLIENT_RATE_WINDOW_MS = 10 * 60 * 1_000;
const GLOBAL_RATE_LIMIT = 30;
const GLOBAL_RATE_WINDOW_MS = 24 * 60 * 60 * 1_000;
const OBSERVED_DATE_TIME =
  /^(\d{4}-\d{2}-\d{2})(?:[ T]\d{2}:\d{2}(?::\d{2})?)?$/;
const COMPLETE_DATE_TIME =
  /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/;

export const RECENT_PERFORMANCE_SOURCE = {
  name: "AirLabs Historical Flight Data API",
  version: "v10",
  url: AIRLABS_DOCUMENTATION_URL,
} as const;

export const RECENT_PERFORMANCE_COVERAGE_NOTICE =
  "Based only on completed-flight records currently returned by AirLabs. Coverage and delay fields vary by flight; missing observations are not inferred. This is historical evidence, not a prediction of a future flight.";

export type RecentPerformanceEvidence = {
  flightIata: string;
  originIata: string;
  destinationIata: string;
  observations: number;
  arrivalDelayKnown: number;
  arrived15PlusLate: number;
  departureDelayKnown: number;
  departed15PlusLate: number;
  earliestObservedDate: string | null;
  latestObservedDate: string | null;
};

type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

type HandlerOptions = {
  getApiKey?: () => string | undefined;
  getDatabase?: () => D1DatabaseLike | Promise<D1DatabaseLike>;
  fetchImpl?: FetchLike;
  now?: () => number;
  timeoutMs?: number;
  cacheTtlMs?: number;
  checkRateLimit?: (
    request: Request,
    now: number,
  ) => RateLimitResult | Promise<RateLimitResult>;
};

export type RecentPerformanceRoute = {
  flightIata: string;
  originIata: string;
  destinationIata: string;
};

type ParsedQuery =
  | { ok: true; routes: RecentPerformanceRoute[] }
  | { ok: false; message: string };

type CacheEntry = {
  expiresAt: number;
  evidence: RecentPerformanceEvidence;
};

class HistoricalProviderError extends Error {
  readonly kind: "timeout" | "unavailable";

  constructor(kind: "timeout" | "unavailable") {
    super(kind);
    this.name = "HistoricalProviderError";
    this.kind = kind;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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

async function environmentDatabase(): Promise<D1DatabaseLike> {
  const workers = await import("cloudflare:workers");
  if (!isD1DatabaseLike(workers.env.DB)) {
    throw new Error("Recent-flight quota storage is unavailable.");
  }
  return workers.env.DB;
}

async function checkPublicRecentPerformanceRate(
  request: Request,
  now: number,
  getDatabase: () => D1DatabaseLike | Promise<D1DatabaseLike>,
): Promise<RateLimitResult> {
  const limiter = new DurableRequestLimiter(await getDatabase());
  const address = cloudflareClientAddress(request);
  if (address) {
    const client = await limiter.consume({
      key: await createQuotaKey("airlabs-history-client", address),
      now,
      windowMs: CLIENT_RATE_WINDOW_MS,
      limit: CLIENT_RATE_LIMIT,
    });
    if (!client.allowed) return client;
  }
  return limiter.consume({
    key: await createQuotaKey("airlabs-history-global", "skyeta"),
    now,
    windowMs: GLOBAL_RATE_WINDOW_MS,
    limit: GLOBAL_RATE_LIMIT,
  });
}

/**
 * Public query contract:
 * `?flights=FLIGHT_IATA:ORIGIN_IATA:DESTINATION_IATA[,..]`
 *
 * One to three unique route-qualified flight identifiers are accepted. Route
 * qualification is required because airlines can reuse a flight number across
 * different airport pairs.
 */
export function parseRecentPerformanceQuery(url: URL): ParsedQuery {
  const values = url.searchParams.getAll("flights");
  const hasUnknownParameter = [...url.searchParams.keys()].some(
    (key) => key !== "flights",
  );
  if (values.length !== 1 || hasUnknownParameter) {
    return {
      ok: false,
      message: "Provide exactly one flights parameter and no other parameters.",
    };
  }

  const identifiers = values[0].split(",");
  if (
    identifiers.length < 1 ||
    identifiers.length > MAX_FLIGHTS ||
    new Set(identifiers).size !== identifiers.length
  ) {
    return {
      ok: false,
      message:
        "Flights must contain one to three unique route-qualified identifiers.",
    };
  }

  const routes: RecentPerformanceRoute[] = [];
  for (const identifier of identifiers) {
    const [flightIata, originIata, destinationIata, extra] =
      identifier.split(":");
    if (
      extra !== undefined ||
      !FLIGHT_IATA.test(flightIata ?? "") ||
      !AIRPORT_IATA.test(originIata ?? "") ||
      !AIRPORT_IATA.test(destinationIata ?? "") ||
      originIata === destinationIata
    ) {
      return {
        ok: false,
        message:
          "Each flight must use FLIGHT_IATA:ORIGIN_IATA:DESTINATION_IATA in uppercase.",
      };
    }
    routes.push({ flightIata, originIata, destinationIata });
  }

  return { ok: true, routes };
}

export function buildAirLabsHistoricalUrl(
  flightIata: string,
  apiKey: string,
): URL {
  const url = new URL(AIRLABS_HISTORICAL_ENDPOINT);
  url.searchParams.set("flight_iata", flightIata);
  url.searchParams.set("api_key", apiKey);
  return url;
}

function historicalRows(payload: unknown): unknown[] | null {
  if (Array.isArray(payload)) return payload;
  if (
    isRecord(payload) &&
    !("error" in payload) &&
    Array.isArray(payload.response)
  ) {
    return payload.response;
  }
  return null;
}

function safeObservedDate(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const match = OBSERVED_DATE_TIME.exec(value);
  if (!match) return null;
  const date = match[1];
  const parsed = new Date(`${date}T00:00:00.000Z`);
  if (
    Number.isNaN(parsed.getTime()) ||
    parsed.toISOString().slice(0, 10) !== date
  ) {
    return null;
  }
  return date;
}

function rowObservedDate(row: Record<string, unknown>): string | null {
  return (
    safeObservedDate(row.dep_time) ??
    safeObservedDate(row.dep_actual) ??
    safeObservedDate(row.arr_time) ??
    safeObservedDate(row.arr_actual)
  );
}

function safeDelayMinutes(value: unknown): number | null {
  return typeof value === "number" &&
    Number.isInteger(value) &&
    value >= -1_440 &&
    value <= 1_440
    ? value
    : null;
}

function safeLocalDateTime(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const match = COMPLETE_DATE_TIME.exec(value);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6] ?? "0");
  if (
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > 31 ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  ) {
    return null;
  }
  const timestamp = Date.UTC(year, month - 1, day, hour, minute, second);
  const parsed = new Date(timestamp);
  if (
    parsed.getUTCFullYear() !== year ||
    parsed.getUTCMonth() !== month - 1 ||
    parsed.getUTCDate() !== day ||
    parsed.getUTCHours() !== hour ||
    parsed.getUTCMinutes() !== minute ||
    parsed.getUTCSeconds() !== second
  ) {
    return null;
  }
  return timestamp;
}

function observedDelayMinutes(
  explicit: unknown,
  scheduled: unknown,
  actual: unknown,
): number | null {
  const stated = safeDelayMinutes(explicit);
  if (stated !== null) return stated;
  const scheduledAt = safeLocalDateTime(scheduled);
  const actualAt = safeLocalDateTime(actual);
  if (scheduledAt === null || actualAt === null) return null;
  const difference = (actualAt - scheduledAt) / 60_000;
  return Number.isFinite(difference) &&
    difference >= -1_440 &&
    difference <= 1_440
    ? difference
    : null;
}

function routeMatches(
  row: Record<string, unknown>,
  route: RecentPerformanceRoute,
): boolean {
  return (
    row.dep_iata === route.originIata && row.arr_iata === route.destinationIata
  );
}

function canRepresentCompletedFlight(row: Record<string, unknown>): boolean {
  if (typeof row.status !== "string") return true;
  const status = row.status.trim().toLowerCase();
  return ![
    "active",
    "canceled",
    "cancelled",
    "diverted",
    "scheduled",
  ].includes(status);
}

export function aggregateHistoricalRows(
  route: RecentPerformanceRoute,
  rows: unknown[],
): RecentPerformanceEvidence {
  let observations = 0;
  let arrivalDelayKnown = 0;
  let arrived15PlusLate = 0;
  let departureDelayKnown = 0;
  let departed15PlusLate = 0;
  let earliestObservedDate: string | null = null;
  let latestObservedDate: string | null = null;

  for (const candidate of rows) {
    if (!isRecord(candidate)) continue;
    if (!routeMatches(candidate, route)) continue;
    if (!canRepresentCompletedFlight(candidate)) continue;
    const observedDate = rowObservedDate(candidate);
    if (!observedDate) continue;

    observations += 1;
    if (earliestObservedDate === null || observedDate < earliestObservedDate) {
      earliestObservedDate = observedDate;
    }
    if (latestObservedDate === null || observedDate > latestObservedDate) {
      latestObservedDate = observedDate;
    }

    const arrivalDelay = observedDelayMinutes(
      candidate.arr_delayed,
      candidate.arr_time,
      candidate.arr_actual,
    );
    if (arrivalDelay !== null) {
      arrivalDelayKnown += 1;
      if (arrivalDelay >= 15) arrived15PlusLate += 1;
    }

    const departureDelay = observedDelayMinutes(
      candidate.dep_delayed,
      candidate.dep_time,
      candidate.dep_actual,
    );
    if (departureDelay !== null) {
      departureDelayKnown += 1;
      if (departureDelay >= 15) departed15PlusLate += 1;
    }
  }

  return {
    ...route,
    observations,
    arrivalDelayKnown,
    arrived15PlusLate,
    departureDelayKnown,
    departed15PlusLate,
    earliestObservedDate,
    latestObservedDate,
  };
}

async function fetchHistoricalEvidence(options: {
  route: RecentPerformanceRoute;
  apiKey: string;
  fetchImpl: FetchLike;
  timeoutMs: number;
}): Promise<RecentPerformanceEvidence> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs);
  try {
    const response = await options.fetchImpl(
      buildAirLabsHistoricalUrl(options.route.flightIata, options.apiKey),
      {
        method: "GET",
        headers: { Accept: "application/json" },
        redirect: "manual",
        signal: controller.signal,
      },
    );
    if (!response.ok) throw new Error("historical_provider_rejected");

    const payload = await readBoundedJson(response, MAX_RESPONSE_BYTES);
    const rows = historicalRows(payload);
    if (rows === null) throw new Error("invalid_historical_response");
    return aggregateHistoricalRows(options.route, rows);
  } catch (error) {
    if (error instanceof BodyTooLargeError) {
      throw new HistoricalProviderError("unavailable");
    }
    throw new HistoricalProviderError(
      controller.signal.aborted ? "timeout" : "unavailable",
    );
  } finally {
    clearTimeout(timeout);
  }
}

export function createRecentPerformanceHandler(options: HandlerOptions = {}) {
  const getApiKey =
    options.getApiKey ?? (() => process.env.AIRLABS_API_KEY?.trim());
  const getDatabase = options.getDatabase ?? environmentDatabase;
  const fetchImpl =
    options.fetchImpl ??
    ((input: string | URL | Request, init?: RequestInit) =>
      globalThis.fetch(input, init));
  const now = options.now ?? Date.now;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const cacheTtlMs = options.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS;
  const checkRateLimit =
    options.checkRateLimit ??
    ((request: Request, current: number) =>
      checkPublicRecentPerformanceRate(request, current, getDatabase));
  const cache = new Map<string, CacheEntry>();
  const inFlight = new Map<string, Promise<RecentPerformanceEvidence>>();

  function saveCache(
    key: string,
    evidence: RecentPerformanceEvidence,
  ): void {
    if (cache.size >= MAX_CACHE_ENTRIES && !cache.has(key)) {
      const oldestKey = cache.keys().next().value;
      if (oldestKey !== undefined) cache.delete(oldestKey);
    }
    cache.set(key, {
      expiresAt: now() + cacheTtlMs,
      evidence,
    });
  }

  function getEvidence(
    route: RecentPerformanceRoute,
    apiKey: string,
  ): Promise<RecentPerformanceEvidence> {
    const key = `${route.flightIata}:${route.originIata}:${route.destinationIata}`;
    const cached = cache.get(key);
    if (cached && cached.expiresAt > now()) {
      return Promise.resolve(cached.evidence);
    }
    if (cached) cache.delete(key);

    const pending = inFlight.get(key);
    if (pending) return pending;

    const request = fetchHistoricalEvidence({
      route,
      apiKey,
      fetchImpl,
      timeoutMs,
    })
      .then((evidence) => {
        saveCache(key, evidence);
        return evidence;
      })
      .finally(() => {
        inFlight.delete(key);
      });
    inFlight.set(key, request);
    return request;
  }

  return async function GET(request: Request): Promise<Response> {
    const parsed = parseRecentPerformanceQuery(new URL(request.url));
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

    const apiKey = getApiKey();
    if (!apiKey) {
      return json(
        {
          ok: false,
          error: {
            code: "not_configured",
            message: "Recent flight performance is not configured.",
          },
        },
        503,
        "no-store",
      );
    }

    let rateLimit: RateLimitResult;
    try {
      rateLimit = await checkRateLimit(request, now());
    } catch {
      return json(
        {
          ok: false,
          error: {
            code: "service_unavailable",
            message: "Recent flight performance is temporarily unavailable.",
          },
        },
        503,
        "no-store",
      );
    }
    if (!rateLimit.allowed) {
      return json(
        {
          ok: false,
          error: {
            code: "rate_limited",
            message:
              "Too many recent-performance checks. Please wait and try again.",
          },
        },
        429,
        "no-store",
        { "Retry-After": String(rateLimit.retryAfterSeconds) },
      );
    }

    const outcomes = await Promise.allSettled(
      parsed.routes.map((route) => getEvidence(route, apiKey)),
    );
    const flights: RecentPerformanceEvidence[] = [];
    const unavailable: RecentPerformanceRoute[] = [];
    for (const [index, outcome] of outcomes.entries()) {
      if (outcome.status === "fulfilled") {
        flights.push(outcome.value);
      } else {
        unavailable.push(parsed.routes[index]);
      }
    }

    if (flights.length > 0) {
      return json(
        {
          ok: true,
          partial: unavailable.length > 0,
          source: RECENT_PERFORMANCE_SOURCE,
          coverageNotice: RECENT_PERFORMANCE_COVERAGE_NOTICE,
          flights,
          unavailable,
        },
        200,
        "public, max-age=300, s-maxage=21600, stale-while-revalidate=86400",
      );
    }

    const timedOut = outcomes.every(
      (outcome) =>
        outcome.status === "rejected" &&
        outcome.reason instanceof HistoricalProviderError &&
        outcome.reason.kind === "timeout",
    );
    return json(
      {
        ok: false,
        error: {
          code: timedOut ? "upstream_timeout" : "upstream_unavailable",
          message: timedOut
            ? "Recent flight performance took too long to respond."
            : "Recent flight performance is temporarily unavailable.",
        },
      },
      timedOut ? 504 : 502,
      "no-store",
    );
  };
}
