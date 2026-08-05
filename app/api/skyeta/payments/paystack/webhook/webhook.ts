import {
  isLiveBookingConfigured,
} from "../../../../../lib/booking/config.ts";
import {
  isD1DatabaseLike,
  type D1DatabaseLike,
} from "../../../../../lib/booking/d1.ts";
import {
  createOpaqueToken,
  sha256Base64Url,
} from "../../../../../lib/booking/idempotency.ts";
import { moneyToMinorUnits, minorUnitsToMoney } from "../../../../../lib/booking/money.ts";
import type { ValidatedOrderPassenger } from "../../../../../lib/booking/passengers.ts";
import {
  decryptPrivateBookingPayload,
  type EncryptedPrivateBookingPayload,
} from "../../../../../lib/booking/private-payload.ts";
import { BookingRepository } from "../../../../../lib/booking/repository.ts";
import type {
  BookingAttemptRecord,
  BookingAttemptState,
  OfferSelectionRecord,
  PrivateBookingPayloadRecord,
  WebhookEventRecord,
  WebhookEventStatus,
} from "../../../../../lib/booking/types";
import {
  createDuffelClient,
  DuffelProviderError,
  type DuffelResult,
} from "../../../../../lib/duffel/client.ts";
import type { DuffelOffer } from "../../../../../lib/duffel/contracts";
import { normalizeDuffelOffer } from "../../../../../lib/duffel/normalize.ts";
import {
  createDuffelOrderService,
  DuffelOrderError,
  type CreatedDuffelOrder,
} from "../../../../../lib/duffel/order.ts";
import {
  createPaystackClient,
  type PaystackVerifyTransactionResult,
} from "../../../../../lib/paystack/client.ts";
import { parsePaystackChargeSuccessEvent } from "../../../../../lib/paystack/webhook.ts";
import type { FlightOffer } from "../../../../../types/flight-booking";
import {
  parsePrivatePaymentCheckoutPayload,
  type PrivatePaymentCheckoutPayload,
} from "../../checkout/checkout.ts";

const MAX_WEBHOOK_BYTES = 256 * 1024;
// Duffel order submission may legitimately take a little over two minutes.
// Do not steal a live invocation, but make a crashed lease recoverable.
const WEBHOOK_PROCESSING_LEASE_MS = 5 * 60 * 1_000;

type RepositoryLike = Pick<
  BookingRepository,
  | "recordWebhookEvent"
  | "transitionWebhookEvent"
  | "getBookingAttemptByPaymentReference"
  | "getOfferSelectionForSession"
  | "getPrivatePayload"
  | "deletePrivatePayload"
  | "transitionBookingAttempt"
  | "finalizeBooking"
>;

type PaystackClientLike = {
  verifyWebhookSignature(
    body: ArrayBuffer | ArrayBufferView,
    signature: string | null | undefined,
  ): Promise<boolean>;
  verifyTransaction(reference: string): Promise<PaystackVerifyTransactionResult>;
};

type DuffelClientLike = {
  request<T>(path: string): Promise<DuffelResult<T>>;
};

type DuffelOrderServiceLike = {
  createOrder(input: {
    offerId: string;
    amount: string;
    currency: string;
    passengers: readonly ValidatedOrderPassenger[];
    bookingAttemptId: string;
  }): Promise<CreatedDuffelOrder>;
};

