import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import test from "node:test";

import {
  createPaystackClient,
  PaystackProviderError,
  verifyPaystackWebhookSignature,
} from "../app/lib/paystack/client.ts";

const TEST_KEY = "sk_test_server-only-secret";

test("Paystack initialization stays on the allowlisted API origin", async () => {
  let requestUrl;
  let requestInit;
  const client = createPaystackClient({
    getSecretKey: () => TEST_KEY,
    fetchImpl: async (input, init) => {
      requestUrl = new URL(input);
      requestInit = init;
      return Response.json(
        {
          status: true,
          message: "provider detail that must not be returned",
          data: {
            authorization_url: "https://checkout.paystack.com/access-123",
            access_code: "access-123",
            reference: "skyeta-123",
          },
        },
        { headers: { "x-request-id": "req_123" } },
      );
    },
  });

  const result = await client.initializeTransaction({
    email: "traveller@example.com",
    amount: 125_050,
    currency: "ngn",
    reference: "skyeta-123",
    callbackUrl: "https://portfolio.example/payments/callback",
    metadata: { bookingAttemptId: "attempt-123" },
    channels: ["card", "bank_transfer"],
  });

  assert.equal(requestUrl.origin, "https://api.paystack.co");
  assert.equal(requestUrl.pathname, "/transaction/initialize");
  assert.equal(requestUrl.search, "");
  assert.equal(requestInit.method, "POST");
  assert.equal(requestInit.cache, "no-store");
  assert.equal(requestInit.redirect, "error");
  assert.ok(requestInit.signal instanceof AbortSignal);
  assert.equal(requestInit.headers.Authorization, `Bearer ${TEST_KEY}`);
  assert.equal(requestInit.headers.Accept, "application/json");
  assert.equal(requestInit.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(requestInit.body), {
    email: "traveller@example.com",
    amount: "125050",
    currency: "NGN",
    reference: "skyeta-123",
    callback_url: "https://portfolio.example/payments/callback",
    metadata: { bookingAttemptId: "attempt-123" },
    channels: ["card", "bank_transfer"],
  });
  assert.deepEqual(result, {
    authorizationUrl: "https://checkout.paystack.com/access-123",
    accessCode: "access-123",
    reference: "skyeta-123",
    environment: "test",
    requestId: "req_123",
  });
  assert.doesNotMatch(JSON.stringify(result), /server-only-secret|provider detail/);
});

test("Paystack accepts only official HTTPS hosted-checkout URLs", async () => {
  const urls = [
    "http://checkout.paystack.com/access",
    "https://checkout.paystack.com.attacker.invalid/access",
    "https://standard.paystack.co.attacker.invalid/access",
    "https://user@checkout.paystack.com/access",
    "https://checkout.paystack.com:444/access",
  ];

  for (const authorizationUrl of urls) {
    const client = createPaystackClient({
      getSecretKey: () => TEST_KEY,
      fetchImpl: async () =>
        Response.json({
          status: true,
          data: {
            authorization_url: authorizationUrl,
            access_code: "access",
            reference: "reference-1",
          },
        }),
    });
    await assert.rejects(
      () =>
        client.initializeTransaction({
          email: "traveller@example.com",
          amount: 10_000,
          reference: "reference-1",
        }),
      (error) =>
        error instanceof PaystackProviderError &&
        error.code === "invalid_response" &&
        !error.message.includes(authorizationUrl),
    );
  }

  const client = createPaystackClient({
    getSecretKey: () => TEST_KEY,
    fetchImpl: async () =>
      Response.json({
        status: true,
        data: {
          authorization_url: "https://standard.paystack.co/checkout/access",
          access_code: "access",
          reference: "reference-2",
        },
      }),
  });
  const result = await client.initializeTransaction({
    email: "traveller@example.com",
    amount: "10000",
    reference: "reference-2",
  });
  assert.equal(
    result.authorizationUrl,
    "https://standard.paystack.co/checkout/access",
  );
});

