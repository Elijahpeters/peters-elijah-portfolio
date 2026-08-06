import {
  AmadeusProviderError,
  createAmadeusClient,
  type AmadeusMode,
  type AmadeusResult,
} from "../../../../lib/amadeus/client.ts";
import {
  AmadeusOfferCache,
  AmadeusOfferTooLargeError,
  type CachedAmadeusOffer,
} from "../../../../lib/amadeus/offer-cache.ts";
import {
  compactAmadeusDictionaries,
  normalizeAmadeusOffer,
} from "../../../../lib/amadeus/normalize.ts";
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
const OFFER_CACHE_TTL_MS = 15 * 60 * 1_000;
const PROVISIONAL_CACHE_ID = `ama_${"0".repeat(32)}`;
const SEARCH_RATE_LIMIT = 10;
const SEARCH_RATE_WINDOW_MS = 10 * 60 * 1_000;

type AmadeusClientLike = {
  getMode(): AmadeusMode | null;
  request<T>(
    path: string,
    options?: {
      method?: "GET" | "POST";
      query?: Record<string, string | number | boolean | null | undefined>;
      body?: unknown;
      headers?: Record<string, string>;
      timeoutMs?: number;
    },
  ): Promise<AmadeusResult<T>>;
};

type OfferCacheLike = {
  save(options: {
    id?: string;
    mode: AmadeusMode;
    offer: unknown;
    dictionaries?: unknown;
    now: number;
    expiresAt: number;
  }): Promise<string>;
  get(id: string, now: number): Promise<CachedAmadeusOffer | null>;
  deleteExpired(now: number, limit?: number): Promise<number>;
};

type HandlerOptions = {
  createClient?: () => AmadeusClientLike;
  createCache?: () => OfferCacheLike | Promise<OfferCacheLike>;
  getDatabase?: () => D1DatabaseLike | Promise<D1DatabaseLike>;
  now?: () => Date;
  checkRateLimit?: (
    request: Request,
    now: number,
  ) => RateLimitResult | Promise<RateLimitResult>;
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
  const address = cloudflareClientAddress(request);
  if (!address) return { allowed: true, retryAfterSeconds: 0 };
  const limiter = new DurableRequestLimiter(await getDatabase());
  return limiter.consume({
    key: await createQuotaKey("amadeus-search", address),
    now,
    windowMs: SEARCH_RATE_WINDOW_MS,
    limit: SEARCH_RATE_LIMIT,
  });
}

function currencyCode(): string | undefined {
  const configured = process.env.AMADEUS_CURRENCY?.trim().toUpperCase();
  return configured && /^[A-Z]{3}$/.test(configured) ? configured : undefined;
}

function travelClass(value: ValidatedFlightSearch["cabinClass"]): string {
  return value.toUpperCase();
}

export function buildAmadeusSearchQuery(search: ValidatedFlightSearch) {
  return {
    originLocationCode: search.origin,
    destinationLocationCode: search.destination,
    departureDate: search.departureDate,
    returnDate: search.returnDate ?? undefined,
    adults: search.passengers.adults,
    children: search.passengers.children || undefined,
    infants: search.passengers.infantsWithoutSeat || undefined,
    travelClass: travelClass(search.cabinClass),
    currencyCode: currencyCode(),
    max: MAX_OFFERS_RETURNED,
  };
}

function providerFailure(error: unknown): Response {
  if (error instanceof AmadeusProviderError) {
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

export function createAmadeusOfferSearchHandler(options: HandlerOptions = {}) {
  const client = options.createClient?.() ?? createAmadeusClient();
  const getDatabase = options.getDatabase ?? environmentDatabase;
  const createCache =
    options.createCache ??
    (async () => new AmadeusOfferCache(await getDatabase()));
  const now = options.now ?? (() => new Date());
  const checkRateLimit =
    options.checkRateLimit ??
    ((request: Request, current: number) =>
      checkPublicSearchRate(request, current, getDatabase));

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
      if (error instanceof BodyTooLargeError) {
        return json(
          {
            ok: false,
            configured: false,
            error: {
              code: "payload_too_large",
              message: "The flight search is too large.",
            },
          },
          413,
        );
      }
      return json(
        {
          ok: false,
          configured: false,
          error: {
            code: "invalid_json",
            message: "The flight search is invalid.",
          },
        },
        400,
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
                "Too many flight searches. Please wait a few minutes and try again.",
              retryable: true,
            },
          },
          429,
          { "Retry-After": String(rateLimit.retryAfterSeconds) },
        );
      }
      const result = await client.request<unknown[]>(
        "/v2/shopping/flight-offers",
        {
          query: buildAmadeusSearchQuery(validation.value),
          timeoutMs: 30_000,
        },
      );
      if (!Array.isArray(result.data)) {
        throw new AmadeusProviderError({
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
      for (const rawOffer of result.data.slice(0, MAX_OFFERS_RETURNED)) {
        const compactDictionaries = compactAmadeusDictionaries(
          rawOffer,
          result.dictionaries,
        );
        const provisional = normalizeAmadeusOffer({
          value: rawOffer,
          dictionaries: compactDictionaries,
          configuredMode: result.mode,
          cacheId: PROVISIONAL_CACHE_ID,
          now: current,
          expiresAt,
        });
        if (!provisional) continue;
        let cacheId: string;
        try {
          cacheId = await cache.save({
            mode: result.mode,
            offer: rawOffer,
            dictionaries: compactDictionaries,
            now: current.getTime(),
            expiresAt: expiresAt.getTime(),
          });
        } catch (error) {
          if (error instanceof AmadeusOfferTooLargeError) continue;
          throw error;
        }
        offers.push({ ...provisional, id: cacheId });
      }
      if (result.data.length > 0 && offers.length === 0) {
        throw new AmadeusProviderError({
          code: "invalid_response",
          message: "The flight provider returned incomplete fare information.",
          status: 502,
          retryable: true,
        });
      }

      const isLive = result.mode === "live";
      return json(
        {
          ok: true,
          configured: true,
          provider: "amadeus",
          mode: result.mode,
          isLive,
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
