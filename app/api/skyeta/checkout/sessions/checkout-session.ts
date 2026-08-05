import {
  createDuffelClient,
  DuffelProviderError,
  type DuffelResult,
} from "../../../../lib/duffel/client.ts";
import type { DuffelOffer } from "../../../../lib/duffel/contracts";
import { normalizeDuffelOffer } from "../../../../lib/duffel/normalize.ts";
import { BookingRepository } from "../../../../lib/booking/repository.ts";
import {
  isD1DatabaseLike,
  type D1DatabaseLike,
} from "../../../../lib/booking/d1.ts";
import { moneyToMinorUnits } from "../../../../lib/booking/money.ts";
import {
  createOpaqueToken,
  sha256Base64Url,
} from "../../../../lib/booking/idempotency.ts";
import {
  createBookingSession,
  hashBookingSessionToken,
  readBookingSessionCookie,
  serializeBookingSessionCookie,
} from "../../../../lib/booking/session.ts";
import type {
  StoredFareSummary,
  StoredItinerarySummary,
  StoredRiskSummary,
} from "../../../../lib/booking/types";
import {
  hasJsonContentType,
  isSameOriginRequest,
} from "../../../../lib/http/validation.ts";
import { addSkyetaRisk } from "../../../../lib/skyeta/offer-risk.ts";
import type { FlightOffer } from "../../../../types/flight-booking";

const OFFER_ID = /^off_[A-Za-z0-9_]{1,190}$/;
const MAX_BODY_BYTES = 4_000;

type DuffelClientLike = {
  request<T>(path: string): Promise<DuffelResult<T>>;
};

