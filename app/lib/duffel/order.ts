import type { ValidatedOrderPassenger } from "../booking/passengers";
import {
  createDuffelClient,
  DuffelProviderError,
  type DuffelResult,
} from "./client.ts";

export const DUFFEL_ORDER_TIMEOUT_MS = 135_000;

const OFFER_ID = /^off_[A-Za-z0-9_]{1,190}$/;
const PASSENGER_ID = /^pas_[A-Za-z0-9_-]{1,190}$/;
const ORDER_ID = /^ord_[A-Za-z0-9_-]{1,190}$/;
const MONEY_AMOUNT = /^(?:0|[1-9]\d*)(?:\.\d{1,6})?$/;
const CURRENCY = /^[A-Z]{3}$/;
const BOOKING_ATTEMPT_ID = /^[A-Za-z0-9._:-]{1,128}$/;
const REQUEST_ID = /^[A-Za-z0-9._:-]{1,200}$/;
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE = /^\+[1-9]\d{6,14}$/;
const COUNTRY_CODE = /^[A-Z]{2}$/;
const DOCUMENT_IDENTIFIER = /^[A-Za-z0-9 -]+$/;
const CONTROL_CHARACTERS = /[\u0000-\u001F\u007F]/u;
const TITLES = new Set(["mr", "ms", "mrs", "miss", "dr"]);
const GENDERS = new Set(["m", "f"]);
const PASSENGER_KEYS = new Set([
  "id",
  "title",
  "given_name",
  "family_name",
  "born_on",
  "gender",
  "email",
  "phone_number",
  "identity_documents",
  "infant_passenger_id",
]);
const DOCUMENT_KEYS = new Set([
  "type",
  "unique_identifier",
  "expires_on",
  "issuing_country_code",
]);

type DuffelOrderResponse = {
  id?: unknown;
  booking_reference?: unknown;
  total_amount?: unknown;
  total_currency?: unknown;
  live_mode?: unknown;
};

export type DuffelOrderClient = {
  request<T>(
    path: string,
    options: {
      method: "POST";
      body: unknown;
      idempotencyKey: string;
      signal?: AbortSignal;
      timeoutMs: number;
    },
  ): Promise<DuffelResult<T>>;
};

export type CreateDuffelOrderInput = Readonly<{
  offerId: string;
  amount: string;
  currency: string;
  passengers: readonly ValidatedOrderPassenger[];
  bookingAttemptId: string;
  signal?: AbortSignal;
}>;

export type CreatedDuffelOrder = Readonly<{
  id: string;
  bookingReference: string;
  total: Readonly<{
    amount: string;
    currency: string;
  }>;
  liveMode: boolean;
  providerStatus: 200 | 201;
  requestId: string | null;
}>;

export type DuffelOrderFailureOutcome =
  | "uncertain"
  | "retryable"
  | "definitive";

export type DuffelOrderFailureCode =
  | "order_submission_uncertain"
  | "order_submission_retryable"
  | "order_rejected";

export class DuffelOrderError extends Error {
  readonly code: DuffelOrderFailureCode;
  readonly outcome: DuffelOrderFailureOutcome;
  readonly status: number;
  readonly providerStatus: number | null;
  readonly requestId: string | null;
  readonly retryable: boolean;
  readonly neverRetry: boolean;

  constructor(options: {
    outcome: DuffelOrderFailureOutcome;
    providerStatus?: number | null;
    requestId?: string | null;
  }) {
    const code =
      options.outcome === "uncertain"
        ? "order_submission_uncertain"
        : options.outcome === "retryable"
          ? "order_submission_retryable"
          : "order_rejected";
    const message =
      options.outcome === "uncertain"
        ? "The booking result could not be confirmed. Do not submit it again automatically."
        : options.outcome === "retryable"
          ? "The flight provider is temporarily unavailable."
          : "The flight provider rejected the booking request.";
    super(message);
    this.name = "DuffelOrderError";
    this.code = code;
    this.outcome = options.outcome;
    this.status =
      options.outcome === "uncertain"
        ? 502
        : options.outcome === "retryable"
          ? 503
          : 422;
    this.providerStatus = options.providerStatus ?? null;
    this.requestId = options.requestId ?? null;
    this.retryable = options.outcome === "retryable";
    this.neverRetry = options.outcome === "uncertain";
  }
}

