import {
  isD1DatabaseLike,
  type D1DatabaseLike,
} from "../../../../lib/booking/d1.ts";
import { BookingRepository } from "../../../../lib/booking/repository.ts";
import {
  hashBookingSessionToken,
  readBookingSessionCookie,
} from "../../../../lib/booking/session.ts";

const PAYMENT_REFERENCE = /^[A-Za-z0-9.=-]{1,100}$/;

type RepositoryLike = Pick<
  BookingRepository,
  | "getActiveSession"
  | "getBookingAttemptByPaymentReference"
  | "getBookingByAttempt"
>;

type HandlerOptions = {
  getDatabase?: () => D1DatabaseLike | Promise<D1DatabaseLike>;
  createRepository?: (database: D1DatabaseLike) => RepositoryLike;
  now?: () => Date;
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

export function createBookingStatusHandler(options: HandlerOptions = {}) {
  const getDatabase = options.getDatabase ?? environmentDatabase;
  const createRepository =
    options.createRepository ?? ((database) => new BookingRepository(database));
  const now = options.now ?? (() => new Date());

  return async function GET(request: Request): Promise<Response> {
    const reference = new URL(request.url).searchParams.get("reference") ?? "";
    if (!PAYMENT_REFERENCE.test(reference)) {
      return json(
        { ok: false, error: { code: "not_found", message: "Booking confirmation was not found." } },
        404,
      );
    }
    const token = readBookingSessionCookie(request.headers.get("cookie"));
    if (!token) {
      return json(
        { ok: false, error: { code: "not_found", message: "Booking confirmation was not found." } },
        404,
      );
    }

    try {
      const repository = createRepository(await getDatabase());
      const sessionHash = await hashBookingSessionToken(token);
      const session = await repository.getActiveSession(sessionHash, now().getTime());
      if (!session) {
        return json(
          { ok: false, error: { code: "session_expired", message: "This booking session has expired." } },
          410,
        );
      }
      const attempt = await repository.getBookingAttemptByPaymentReference(reference);
      if (!attempt || attempt.sessionHash !== sessionHash) {
        return json(
          { ok: false, error: { code: "not_found", message: "Booking confirmation was not found." } },
          404,
        );
      }

      if (attempt.state === "confirmed") {
        const booking = await repository.getBookingByAttempt(attempt.id, sessionHash);
        if (booking?.status === "confirmed") {
          return json(
            {
              ok: true,
              state: "confirmed",
              bookingReference: booking.bookingReference,
              message: "Your payment is confirmed and the airline has issued a genuine booking reference.",
            },
            200,
          );
        }
      }

      if (attempt.state === "manual_review") {
        return json(
          {
            ok: true,
            state: "manual_review",
            message:
              "Your payment is protected while the airline confirmation is reviewed. Do not make another payment.",
          },
          200,
        );
      }
      if (attempt.state === "failed" || attempt.state === "price_changed") {
        return json(
          {
            ok: true,
            state: "failed",
            message: "This checkout did not create an airline booking. No booking reference was issued.",
          },
          200,
        );
      }
      if (
        attempt.state === "payment_authorized" ||
        attempt.state === "submitting" ||
        attempt.state === "confirmed"
      ) {
        return json(
          {
            ok: true,
            state: "creating_booking",
            message: "Payment is confirmed. SkyETA is waiting for the airline booking reference.",
          },
          200,
        );
      }
      return json(
        {
          ok: true,
          state: "confirming_payment",
          message: "SkyETA is securely confirming the payment before contacting the airline.",
        },
        200,
      );
    } catch {
      return json(
        { ok: false, error: { code: "status_unavailable", message: "Booking confirmation is temporarily unavailable." } },
        503,
      );
    }
  };
}
