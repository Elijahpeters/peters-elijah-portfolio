import {
  bookingCallbackUrl,
  isLiveBookingConfigured,
  isPaystackBookingCurrency,
} from "../../../../lib/booking/config.ts";
import {
  fingerprintBookingRequest,
  hashIdempotencyKey,
  isValidIdempotencyKey,
} from "../../../../lib/booking/idempotency.ts";
import { moneyToMinorUnits } from "../../../../lib/booking/money.ts";
import {
  PassengerValidationError,
  validatePassengerPayload,
  type ValidatedIdentityDocument,
  type ValidatedOrderPassenger,
} from "../../../../lib/booking/passengers.ts";
import {
  decryptPrivateBookingPayload,
  encryptPrivateBookingPayload,
} from "../../../../lib/booking/private-payload.ts";
import {
  BookingRepository,
  BookingStorageConflictError,
} from "../../../../lib/booking/repository.ts";
import {
  hashBookingSessionToken,
  readBookingSessionCookie,
} from "../../../../lib/booking/session.ts";
import type {
  BookingAttemptRecord,
  OfferSelectionRecord,
  PrivateBookingPayloadRecord,
} from "../../../../lib/booking/types";
import {
  isD1DatabaseLike,
  type D1DatabaseLike,
} from "../../../../lib/booking/d1.ts";
import {
  createDuffelClient,
  DuffelProviderError,
  type DuffelResult,
} from "../../../../lib/duffel/client.ts";
import type { DuffelOffer } from "../../../../lib/duffel/contracts";
import { normalizeDuffelOffer } from "../../../../lib/duffel/normalize.ts";
import {
  createPaystackClient,
  PaystackProviderError,
  type PaystackInitializeTransactionInput,
  type PaystackInitializeTransactionResult,
} from "../../../../lib/paystack/client.ts";
import {
  hasJsonContentType,
  isSameOriginRequest,
} from "../../../../lib/http/validation.ts";

const MAX_BODY_BYTES = 48 * 1024;
const PRIVATE_PAYLOAD_TTL_MS = 2 * 60 * 60 * 1_000;
const SELECTION_ID = /^sel_[A-Za-z0-9_-]{32}$/;
const OFFER_ID = /^off_[A-Za-z0-9_]{1,190}$/;
const ATTEMPT_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const PAYMENT_REFERENCE = /^[A-Za-z0-9.=-]{1,100}$/;
const PROVIDER_PASSENGER_ID = /^pas_[A-Za-z0-9_-]{1,190}$/;
const SAFE_TEXT = /^[^\u0000-\u001f\u007f]+$/u;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE = /^\+[1-9]\d{6,14}$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const COUNTRY_CODE = /^[A-Z]{2}$/;
const CHECKOUT_HOSTS = new Set([
  "checkout.paystack.com",
  "standard.paystack.co",
]);

type DuffelClientLike = {
  request<T>(path: string): Promise<DuffelResult<T>>;
};

type PaystackClientLike = {
  initializeTransaction(
    input: PaystackInitializeTransactionInput,
  ): Promise<PaystackInitializeTransactionResult>;
};

type CheckoutRepository = Pick<
  BookingRepository,
  | "getActiveSession"
  | "getOfferSelectionForSession"
  | "acquireBookingAttempt"
  | "getBookingAttemptForSession"
  | "transitionBookingAttempt"
  | "savePrivatePayload"
  | "getPrivatePayload"
  | "deletePrivatePayload"
>;

export type PrivatePaymentCheckoutPayload = {
  version: 1;
  paymentEmail: string;
  paymentReference: string;
  /** Null only between durable payload creation and Paystack initialization. */
  checkoutUrl: string | null;
  offerId: string;
  passengers: ValidatedOrderPassenger[];
};

