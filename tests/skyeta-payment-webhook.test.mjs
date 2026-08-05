import assert from "node:assert/strict";
import test from "node:test";

import { createPaystackBookingWebhookHandler } from "../app/api/skyeta/payments/paystack/webhook/webhook.ts";
import { DuffelOrderError } from "../app/lib/duffel/order.ts";

const NOW = new Date("2026-08-05T12:00:00Z");
const REFERENCE = "skyeta-attempt-123";
const ATTEMPT_ID = "attempt-123";
const OFFER_ID = "off_live_123";

const passenger = {
  id: "pas_adult_1",
  title: "ms",
  given_name: "Ada",
  family_name: "Example",
  born_on: "1990-01-01",
  gender: "f",
  email: "traveller@example.com",
  phone_number: "+2348000000000",
};

const privatePayload = {
  version: 1,
  paymentEmail: "traveller@example.com",
  paymentReference: REFERENCE,
  checkoutUrl: "https://checkout.paystack.com/example",
  offerId: OFFER_ID,
  passengers: [passenger],
};

function attempt(overrides = {}) {
  return {
    id: ATTEMPT_ID,
    sessionHash: "session-hash",
    offerSelectionId: "sel_12345678901234567890123456789012",
    idempotencyKeyHash: "idempotency-hash",
    requestFingerprint: "fingerprint",
    provider: "duffel",
    providerEnvironment: "live",
    state: "awaiting_payment",
    currency: "USD",
    totalAmountMinor: 12_500,
    providerRequestId: null,
    paymentReference: REFERENCE,
    failureCode: null,
    retryable: false,
    createdAt: NOW.getTime() - 1_000,
    updatedAt: NOW.getTime() - 1_000,
    ...overrides,
  };
}

function selection() {
  return {
    id: "sel_12345678901234567890123456789012",
    sessionHash: "session-hash",
    provider: "duffel",
    providerEnvironment: "live",
    providerOfferId: OFFER_ID,
    status: "refreshed",
    offerExpiresAt: NOW.getTime() + 3_600_000,
    currency: "USD",
    totalAmountMinor: 12_500,
    itinerary: {
      journeys: [
        {
          origin: "JFK",
          destination: "LAX",
          departureAt: "2026-08-06T10:00:00Z",
          arrivalAt: "2026-08-06T13:00:00Z",
          segmentCount: 1,
          marketingCarriers: ["ZZ"],
        },
      ],
      totalSegments: 1,
      totalStops: 0,
    },
    fare: {
      cabinClass: "economy",
      fareBrand: null,
      passengerTypes: ["adult"],
      providerPassengers: [{ id: "pas_adult_1", type: "adult" }],
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
    createdAt: NOW.getTime() - 1_000,
    updatedAt: NOW.getTime() - 1_000,
  };
}

function rawOffer() {
  const airline = { name: "Example Air", iata_code: "ZZ" };
  const origin = {
    iata_code: "JFK",
    name: "John F Kennedy International",
    city_name: "New York",
    iata_country_code: "US",
  };
  const destination = {
    iata_code: "LAX",
    name: "Los Angeles International",
    city_name: "Los Angeles",
    iata_country_code: "US",
  };
  return {
    id: OFFER_ID,
    live_mode: true,
    partial: false,
    expires_at: "2026-08-05T13:00:00Z",
    total_amount: "125.00",
    total_currency: "USD",
    owner: airline,
    passengers: [{ id: "pas_adult_1", type: "adult" }],
    slices: [
      {
        id: "slice_1",
        origin,
        destination,
        segments: [
          {
            id: "seg_1",
            origin,
            destination,
            departing_at: "2026-08-06T10:00:00Z",
            arriving_at: "2026-08-06T13:00:00Z",
            marketing_carrier: airline,
            operating_carrier: airline,
            passengers: [
              {
                passenger_id: "pas_adult_1",
                cabin_class: "economy",
                baggages: [],
              },
            ],
            stops: [],
          },
        ],
      },
    ],
  };
}

function transaction(overrides = {}) {
  return {
    status: "success",
    reference: REFERENCE,
    amount: 12_500,
    currency: "USD",
    environment: "live",
    paidAt: "2026-08-05T11:59:30Z",
    channel: "card",
    customerEmail: "traveller@example.com",
    metadata: { bookingAttemptId: ATTEMPT_ID },
    requestId: "paystack-request-1",
    ...overrides,
  };
}

function signedRequest(body) {
  return new Request(
    "https://peterselijah.name.ng/api/skyeta/payments/paystack/webhook",
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-paystack-signature": "a".repeat(128),
      },
      body: typeof body === "string" ? body : JSON.stringify(body),
    },
  );
}

