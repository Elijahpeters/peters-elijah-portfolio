import assert from "node:assert/strict";
import test from "node:test";

import { DuffelProviderError } from "../app/lib/duffel/client.ts";
import {
  createDuffelOrderService,
  DUFFEL_ORDER_TIMEOUT_MS,
  DuffelOrderError,
  DuffelOrderInputError,
} from "../app/lib/duffel/order.ts";

const passenger = {
  id: "pas_adult_1",
  title: "mr",
  given_name: "Ada",
  family_name: "Example",
  born_on: "1990-01-01",
  gender: "f",
  email: "traveller@example.com",
  phone_number: "+2348000000000",
};

const orderInput = {
  offerId: "off_live_123",
  amount: "1250.50",
  currency: "USD",
  passengers: [passenger],
  bookingAttemptId: "attempt_123:payment_456",
};

function providerOrder(overrides = {}) {
  return {
    id: "ord_123",
    booking_reference: "ABC123",
    total_amount: orderInput.amount,
    total_currency: orderInput.currency,
    live_mode: true,
    ...overrides,
  };
}

function successResult(overrides = {}) {
  return {
    data: providerOrder(),
    mode: "live",
    requestId: "req_123",
    providerStatus: 201,
    ...overrides,
  };
}

test("Duffel order service submits one strict instant balance order", async () => {
  let requestPath;
  let requestOptions;
  const service = createDuffelOrderService({
    client: {
      async request(path, options) {
        requestPath = path;
        requestOptions = options;
        return successResult();
      },
    },
  });

  const result = await service.createOrder(orderInput);

  assert.equal(requestPath, "/air/orders");
  assert.equal(requestOptions.method, "POST");
  assert.equal(
    requestOptions.idempotencyKey,
    "skyeta-order:attempt_123:payment_456",
  );
  assert.equal(requestOptions.timeoutMs, 135_000);
  assert.equal(DUFFEL_ORDER_TIMEOUT_MS, 135_000);
  assert.deepEqual(requestOptions.body, {
    data: {
      type: "instant",
      selected_offers: ["off_live_123"],
      payments: [
        { type: "balance", currency: "USD", amount: "1250.50" },
      ],
      passengers: [passenger],
      metadata: { booking_attempt_id: "attempt_123:payment_456" },
    },
  });
  assert.deepEqual(result, {
    id: "ord_123",
    bookingReference: "ABC123",
    total: { amount: "1250.50", currency: "USD" },
    liveMode: true,
    providerStatus: 201,
    requestId: "req_123",
  });
});

test("Duffel order service rejects malformed identifiers and money before submission", async () => {
  let requests = 0;
  const service = createDuffelOrderService({
    client: {
      async request() {
        requests += 1;
        return successResult();
      },
    },
  });

  const invalidInputs = [
    { ...orderInput, offerId: "https://attacker.invalid/off_1" },
    { ...orderInput, amount: "01250.50" },
    { ...orderInput, amount: "1250.5000000" },
    { ...orderInput, amount: "1e3" },
    { ...orderInput, currency: "usd" },
    { ...orderInput, bookingAttemptId: "attempt id with spaces" },
    {
      ...orderInput,
      passengers: [{ ...passenger, id: "not-a-passenger-id" }],
    },
    {
      ...orderInput,
      passengers: [{ ...passenger, email: "traveller.example.com" }],
    },
    {
      ...orderInput,
      passengers: [
        {
          ...passenger,
          identity_documents: [
            {
              type: "passport",
              unique_identifier: "A1234567",
              expires_on: "not-a-date",
              issuing_country_code: "US",
            },
          ],
        },
      ],
    },
    { ...orderInput, passengers: [passenger, { ...passenger }] },
  ];

  for (const input of invalidInputs) {
    await assert.rejects(
      () => service.createOrder(input),
      (error) =>
        error instanceof DuffelOrderInputError &&
        !error.message.includes("traveller@example.com") &&
        !error.message.includes(input.offerId),
    );
  }
  assert.equal(requests, 0);
});

test("Duffel order service treats 202 and malformed success responses as uncertain", async () => {
  const results = [
    successResult({ providerStatus: 202 }),
    successResult({ data: providerOrder({ id: "not-an-order" }) }),
    successResult({ data: providerOrder({ booking_reference: "" }) }),
    successResult({ data: providerOrder({ total_amount: "1250.51" }) }),
    successResult({ data: providerOrder({ total_currency: "EUR" }) }),
    successResult({ data: providerOrder({ live_mode: "true" }) }),
  ];

  for (const providerResult of results) {
    const service = createDuffelOrderService({
      client: { async request() { return providerResult; } },
    });
    await assert.rejects(
      () => service.createOrder(orderInput),
      (error) =>
        error instanceof DuffelOrderError &&
        error.outcome === "uncertain" &&
        error.neverRetry === true &&
        error.retryable === false &&
        !JSON.stringify(error).includes("traveller@example.com"),
    );
  }
});

test("Duffel order service classifies ambiguous provider and transport failures as never-retry", async () => {
  const failures = [
    new DuffelProviderError({
      code: "unavailable",
      message: "raw provider message about traveller@example.com",
      status: 502,
      providerStatus: 500,
      requestId: "req_500",
      retryable: true,
    }),
    new DuffelProviderError({
      code: "unavailable",
      message: "raw provider message about traveller@example.com",
      status: 502,
      providerStatus: 502,
      retryable: true,
    }),
    new DuffelProviderError({
      code: "timeout",
      message: "raw timeout detail about traveller@example.com",
      status: 504,
      retryable: true,
    }),
    new TypeError("network detail about traveller@example.com"),
    new DuffelProviderError({
      code: "invalid_response",
      message: "raw response about traveller@example.com",
      status: 502,
      providerStatus: 200,
      retryable: true,
    }),
  ];

  for (const failure of failures) {
    const service = createDuffelOrderService({
      client: { async request() { throw failure; } },
    });
    await assert.rejects(
      () => service.createOrder(orderInput),
      (error) =>
        error instanceof DuffelOrderError &&
        error.outcome === "uncertain" &&
        error.neverRetry === true &&
        error.retryable === false &&
        !error.message.includes("traveller@example.com") &&
        !JSON.stringify(error).includes("traveller@example.com"),
    );
  }
});

test("Duffel order service makes only 503 retryable and other 4xx definitive", async () => {
  const cases = [
    { providerStatus: 503, outcome: "retryable", retryable: true },
    { providerStatus: 400, outcome: "definitive", retryable: false },
    { providerStatus: 401, outcome: "definitive", retryable: false },
    { providerStatus: 409, outcome: "definitive", retryable: false },
    { providerStatus: 422, outcome: "definitive", retryable: false },
    { providerStatus: 429, outcome: "definitive", retryable: false },
  ];

  for (const expected of cases) {
    const service = createDuffelOrderService({
      client: {
        async request() {
          throw new DuffelProviderError({
            code:
              expected.providerStatus === 503
                ? "unavailable"
                : "provider_rejected",
            message: "provider detail about traveller@example.com",
            status: expected.providerStatus === 503 ? 502 : 422,
            providerStatus: expected.providerStatus,
            requestId: `req_${expected.providerStatus}`,
            retryable: true,
          });
        },
      },
    });

    await assert.rejects(
      () => service.createOrder(orderInput),
      (error) =>
        error instanceof DuffelOrderError &&
        error.outcome === expected.outcome &&
        error.retryable === expected.retryable &&
        error.neverRetry === false &&
        error.providerStatus === expected.providerStatus &&
        !error.message.includes("traveller@example.com"),
    );
  }
});