type HandlerOptions = {
  isConfigured?: () => boolean;
  createPaystack?: () => PaystackClientLike;
  createDuffel?: () => DuffelClientLike;
  createOrderService?: () => DuffelOrderServiceLike;
  getDatabase?: () => D1DatabaseLike | Promise<D1DatabaseLike>;
  createRepository?: (database: D1DatabaseLike) => RepositoryLike;
  decryptPayload?: (
    record: EncryptedPrivateBookingPayload,
    bookingAttemptId: string,
  ) => Promise<unknown>;
  now?: () => Date;
  createEventId?: () => string;
  createBookingId?: () => string;
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

async function loadLiveOffer(
  client: DuffelClientLike,
  offerId: string,
): Promise<FlightOffer | null> {
  const result = await client.request<DuffelOffer>(`/air/offers/${offerId}`);
  const offer = normalizeDuffelOffer(result.data, result.mode);
  if (
    result.mode !== "live" ||
    !offer ||
    offer.id !== offerId ||
    !offer.source.isLive ||
    !offer.isBookable
  ) {
    return null;
  }
  return offer;
}

function exactVerifiedPayment(
  transaction: PaystackVerifyTransactionResult,
  attempt: BookingAttemptRecord,
  payload: PrivatePaymentCheckoutPayload,
): boolean {
  return (
    transaction.environment === "live" &&
    transaction.status === "success" &&
    transaction.reference === attempt.paymentReference &&
    transaction.reference === payload.paymentReference &&
    transaction.amount === attempt.totalAmountMinor &&
    transaction.currency === attempt.currency.toUpperCase() &&
    transaction.metadata?.bookingAttemptId === attempt.id &&
    transaction.customerEmail?.trim().toLowerCase() === payload.paymentEmail &&
    typeof transaction.paidAt === "string" &&
    transaction.paidAt.length > 0
  );
}

function exactLiveOffer(
  offer: FlightOffer | null,
  selection: OfferSelectionRecord | null,
  attempt: BookingAttemptRecord,
  payload: PrivatePaymentCheckoutPayload,
  now: number,
): offer is FlightOffer {
  if (
    !offer ||
    !selection ||
    offer.id !== payload.offerId ||
    selection.provider !== "duffel" ||
    selection.providerEnvironment !== "live" ||
    selection.providerOfferId !== payload.offerId ||
    attempt.provider !== "duffel" ||
    attempt.providerEnvironment !== "live" ||
    offer.source.environment !== "live" ||
    !offer.source.isLive ||
    !offer.isBookable ||
    Date.parse(offer.expiresAt) <= now ||
    selection.offerExpiresAt === null ||
    selection.offerExpiresAt <= now ||
    selection.currency !== attempt.currency ||
    selection.totalAmountMinor !== attempt.totalAmountMinor ||
    offer.total.currency !== attempt.currency ||
    !Array.isArray(selection.fare.providerPassengers) ||
    selection.fare.providerPassengers.length !== offer.passengers.length ||
    payload.passengers.length !== offer.passengers.length ||
    selection.fare.providerPassengers.some(
      (storedPassenger, index) =>
        storedPassenger.id !== offer.passengers[index]?.id ||
        storedPassenger.type !== offer.passengers[index]?.type ||
        storedPassenger.id !== payload.passengers[index]?.id,
    )
  ) {
    return false;
  }
  try {
    return moneyToMinorUnits(offer.total) === attempt.totalAmountMinor;
  } catch {
    return false;
  }
}

export function createPaystackBookingWebhookHandler(options: HandlerOptions = {}) {
  const isConfigured = options.isConfigured ?? (() => isLiveBookingConfigured());
  const createPaystack = options.createPaystack ?? (() => createPaystackClient());
  const createDuffel = options.createDuffel ?? (() => createDuffelClient());
  const createOrderService =
    options.createOrderService ?? (() => createDuffelOrderService());
  const getDatabase = options.getDatabase ?? environmentDatabase;
  const createRepository =
    options.createRepository ?? ((database) => new BookingRepository(database));
  const decryptPayload =
    options.decryptPayload ??
    ((record, bookingAttemptId) =>
      decryptPrivateBookingPayload(record, bookingAttemptId));
  const now = options.now ?? (() => new Date());
  const createEventId =
    options.createEventId ?? (() => `whe_${createOpaqueToken(24)}`);
  const createBookingId =
    options.createBookingId ?? (() => `bkg_${createOpaqueToken(24)}`);

  return async function POST(request: Request): Promise<Response> {
    if (!isConfigured()) {
      return json({ ok: false, status: "unavailable" }, 503);
    }

    const declaredLength = Number(request.headers.get("content-length") ?? 0);
    if (Number.isFinite(declaredLength) && declaredLength > MAX_WEBHOOK_BYTES) {
      return json({ ok: false, status: "payload_too_large" }, 413);
    }

    let rawBody: Uint8Array;
    try {
      rawBody = new Uint8Array(await request.arrayBuffer());
    } catch {
      return json({ ok: false, status: "invalid_request" }, 400);
    }
    if (rawBody.byteLength > MAX_WEBHOOK_BYTES) {
      return json({ ok: false, status: "payload_too_large" }, 413);
    }

    const signature = request.headers.get("x-paystack-signature");
    const paystack = createPaystack();
    let validSignature = false;
    try {
      validSignature = await paystack.verifyWebhookSignature(rawBody, signature);
    } catch {
      return json({ ok: false, status: "unavailable" }, 503);
    }
    if (!validSignature) {
      return json({ ok: false, status: "invalid_signature" }, 401);
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(rawBody));
    } catch {
      return json({ ok: true, status: "ignored" }, 200);
    }
    const event = parsePaystackChargeSuccessEvent(parsed);
    if (!event) {
      return json({ ok: true, status: "ignored" }, 200);
    }

    const receivedAt = now().getTime();
    let repository: RepositoryLike;
    let storedEvent: WebhookEventRecord;
    try {
      repository = createRepository(await getDatabase());
      const recorded = await repository.recordWebhookEvent({
        id: createEventId(),
        provider: "paystack",
        providerEventId: event.providerEventId,
        eventType: event.eventType,
        payloadHash: await sha256Base64Url(rawBody),
        signatureHash: await sha256Base64Url(signature ?? ""),
        relatedProviderOrderId: null,
        receivedAt,
      });
      storedEvent = recorded.event;
      if (!recorded.created) {
        if (
          storedEvent.status === "processed" ||
          storedEvent.status === "ignored"
        ) {
          return json({ ok: true, status: "duplicate" }, 200);
        }
        if (storedEvent.status === "processing") {
          if (
            storedEvent.receivedAt <=
            receivedAt - WEBHOOK_PROCESSING_LEASE_MS
          ) {
            await repository.transitionWebhookEvent({
              provider: "paystack",
              providerEventId: event.providerEventId,
              expectedStatuses: ["processing"],
              nextStatus: "failed",
              failureCode: "processing_lease_expired",
              processedAt: null,
            });
          }
          // Paystack will retry. A later delivery can reclaim an expired lease.
          return json({ ok: false, status: "processing" }, 503);
        }
      }
      const acquired = await repository.transitionWebhookEvent({
        provider: "paystack",
        providerEventId: event.providerEventId,
        expectedStatuses: [storedEvent.status],
        nextStatus: "processing",
        failureCode: null,
        processedAt: null,
      });
      if (!acquired) {
        return json({ ok: true, status: "duplicate" }, 200);
      }
      storedEvent = acquired;
    } catch {
      return json({ ok: false, status: "storage_unavailable" }, 503);
    }

    const transitionEvent = async (
      expectedStatuses: WebhookEventStatus[],
      nextState: WebhookEventStatus,
      failureCode: string | null,
    ): Promise<void> => {
      await repository.transitionWebhookEvent({
        provider: "paystack",
        providerEventId: event.providerEventId,
        expectedStatuses,
        nextStatus: nextState,
        failureCode,
        processedAt:
          nextState === "processed" || nextState === "ignored"
            ? now().getTime()
            : null,
      });
    };

    const ignoreEvent = async (failureCode: string): Promise<Response> => {
      try {
        await transitionEvent(["processing"], "ignored", failureCode);
      } catch {
        // A valid but unrelated payment event must not trigger provider retries.
      }
      return json({ ok: true, status: "ignored" }, 200);
    };

    let attempt: BookingAttemptRecord | null;
    try {
      attempt = await repository.getBookingAttemptByPaymentReference(event.reference);
    } catch {
      await transitionEvent(["processing"], "failed", "storage_unavailable").catch(() => {});
      return json({ ok: false, status: "storage_unavailable" }, 503);
    }
    if (!attempt) return ignoreEvent("unknown_payment_reference");
    let activeAttempt = attempt;

    if (activeAttempt.state === "confirmed") {
      await repository.deletePrivatePayload(activeAttempt.id).catch(() => {});
      await transitionEvent(["processing"], "processed", null).catch(() => {});
      return json({ ok: true, status: "processed" }, 200);
    }

    const putAttemptInManualReview = async (
      currentState: BookingAttemptState,
      failureCode: string,
      deletePayload = true,
    ): Promise<Response> => {
      try {
        await repository.transitionBookingAttempt({
          id: activeAttempt.id,
          sessionHash: activeAttempt.sessionHash,
          expectedStates: [currentState],
          nextState: "manual_review",
          failureCode,
          retryable: false,
          now: now().getTime(),
        });
        if (deletePayload) {
          await repository.deletePrivatePayload(activeAttempt.id).catch(() => {});
        }
        await transitionEvent(["processing"], "processed", failureCode);
      } catch {
        // Never ask Paystack to retry after a result requiring human review.
      }
      return json({ ok: true, status: "manual_review" }, 200);
    };

    if (activeAttempt.state === "manual_review") {
      await repository.deletePrivatePayload(activeAttempt.id).catch(() => {});
      await transitionEvent(
        ["processing"],
        "processed",
        activeAttempt.failureCode,
      ).catch(() => {});
      return json({ ok: true, status: "processed" }, 200);
    }
    if (activeAttempt.state === "submitting") {
      return putAttemptInManualReview(
        "submitting",
        "order_submission_uncertain",
      );
    }

    if (
      activeAttempt.state !== "awaiting_payment" &&
      activeAttempt.state !== "payment_authorized"
    ) {
      return putAttemptInManualReview(
        activeAttempt.state,
        "unexpected_attempt_state",
      );
    }

    let privateRecord: PrivateBookingPayloadRecord | null;
    let payload: PrivatePaymentCheckoutPayload | null = null;
    try {
      privateRecord = await repository.getPrivatePayload(activeAttempt.id, now().getTime());
      if (privateRecord) {
        payload = parsePrivatePaymentCheckoutPayload(
          await decryptPayload(privateRecord, activeAttempt.id),
        );
      }
    } catch {
      privateRecord = null;
    }
    if (
      !privateRecord ||
      !payload ||
      payload.paymentReference !== event.reference
    ) {
      return putAttemptInManualReview(activeAttempt.state, "private_payload_unavailable");
    }

    let transaction: PaystackVerifyTransactionResult;
    try {
      transaction = await paystack.verifyTransaction(event.reference);
    } catch {
      await transitionEvent(["processing"], "failed", "payment_verification_unavailable").catch(() => {});
      return json({ ok: false, status: "verification_unavailable" }, 503);
    }
    if (!exactVerifiedPayment(transaction, activeAttempt, payload)) {
      return putAttemptInManualReview(activeAttempt.state, "payment_verification_mismatch");
    }

    if (activeAttempt.state === "awaiting_payment") {
      const authorized = await repository.transitionBookingAttempt({
        id: activeAttempt.id,
        sessionHash: activeAttempt.sessionHash,
        expectedStates: ["awaiting_payment"],
        nextState: "payment_authorized",
        providerRequestId: transaction.requestId,
        failureCode: null,
        retryable: false,
        now: now().getTime(),
      });
      if (!authorized) {
        await transitionEvent(["processing"], "processed", "concurrent_processing").catch(() => {});
        return json({ ok: true, status: "duplicate" }, 200);
      }
      activeAttempt = authorized;
    }

    const submitting = await repository.transitionBookingAttempt({
      id: activeAttempt.id,
      sessionHash: activeAttempt.sessionHash,
      expectedStates: ["payment_authorized"],
      nextState: "submitting",
      failureCode: null,
      retryable: false,
      now: now().getTime(),
    });
    if (!submitting) {
      await transitionEvent(["processing"], "processed", "concurrent_processing").catch(() => {});
      return json({ ok: true, status: "duplicate" }, 200);
    }
    activeAttempt = submitting;

    let selection: OfferSelectionRecord | null = null;
    let refreshedOffer: FlightOffer | null = null;
    try {
      selection = await repository.getOfferSelectionForSession(
        activeAttempt.offerSelectionId,
        activeAttempt.sessionHash,
      );
      refreshedOffer = await loadLiveOffer(createDuffel(), payload.offerId);
    } catch (error) {
      if (error instanceof DuffelProviderError && error.providerStatus === 503) {
        await repository.transitionBookingAttempt({
          id: activeAttempt.id,
          sessionHash: activeAttempt.sessionHash,
          expectedStates: ["submitting"],
          nextState: "payment_authorized",
          failureCode: "offer_refresh_unavailable",
          retryable: true,
          now: now().getTime(),
        }).catch(() => {});
        await transitionEvent(["processing"], "failed", "offer_refresh_unavailable").catch(() => {});
        return json({ ok: false, status: "temporarily_unavailable" }, 503);
      }
      return putAttemptInManualReview("submitting", "fare_reconfirmation_failed");
    }

    if (!exactLiveOffer(refreshedOffer, selection, activeAttempt, payload, now().getTime())) {
      return putAttemptInManualReview("submitting", "fare_reconfirmation_mismatch");
    }
    if (!selection) {
      return putAttemptInManualReview("submitting", "fare_reconfirmation_mismatch");
    }

    const amount = minorUnitsToMoney(
      activeAttempt.totalAmountMinor,
      activeAttempt.currency,
    ).amount;
    let order: CreatedDuffelOrder;
    try {
      order = await createOrderService().createOrder({
        offerId: payload.offerId,
        amount,
        currency: activeAttempt.currency,
        passengers: payload.passengers,
        bookingAttemptId: activeAttempt.id,
      });
    } catch (error) {
      if (error instanceof DuffelOrderError && error.outcome === "retryable") {
        await repository.transitionBookingAttempt({
          id: activeAttempt.id,
          sessionHash: activeAttempt.sessionHash,
          expectedStates: ["submitting"],
          nextState: "payment_authorized",
          providerRequestId: error.requestId,
          failureCode: error.code,
          retryable: true,
          now: now().getTime(),
        }).catch(() => {});
        await transitionEvent(["processing"], "failed", error.code).catch(() => {});
        return json({ ok: false, status: "temporarily_unavailable" }, 503);
      }
      const failureCode =
        error instanceof DuffelOrderError && error.outcome === "definitive"
          ? "refund_required_order_rejected"
          : "order_submission_uncertain";
      return putAttemptInManualReview("submitting", failureCode);
    }

    if (
      !order.liveMode ||
      order.total.currency !== activeAttempt.currency ||
      moneyToMinorUnits(order.total) !== activeAttempt.totalAmountMinor
    ) {
      return putAttemptInManualReview("submitting", "order_submission_uncertain");
    }

    try {
      await repository.finalizeBooking({
        id: createBookingId(),
        sessionHash: activeAttempt.sessionHash,
        bookingAttemptId: activeAttempt.id,
        offerSelectionId: activeAttempt.offerSelectionId,
        provider: "duffel",
        providerEnvironment: "live",
        providerOrderId: order.id,
        bookingReference: order.bookingReference,
        status: "confirmed",
        currency: activeAttempt.currency,
        totalAmountMinor: activeAttempt.totalAmountMinor,
        itinerary: selection.itinerary,
        fare: selection.fare,
        now: now().getTime(),
      });
      await repository.deletePrivatePayload(activeAttempt.id);
      await transitionEvent(["processing"], "processed", null);
      return json({ ok: true, status: "processed" }, 200);
    } catch {
      // The provider may already have issued a real order. Never submit it again.
      await repository.transitionBookingAttempt({
        id: activeAttempt.id,
        sessionHash: activeAttempt.sessionHash,
        expectedStates: ["submitting", "confirmed"],
        nextState: "manual_review",
        providerRequestId: order.requestId,
        failureCode: "booking_persistence_uncertain",
        retryable: false,
        now: now().getTime(),
      }).catch(() => {});
      await repository.deletePrivatePayload(activeAttempt.id).catch(() => {});
      await transitionEvent(["processing"], "processed", "booking_persistence_uncertain").catch(() => {});
      return json({ ok: true, status: "manual_review" }, 200);
    }
  };
}
