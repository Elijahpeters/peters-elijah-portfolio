import {
  createDuffelClient,
  DuffelProviderError,
  type DuffelResult,
} from "../../../../lib/duffel/client.ts";
import type {
  DuffelMode,
  DuffelOfferRequest,
} from "../../../../lib/duffel/contracts";
import { normalizeDuffelOffers } from "../../../../lib/duffel/normalize.ts";
import {
  hasJsonContentType,
  validateFlightSearch,
  type ValidatedFlightSearch,
} from "../../../../lib/http/validation.ts";
import {
  addSkyetaRisk,
  type FlightOfferWithSkyetaRisk,
} from "../../../../lib/skyeta/offer-risk.ts";

const MAX_BODY_BYTES = 24_000;
const MAX_OFFERS_RETURNED = 30;

type DuffelClientLike = {
  getMode(): DuffelMode | null;
  request<T>(
    path: string,
    options?: {
      method?: "GET" | "POST" | "PATCH" | "DELETE";
      query?: Record<string, string | number | boolean | null | undefined>;
      body?: unknown;
      timeoutMs?: number;
    },
  ): Promise<DuffelResult<T>>;
};

type HandlerOptions = {
  createClient?: () => DuffelClientLike;
  now?: () => Date;
  bookingEnabled?: () => boolean;
};

function json(body: unknown, status: number): Response {
  return Response.json(body, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function duffelPassengers(search: ValidatedFlightSearch) {
  return [
    ...Array.from({ length: search.passengers.adults }, () => ({
      type: "adult",
    })),
    ...Array.from({ length: search.passengers.children }, () => ({
      type: "child",
    })),
    ...Array.from({ length: search.passengers.infantsWithoutSeat }, () => ({
      type: "infant_without_seat",
    })),
  ];
}

export function buildDuffelOfferRequest(search: ValidatedFlightSearch) {
  const slices = [
    {
      origin: search.origin,
      destination: search.destination,
      departure_date: search.departureDate,
    },
  ];
  if (search.returnDate) {
    slices.push({
      origin: search.destination,
      destination: search.origin,
      departure_date: search.returnDate,
    });
  }
  return {
    data: {
      slices,
      passengers: duffelPassengers(search),
      cabin_class: search.cabinClass,
    },
  };
}

function enrichedOffers(
  rawOffers: unknown,
  mode: DuffelMode,
  canBook: boolean,
): FlightOfferWithSkyetaRisk[] | null {
  if (!Array.isArray(rawOffers)) return null;
  const normalized = normalizeDuffelOffers(rawOffers, mode);
  if (rawOffers.length > 0 && normalized.length === 0) return null;
  return normalized.slice(0, MAX_OFFERS_RETURNED).map((offer) =>
    addSkyetaRisk({
      ...offer,
      isBookable: offer.isBookable && canBook,
    }),
  );
}

function providerFailure(error: unknown): Response {
  if (error instanceof DuffelProviderError) {
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

export function createOfferSearchHandler(options: HandlerOptions = {}) {
  const createClient = options.createClient ?? (() => createDuffelClient());
  const now = options.now ?? (() => new Date());
  const bookingEnabled =
    options.bookingEnabled ??
    (() => process.env.SKYETA_BOOKING_ENABLED?.trim() === "true");

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

    const contentLength = Number(request.headers.get("content-length") ?? 0);
    if (Number.isFinite(contentLength) && contentLength > MAX_BODY_BYTES) {
      return json(
        {
          ok: false,
          configured: false,
          error: { code: "payload_too_large", message: "The flight search is too large." },
        },
        413,
      );
    }

    let input: unknown;
    try {
      input = await request.json();
    } catch {
      return json(
        {
          ok: false,
          configured: false,
          error: { code: "invalid_json", message: "The flight search is invalid." },
        },
        400,
      );
    }

    const validation = validateFlightSearch(input, now());
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

    const client = createClient();
    try {
      const result = await client.request<DuffelOfferRequest>(
        "/air/offer_requests",
        {
          method: "POST",
          query: { return_offers: true, supplier_timeout: 20_000 },
          body: buildDuffelOfferRequest(validation.value),
          timeoutMs: 25_000,
        },
      );
      const offerRequest = result.data;
      if (
        typeof offerRequest !== "object" ||
        offerRequest === null ||
        !Array.isArray(offerRequest.offers)
      ) {
        throw new DuffelProviderError({
          code: "invalid_response",
          message: "The flight provider returned an invalid response.",
          status: 502,
          retryable: true,
        });
      }

      const isLive = result.mode === "live";
      const canBook = isLive && bookingEnabled();
      const offers = enrichedOffers(offerRequest.offers, result.mode, canBook);
      if (!offers) {
        throw new DuffelProviderError({
          code: "invalid_response",
          message: "The flight provider returned incomplete fare information.",
          status: 502,
          retryable: true,
        });
      }

      return json(
        {
          ok: true,
          configured: true,
          provider: "duffel",
          mode: result.mode,
          isLive,
          bookingEnabled: canBook,
          offerRequestId:
            typeof offerRequest.id === "string" ? offerRequest.id : null,
          searchedAt: now().toISOString(),
          offers,
        },
        200,
      );
    } catch (error) {
      return providerFailure(error);
    }
  };
}
