const AIRLABS_SCHEDULES_ENDPOINT =
  "https://airlabs.co/api/v9/schedules";

export const AIRLABS_SCHEDULE_FIELDS = [
  "airline_iata",
  "flight_iata",
  "flight_number",
  "dep_iata",
  "arr_iata",
  "dep_time",
  "dep_time_utc",
  "dep_estimated",
  "dep_estimated_utc",
  "arr_time",
  "arr_time_utc",
  "arr_estimated",
  "arr_estimated_utc",
  "status",
  "duration",
  "dep_delayed",
  "arr_delayed",
] as const;

const DEFAULT_TIMEOUT_MS = 6_000;
const DEFAULT_CACHE_TTL_MS = 60_000;
const MAX_CACHE_ENTRIES = 100;
const MAX_FLIGHTS = 50;
const IATA_AIRPORT = /^[A-Z]{3}$/;
const IATA_AIRLINE = /^[A-Z0-9]{2}$/;
const FLIGHT_IATA = /^[A-Z0-9]{2,10}$/;
const FLIGHT_NUMBER = /^[A-Z0-9]{1,8}$/;
const AIRLABS_DATE_TIME = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?$/;
const ALLOWED_STATUSES = new Set([
  "scheduled",
  "cancelled",
  "active",
  "landed",
  "en-route",
]);

export type LiveFlightQuery = {
  origin: string;
  destination: string;
  airline: string | null;
};

export type LiveFlight = {
  id: string;
  airlineIata: string | null;
  flightIata: string | null;
  flightNumber: string | null;
  origin: string;
  destination: string;
  departure: {
    scheduledLocal: string | null;
    scheduledUtc: string | null;
    estimatedLocal: string | null;
    estimatedUtc: string | null;
  };
  arrival: {
    scheduledLocal: string | null;
    scheduledUtc: string | null;
    estimatedLocal: string | null;
    estimatedUtc: string | null;
  };
  status: string | null;
  durationMinutes: number | null;
  departureDelayMinutes: number | null;
  arrivalDelayMinutes: number | null;
};

type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

type HandlerOptions = {
  getApiKey?: () => string | undefined;
  fetchImpl?: FetchLike;
  now?: () => number;
  timeoutMs?: number;
  cacheTtlMs?: number;
};

type CacheEntry = {
  expiresAt: number;
  body: {
    configured: true;
    source: "airlabs";
    query: LiveFlightQuery;
    fetchedAt: string;
    flights: LiveFlight[];
  };
};