function chargeEvent(overrides = {}) {
  return {
    event: "charge.success",
    data: {
      id: 12345,
      reference: REFERENCE,
      // This untrusted value is intentionally wrong. The handler must use the
      // independently verified transaction amount instead.
      amount: 1,
      ...overrides,
    },
  };
}

function harness(options = {}) {
  let currentAttempt = attempt(options.attempt);
  let webhook = {
    id: "webhook-1",
    provider: "paystack",
    providerEventId: "charge.success:12345",
    eventType: "charge.success",
    payloadHash: "payload-hash",
    signatureHash: "signature-hash",
    relatedProviderOrderId: null,
    status: options.webhookStatus ?? "received",
    failureCode: null,
    receivedAt: NOW.getTime(),
    processedAt: null,
  };
  const state = {
    databaseAccessed: false,
    transactionVerified: false,
    orderCalls: 0,
    deletedPayload: false,
    finalized: null,
    attemptTransitions: [],
    eventTransitions: [],
  };

  const repository = {
    async recordWebhookEvent(input) {
      if (options.duplicate) {
        webhook = {
          ...webhook,
          status: options.duplicateStatus ?? "processed",
        };
        return { event: webhook, created: false };
      }
      webhook = { ...webhook, ...input };
      return { event: webhook, created: true };
    },
    async transitionWebhookEvent(input) {
      state.eventTransitions.push(input);
      if (!input.expectedStatuses.includes(webhook.status)) return null;
      webhook = {
        ...webhook,
        status: input.nextStatus,
        failureCode:
          input.failureCode === undefined ? webhook.failureCode : input.failureCode,
        processedAt:
          input.processedAt === undefined ? webhook.processedAt : input.processedAt,
      };
      return webhook;
    },
    async getBookingAttemptByPaymentReference(reference) {
      return reference === REFERENCE ? currentAttempt : null;
    },
    async getOfferSelectionForSession() {
      return selection();
    },
    async getPrivatePayload() {
      return {
        bookingAttemptId: ATTEMPT_ID,
        ciphertext: "encrypted",
        iv: "iv",
        createdAt: NOW.getTime() - 1_000,
        expiresAt: NOW.getTime() + 3_600_000,
      };
    },
    async deletePrivatePayload() {
      state.deletedPayload = true;
      return true;
    },
    async transitionBookingAttempt(input) {
      state.attemptTransitions.push(input);
      if (!input.expectedStates.includes(currentAttempt.state)) return null;
      currentAttempt = {
        ...currentAttempt,
        state: input.nextState,
        providerRequestId:
          input.providerRequestId === undefined
            ? currentAttempt.providerRequestId
            : input.providerRequestId,
        failureCode:
          input.failureCode === undefined
            ? currentAttempt.failureCode
            : input.failureCode,
        retryable:
          input.retryable === undefined ? currentAttempt.retryable : input.retryable,
      };
      return currentAttempt;
    },
    async finalizeBooking(input) {
      state.finalized = input;
      currentAttempt = { ...currentAttempt, state: "confirmed" };
      return { ...input, status: "confirmed" };
    },
  };

  const handler = createPaystackBookingWebhookHandler({
    isConfigured: () => true,
    now: () => NOW,
    createEventId: () => "webhook-1",
    createBookingId: () => "booking-1",
    getDatabase: () => {
      state.databaseAccessed = true;
      return {};
    },
    createRepository: () => repository,
    decryptPayload: async () => options.privatePayload ?? privatePayload,
    createPaystack: () => ({
      verifyWebhookSignature: async () => options.validSignature ?? true,
      verifyTransaction: async () => {
        state.transactionVerified = true;
        return transaction(options.transaction);
      },
    }),
    createDuffel: () => ({
      async request() {
        return {
          data: rawOffer(),
          mode: "live",
          providerStatus: 200,
          requestId: "duffel-offer-request-1",
        };
      },
    }),
    createOrderService: () => ({
      async createOrder() {
        state.orderCalls += 1;
        if (options.orderError) throw options.orderError;
        return {
          id: "ord_123",
          bookingReference: "ABC123",
          total: { amount: "125.00", currency: "USD" },
          liveMode: true,
          providerStatus: 201,
          requestId: "duffel-order-request-1",
        };
      },
    }),
  });

  return { handler, state, currentAttempt: () => currentAttempt };
}

