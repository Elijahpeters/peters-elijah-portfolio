import {
  createIgnavClient,
  IgnavProviderError,
  type IgnavResult,
} from "../../../../../lib/ignav/client.ts";
import {
  IgnavOfferCache,
  isIgnavCacheId,
  type CachedIgnavOffer,
} from "../../../../../lib/ignav/offer-cache.ts";
import {
  ignavOfferIdentity,
  normalizeIgnavItinerary,
} from "../../../../../lib/ignav/normalize.ts";
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
import type {
  ExternalBookingLink,
  Money,
} from "../../../../../types/flight-booking.ts";

const OFFER_CACHE_TTL_MS = 10 * 60 * 1_000;
const MAX_OFFER_LIFETIME_MS = 30 * 60 * 1_000;
const REFRESH_RATE_LIMIT = 12;
const REFRESH_RATE_WINDOW_MS = 10 * 60 * 1_000;
const OFFER_REFRESH_COOLDOWN_MS = 30 * 1_000;
const GLOBAL_PROVIDER_LIMIT = 50;
const GLOBAL_PROVIDER_WINDOW_MS = 24 * 60 * 60 * 1_000;
const MAX_BOOKING_LINKS = 8;

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
    passengers: CachedIgnavOffer["passengers"];
    expected: CachedIgnavOffer["expected"];
    identity: string;
    now: number;
    expiresAt: number;
  }): Promise<string>;
  get(id: string, now: number): Promise<CachedIgnavOffer | null>;
};

type HandlerOptions = {
  createClient?: () => IgnavClientLike;
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown, maxLength: number): string | null {
  return typeof value === "string" &&
    value.trim().length > 0 &&
    value.length <= maxLength
    ? value.trim()
    : null;
}

function verifiedMoney(value: unknown): Money | null {
  if (!isRecord(value) || value.status !== "verified") return null;
  const currency = text(value.currency, 3);
  const amount = value.amount;
  if (
    !currency ||
    !/^[A-Z]{3}$/.test(currency) ||
    typeof amount !== "number" ||
    !Number.isFinite(amount) ||
    amount < 0 ||
    amount > 1_000_000_000_000
  ) {
    return null;
  }
  return { amount: String(amount), currency };
}

function safeExternalUrl(value: unknown): string | null {
  const raw = text(value, 2_048);
  if (!raw) return null;
  try {
    const url = new URL(raw);
    const hostname = url.hostname.toLowerCase();
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      !hostname ||
      hostname === "localhost" ||
      hostname.endsWith(".localhost") ||
      hostname.endsWith(".local") ||
      hostname.endsWith(".internal") ||
      /^(?:0\.|10\.|127\.|192\.168\.|169\.254\.)/.test(hostname) ||
      /^172\.(?:1[6-9]|2\d|3[01])\./.test(hostname) ||
      /^100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(hostname) ||
      /^198\.1[89]\./.test(hostname) ||
      /^(?:22[4-9]|23\d|24\d|25[0-5])\./.test(hostname) ||
      hostname === "[::]" ||
      hostname === "[::1]" ||
      /^\[(?:fc|fd|fe8|fe9|fea|feb)/.test(hostname)
    ) {
      return null;
    }
    return url.toString();
  } catch {
    return null;
  }
}