test("Paystack verification validates the reference and returns safe fields only", async () => {
  let requestUrl;
  let requestInit;
  let fetchCount = 0;
  const client = createPaystackClient({
    getSecretKey: () => TEST_KEY,
    fetchImpl: async (input, init) => {
      fetchCount += 1;
      requestUrl = new URL(input);
      requestInit = init;
      return Response.json({
        status: true,
        message: "Verification successful",
        data: {
          status: "success",
          reference: "skyeta.verify-123",
          amount: 125050,
          currency: "NGN",
          domain: "test",
          paid_at: "2026-08-05T12:00:00.000Z",
          channel: "card",
          gateway_response: "raw bank response",
          customer: {
            email: " Traveller@Example.com ",
            phone: "+234000000000",
          },
          metadata: {
            bookingAttemptId: "attempt-123",
            arbitraryProviderData: "raw metadata secret",
          },
          authorization: { authorization_code: "AUTH_secret" },
        },
      });
    },
  });

  const result = await client.verifyTransaction("skyeta.verify-123");
  assert.equal(
    requestUrl.toString(),
    "https://api.paystack.co/transaction/verify/skyeta.verify-123",
  );
  assert.equal(requestInit.method, "GET");
  assert.equal(requestInit.body, undefined);
  assert.deepEqual(result, {
    status: "success",
    reference: "skyeta.verify-123",
    amount: 125050,
    currency: "NGN",
    environment: "test",
    paidAt: "2026-08-05T12:00:00.000Z",
    channel: "card",
    customerEmail: "traveller@example.com",
    metadata: { bookingAttemptId: "attempt-123" },
    requestId: null,
  });
  assert.doesNotMatch(
    JSON.stringify(result),
    /raw bank response|raw metadata secret|\+234000000000|AUTH_secret/,
  );

  for (const reference of [
    "../secrets",
    "https://attacker.invalid/transaction/verify/ref",
    "reference?redirect=https://attacker.invalid",
  ]) {
    await assert.rejects(
      () => client.verifyTransaction(reference),
      (error) =>
        error instanceof PaystackProviderError &&
        error.code === "invalid_request",
    );
  }
  assert.equal(fetchCount, 1);
});

test("Paystack errors are structured and omit credentials and provider messages", async () => {
  const client = createPaystackClient({
    getSecretKey: () => TEST_KEY,
    fetchImpl: async () =>
      Response.json(
        {
          status: false,
          message: "raw provider message containing private customer data",
        },
        { status: 400, headers: { "x-request-id": "req_rejected" } },
      ),
  });

  await assert.rejects(
    () =>
      client.initializeTransaction({
        email: "traveller@example.com",
        amount: 10_000,
        reference: "reference-1",
      }),
    (error) =>
      error instanceof PaystackProviderError &&
      error.code === "provider_rejected" &&
      error.status === 422 &&
      error.providerStatus === 400 &&
      error.requestId === "req_rejected" &&
      !error.message.includes("customer") &&
      !JSON.stringify(error).includes(TEST_KEY) &&
      !JSON.stringify(error).includes("raw provider message"),
  );
});

test("Paystack client enforces bounded request timeouts", async () => {
  assert.throws(
    () => createPaystackClient({ timeoutMs: 0 }),
    (error) =>
      error instanceof PaystackProviderError &&
      error.code === "invalid_request",
  );
  assert.throws(
    () => createPaystackClient({ timeoutMs: 30_001 }),
    (error) =>
      error instanceof PaystackProviderError &&
      error.code === "invalid_request",
  );

  const client = createPaystackClient({
    getSecretKey: () => TEST_KEY,
    timeoutMs: 5,
    fetchImpl: async (_input, init) =>
      new Promise((_resolve, reject) => {
        init.signal.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      }),
  });
  await assert.rejects(
    () => client.verifyTransaction("reference-1"),
    (error) =>
      error instanceof PaystackProviderError &&
      error.code === "timeout" &&
      error.status === 504 &&
      error.retryable === true &&
      !JSON.stringify(error).includes(TEST_KEY),
  );
});

test("Paystack webhook verifier checks the exact raw bytes with HMAC-SHA512", async () => {
  const rawBody = new TextEncoder().encode(
    '{"event":"charge.success","data":{"reference":"skyeta-123"}}',
  );
  const signature = createHmac("sha512", TEST_KEY)
    .update(rawBody)
    .digest("hex");

  assert.equal(
    await verifyPaystackWebhookSignature(rawBody, signature, TEST_KEY),
    true,
  );
  assert.equal(
    await verifyPaystackWebhookSignature(
      rawBody,
      signature.toUpperCase(),
      TEST_KEY,
    ),
    true,
  );
  const changedBody = rawBody.slice();
  changedBody[changedBody.length - 2] ^= 1;
  assert.equal(
    await verifyPaystackWebhookSignature(changedBody, signature, TEST_KEY),
    false,
  );
  assert.equal(
    await verifyPaystackWebhookSignature(rawBody, "not-hex", TEST_KEY),
    false,
  );

  const padded = new Uint8Array(rawBody.length + 8);
  padded.set(rawBody, 4);
  const exactView = padded.subarray(4, 4 + rawBody.length);
  assert.equal(
    await verifyPaystackWebhookSignature(exactView, signature, TEST_KEY),
    true,
  );
});