test("bad signatures are rejected before JSON parsing or storage", async () => {
  const { handler, state } = harness({ validSignature: false });
  const response = await handler(signedRequest("not-json"));

  assert.equal(response.status, 401);
  assert.equal(state.databaseAccessed, false);
  assert.equal(state.transactionVerified, false);
  assert.equal(state.orderCalls, 0);
});

test("a verified amount mismatch moves the paid attempt to manual review without ordering", async () => {
  const { handler, state, currentAttempt } = harness({
    transaction: { amount: 12_499 },
  });
  const response = await handler(signedRequest(chargeEvent()));

  assert.equal(response.status, 200);
  assert.equal((await response.json()).status, "manual_review");
  assert.equal(state.transactionVerified, true);
  assert.equal(state.orderCalls, 0);
  assert.equal(currentAttempt().state, "manual_review");
  assert.equal(currentAttempt().failureCode, "payment_verification_mismatch");
  assert.equal(state.deletedPayload, true);
});

test("a signed and independently verified live payment creates one exact genuine booking", async () => {
  const { handler, state, currentAttempt } = harness();
  const response = await handler(signedRequest(chargeEvent()));
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(body.status, "processed");
  assert.equal(state.transactionVerified, true);
  assert.equal(state.orderCalls, 1);
  assert.equal(currentAttempt().state, "confirmed");
  assert.equal(state.finalized.providerOrderId, "ord_123");
  assert.equal(state.finalized.bookingReference, "ABC123");
  assert.equal(state.finalized.currency, "USD");
  assert.equal(state.finalized.totalAmountMinor, 12_500);
  assert.equal(state.deletedPayload, true);
  assert.deepEqual(
    state.attemptTransitions.map((entry) => entry.nextState),
    ["payment_authorized", "submitting"],
  );
});

test("an uncertain Duffel order response is never retried automatically", async () => {
  const { handler, state, currentAttempt } = harness({
    orderError: new DuffelOrderError({
      outcome: "uncertain",
      providerStatus: 500,
      requestId: "duffel-order-request-500",
    }),
  });
  const response = await handler(signedRequest(chargeEvent()));

  assert.equal(response.status, 200);
  assert.equal((await response.json()).status, "manual_review");
  assert.equal(state.orderCalls, 1);
  assert.equal(currentAttempt().state, "manual_review");
  assert.equal(currentAttempt().failureCode, "order_submission_uncertain");
  assert.equal(currentAttempt().retryable, false);
  assert.equal(state.finalized, null);
  assert.equal(state.deletedPayload, true);
});

test("a previously processed provider event is acknowledged without payment or airline calls", async () => {
  const { handler, state } = harness({ duplicate: true });
  const response = await handler(signedRequest(chargeEvent()));

  assert.equal(response.status, 200);
  assert.equal((await response.json()).status, "duplicate");
  assert.equal(state.transactionVerified, false);
  assert.equal(state.orderCalls, 0);
});

test("an in-progress webhook returns a retryable response instead of being acknowledged forever", async () => {
  const { handler, state } = harness({
    duplicate: true,
    duplicateStatus: "processing",
  });
  const response = await handler(signedRequest(chargeEvent()));

  assert.equal(response.status, 503);
  assert.equal((await response.json()).status, "processing");
  assert.equal(state.transactionVerified, false);
  assert.equal(state.orderCalls, 0);
});

test("a stranded submitting attempt is quarantined instead of being ordered again", async () => {
  const { handler, state, currentAttempt } = harness({
    attempt: { state: "submitting" },
  });
  const response = await handler(signedRequest(chargeEvent()));

  assert.equal(response.status, 200);
  assert.equal((await response.json()).status, "manual_review");
  assert.equal(currentAttempt().state, "manual_review");
  assert.equal(currentAttempt().failureCode, "order_submission_uncertain");
  assert.equal(state.transactionVerified, false);
  assert.equal(state.orderCalls, 0);
});