export type PaymentCheckoutHandlerOptions = {
  getDatabase?: () => D1DatabaseLike | Promise<D1DatabaseLike>;
  getRepository?: () => CheckoutRepository | Promise<CheckoutRepository>;
  createDuffelClient?: () => DuffelClientLike;
  createPaystackClient?: () => PaystackClientLike;
  bookingConfigured?: () => boolean;
  paymentCurrencyAllowed?: (currency: string) => boolean;
  getCallbackUrl?: () => string;
  now?: () => Date;
  createAttemptId?: () => string;
  createPaymentReference?: (bookingAttemptId: string) => string;
  encryptPayload?: typeof encryptPrivateBookingPayload;
  decryptPayload?: typeof decryptPrivateBookingPayload;
};

class PaymentCheckoutError extends Error {
  readonly code: string;
  readonly status: number;
  readonly retryable: boolean;

  constructor(
    code: string,
    message: string,
    status: number,
    retryable = false,
  ) {
    super(message);
    this.name = "PaymentCheckoutError";
    this.code = code;
    this.status = status;
    this.retryable = retryable;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function safeString(
  value: unknown,
  minimum: number,
  maximum: number,
): string | null {
  return typeof value === "string" &&
    value.length >= minimum &&
    value.length <= maximum &&
    SAFE_TEXT.test(value)
    ? value
    : null;
}

function validIsoDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return (
    Number.isFinite(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}

function officialCheckoutUrl(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 2_048) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      url.username === "" &&
      url.password === "" &&
      url.port === "" &&
      CHECKOUT_HOSTS.has(url.hostname.toLowerCase())
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}

function parsedIdentityDocuments(
  value: unknown,
): ValidatedIdentityDocument[] | null {
  if (!Array.isArray(value) || value.length !== 1) return null;
  const document = value[0];
  if (
    !isRecord(document) ||
    document.type !== "passport" ||
    !safeString(document.unique_identifier, 3, 40) ||
    typeof document.expires_on !== "string" ||
    !validIsoDate(document.expires_on) ||
    typeof document.issuing_country_code !== "string" ||
    !COUNTRY_CODE.test(document.issuing_country_code)
  ) {
    return null;
  }
  const uniqueIdentifier = safeString(document.unique_identifier, 3, 40);
  if (!uniqueIdentifier || !/^[A-Za-z0-9 -]+$/.test(uniqueIdentifier)) {
    return null;
  }
  return [
    {
      type: "passport",
      unique_identifier: uniqueIdentifier,
      expires_on: document.expires_on,
      issuing_country_code: document.issuing_country_code,
    },
  ];
}

function parsedOrderPassenger(value: unknown): ValidatedOrderPassenger | null {
  if (!isRecord(value)) return null;
  const id = safeString(value.id, 5, 200);
  const givenName = safeString(value.given_name, 1, 100);
  const familyName = safeString(value.family_name, 1, 100);
  const email = typeof value.email === "string" ? value.email : "";
  const phoneNumber = typeof value.phone_number === "string" ? value.phone_number : "";
  if (
    !id ||
    !PROVIDER_PASSENGER_ID.test(id) ||
    !["mr", "ms", "mrs", "miss", "dr"].includes(String(value.title)) ||
    !givenName ||
    !familyName ||
    typeof value.born_on !== "string" ||
    !validIsoDate(value.born_on) ||
    (value.gender !== "m" && value.gender !== "f") ||
    (email !== "" && (email.length > 254 || !EMAIL.test(email))) ||
    (phoneNumber !== "" && !PHONE.test(phoneNumber))
  ) {
    return null;
  }

  const identityDocuments =
    value.identity_documents === undefined
      ? undefined
      : parsedIdentityDocuments(value.identity_documents);
  if (value.identity_documents !== undefined && !identityDocuments) return null;
  const infantPassengerId =
    value.infant_passenger_id === undefined
      ? undefined
      : safeString(value.infant_passenger_id, 5, 200);
  if (
    value.infant_passenger_id !== undefined &&
    (!infantPassengerId || !PROVIDER_PASSENGER_ID.test(infantPassengerId))
  ) {
    return null;
  }

  return {
    id,
    title: value.title as ValidatedOrderPassenger["title"],
    given_name: givenName,
    family_name: familyName,
    born_on: value.born_on,
    gender: value.gender,
    email,
    phone_number: phoneNumber,
    ...(identityDocuments ? { identity_documents: identityDocuments } : {}),
    ...(infantPassengerId ? { infant_passenger_id: infantPassengerId } : {}),
  };
}

/** Returns a schema-clean copy of decrypted checkout data, or null on mismatch. */
export function parsePrivatePaymentCheckoutPayload(
  value: unknown,
): PrivatePaymentCheckoutPayload | null {
  if (
    !isRecord(value) ||
    value.version !== 1 ||
    typeof value.paymentEmail !== "string" ||
    value.paymentEmail.length > 254 ||
    !EMAIL.test(value.paymentEmail) ||
    typeof value.paymentReference !== "string" ||
    !PAYMENT_REFERENCE.test(value.paymentReference) ||
    typeof value.offerId !== "string" ||
    !OFFER_ID.test(value.offerId) ||
    !Array.isArray(value.passengers) ||
    value.passengers.length < 1 ||
    value.passengers.length > 9
  ) {
    return null;
  }
  const checkoutUrl =
    value.checkoutUrl === null ? null : officialCheckoutUrl(value.checkoutUrl);
  if (value.checkoutUrl !== null && !checkoutUrl) return null;
  const passengers = value.passengers.map(parsedOrderPassenger);
  if (passengers.some((passenger) => passenger === null)) return null;
  const cleanPassengers = passengers as ValidatedOrderPassenger[];
  if (
    cleanPassengers[0].email !== value.paymentEmail ||
    !PHONE.test(cleanPassengers[0].phone_number)
  ) {
    return null;
  }
  if (new Set(cleanPassengers.map((passenger) => passenger.id)).size !== cleanPassengers.length) {
    return null;
  }
  return {
    version: 1,
    paymentEmail: value.paymentEmail,
    paymentReference: value.paymentReference,
    checkoutUrl,
    offerId: value.offerId,
    passengers: cleanPassengers,
  };
}

export function isPrivatePaymentCheckoutPayload(
  value: unknown,
): value is PrivatePaymentCheckoutPayload {
  return parsePrivatePaymentCheckoutPayload(value) !== null;
}

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

function failure(error: unknown): Response {
  if (error instanceof PassengerValidationError) {
    return json(
      {
        ok: false,
        error: {
          code: "invalid_passengers",
          message: error.message,
          field: error.field,
        },
      },
      422,
    );
  }
  if (error instanceof PaymentCheckoutError) {
    return json(
      {
        ok: false,
        error: {
          code: error.code,
          message: error.message,
          retryable: error.retryable,
        },
      },
      error.status,
    );
  }
  if (error instanceof BookingStorageConflictError) {
    return json(
      {
        ok: false,
        error: {
          code: "idempotency_conflict",
          message: "This idempotency key was already used for another checkout.",
        },
      },
      409,
    );
  }
  if (error instanceof DuffelProviderError) {
    return json(
      {
        ok: false,
        error: {
          code: "fare_reconfirmation_failed",
          message: "The fare could not be reconfirmed.",
          retryable: error.retryable,
        },
      },
      error.status,
    );
  }
  if (error instanceof PaystackProviderError) {
    return json(
      {
        ok: false,
        error: {
          code: "payment_initialization_failed",
          message: "Secure payment could not be started.",
          retryable: error.retryable,
        },
      },
      error.status,
    );
  }
  return json(
    {
      ok: false,
      error: {
        code: "checkout_unavailable",
        message: "Secure checkout is temporarily unavailable.",
        retryable: true,
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

async function boundedJsonBody(request: Request): Promise<unknown> {
  const contentLength = request.headers.get("content-length");
  if (contentLength !== null) {
    if (!/^\d+$/.test(contentLength)) {
      throw new PaymentCheckoutError(
        "invalid_request",
        "The checkout request is invalid.",
        400,
      );
    }
    if (Number(contentLength) > MAX_BODY_BYTES) {
      throw new PaymentCheckoutError(
        "payload_too_large",
        "The checkout request is too large.",
        413,
      );
    }
  }
  const bytes = await request.arrayBuffer();
  if (bytes.byteLength > MAX_BODY_BYTES) {
    throw new PaymentCheckoutError(
      "payload_too_large",
      "The checkout request is too large.",
      413,
    );
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new PaymentCheckoutError(
      "invalid_json",
      "The checkout request is invalid.",
      400,
    );
  }
}

function sameProviderPassengers(
  selection: OfferSelectionRecord,
  refreshed: readonly { id: string; type: string }[],
): boolean {
  const stored = selection.fare.providerPassengers;
  return (
    Array.isArray(stored) &&
    stored.length === refreshed.length &&
    stored.every(
      (passenger, index) =>
        passenger.id === refreshed[index]?.id &&
        passenger.type === refreshed[index]?.type,
    )
  );
}

function passengerCounts(
  passengers: readonly { type: string }[],
): { adults: number; children: number; infantsWithoutSeat: number } {
  return {
    adults: passengers.filter((passenger) => passenger.type === "adult").length,
    children: passengers.filter(
      (passenger) =>
        passenger.type === "child" || passenger.type === "infant_with_seat",
    ).length,
    infantsWithoutSeat: passengers.filter(
      (passenger) => passenger.type === "infant_without_seat",
    ).length,
  };
}

async function encryptedPayloadRecord(
  payload: PrivatePaymentCheckoutPayload,
  attemptId: string,
  createdAt: number,
  expiresAt: number,
  encrypt: typeof encryptPrivateBookingPayload,
): Promise<PrivateBookingPayloadRecord> {
  const encrypted = await encrypt(payload, attemptId);
  return {
    bookingAttemptId: attemptId,
    ciphertext: encrypted.ciphertext,
    iv: encrypted.iv,
    createdAt,
    expiresAt,
  };
}

async function readPrivatePayload(
  repository: CheckoutRepository,
  attemptId: string,
  now: number,
  decrypt: typeof decryptPrivateBookingPayload,
): Promise<{
  payload: PrivatePaymentCheckoutPayload;
  record: PrivateBookingPayloadRecord;
} | null> {
  const record = await repository.getPrivatePayload(attemptId, now);
  if (!record) return null;
  const decrypted = await decrypt<unknown>(
    { ciphertext: record.ciphertext, iv: record.iv },
    attemptId,
  );
  const payload = parsePrivatePaymentCheckoutPayload(decrypted);
  if (!payload) {
    throw new PaymentCheckoutError(
      "checkout_state_invalid",
      "Secure checkout could not be resumed.",
      503,
      true,
    );
  }
  return { payload, record };
}

async function markAttemptFailed(
  repository: CheckoutRepository,
  attempt: BookingAttemptRecord,
  now: number,
  error: unknown,
): Promise<void> {
  try {
    const transitioned = await repository.transitionBookingAttempt({
      id: attempt.id,
      sessionHash: attempt.sessionHash,
      expectedStates: ["created"],
      nextState: "failed",
      failureCode:
        error instanceof PaystackProviderError
          ? `paystack_${error.code}`
          : error instanceof PaymentCheckoutError
            ? error.code
            : "payment_initialization_failed",
      retryable:
        error instanceof PaystackProviderError ||
        error instanceof PaymentCheckoutError
          ? error.retryable
          : true,
      now,
    });
    if (transitioned) await repository.deletePrivatePayload(attempt.id);
  } catch {
    // Cleanup must never replace the safe checkout error or expose private data.
  }
}

export function createPaymentCheckoutHandler(
  options: PaymentCheckoutHandlerOptions = {},
) {
  const configured = options.bookingConfigured ?? isLiveBookingConfigured;
  const currencyAllowed =
    options.paymentCurrencyAllowed ?? isPaystackBookingCurrency;
  const callbackUrl = options.getCallbackUrl ?? bookingCallbackUrl;
  const clock = options.now ?? (() => new Date());
  const makeAttemptId =
    options.createAttemptId ?? (() => `attempt-${crypto.randomUUID()}`);
  const makePaymentReference =
    options.createPaymentReference ?? ((attemptId) => `skyeta-${attemptId}`);
  const makeDuffelClient =
    options.createDuffelClient ?? (() => createDuffelClient());
  const makePaystackClient =
    options.createPaystackClient ?? (() => createPaystackClient());
  const encrypt = options.encryptPayload ?? encryptPrivateBookingPayload;
  const decrypt = options.decryptPayload ?? decryptPrivateBookingPayload;
  const getDatabase = options.getDatabase ?? environmentDatabase;
  const getRepository =
    options.getRepository ??
    (async () => new BookingRepository(await getDatabase()));

  return async function POST(request: Request): Promise<Response> {
    // This readiness gate intentionally runs before the PII-bearing body is read.
    if (!configured()) {
      return json(
        {
          ok: false,
          error: {
            code: "booking_not_configured",
            message: "Live booking and payment are not available.",
          },
        },
        503,
      );
    }
    if (!isSameOriginRequest(request)) {
      return json(
        {
          ok: false,
          error: {
            code: "invalid_origin",
            message: "This checkout request was not accepted.",
          },
        },
        403,
      );
    }
    if (!hasJsonContentType(request)) {
      return json(
        {
          ok: false,
          error: {
            code: "unsupported_media_type",
            message: "Submit checkout as JSON.",
          },
        },
        415,
      );
    }
    const idempotencyKey = request.headers.get("idempotency-key") ?? "";
    if (!isValidIdempotencyKey(idempotencyKey)) {
      return json(
        {
          ok: false,
          error: {
            code: "invalid_idempotency_key",
            message: "Use a valid idempotency key for checkout.",
          },
        },
        400,
      );
    }

    try {
      const body = await boundedJsonBody(request);
      const selectionId =
        isRecord(body) && typeof body.checkoutSessionId === "string"
          ? body.checkoutSessionId
          : "";
      if (!SELECTION_ID.test(selectionId)) {
        throw new PaymentCheckoutError(
          "checkout_not_found",
          "Checkout was not found.",
          404,
        );
      }
      const sessionToken = readBookingSessionCookie(
        request.headers.get("cookie"),
      );
      if (!sessionToken) {
        throw new PaymentCheckoutError(
          "checkout_not_found",
          "Checkout was not found.",
          404,
        );
      }

      const currentTime = clock().getTime();
      if (!Number.isSafeInteger(currentTime) || currentTime < 0) {
        throw new Error("Invalid checkout clock.");
      }
      const repository = await getRepository();
      const sessionHash = await hashBookingSessionToken(sessionToken);
      const session = await repository.getActiveSession(sessionHash, currentTime);
      if (!session) {
        throw new PaymentCheckoutError(
          "checkout_expired",
          "This checkout session has expired.",
          410,
        );
      }
      const selection = await repository.getOfferSelectionForSession(
        selectionId,
        sessionHash,
      );
      if (!selection) {
        throw new PaymentCheckoutError(
          "checkout_not_found",
          "Checkout was not found.",
          404,
        );
      }
      if (
        selection.provider !== "duffel" ||
        selection.providerEnvironment !== "live" ||
        (selection.status !== "selected" && selection.status !== "refreshed") ||
        selection.offerExpiresAt === null ||
        !Number.isSafeInteger(selection.offerExpiresAt) ||
        selection.offerExpiresAt <= currentTime ||
        !Number.isSafeInteger(selection.totalAmountMinor) ||
        selection.totalAmountMinor < 1 ||
        !OFFER_ID.test(selection.providerOfferId)
      ) {
        throw new PaymentCheckoutError(
          "fare_unavailable",
          "This fare is no longer available for live checkout.",
          409,
        );
      }
      if (!currencyAllowed(selection.currency)) {
        throw new PaymentCheckoutError(
          "unsupported_payment_currency",
          "This fare currency is not available for secure payment.",
          409,
        );
      }

      const providerResult = await makeDuffelClient().request<DuffelOffer>(
        `/air/offers/${selection.providerOfferId}`,
      );
      const refreshed = normalizeDuffelOffer(
        providerResult.data,
        providerResult.mode,
      );
      const refreshedExpiresAt = refreshed
        ? Date.parse(refreshed.expiresAt)
        : Number.NaN;
      let refreshedAmount: number | null = null;
      try {
        refreshedAmount = refreshed ? moneyToMinorUnits(refreshed.total) : null;
      } catch {
        refreshedAmount = null;
      }
      if (
        !refreshed ||
        providerResult.mode !== "live" ||
        refreshed.id !== selection.providerOfferId ||
        !refreshed.source.isLive ||
        !refreshed.isBookable ||
        !Number.isFinite(refreshedExpiresAt) ||
        refreshedExpiresAt <= currentTime ||
        refreshedAmount !== selection.totalAmountMinor ||
        refreshed.total.currency.toUpperCase() !== selection.currency.toUpperCase() ||
        !sameProviderPassengers(selection, refreshed.passengers)
      ) {
        throw new PaymentCheckoutError(
          "fare_changed",
          "The fare changed before payment. Start checkout again with the current fare.",
          409,
        );
      }
      const firstDepartureAt = refreshed.slices[0]?.segments[0]?.departingAt;
      if (!firstDepartureAt) {
        throw new PaymentCheckoutError(
          "fare_changed",
          "The fare changed before payment. Start checkout again with the current fare.",
          409,
        );
      }
      const passengerPayload = validatePassengerPayload(
        isRecord(body) ? body.passengers : undefined,
        refreshed.passengers,
        {
          identityDocumentsRequired:
            refreshed.passengerIdentityDocumentsRequired,
          firstDepartureAt,
        },
      );

      const idempotencyKeyHash = await hashIdempotencyKey(idempotencyKey);
      const requestFingerprint = await fingerprintBookingRequest({
        sessionHash,
        offerSelectionId: selection.id,
        currency: selection.currency,
        totalAmountMinor: selection.totalAmountMinor,
        passengerCounts: passengerCounts(refreshed.passengers),
      });
      const proposedAttemptId = makeAttemptId();
      if (!ATTEMPT_ID.test(proposedAttemptId)) {
        throw new Error("Invalid generated booking attempt identifier.");
      }
      const acquired = await repository.acquireBookingAttempt({
        id: proposedAttemptId,
        sessionHash,
        offerSelectionId: selection.id,
        idempotencyKeyHash,
        requestFingerprint,
        provider: "duffel",
        providerEnvironment: "live",
        currency: selection.currency,
        totalAmountMinor: selection.totalAmountMinor,
        now: currentTime,
      });
      const attempt = acquired.attempt;
      const existingPrivate = await readPrivatePayload(
        repository,
        attempt.id,
        currentTime,
        decrypt,
      );

      if (attempt.state === "awaiting_payment") {
        if (
          !existingPrivate?.payload.checkoutUrl ||
          existingPrivate.payload.offerId !== selection.providerOfferId ||
          existingPrivate.payload.paymentReference !== attempt.paymentReference
        ) {
          throw new PaymentCheckoutError(
            "checkout_state_invalid",
            "Secure checkout could not be resumed.",
            503,
            true,
          );
        }
        return json(
          { ok: true, checkoutUrl: existingPrivate.payload.checkoutUrl },
          200,
        );
      }
      if (attempt.state !== "created") {
        throw new PaymentCheckoutError(
          "checkout_already_processed",
          "This checkout request has already been processed.",
          409,
        );
      }

      let privatePayload: PrivatePaymentCheckoutPayload;
      let payloadCreatedAt: number;
      let payloadExpiresAt: number;
      if (existingPrivate) {
        if (existingPrivate.payload.offerId !== selection.providerOfferId) {
          throw new PaymentCheckoutError(
            "checkout_state_invalid",
            "Secure checkout could not be resumed.",
            503,
            true,
          );
        }
        privatePayload = existingPrivate.payload;
        payloadCreatedAt = existingPrivate.record.createdAt;
        payloadExpiresAt = existingPrivate.record.expiresAt;
      } else {
        const paymentReference = makePaymentReference(attempt.id);
        if (!PAYMENT_REFERENCE.test(paymentReference)) {
          throw new Error("Invalid generated payment reference.");
        }
        privatePayload = {
          version: 1,
          paymentEmail: passengerPayload.paymentEmail,
          paymentReference,
          checkoutUrl: null,
          offerId: selection.providerOfferId,
          passengers: passengerPayload.passengers,
        };
        payloadCreatedAt = currentTime;
        // Keep reconciliation material briefly beyond fare expiry because a
        // signed payment event can arrive after the selected offer expires.
        payloadExpiresAt = Math.min(
          currentTime + PRIVATE_PAYLOAD_TTL_MS,
          session.expiresAt,
        );
        await repository.savePrivatePayload(
          await encryptedPayloadRecord(
            privatePayload,
            attempt.id,
            payloadCreatedAt,
            payloadExpiresAt,
            encrypt,
          ),
        );
      }

      if (privatePayload.checkoutUrl) {
        const transitioned = await repository.transitionBookingAttempt({
          id: attempt.id,
          sessionHash,
          expectedStates: ["created"],
          nextState: "awaiting_payment",
          paymentReference: privatePayload.paymentReference,
          now: currentTime,
        });
        if (!transitioned) {
          throw new PaymentCheckoutError(
            "checkout_state_invalid",
            "Secure checkout could not be resumed.",
            503,
            true,
          );
        }
        return json({ ok: true, checkoutUrl: privatePayload.checkoutUrl }, 200);
      }

      try {
        const initialized = await makePaystackClient().initializeTransaction({
          email: privatePayload.paymentEmail,
          amount: selection.totalAmountMinor,
          currency: selection.currency.toUpperCase(),
          reference: privatePayload.paymentReference,
          callbackUrl: callbackUrl(),
          metadata: { bookingAttemptId: attempt.id },
        });
        const hostedUrl = officialCheckoutUrl(initialized.authorizationUrl);
        if (
          initialized.environment !== "live" ||
          initialized.reference !== privatePayload.paymentReference ||
          !hostedUrl
        ) {
          throw new PaymentCheckoutError(
            "payment_invalid_response",
            "Secure payment could not be started.",
            502,
            true,
          );
        }
        privatePayload = { ...privatePayload, checkoutUrl: hostedUrl };
        await repository.savePrivatePayload(
          await encryptedPayloadRecord(
            privatePayload,
            attempt.id,
            payloadCreatedAt,
            payloadExpiresAt,
            encrypt,
          ),
        );
        const transitioned = await repository.transitionBookingAttempt({
          id: attempt.id,
          sessionHash,
          expectedStates: ["created"],
          nextState: "awaiting_payment",
          providerRequestId: initialized.requestId,
          paymentReference: initialized.reference,
          failureCode: null,
          retryable: false,
          now: currentTime,
        });
        if (!transitioned) {
          throw new PaymentCheckoutError(
            "checkout_state_invalid",
            "Secure checkout could not be finalized.",
            503,
            true,
          );
        }
        return json({ ok: true, checkoutUrl: hostedUrl }, 201);
      } catch (error) {
        await markAttemptFailed(repository, attempt, currentTime, error);
        throw error;
      }
    } catch (error) {
      return failure(error);
    }
  };
}

export const createPaystackCheckoutHandler = createPaymentCheckoutHandler;
