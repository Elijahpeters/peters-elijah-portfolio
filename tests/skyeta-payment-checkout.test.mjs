import assert from "node:assert/strict";
import test from "node:test";

import {
  createPaymentCheckoutHandler,
  parsePrivatePaymentCheckoutPayload,
} from "../app/api/skyeta/payments/checkout/checkout.ts";
import { PaystackProviderError } from "../app/lib/paystack/client.ts";

const NOW = Date.parse("2026-08-05T12:00:00.000Z");
const SELECTION_ID = `sel_${"a".repeat(32)}`;
const SESSION_TOKEN = "A".repeat(43);
const OFFER_ID = "off_live123";
const IDEMPOTENCY_KEY = "checkout-1234567890abcdef";
const ATTEMPT_ID = "attempt-12345678-1234-4234-9234-123456789abc";
const PAYMENT_REFERENCE = `skyeta-${ATTEMPT_ID}`;
const CHECKOUT_URL = "https://checkout.paystack.com/hosted-123";

const passengerInput = [
  {
    type: "adult",
    title: "mr",
    givenName: "Peter",
    familyName: "Example",
    bornOn: "1990-01-02",
    gender: "m",
    email: "Peter@example.com",
    phoneNumber: "+2348012345678",
  },
];

function duffelOffer(overrides = {}) {
  return {
    id: OFFER_ID,
    live_mode: true,
    partial: false,
    expires_at: "2026-08-05T12:20:00Z",
    total_amount: "1250.50",
    total_currency: "NGN",
    owner: { name: "Test Air", iata_code: "TA" },
    passengers: [{ id: "pas_adult", type: "adult" }],
    passenger_identity_documents_required: false,
    supported_passenger_identity_document_types: [],
    slices: [
      {
        id: "sli_1",
        segments: [
          {
            id: "seg_1",
            departing_at: "2026-08-06T08:00:00",
            arriving_at: "2026-08-06T10:00:00",
            origin: { iata_code: "LOS" },
            destination: { iata_code: "ABV" },
            marketing_carrier: { name: "Test Air", iata_code: "TA" },
            operating_carrier: { name: "Test Air", iata_code: "TA" },
            passengers: [
              { passenger_id: "pas_adult", cabin_class: "economy" },
            ],
          },
        ],
      },
    ],
    ...overrides,
  };
}

function selection(overrides = {}) {
  return {
    id: SELECTION_ID,
    sessionHash: "session-hash",
    provider: "duffel",
    providerEnvironment: "live",
    providerOfferId: OFFER_ID,
    status: "refreshed",
    offerExpiresAt: Date.parse("2026-08-05T12:20:00Z"),
    currency: "NGN",
    totalAmountMinor: 125050,
    itinerary: {
      journeys: [],
      totalSegments: 1,
      totalStops: 0,
    },
    fare: {
      cabinClass: "economy",
      fareBrand: null,
      passengerTypes: ["adult"],
      providerPassengers: [{ id: "pas_adult", type: "adult" }],
      identityDocumentsRequired: false,
      supportedIdentityDocumentTypes: [],
      changeable: null,
      refundable: null,
      baggage: [],
    },
    risk: {
      coverage: "unavailable",
      delayRiskPercent: null,
      coveredSegments: 0,
      totalSegments: 1,
      modelVersion: null,
    },
    providerSnapshotHash: "snapshot",
    createdAt: NOW,
    updatedAt: NOW,
    ...overrides,
  };
}

function bookingAttempt(overrides = {}) {
  return {
    id: ATTEMPT_ID,
    sessionHash: "session-hash",
    offerSelectionId: SELECTION_ID,
    idempotencyKeyHash: "idempotency-hash",
    requestFingerprint: "request-fingerprint",
    provider: "duffel",
    providerEnvironment: "live",
    state: "created",
    currency: "NGN",
    totalAmountMinor: 125050,
    providerRequestId: null,
    paymentReference: null,
    failureCode: null,
    retryable: false,
    createdAt: NOW,
    updatedAt: NOW,
    ...overrides,
  };
}

function fakeRepository(options = {}) {
  const savedPayloads = [];
  const transitions = [];
  const acquiredInputs = [];
  const deletedPayloads = [];
  let attempt = options.attempt ?? bookingAttempt();
  return {
    savedPayloads,
    transitions,
    acquiredInputs,
    deletedPayloads,
    async getActiveSession(sessionHash) {
      return {
        sessionHash,
        status: "active",
        createdAt: NOW,
        lastSeenAt: NOW,
        expiresAt: NOW + 24 * 60 * 60 * 1000,
      };
    },
    async getOfferSelectionForSession() {
      return options.selection ?? selection();
    },
    async acquireBookingAttempt(input) {
      acquiredInputs.push(input);
      return { attempt, created: options.created ?? true };
    },
    async getBookingAttemptForSession() {
      return attempt;
    },
    async transitionBookingAttempt(input) {
      transitions.push(input);
      attempt = {
        ...attempt,
        state: input.nextState,
        paymentReference:
          input.paymentReference === undefined
            ? attempt.paymentReference
            : input.paymentReference,
        providerRequestId:
          input.providerRequestId === undefined
            ? attempt.providerRequestId
            : input.providerRequestId,
        failureCode:
          input.failureCode === undefined
            ? attempt.failureCode
            : input.failureCode,
        retryable:
          input.retryable === undefined ? attempt.retryable : input.retryable,
      };
      return options.transitionReturnsNull ? null : attempt;
    },
    async savePrivatePayload(record) {
      savedPayloads.push(record);
      return record;
    },
    async getPrivatePayload() {
      return options.privateRecord ?? null;
    },
    async deletePrivatePayload(id) {
      deletedPayloads.push(id);
      return true;
    },
  };
}