type HandlerOptions = {
  createClient?: () => DuffelClientLike;
  getDatabase?: () => D1DatabaseLike | Promise<D1DatabaseLike>;
  now?: () => Date;
  bookingEnabled?: () => boolean;
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

function itinerarySummary(offer: FlightOffer): StoredItinerarySummary {
  const journeys = offer.slices.map((slice) => {
    const first = slice.segments[0];
    const last = slice.segments.at(-1);
    if (!first || !last) throw new Error("The itinerary is incomplete.");
    return {
      origin: first.origin.iataCode,
      destination: last.destination.iataCode,
      departureAt: first.departingAt,
      arrivalAt: last.arrivingAt,
      segmentCount: slice.segments.length,
      marketingCarriers: [
        ...new Set(
          slice.segments
            .map((segment) => segment.marketingCarrier.iataCode)
            .filter((code): code is string => Boolean(code)),
        ),
      ],
    };
  });
  const totalSegments = journeys.reduce((sum, journey) => sum + journey.segmentCount, 0);
  return {
    journeys,
    totalSegments,
    totalStops: Math.max(0, totalSegments - journeys.length),
  };
}

function fareSummary(offer: FlightOffer): StoredFareSummary {
  const firstSegment = offer.slices[0]?.segments[0];
  return {
    cabinClass: firstSegment?.cabinClass ?? null,
    fareBrand: firstSegment?.fareBrandName ?? null,
    passengerTypes: offer.passengers.map((passenger) => passenger.type),
    providerPassengers: offer.passengers.map((passenger) => ({
      id: passenger.id,
      type: passenger.type,
    })),
    identityDocumentsRequired: offer.passengerIdentityDocumentsRequired,
    supportedIdentityDocumentTypes: offer.supportedIdentityDocumentTypes,
    changeable:
      offer.fareConditions.changeBeforeDeparture.status === "unknown"
        ? null
        : offer.fareConditions.changeBeforeDeparture.status === "allowed",
    refundable:
      offer.fareConditions.refundBeforeDeparture.status === "unknown"
        ? null
        : offer.fareConditions.refundBeforeDeparture.status === "allowed",
    baggage: offer.baggage
      .filter((item) => item.type === "carry_on" || item.type === "checked")
      .map((item) => ({
        type: item.type as "carry_on" | "checked",
        quantity: item.quantity,
        weightKilograms: null,
      })),
  };
}

function riskSummary(
  risk: ReturnType<typeof addSkyetaRisk>["skyetaRisk"],
): StoredRiskSummary {
  if (risk.status === "unavailable") {
    return {
      coverage: "unavailable",
      delayRiskPercent: null,
      coveredSegments: 0,
      totalSegments: risk.totalSegments,
      modelVersion: null,
    };
  }
  return {
    coverage: risk.coverage === "complete" ? "full" : "partial",
    delayRiskPercent: risk.percentage,
    coveredSegments: risk.scoredSegments,
    totalSegments: risk.totalSegments,
    modelVersion: null,
  };
}

function providerErrorResponse(error: unknown): Response {
  if (error instanceof DuffelProviderError) {
    return json(
      {
        ok: false,
        configured: error.code !== "not_configured",
        error: { code: error.code, message: error.message },
      },
      error.status,
    );
  }
  return json(
    {
      ok: false,
      configured: true,
      error: {
        code: "checkout_unavailable",
        message: "Checkout could not be started.",
      },
    },
    503,
  );
}

async function environmentDatabase(): Promise<D1DatabaseLike> {
  const workers = await import("cloudflare:workers");
  if (!isD1DatabaseLike(workers.env.DB)) {
    throw new Error("Booking storage is unavailable.");
  }
  return workers.env.DB;
}

export function createCheckoutSessionHandler(options: HandlerOptions = {}) {
  const createClient = options.createClient ?? (() => createDuffelClient());
  const getDatabase = options.getDatabase ?? environmentDatabase;
  const now = options.now ?? (() => new Date());
  const bookingEnabled =
    options.bookingEnabled ??
    (() => process.env.SKYETA_BOOKING_ENABLED?.trim() === "true");

  return async function POST(request: Request): Promise<Response> {
    if (!isSameOriginRequest(request)) {
      return json(
        { ok: false, error: { code: "invalid_origin", message: "This checkout request was not accepted." } },
        403,
      );
    }
    if (!hasJsonContentType(request)) {
      return json(
        { ok: false, error: { code: "unsupported_media_type", message: "Submit checkout as JSON." } },
        415,
      );
    }
    const contentLength = Number(request.headers.get("content-length") ?? 0);
    if (Number.isFinite(contentLength) && contentLength > MAX_BODY_BYTES) {
      return json(
        { ok: false, error: { code: "payload_too_large", message: "The checkout request is too large." } },
        413,
      );
    }

    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return json(
        { ok: false, error: { code: "invalid_json", message: "The checkout request is invalid." } },
        400,
      );
    }
    const offerId = isRecord(body) && typeof body.offerId === "string" ? body.offerId : "";
    if (!OFFER_ID.test(offerId)) {
      return json(
        { ok: false, error: { code: "invalid_offer", message: "Choose a valid flight offer." } },
        400,
      );
    }

    const current = now();
    try {
      const providerResult = await createClient().request<DuffelOffer>(
        `/air/offers/${offerId}`,
      );
      const normalized = normalizeDuffelOffer(providerResult.data, providerResult.mode);
      if (
        !normalized ||
        normalized.id !== offerId ||
        providerResult.mode !== "live" ||
        !normalized.source.isLive ||
        !normalized.isBookable ||
        !bookingEnabled() ||
        Date.parse(normalized.expiresAt) <= current.getTime()
      ) {
        return json(
          {
            ok: false,
            configured: true,
            error: {
              code: "booking_not_enabled",
              message: "This fare is not available for live checkout.",
            },
          },
          409,
        );
      }

      const offer = addSkyetaRisk(normalized);
      const db = await getDatabase();
      const repository = new BookingRepository(db);
      let token = readBookingSessionCookie(request.headers.get("cookie"));
      let session = token
        ? await repository.getActiveSession(
            await hashBookingSessionToken(token),
            current.getTime(),
          )
        : null;
      let setCookie: string | null = null;
      if (!session || !token) {
        const created = await createBookingSession(current.getTime());
        token = created.token;
        session = await repository.createSession(created.record);
        setCookie = serializeBookingSessionCookie(token, session.expiresAt, {
          secure: new URL(request.url).protocol === "https:",
          now: current.getTime(),
        });
      } else {
        await repository.touchActiveSession(session.sessionHash, current.getTime());
      }

      const safeItinerary = itinerarySummary(offer);
      const safeFare = fareSummary(offer);
      const safeRisk = riskSummary(offer.skyetaRisk);
      const snapshotHash = await sha256Base64Url(
        JSON.stringify({
          id: offer.id,
          expiresAt: offer.expiresAt,
          total: offer.total,
          itinerary: safeItinerary,
          fare: safeFare,
        }),
      );
      const selectionId = `sel_${createOpaqueToken(24)}`;
      const selection = await repository.saveOfferSelection({
        id: selectionId,
        sessionHash: session.sessionHash,
        provider: "duffel",
        providerEnvironment: "live",
        providerOfferId: offer.id,
        status: "refreshed",
        offerExpiresAt: Date.parse(offer.expiresAt),
        currency: offer.total.currency,
        totalAmountMinor: moneyToMinorUnits(offer.total),
        itinerary: safeItinerary,
        fare: safeFare,
        risk: safeRisk,
        providerSnapshotHash: snapshotHash,
        now: current.getTime(),
      });

      return json(
        {
          ok: true,
          checkoutSessionId: selection.id,
          expiresAt: offer.expiresAt,
          offer,
        },
        201,
        setCookie ? { "Set-Cookie": setCookie } : {},
      );
    } catch (error) {
      return providerErrorResponse(error);
    }
  };
}