export function normalizeIgnavBookingLinks(
  value: unknown,
  expectReturn = false,
): ExternalBookingLink[] {
  if (!Array.isArray(value)) return [];
  const result: ExternalBookingLink[] = [];
  const seen = new Set<string>();
  for (const option of value.slice(0, 6)) {
    if (
      !isRecord(option) ||
      !Array.isArray(option.legs) ||
      !Array.isArray(option.links)
    ) {
      continue;
    }
    const coverage = new Set(option.legs);
    const required = expectReturn
      ? ["outbound", "inbound"]
      : ["outbound"];
    if (
      coverage.size !== required.length ||
      !required.every((leg) => coverage.has(leg))
    ) {
      continue;
    }
    for (const entry of option.links.slice(0, 8)) {
      if (!isRecord(entry)) continue;
      const providerName = text(entry.provider_name, 150);
      const providerType = entry.provider_type;
      const url = safeExternalUrl(entry.url);
      if (
        !providerName ||
        (providerType !== "airline" && providerType !== "third_party") ||
        !url ||
        seen.has(url)
      ) {
        continue;
      }
      seen.add(url);
      result.push({
        providerName,
        providerType,
        fareName: text(entry.fare_name, 150),
        price: verifiedMoney(entry.price),
        url,
      });
      if (result.length >= MAX_BOOKING_LINKS) return result;
    }
  }
  return result;
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
      key: await createQuotaKey("ignav-refresh-client", address),
      now,
      windowMs: REFRESH_RATE_WINDOW_MS,
      limit: REFRESH_RATE_LIMIT,
    });
    if (!clientQuota.allowed) return clientQuota;
  }
  const offerQuota = await limiter.consume({
    key: await createQuotaKey("ignav-refresh-offer", offerId),
    now,
    windowMs: OFFER_REFRESH_COOLDOWN_MS,
    limit: 1,
  });
  if (!offerQuota.allowed) return offerQuota;
  return limiter.consume({
    key: await createQuotaKey("ignav-provider-global", "skyeta"),
    now,
    windowMs: GLOBAL_PROVIDER_WINDOW_MS,
    limit: GLOBAL_PROVIDER_LIMIT,
  });
}

function errorResponse(error: unknown): Response {
  if (error instanceof IgnavProviderError) {
    if (error.providerStatus === 404) {
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
        message: "The latest fare could not be confirmed.",
        retryable: true,
      },
    },
    502,
  );
}

export function createIgnavOfferRefreshHandler(options: HandlerOptions = {}) {
  const client = options.createClient?.() ?? createIgnavClient();
  const getDatabase = options.getDatabase ?? environmentDatabase;
  const createCache =
    options.createCache ??
    (async () => new IgnavOfferCache(await getDatabase()));
  const now = options.now ?? (() => new Date());
  const checkRateLimit =
    options.checkRateLimit ??
    ((request: Request, offerId: string, current: number) =>
      checkPublicRefreshRate(request, offerId, current, getDatabase));

  return async function POST(
    request: Request,
    offerId: string,
  ): Promise<Response> {
    if (!isIgnavCacheId(offerId)) {
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
        "/api/fares/booking-links",
        { ignav_id: cached.ignavId },
        { timeoutMs: 30_000 },
      );
      if (!isRecord(result.data) || !isRecord(result.data.itinerary)) {
        throw new IgnavProviderError({
          code: "invalid_response",
          message: "The flight provider returned incomplete fare information.",
          status: 502,
          retryable: true,
        });
      }
      const expiresAt = new Date(
        Math.min(current.getTime() + OFFER_CACHE_TTL_MS, absoluteExpiryAt),
      );
      const normalized = normalizeIgnavItinerary({
        value: result.data.itinerary,
        cacheId: offerId,
        now: current,
        expiresAt,
        passengers: cached.passengers,
        expected: cached.expected,
      });
      if (!normalized || ignavOfferIdentity(normalized) !== cached.identity) {
        throw new IgnavProviderError({
          code: "invalid_response",
          message: "The selected itinerary changed. Search again before continuing.",
          status: 409,
          retryable: false,
        });
      }
      await cache.save({
        id: offerId,
        itinerary: result.data.itinerary,
        ignavId: cached.ignavId,
        passengers: cached.passengers,
        expected: cached.expected,
        identity: cached.identity,
        now: cached.createdAt,
        expiresAt: expiresAt.getTime(),
      });

      return json(
        {
          ok: true,
          configured: true,
          provider: "ignav",
          mode: "live",
          isLive: true,
          bookingEnabled: false,
          priceReconfirmed: true,
          checkedAt: current.toISOString(),
          offer: addSkyetaRisk(normalized),
          bookingLinks: normalizeIgnavBookingLinks(
            result.data.booking_options,
            cached.expected.returnDate !== null,
          ),
        },
        200,
      );
    } catch (error) {
      return errorResponse(error);
    }
  };
}