export class DuffelOrderInputError extends TypeError {
  readonly field: string;

  constructor(field: string) {
    super("The flight order request is invalid.");
    this.name = "DuffelOrderInputError";
    this.field = field;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function invalidInput(field: string): never {
  throw new DuffelOrderInputError(field);
}

function exactString(
  value: unknown,
  field: string,
  minimum: number,
  maximum: number,
): string {
  if (
    typeof value !== "string" ||
    value.length < minimum ||
    value.length > maximum ||
    value.trim() !== value ||
    CONTROL_CHARACTERS.test(value)
  ) {
    invalidInput(field);
  }
  return value;
}

function isoDate(value: unknown, field: string): string {
  const date = exactString(value, field, 10, 10);
  const match = ISO_DATE.exec(date);
  if (!match) invalidInput(field);
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (
    parsed.getUTCFullYear() !== year ||
    parsed.getUTCMonth() !== month - 1 ||
    parsed.getUTCDate() !== day
  ) {
    invalidInput(field);
  }
  return date;
}

function onlyKeys(
  value: Record<string, unknown>,
  allowed: ReadonlySet<string>,
  field: string,
): void {
  if (Object.keys(value).some((key) => !allowed.has(key))) {
    invalidInput(field);
  }
}

function validatedPassenger(
  passenger: unknown,
  index: number,
  ids: Set<string>,
): ValidatedOrderPassenger {
  const field = `passengers[${index}]`;
  if (!isRecord(passenger)) invalidInput(field);
  onlyKeys(passenger, PASSENGER_KEYS, field);

  const id = exactString(passenger.id, `${field}.id`, 5, 194);
  if (!PASSENGER_ID.test(id) || ids.has(id)) invalidInput(`${field}.id`);
  ids.add(id);

  const title = exactString(passenger.title, `${field}.title`, 2, 4);
  if (!TITLES.has(title)) invalidInput(`${field}.title`);
  const gender = exactString(passenger.gender, `${field}.gender`, 1, 1);
  if (!GENDERS.has(gender)) invalidInput(`${field}.gender`);
  const email = exactString(passenger.email, `${field}.email`, index === 0 ? 3 : 0, 254);
  if (
    (email.length > 0 && (!EMAIL.test(email) || email.toLowerCase() !== email)) ||
    (index === 0 && email.length === 0)
  ) {
    invalidInput(`${field}.email`);
  }
  const phoneNumber = exactString(
    passenger.phone_number,
    `${field}.phone_number`,
    index === 0 ? 8 : 0,
    16,
  );
  if (
    (phoneNumber.length > 0 && !PHONE.test(phoneNumber)) ||
    (index === 0 && phoneNumber.length === 0)
  ) {
    invalidInput(`${field}.phone_number`);
  }

  let identityDocuments: ValidatedOrderPassenger["identity_documents"];
  if (passenger.identity_documents !== undefined) {
    if (
      !Array.isArray(passenger.identity_documents) ||
      passenger.identity_documents.length !== 1
    ) {
      invalidInput(`${field}.identity_documents`);
    }
    identityDocuments = passenger.identity_documents.map((document, documentIndex) => {
      const documentField = `${field}.identity_documents[${documentIndex}]`;
      if (!isRecord(document)) invalidInput(documentField);
      onlyKeys(document, DOCUMENT_KEYS, documentField);
      if (document.type !== "passport") invalidInput(`${documentField}.type`);
      const uniqueIdentifier = exactString(
        document.unique_identifier,
        `${documentField}.unique_identifier`,
        3,
        40,
      );
      if (!DOCUMENT_IDENTIFIER.test(uniqueIdentifier)) {
        invalidInput(`${documentField}.unique_identifier`);
      }
      const issuingCountryCode = exactString(
        document.issuing_country_code,
        `${documentField}.issuing_country_code`,
        2,
        2,
      );
      if (!COUNTRY_CODE.test(issuingCountryCode)) {
        invalidInput(`${documentField}.issuing_country_code`);
      }
      return {
        type: "passport" as const,
        unique_identifier: uniqueIdentifier,
        expires_on: isoDate(document.expires_on, `${documentField}.expires_on`),
        issuing_country_code: issuingCountryCode,
      };
    });
  }

  let infantPassengerId: string | undefined;
  if (passenger.infant_passenger_id !== undefined) {
    infantPassengerId = exactString(
      passenger.infant_passenger_id,
      `${field}.infant_passenger_id`,
      5,
      194,
    );
    if (!PASSENGER_ID.test(infantPassengerId) || infantPassengerId === id) {
      invalidInput(`${field}.infant_passenger_id`);
    }
  }

  return {
    id,
    title: title as ValidatedOrderPassenger["title"],
    given_name: exactString(passenger.given_name, `${field}.given_name`, 1, 100),
    family_name: exactString(passenger.family_name, `${field}.family_name`, 1, 100),
    born_on: isoDate(passenger.born_on, `${field}.born_on`),
    gender: gender as ValidatedOrderPassenger["gender"],
    email,
    phone_number: phoneNumber,
    ...(identityDocuments ? { identity_documents: identityDocuments } : {}),
    ...(infantPassengerId ? { infant_passenger_id: infantPassengerId } : {}),
  };
}

function validatedInput(value: CreateDuffelOrderInput): {
  offerId: string;
  amount: string;
  currency: string;
  passengers: ValidatedOrderPassenger[];
  bookingAttemptId: string;
  signal?: AbortSignal;
} {
  if (!isRecord(value)) invalidInput("order");
  if (typeof value.offerId !== "string" || !OFFER_ID.test(value.offerId)) {
    invalidInput("offerId");
  }
  if (
    typeof value.amount !== "string" ||
    value.amount.length > 50 ||
    !MONEY_AMOUNT.test(value.amount)
  ) {
    invalidInput("amount");
  }
  if (typeof value.currency !== "string" || !CURRENCY.test(value.currency)) {
    invalidInput("currency");
  }
  if (
    typeof value.bookingAttemptId !== "string" ||
    !BOOKING_ATTEMPT_ID.test(value.bookingAttemptId)
  ) {
    invalidInput("bookingAttemptId");
  }
  if (
    !Array.isArray(value.passengers) ||
    value.passengers.length < 1 ||
    value.passengers.length > 9
  ) {
    invalidInput("passengers");
  }

  const ids = new Set<string>();
  const passengers = value.passengers.map((passenger, index) =>
    validatedPassenger(passenger, index, ids));
  const attachedInfants = new Set<string>();
  passengers.forEach((passenger, index) => {
    const infantId = passenger.infant_passenger_id;
    if (
      infantId &&
      (!ids.has(infantId) || attachedInfants.has(infantId))
    ) {
      invalidInput(`passengers[${index}].infant_passenger_id`);
    }
    if (infantId) attachedInfants.add(infantId);
  });

  if (
    value.signal !== undefined &&
    !(value.signal instanceof AbortSignal)
  ) {
    invalidInput("signal");
  }

  return {
    offerId: value.offerId,
    amount: value.amount,
    currency: value.currency,
    passengers,
    bookingAttemptId: value.bookingAttemptId,
    ...(value.signal ? { signal: value.signal } : {}),
  };
}

function orderFailure(
  outcome: DuffelOrderFailureOutcome,
  providerStatus: number | null = null,
  requestId: string | null = null,
): DuffelOrderError {
  return new DuffelOrderError({
    outcome,
    providerStatus,
    requestId:
      typeof requestId === "string" && REQUEST_ID.test(requestId)
        ? requestId
        : null,
  });
}

function classifiedFailure(error: unknown): DuffelOrderError {
  if (error instanceof DuffelOrderError) return error;

  if (error instanceof DuffelProviderError) {
    const providerStatus = error.providerStatus;
    if (providerStatus === 503) {
      return orderFailure("retryable", providerStatus, error.requestId);
    }
    if (
      providerStatus === 202 ||
      (providerStatus !== null && providerStatus >= 500) ||
      error.code === "timeout" ||
      error.code === "unavailable" ||
      error.code === "invalid_response"
    ) {
      return orderFailure("uncertain", providerStatus, error.requestId);
    }
    if (
      providerStatus !== null &&
      providerStatus >= 400 &&
      providerStatus < 500
    ) {
      return orderFailure("definitive", providerStatus, error.requestId);
    }
    return orderFailure("definitive", providerStatus, error.requestId);
  }

  // Once request() has been invoked, an unknown rejection may be a transport
  // failure. It must never cause an automatic second order submission.
  return orderFailure("uncertain");
}

function normalizedOrder(
  result: DuffelResult<DuffelOrderResponse>,
  input: { amount: string; currency: string },
): CreatedDuffelOrder | null {
  if (result.providerStatus !== 200 && result.providerStatus !== 201) {
    return null;
  }
  if (!isRecord(result.data)) return null;

  const order = result.data as DuffelOrderResponse;
  if (
    typeof order.id !== "string" ||
    !ORDER_ID.test(order.id) ||
    typeof order.booking_reference !== "string" ||
    order.booking_reference.length < 1 ||
    order.booking_reference.length > 100 ||
    order.booking_reference.trim() !== order.booking_reference ||
    CONTROL_CHARACTERS.test(order.booking_reference) ||
    typeof order.total_amount !== "string" ||
    !MONEY_AMOUNT.test(order.total_amount) ||
    order.total_amount !== input.amount ||
    typeof order.total_currency !== "string" ||
    !CURRENCY.test(order.total_currency) ||
    order.total_currency !== input.currency ||
    typeof order.live_mode !== "boolean" ||
    (result.mode !== "test" && result.mode !== "live")
  ) {
    return null;
  }

  return {
    id: order.id,
    bookingReference: order.booking_reference,
    total: {
      amount: order.total_amount,
      currency: order.total_currency,
    },
    liveMode: result.mode === "live" && order.live_mode,
    providerStatus: result.providerStatus,
    requestId:
      typeof result.requestId === "string" && REQUEST_ID.test(result.requestId)
        ? result.requestId
        : null,
  };
}

export function createDuffelOrderService(
  options: { client?: DuffelOrderClient } = {},
) {
  const client = options.client ?? createDuffelClient();

  return {
    async createOrder(
      rawInput: CreateDuffelOrderInput,
    ): Promise<CreatedDuffelOrder> {
      const input = validatedInput(rawInput);
      let result: DuffelResult<DuffelOrderResponse>;
      try {
        result = await client.request<DuffelOrderResponse>("/air/orders", {
          method: "POST",
          body: {
            data: {
              type: "instant",
              selected_offers: [input.offerId],
              payments: [
                {
                  type: "balance",
                  currency: input.currency,
                  amount: input.amount,
                },
              ],
              passengers: input.passengers,
              metadata: { booking_attempt_id: input.bookingAttemptId },
            },
          },
          idempotencyKey: `skyeta-order:${input.bookingAttemptId}`,
          ...(input.signal ? { signal: input.signal } : {}),
          timeoutMs: DUFFEL_ORDER_TIMEOUT_MS,
        });
      } catch (error) {
        throw classifiedFailure(error);
      }

      if (result.providerStatus === 202) {
        throw orderFailure("uncertain", 202, result.requestId);
      }
      const order = normalizedOrder(result, input);
      if (!order) {
        throw orderFailure(
          "uncertain",
          typeof result.providerStatus === "number"
            ? result.providerStatus
            : null,
          typeof result.requestId === "string" ? result.requestId : null,
        );
      }
      return order;
    },
  };
}