function checkoutRequest(body, headers = {}) {
  return new Request("https://portfolio.example/api/skyeta/payments/checkout", {
    method: "POST",
    headers: {
      Origin: "https://portfolio.example",
      "Content-Type": "application/json",
      "Idempotency-Key": IDEMPOTENCY_KEY,
      Cookie: `skyeta_booking_session=${SESSION_TOKEN}`,
      ...headers,
    },
    body: JSON.stringify(body),
  });
}

function successfulOptions(repository, captures = {}) {
  const encryptedValues = captures.encryptedValues ?? [];
  return {
    bookingConfigured: () => true,
    paymentCurrencyAllowed: () => true,
    getCallbackUrl: () =>
      "https://portfolio.example/skyeta/payment/return",
    now: () => new Date(NOW),
    createAttemptId: () => ATTEMPT_ID,
    createPaymentReference: () => PAYMENT_REFERENCE,
    getRepository: () => repository,
    createDuffelClient: () => ({
      async request(path) {
        captures.duffelPath = path;
        return {
          data: captures.offer ?? duffelOffer(),
          mode: "live",
          requestId: "duffel-request",
        };
      },
    }),
    createPaystackClient: () => ({
      async initializeTransaction(input) {
        captures.paystackInput = input;
        if (captures.paystackError) throw captures.paystackError;
        return {
          authorizationUrl: CHECKOUT_URL,
          accessCode: "hosted-123",
          reference: PAYMENT_REFERENCE,
          environment: "live",
          requestId: "paystack-request",
        };
      },
    }),
    async encryptPayload(value) {
      encryptedValues.push(structuredClone(value));
      return {
        ciphertext: `ciphertext-${encryptedValues.length}`,
        iv: `iv-${encryptedValues.length}`,
      };
    },
    encryptedValues,
  };
}

test("disabled booking is rejected before the PII body is read", async () => {
  let bodyReads = 0;
  let dependencyCalls = 0;
  const handler = createPaymentCheckoutHandler({
    bookingConfigured: () => false,
    getRepository: () => {
      dependencyCalls += 1;
      throw new Error("must not be called");
    },
  });
  const request = {
    url: "https://portfolio.example/api/skyeta/payments/checkout",
    headers: new Headers({ "Content-Type": "application/json" }),
    async arrayBuffer() {
      bodyReads += 1;
      return new ArrayBuffer(0);
    },
  };

  const response = await handler(request);
  assert.equal(response.status, 503);
  assert.equal(bodyReads, 0);
  assert.equal(dependencyCalls, 0);
  assert.equal((await response.json()).error.code, "booking_not_configured");
});

test("checkout initializes the exact live fare and stores only encrypted PII", async () => {
  const repository = fakeRepository();
  const captures = { encryptedValues: [] };
  const handler = createPaymentCheckoutHandler(
    successfulOptions(repository, captures),
  );

  const response = await handler(
    checkoutRequest({ checkoutSessionId: SELECTION_ID, passengers: passengerInput }),
  );
  const body = await response.json();

  assert.equal(response.status, 201);
  assert.deepEqual(body, { ok: true, checkoutUrl: CHECKOUT_URL });
  assert.equal(JSON.stringify(body).includes("Peter"), false);
  assert.equal(JSON.stringify(body).includes(PAYMENT_REFERENCE), false);
  assert.equal(captures.duffelPath, `/air/offers/${OFFER_ID}`);
  assert.deepEqual(captures.paystackInput, {
    email: "peter@example.com",
    amount: 125050,
    currency: "NGN",
    reference: PAYMENT_REFERENCE,
    callbackUrl: "https://portfolio.example/skyeta/payment/return",
    metadata: { bookingAttemptId: ATTEMPT_ID },
  });
  assert.equal(repository.savedPayloads.length, 2);
  assert.equal(repository.savedPayloads[0].ciphertext, "ciphertext-1");
  assert.equal("passengers" in repository.savedPayloads[0], false);
  assert.equal(
    repository.savedPayloads[0].expiresAt,
    NOW + 2 * 60 * 60 * 1000,
  );
  assert.equal(
    repository.savedPayloads[0].expiresAt > selection().offerExpiresAt,
    true,
  );
  assert.equal(captures.encryptedValues[0].checkoutUrl, null);
  assert.equal(captures.encryptedValues[1].checkoutUrl, CHECKOUT_URL);
  assert.equal(captures.encryptedValues[0].paymentEmail, "peter@example.com");
  assert.equal(captures.encryptedValues[0].passengers[0].id, "pas_adult");
  assert.equal(repository.transitions.at(-1).nextState, "awaiting_payment");
  assert.equal(
    repository.transitions.at(-1).paymentReference,
    PAYMENT_REFERENCE,
  );
  assert.equal(repository.transitions.at(-1).providerRequestId, "paystack-request");
  assert.doesNotMatch(
    JSON.stringify(repository.acquiredInputs[0]),
    /Peter|peter@example.com|\+2348012345678/,
  );
});
test("changed provider amount is rejected before passenger storage or payment", async () => {
  const repository = fakeRepository();
  const captures = {
    offer: duffelOffer({ total_amount: "1251.50" }),
    encryptedValues: [],
  };
  const handler = createPaymentCheckoutHandler(
    successfulOptions(repository, captures),
  );
  const response = await handler(
    checkoutRequest({ checkoutSessionId: SELECTION_ID, passengers: passengerInput }),
  );
  const body = await response.json();

  assert.equal(response.status, 409);
  assert.equal(body.error.code, "fare_changed");
  assert.equal(captures.paystackInput, undefined);
  assert.equal(captures.encryptedValues.length, 0);
  assert.equal(repository.acquiredInputs.length, 0);
});

