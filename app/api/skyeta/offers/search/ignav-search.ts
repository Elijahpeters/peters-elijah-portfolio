import {
  createIgnavClient,
  IgnavProviderError,
  type IgnavResult,
} from "../../../../lib/ignav/client.ts";
import {
  IgnavOfferCache,
  IgnavOfferTooLargeError,
  isIgnavProviderId,
  type CachedIgnavOffer,
} from "../../../../lib/ignav/offer-cache.ts";
import {
  ignavOfferIdentity,
  normalizeIgnavItinerary,
  type IgnavTripExpectation,
} from "../../../../lib/ignav/normalize.ts";
import {
  cloudflareClientAddress,
  createQuotaKey,
  DurableRequestLimiter,
  type RateLimitResult,
} from "../../../../lib/amadeus/rate-limit.ts";
import {
  isD1DatabaseLike,
  type D1DatabaseLike,
} from "../../../../lib/booking/d1.ts";
import {
  BodyTooLargeError,
  readBoundedJson,
} from "../../../../lib/http/bounded-json.ts";
import {
  hasJsonContentType,
  validateFlightSearch,
  type ValidatedFlightSearch,
} from "../../../../lib/http/validation.ts";
import { addSkyetaRisk } from "../../../../lib/skyeta/offer-risk.ts";
import type { FlightOffer } from "../../../../types/flight-booking.ts";

const MAX_BODY_BYTES = 24_000;
const MAX_OFFERS_RETURNED = 12;
const OFFER_CACHE_TTL_MS = 10 * 60 * 1_000;
const PROVISIONAL_CACHE_ID = `ign_${"0".repeat(32)}`;
const CLIENT_SEARCH_LIMIT = 6;
const CLIENT_SEARCH_WINDOW_MS = 10 * 60 * 1_000;
const GLOBAL_PROVIDER_LIMIT = 50;
const GLOBAL_PROVIDER_WINDOW_MS = 24 * 60 * 60 * 1_000;

type IgnavSearchResponse = {
  origin?: unknown;
  destination?: unknown;
  departure_date?: unknown;
  return_date?: unknown;
  itineraries?: unknown;
};

type IgnavClientLike = {
  request<T>(
    path: string,
    body: unknown,
    options?: { signal?: AbortSignal; timeoutMs?: number },
  ): Promise<IgnavResult<T>>;
};

type OfferCacheLike = {
  save(options: {
    id?: string;
    itinerary: unknown;
    ignavId: string;
    passengers: ValidatedFlightSearch["passengers"];
    expected: IgnavTripExpectation;
    identity: string;
    now: number;
    expiresAt: number;
  }): Promise<string>;
  get(id: string, now: number): Promise<CachedIgnavOffer | null>;
  deleteExpired(now: number, limit?: number): Promise<number>;
};

type HandlerOptions = {
  createClient?: () => IgnavClientLike;
  createCache?: () => OfferCacheLike | Promise<OfferCacheLike>;
  getDatabase?: () => D1DatabaseLike | Promise<D1DatabaseLike>;
  now?: () => Date;
  checkRateLimit?: (
    request: Request,
    now: number,
  ) => RateLimitResult | Promise<RateLimitResult>;
  market?: () => string;
};