type ParsedQuery =
  | { ok: true; query: LiveFlightQuery }
  | { ok: false; message: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function parseLiveFlightQuery(url: URL): ParsedQuery {
  const originValues = url.searchParams.getAll("origin");
  const destinationValues = url.searchParams.getAll("destination");
  const airlineValues = url.searchParams.getAll("airline");

  if (
    originValues.length !== 1 ||
    destinationValues.length !== 1 ||
    airlineValues.length > 1
  ) {
    return {
      ok: false,
      message:
        "Provide one origin and one destination, with at most one airline.",
    };
  }

  const origin = originValues[0];
  const destination = destinationValues[0];
  const airline = airlineValues[0] ?? null;

  if (!IATA_AIRPORT.test(origin) || !IATA_AIRPORT.test(destination)) {
    return {
      ok: false,
      message: "Origin and destination must be uppercase three-letter IATA codes.",
    };
  }
  if (origin === destination) {
    return {
      ok: false,
      message: "Origin and destination must be different airports.",
    };
  }
  if (airline !== null && !IATA_AIRLINE.test(airline)) {
    return {
      ok: false,
      message: "Airline must be an uppercase two-character IATA code.",
    };
  }

  return {
    ok: true,
    query: { origin, destination, airline },
  };
}

export function buildAirLabsSchedulesUrl(
  query: LiveFlightQuery,
  apiKey: string,
): URL {
  const url = new URL(AIRLABS_SCHEDULES_ENDPOINT);
  url.searchParams.set("dep_iata", query.origin);
  url.searchParams.set("arr_iata", query.destination);
  if (query.airline) {
    url.searchParams.set("airline_iata", query.airline);
  }
  url.searchParams.set("_fields", AIRLABS_SCHEDULE_FIELDS.join(","));
  url.searchParams.set("limit", String(MAX_FLIGHTS));
  url.searchParams.set("api_key", apiKey);
  return url;
}

function safeCode(
  value: unknown,
  pattern: RegExp,
): string | null {
  return typeof value === "string" && pattern.test(value) ? value : null;
}

function safeDateTime(value: unknown): string | null {
  return typeof value === "string" && AIRLABS_DATE_TIME.test(value)
    ? value
    : null;
}

function safeMinutes(value: unknown): number | null {
  return typeof value === "number" &&
    Number.isInteger(value) &&
    value >= 0 &&
    value <= 1_440
    ? value
    : null;
}

function scheduleRows(payload: unknown): unknown[] | null {
  if (Array.isArray(payload)) return payload;
  if (isRecord(payload) && Array.isArray(payload.response)) {
    return payload.response;
  }
  return null;
}

export function airLabsErrorCode(payload: unknown): string | null {
  if (
    !isRecord(payload) ||
    !isRecord(payload.error) ||
    typeof payload.error.code !== "string"
  ) {
    return null;
  }
  return payload.error.code;
}

export function sanitizeAirLabsSchedules(
  payload: unknown,
  query: LiveFlightQuery,
): LiveFlight[] | null {
  const rows = scheduleRows(payload);
  if (rows === null) return null;

  const flights: LiveFlight[] = [];
  for (const [index, row] of rows.entries()) {
    if (!isRecord(row)) continue;

    // AirLabs supports arrival filtering, but enforce the complete route again
    // so an upstream filtering regression cannot leak unrelated schedules.
    if (row.dep_iata !== query.origin || row.arr_iata !== query.destination) {
      continue;
    }
    if (query.airline && row.airline_iata !== query.airline) continue;

    const airlineIata = safeCode(row.airline_iata, IATA_AIRLINE);
    const flightIata = safeCode(row.flight_iata, FLIGHT_IATA);
    const flightNumber = safeCode(row.flight_number, FLIGHT_NUMBER);
    const scheduledDepartureLocal = safeDateTime(row.dep_time);
    const scheduledDepartureUtc = safeDateTime(row.dep_time_utc);

    flights.push({
      id: `${flightIata ?? "flight"}:${scheduledDepartureUtc ?? scheduledDepartureLocal ?? "unknown"}:${index}`,
      airlineIata,
      flightIata,
      flightNumber,
      origin: query.origin,
      destination: query.destination,
      departure: {
        scheduledLocal: scheduledDepartureLocal,
        scheduledUtc: scheduledDepartureUtc,
        estimatedLocal: safeDateTime(row.dep_estimated),
        estimatedUtc: safeDateTime(row.dep_estimated_utc),
      },
      arrival: {
        scheduledLocal: safeDateTime(row.arr_time),
        scheduledUtc: safeDateTime(row.arr_time_utc),
        estimatedLocal: safeDateTime(row.arr_estimated),
        estimatedUtc: safeDateTime(row.arr_estimated_utc),
      },
      status:
        typeof row.status === "string" && ALLOWED_STATUSES.has(row.status)
          ? row.status
          : null,
      durationMinutes: safeMinutes(row.duration),
      departureDelayMinutes: safeMinutes(row.dep_delayed),
      arrivalDelayMinutes: safeMinutes(row.arr_delayed),
    });

    if (flights.length >= MAX_FLIGHTS) break;
  }

  return flights.sort((left, right) => {
    const leftTime =
      left.departure.scheduledUtc ?? left.departure.scheduledLocal ?? "";
    const rightTime =
      right.departure.scheduledUtc ?? right.departure.scheduledLocal ?? "";
    return leftTime.localeCompare(rightTime);
  });
}

function json(body: unknown, status: number, cacheControl: string): Response {
  return Response.json(body, {
    status,
    headers: {
      "Cache-Control": cacheControl,
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}

function queryCacheKey(query: LiveFlightQuery): string {
  return `${query.origin}|${query.destination}|${query.airline ?? ""}`;
}

function upstreamErrorMessage(code: string | null): string {
  if (
    code === "minute_limit_exceeded" ||
    code === "hour_limit_exceeded" ||
    code === "month_limit_exceeded"
  ) {
    return "The live schedule provider is temporarily rate limited.";
  }
  if (code === "unknown_api_key" || code === "expired_api_key") {
    return "Live schedule authentication is unavailable.";
  }
  return "The live schedule provider could not complete this request.";
}

export function createLiveFlightsHandler(options: HandlerOptions = {}) {
  const getApiKey =
    options.getApiKey ?? (() => process.env.AIRLABS_API_KEY?.trim());
  const fetchImpl = options.fetchImpl ?? fetch;
  const now = options.now ?? Date.now;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  const cacheTtlMs = options.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS;
  const cache = new Map<string, CacheEntry>();

  return async function GET(request: Request): Promise<Response> {
    const parsed = parseLiveFlightQuery(new URL(request.url));
    if (parsed.ok === false) {
      return json(
        {
          configured: false,
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
          configured: false,
          source: "airlabs",
          query: parsed.query,
          flights: [],
          message: "Live flight lookup is not configured.",
        },
        200,
        "no-store",
      );
    }

    const cacheKey = queryCacheKey(parsed.query);
    const cached = cache.get(cacheKey);
    if (cached && cached.expiresAt > now()) {
      return json(cached.body, 200, "public, max-age=30, s-maxage=60");
    }
    if (cached) cache.delete(cacheKey);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    let upstream: Response | null = null;
    let payload: unknown = null;
    try {
      upstream = await fetchImpl(
        buildAirLabsSchedulesUrl(parsed.query, apiKey),
        {
          method: "GET",
          headers: { Accept: "application/json" },
          signal: controller.signal,
          cache: "no-store",
        },
      );
      payload = await upstream.json();
    } catch {
      const timedOut = controller.signal.aborted;
      return json(
        {
          configured: true,
          source: "airlabs",
          query: parsed.query,
          flights: [],
          error: {
            code: timedOut ? "upstream_timeout" : "upstream_unavailable",
            message: timedOut
              ? "The live schedule provider timed out."
              : "The live schedule provider is unavailable.",
          },
        },
        timedOut ? 504 : 502,
        "no-store",
      );
    } finally {
      clearTimeout(timeout);
    }

    const providerErrorCode = airLabsErrorCode(payload);
    const flights = sanitizeAirLabsSchedules(payload, parsed.query);
    if (
      upstream === null ||
      !upstream.ok ||
      providerErrorCode !== null ||
      flights === null
    ) {
      return json(
        {
          configured: true,
          source: "airlabs",
          query: parsed.query,
          flights: [],
          error: {
            code: "upstream_error",
            message: upstreamErrorMessage(providerErrorCode),
          },
        },
        502,
        "no-store",
      );
    }

    const body: CacheEntry["body"] = {
      configured: true,
      source: "airlabs",
      query: parsed.query,
      fetchedAt: new Date(now()).toISOString(),
      flights,
    };

    if (cache.size >= MAX_CACHE_ENTRIES) {
      const oldestKey = cache.keys().next().value;
      if (oldestKey !== undefined) cache.delete(oldestKey);
    }
    cache.set(cacheKey, { expiresAt: now() + cacheTtlMs, body });

    return json(body, 200, "public, max-age=30, s-maxage=60");
  };
}