test("Paystack initialization failure marks the attempt failed and deletes ciphertext", async () => {
  const repository = fakeRepository();
  const captures = {
    encryptedValues: [],
    paystackError: new PaystackProviderError({
      code: "unavailable",
      message: "The payment provider is unavailable.",
      status: 502,
      retryable: true,
    }),
  };
  const handler = createPaymentCheckoutHandler(
    successfulOptions(repository, captures),
  );
  const response = await handler(
    checkoutRequest({ checkoutSessionId: SELECTION_ID, passengers: passengerInput }),
  );
  const body = await response.json();

  assert.equal(response.status, 502);
  assert.equal(body.error.code, "payment_initialization_failed");
  assert.equal(repository.transitions.at(-1).nextState, "failed");
  assert.equal(repository.transitions.at(-1).failureCode, "paystack_unavailable");
  assert.deepEqual(repository.deletedPayloads, [ATTEMPT_ID]);
  assert.doesNotMatch(JSON.stringify(body), /Peter|peter@example.com|hosted-123/);
});

test("an awaiting idempotent attempt returns its encrypted hosted URL without reinitializing", async () => {
  const repository = fakeRepository({
    created: false,
    attempt: bookingAttempt({
      state: "awaiting_payment",
      paymentReference: PAYMENT_REFERENCE,
    }),
    privateRecord: {
      bookingAttemptId: ATTEMPT_ID,
      ciphertext: "ciphertext",
      iv: "iv",
      createdAt: NOW,
      expiresAt: NOW + 60_000,
    },
  });
  const captures = { encryptedValues: [], paystackCalls: 0 };
  const options = successfulOptions(repository, captures);
  options.decryptPayload = async () => ({
    version: 1,
    paymentEmail: "peter@example.com",
    paymentReference: PAYMENT_REFERENCE,
    checkoutUrl: CHECKOUT_URL,
    offerId: OFFER_ID,
    passengers: [
      {
        id: "pas_adult",
        title: "mr",
        given_name: "Peter",
        family_name: "Example",
        born_on: "1990-01-02",
        gender: "m",
        email: "peter@example.com",
        phone_number: "+2348012345678",
      },
    ],
  });
  options.createPaystackClient = () => ({
    async initializeTransaction() {
      captures.paystackCalls += 1;
      throw new Error("must not initialize twice");
    },
  });
  const response = await createPaymentCheckoutHandler(options)(
    checkoutRequest({ checkoutSessionId: SELECTION_ID, passengers: passengerInput }),
  );

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, checkoutUrl: CHECKOUT_URL });
  assert.equal(captures.paystackCalls, 0);
  assert.equal(repository.savedPayloads.length, 0);
});

test("private checkout parser returns a schema-clean payload", () => {
  const parsed = parsePrivatePaymentCheckoutPayload({
    version: 1,
    paymentEmail: "peter@example.com",
    paymentReference: PAYMENT_REFERENCE,
    checkoutUrl: CHECKOUT_URL,
    offerId: OFFER_ID,
    arbitrarySecret: "must be dropped",
    passengers: [
      {
        id: "pas_adult",
        title: "mr",
        given_name: "Peter",
        family_name: "Example",
        born_on: "1990-01-02",
        gender: "m",
        email: "peter@example.com",
        phone_number: "+2348012345678",
        providerSecret: "must be dropped",
      },
    ],
  });

  assert.ok(parsed);
  assert.equal("arbitrarySecret" in parsed, false);
  assert.equal("providerSecret" in parsed.passengers[0], false);
  assert.equal(
    parsePrivatePaymentCheckoutPayload({
      ...parsed,
      checkoutUrl: "https://checkout.paystack.com.attacker.invalid/x",
    }),
    null,
  );
});
