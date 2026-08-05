import {
  isD1DatabaseLike,
  type D1DatabaseLike,
} from "../../../../../lib/booking/d1.ts";
import { minorUnitsToMoney } from "../../../../../lib/booking/money.ts";
import { BookingRepository } from "../../../../../lib/booking/repository.ts";
import {
  isLiveBookingConfigured,
  isPaystackBookingCurrency,
} from "../../../../../lib/booking/config.ts";
import {
  hashBookingSessionToken,
  readBookingSessionCookie,
} from "../../../../../lib/booking/session.ts";

const SELECTION_ID = /^sel_[A-Za-z0-9_-]{32}$/;

type HandlerOptions = {
  getDatabase?: () => D1DatabaseLike | Promise<D1DatabaseLike>;
  now?: () => Date;
  paymentConfigured?: () => boolean;
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

async function environmentDatabase(): Promise<D1DatabaseLike> {
  const workers = await import("cloudflare:workers");
  if (!isD1DatabaseLike(workers.env.DB)) {
    throw new Error("Booking storage is unavailable.");
  }
  return workers.env.DB;
}

export function createGetCheckoutSessionHandler(options: HandlerOptions = {}) {
  const getDatabase = options.getDatabase ?? environmentDatabase;
  const now = options.now ?? (() => new Date());
  const paymentConfigured =
    options.paymentConfigured ??
    (() => isLiveBookingConfigured());

  return async function GET(
    request: Request,
    sessionId: string,
  ): Promise<Response> {
    if (!SELECTION_ID.test(sessionId)) {
      return json(
        { ok: false, error: { code: "not_found", message: "Checkout was not found." } },
        404,
      );
    }
    const token = readBookingSessionCookie(request.headers.get("cookie"));
    if (!token) {
      return json(
        { ok: false, error: { code: "not_found", message: "Checkout was not found." } },
        404,
      );
    }

    try {
      const currentTime = now().getTime();
      const repository = new BookingRepository(await getDatabase());
      const sessionHash = await hashBookingSessionToken(token);
      const activeSession = await repository.getActiveSession(sessionHash, currentTime);
      if (!activeSession) {
        return json(
          { ok: false, error: { code: "session_expired", message: "This checkout session has expired." } },
          410,
        );
      }
      const selection = await repository.getOfferSelectionForSession(
        sessionId,
        sessionHash,
      );
      if (!selection) {
        return json(
          { ok: false, error: { code: "not_found", message: "Checkout was not found." } },
          404,
        );
      }
      if (
        selection.offerExpiresAt !== null &&
        selection.offerExpiresAt <= currentTime
      ) {
        return json(
          { ok: false, error: { code: "fare_expired", message: "This fare has expired. Search again for a current price." } },
          410,
        );
      }

      return json(
        {
          ok: true,
          checkoutSessionId: selection.id,
          providerEnvironment: selection.providerEnvironment,
          total: minorUnitsToMoney(
            selection.totalAmountMinor,
            selection.currency,
          ),
          expiresAt:
            selection.offerExpiresAt === null
              ? null
              : new Date(selection.offerExpiresAt).toISOString(),
          itinerary: selection.itinerary,
          fare: {
            cabinClass: selection.fare.cabinClass,
            fareBrand: selection.fare.fareBrand,
            passengerTypes: selection.fare.passengerTypes,
            identityDocumentsRequired:
              selection.fare.identityDocumentsRequired,
            supportedIdentityDocumentTypes:
              selection.fare.supportedIdentityDocumentTypes,
            changeable: selection.fare.changeable,
            refundable: selection.fare.refundable,
            baggage: selection.fare.baggage,
          },
          risk: selection.risk,
          paymentConfigured:
            selection.providerEnvironment === "live" &&
            isPaystackBookingCurrency(selection.currency) &&
            paymentConfigured(),
        },
        200,
      );
    } catch {
      return json(
        { ok: false, error: { code: "checkout_unavailable", message: "Checkout is temporarily unavailable." } },
        503,
      );
    }
  };
}
