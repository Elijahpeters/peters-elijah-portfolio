import {
  AmadeusProviderError,
  createAmadeusClient,
  type AmadeusMode,
  type AmadeusResult,
} from "../../../../../lib/amadeus/client.ts";
import {
  AmadeusOfferCache,
  isAmadeusCacheId,
  type CachedAmadeusOffer,
} from "../../../../../lib/amadeus/offer-cache.ts";
import {
  compactAmadeusDictionaries,
  normalizeAmadeusOffer,
} from "../../../../../lib/amadeus/normalize.ts";
import {
  cloudflareClientAddress,
  createQuotaKey,
  DurableRequestLimiter,
  type RateLimitResult,
} from "../../../../../lib/amadeus/rate-limit.ts";
import {
  isD1DatabaseLike,
  type D1DatabaseLike,
} from "../../../../../lib/booking/d1.ts";
import { addSkyetaRisk } from "../../../../../lib/skyeta/offer-risk.ts";

const OFFER_CACHE_TTL_MS = 15 * 60 * 1_000;
const MAX_OFFER_LIFETIME_MS = 30 * 60 * 1_000;
const REFRESH_RATE_LIMIT = 20;
const REFRESH_RATE_WINDOW_MS = 10 * 60 * 1_000;
const OFFER_REFRESH_COOLDOWN_MS = 20 * 1_000;

type AmadeusClientLike = {
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
};

type HandlerOptions = {
  createClient?: () => AmadeusClientLike;
  createCache?: () => OfferCacheLike | Promise<OfferCacheLike>;
  getDatabase?: () => D1DatabaseLike | Promise<D1DatabaseLike>;
  now?: () => Date;
  checkRateLimit?: (
    request: Request,
    offerId: string,
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

async function checkPublicRefreshRate(
  request: Request,
  offerId: string,
  now: number,
  getDatabase: () => D1DatabaseLike | Promise<D1DatabaseLike>,
): Promise<RateLimitResult> {
  const limiter = new DurableRequestLimiter(await getDatabase());
  const address = cloudflareClientAddress(request);
  if (address) {
    const clientQuota = await limiter.consume({
      key: await createQuotaKey("amadeus-refresh-client", address),
      now,
      windowMs: REFRESH_RATE_WINDOW_MS,
      limit: REFRESH_RATE_LIMIT,
    });
    if (!clientQuota.allowed) return clientQuota;
  }
  return limiter.consume({
    key: await createQuotaKey("amadeus-refresh-offer", offerId),
    now,
    windowMs: OFFER_REFRESH_COOLDOWN_MS,
    limit: 1,
  });
}

function errorResponse(error: unknown): Response {
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
        code: "refresh_failed",
        message: "The fare could not be reconfirmed.",
        retryable: true,
      },
    },
    502,
  );
}

export function createAmadeusOfferRefreshHandler(options: HandlerOptions = {}) {
  const client = options.createClient?.() ?? createAmadeusClient();
  const getDatabase = options.getDatabase ?? environmentDatabase;
  const createCache =
    options.createCache ??
    (async () => new AmadeusOfferCache(await getDatabase()));
  const now = options.now ?? (() => new Date());
  const checkRateLimit =
    options.checkRateLimit ??
    ((request: Request, offerId: string, current: number) =>
      checkPublicRefreshRate(request, offerId, current, getDatabase));

  return async function POST(
    request: Request,
    offerId: string,
  ): Promise<Response> {
    if (!isAmadeusCacheId(offerId)) {
      return json(
        {
          ok: false,
          configured: false,
          error: {
            code: "invalid_offer",
            message: "Choose a valid flight offer.",
          },
        },
        400,
      );
    }

    const current = now();
    try {
      const cache = await createCache();
      const cached = await cache.get(offerId, current.getTime());
      if (!cached) {
        return json(
          {
            ok: false,
            configured: true,
            error: {
              code: "offer_expired",
              message: "This fare snapshot expired. Search again for current prices.",
              retryable: false,
            },
          },
          410,
        );
      }
      const absoluteExpiryAt = cached.createdAt + MAX_OFFER_LIFETIME_MS;
      if (
        !Number.isSafeInteger(cached.createdAt) ||
        cached.createdAt > current.getTime() ||
        current.getTime() >= absoluteExpiryAt
      ) {
        return json(
          {
            ok: false,
            configured: true,
            error: {
              code: "offer_expired",
              message: "This fare snapshot expired. Search again for current prices.",
              retryable: false,
            },
          },
          410,
        );
      }
      const rateLimit = await checkRateLimit(
        request,
        offerId,
        current.getTime(),
      );
      if (!rateLimit.allowed) {
        return json(
          {
            ok: false,
            configured: true,
            error: {
              code: "rate_limited",
              message: "This fare was checked recently. Please wait before checking again.",
              retryable: true,
            },
          },
          429,
          { "Retry-After": String(rateLimit.retryAfterSeconds) },
        );
      }

      const result = await client.request<Record<string, unknown>>(
        "/v1/shopping/flight-offers/pricing",
        {
          method: "POST",
          query: { include: "detailed-fare-rules" },
          headers: { "X-HTTP-Method-Override": "GET" },
          body: {
            data: {
              type: "flight-offers-pricing",
              flightOffers: [cached.offer],
            },
          },
          timeoutMs: 30_000,
        },
      );
      if (result.mode !== cached.mode || !Array.isArray(result.data.flightOffers)) {
        throw new AmadeusProviderError({
          code: "invalid_response",
          message: "The flight provider returned incomplete fare information.",
          status: 502,
          retryable: true,
        });
      }
      const rawOffer = result.data.flightOffers[0];
      const expiresAt = new Date(
        Math.min(current.getTime() + OFFER_CACHE_TTL_MS, absoluteExpiryAt),
      );
      const dictionaries = compactAmadeusDictionaries(
        rawOffer,
        result.dictionaries ?? cached.dictionaries,
      );
      const normalized = normalizeAmadeusOffer({
        value: rawOffer,
        dictionaries,
        configuredMode: result.mode,
        cacheId: offerId,
        now: current,
        expiresAt,
      });
      if (!normalized) {
        throw new AmadeusProviderError({
          code: "invalid_response",
          message: "The flight provider returned incomplete fare information.",
          status: 502,
          retryable: true,
        });
      }
      await cache.save({
        id: offerId,
        mode: result.mode,
        offer: rawOffer,
        dictionaries,
        now: cached.createdAt,
        expiresAt: expiresAt.getTime(),
      });

      return json(
        {
          ok: true,
          configured: true,
          provider: "amadeus",
          mode: result.mode,
          isLive: result.mode === "live",
          bookingEnabled: false,
          priceReconfirmed: true,
          checkedAt: current.toISOString(),
          offer: addSkyetaRisk(normalized),
        },
        200,
      );
    } catch (error) {
      return errorResponse(error);
    }
  };
}
