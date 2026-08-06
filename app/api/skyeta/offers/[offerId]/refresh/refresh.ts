import {
  createDuffelClient,
  DuffelProviderError,
  type DuffelResult,
} from "../../../../../lib/duffel/client.ts";
import type { DuffelOffer } from "../../../../../lib/duffel/contracts";
import { normalizeDuffelOffer } from "../../../../../lib/duffel/normalize.ts";
import { addSkyetaRisk } from "../../../../../lib/skyeta/offer-risk.ts";

const OFFER_ID = /^off_[A-Za-z0-9_]{1,190}$/;

type DuffelClientLike = {
  request<T>(path: string): Promise<DuffelResult<T>>;
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

function errorResponse(error: unknown): Response {
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
        code: "refresh_failed",
        message: "The fare could not be reconfirmed.",
        retryable: true,
      },
    },
    502,
  );
}

export function createOfferRefreshHandler(options: HandlerOptions = {}) {
  const createClient = options.createClient ?? (() => createDuffelClient());
  const now = options.now ?? (() => new Date());
  const bookingEnabled =
    options.bookingEnabled ??
    (() => process.env.SKYETA_BOOKING_ENABLED?.trim() === "true");

  return async function POST(
    _request: Request,
    offerId: string,
  ): Promise<Response> {
    if (!OFFER_ID.test(offerId)) {
      return json(
        {
          ok: false,
          configured: false,
          error: { code: "invalid_offer", message: "Choose a valid flight offer." },
        },
        400,
      );
    }

    try {
      const result = await createClient().request<DuffelOffer>(
        `/air/offers/${offerId}`,
      );
      const normalized = normalizeDuffelOffer(result.data, result.mode);
      if (!normalized || normalized.id !== offerId) {
        throw new DuffelProviderError({
          code: "invalid_response",
          message: "The flight provider returned incomplete fare information.",
          status: 502,
          retryable: true,
        });
      }

      const checkedAt = now();
      const notExpired = Date.parse(normalized.expiresAt) > checkedAt.getTime();
      if (!notExpired) {
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
      const canBook =
        result.mode === "live" && bookingEnabled();
      const offer = addSkyetaRisk(normalized);

      return json(
        {
          ok: true,
          configured: true,
          provider: "duffel",
          mode: result.mode,
          isLive: result.mode === "live",
          bookingEnabled: canBook,
          priceReconfirmed: true,
          checkedAt: checkedAt.toISOString(),
          offer,
        },
        200,
      );
    } catch (error) {
      return errorResponse(error);
    }
  };
}