function json(
  body: unknown,
  status: number,
  headers: Record<string, string> = {},
): Response {
  return Response.json(body, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
      ...headers,
    },
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function environmentDatabase(): Promise<D1DatabaseLike> {
  const workers = await import("cloudflare:workers");
  if (!isD1DatabaseLike(workers.env.DB)) {
    throw new Error("Flight offer storage is unavailable.");
  }
  return workers.env.DB;
}

async function checkPublicSearchRate(
  request: Request,
  now: number,
  getDatabase: () => D1DatabaseLike | Promise<D1DatabaseLike>,
): Promise<RateLimitResult> {
  const limiter = new DurableRequestLimiter(await getDatabase());
  const address = cloudflareClientAddress(request);
  if (address) {
    const client = await limiter.consume({
      key: await createQuotaKey("ignav-search-client", address),
      now,
      windowMs: CLIENT_SEARCH_WINDOW_MS,
      limit: CLIENT_SEARCH_LIMIT,
    });
    if (!client.allowed) return client;
  }
  return limiter.consume({
    key: await createQuotaKey("ignav-provider-global", "skyeta"),
    now,
    windowMs: GLOBAL_PROVIDER_WINDOW_MS,
    limit: GLOBAL_PROVIDER_LIMIT,
  });
}

function configuredMarket(): string {
  const value = process.env.IGNAV_MARKET?.trim().toUpperCase();
  return value && /^[A-Z]{2}$/.test(value) ? value : "NG";
}

export function buildIgnavSearchRequest(search: ValidatedFlightSearch, market: string) {
  return {
    origin: search.origin,
    destination: search.destination,
    departure_date: search.departureDate,
    ...(search.returnDate ? { return_date: search.returnDate } : {}),
    adults: search.passengers.adults,
    children: search.passengers.children,
    infants_on_lap: search.passengers.infantsWithoutSeat,
    cabin_class: search.cabinClass,
    max_stops: 2,
    allow_self_transfer: false,
    market,
  };
}

function providerFailure(error: unknown): Response {
  if (error instanceof IgnavProviderError) {
    return json(
      {
        ok: false,
        configured: error.code !== "not_configured",
        error: {
          code: error.code,
          message: error.message,
          retryable: error.retryable,
        },
      },
      error.status,
    );
  }
  return json(
    {
      ok: false,
      configured: true,
      error: {
        code: "search_failed",
        message: "Flight search could not be completed.",
        retryable: true,
      },
    },
    502,
  );
}

export function createIgnavOfferSearchHandler(options: HandlerOptions = {}) {
  const client = options.createClient?.() ?? createIgnavClient();
  const getDatabase = options.getDatabase ?? environmentDatabase;
  const createCache =
    options.createCache ??
    (async () => new IgnavOfferCache(await getDatabase()));
  const now = options.now ?? (() => new Date());
  const checkRateLimit =
    options.checkRateLimit ??
    ((request: Request, current: number) =>
      checkPublicSearchRate(request, current, getDatabase));
  const market = options.market ?? configuredMarket;

  return async function POST(request: Request): Promise<Response> {
    if (!hasJsonContentType(request)) {
      return json(
        {
          ok: false,
          configured: false,
          error: {
            code: "unsupported_media_type",
            message: "Submit the flight search as JSON.",
          },
        },
        415,
      );
    }
    let input: unknown;
    try {
      input = await readBoundedJson(request, MAX_BODY_BYTES);
    } catch (error) {
      return json(
        {
          ok: false,
          configured: false,
          error: {
            code:
              error instanceof BodyTooLargeError
                ? "payload_too_large"
                : "invalid_json",
            message:
              error instanceof BodyTooLargeError
                ? "The flight search is too large."
                : "The flight search is invalid.",
          },
        },
        error instanceof BodyTooLargeError ? 413 : 400,
      );
    }
    const current = now();
    const validation = validateFlightSearch(input, current);
    if (!validation.ok) {
      return json(
        {
          ok: false,
          configured: false,
          error: {
            code: "validation_error",
            message: "Check the flight search details.",
            fields: validation.fields,
          },
        },
        400,
      );
    }

    try {
      const rateLimit = await checkRateLimit(request, current.getTime());
      if (!rateLimit.allowed) {
        return json(
          {
            ok: false,
            configured: true,
            error: {
              code: "rate_limited",
              message:
                "Live fare search is busy. Please wait a little before trying again.",
              retryable: true,
            },
          },
          429,
          { "Retry-After": String(rateLimit.retryAfterSeconds) },
        );
      }

      const expectReturn = Boolean(validation.value.returnDate);
      const expected: IgnavTripExpectation = {
        origin: validation.value.origin,
        destination: validation.value.destination,
        departureDate: validation.value.departureDate,
        returnDate: validation.value.returnDate,
        cabinClass: validation.value.cabinClass,
      };
      const endpoint = expectReturn
        ? "/api/fares/round-trip"
        : "/api/fares/one-way";
      const result = await client.request<IgnavSearchResponse>(
        endpoint,
        buildIgnavSearchRequest(validation.value, market()),
        { timeoutMs: 30_000 },
      );
      if (
        !isRecord(result.data) ||
        !Array.isArray(result.data.itineraries) ||
        result.data.origin !== expected.origin ||
        result.data.destination !== expected.destination ||
        result.data.departure_date !== expected.departureDate ||
        (expectReturn
          ? result.data.return_date !== expected.returnDate
          : result.data.return_date !== undefined && result.data.return_date !== null)
      ) {
        throw new IgnavProviderError({
          code: "invalid_response",
          message: "The flight provider returned an invalid response.",
          status: 502,
          retryable: true,
        });
      }

      const cache = await createCache();
      await cache.deleteExpired(current.getTime(), 500);
      const expiresAt = new Date(current.getTime() + OFFER_CACHE_TTL_MS);
      const offers: FlightOffer[] = [];
      for (const itinerary of result.data.itineraries.slice(0, MAX_OFFERS_RETURNED)) {
        if (!isRecord(itinerary)) continue;
        const ignavId = isIgnavProviderId(itinerary.ignav_id)
          ? itinerary.ignav_id
          : null;
        if (!ignavId) continue;
        const provisional = normalizeIgnavItinerary({
          value: itinerary,
          cacheId: PROVISIONAL_CACHE_ID,
          now: current,
          expiresAt,
          passengers: validation.value.passengers,
          expected,
        });
        if (!provisional) continue;
        let cacheId: string;
        try {
          cacheId = await cache.save({
            itinerary,
            ignavId,
            passengers: validation.value.passengers,
            expected,
            identity: ignavOfferIdentity(provisional),
            now: current.getTime(),
            expiresAt: expiresAt.getTime(),
          });
        } catch (error) {
          if (error instanceof IgnavOfferTooLargeError) continue;
          throw error;
        }
        offers.push({ ...provisional, id: cacheId });
      }

      return json(
        {
          ok: true,
          configured: true,
          provider: "ignav",
          mode: "live",
          isLive: true,
          bookingEnabled: false,
          offerRequestId: result.requestId,
          searchedAt: current.toISOString(),
          offers: offers.map((offer) => addSkyetaRisk(offer)),
        },
        200,
      );
    } catch (error) {
      return providerFailure(error);
    }
  };
}
