import assert from "node:assert/strict";
import test from "node:test";

import {
  createDuffelClient,
  DuffelProviderError,
} from "../app/lib/duffel/client.ts";

test("Duffel client keeps credentials server-side and sends required v2 headers", async () => {
  const secret = "duffel_live_server-only-secret";
  let requestUrl;
  let requestInit;
  const client = createDuffelClient({
    getConfig: () => ({ accessToken: secret, mode: "live" }),
    fetchImpl: async (input, init) => {
      requestUrl = new URL(input);
      requestInit = init;
      return Response.json(
        { data: { id: "off_123" }, meta: { limit: 1 } },
        { headers: { "x-request-id": "req_123" } },
      );
    },
  });

  const result = await client.request("/air/offers", {
    method: "POST",
    query: { limit: 1, ignored: null },
    body: { data: { offer_request_id: "orq_123" } },
    idempotencyKey: "skyeta-search-123",
  });

  assert.equal(requestUrl.origin, "https://api.duffel.com");
  assert.equal(requestUrl.pathname, "/air/offers");
  assert.equal(requestUrl.searchParams.get("limit"), "1");
  assert.equal(requestUrl.searchParams.has("ignored"), false);
  assert.equal(requestInit.method, "POST");
  assert.equal(requestInit.cache, "no-store");
  assert.ok(requestInit.signal instanceof AbortSignal);
  assert.equal(requestInit.headers.Accept, "application/json");
  assert.equal(requestInit.headers.Authorization, `Bearer ${secret}`);
  assert.equal(requestInit.headers["Duffel-Version"], "v2");
  assert.equal(requestInit.headers["Content-Type"], "application/json");
  assert.equal(requestInit.headers["Idempotency-Key"], "skyeta-search-123");
  assert.deepEqual(JSON.parse(requestInit.body), {
    data: { offer_request_id: "orq_123" },
  });
  assert.deepEqual(result, {
    data: { id: "off_123" },
    meta: { limit: 1 },
    mode: "live",
    providerStatus: 200,
    requestId: "req_123",
  });
  assert.doesNotMatch(JSON.stringify(result), /server-only-secret/);
});

test("Duffel client refuses external URLs before credentials can be sent", async () => {
  let fetchCount = 0;
  const client = createDuffelClient({
    getConfig: () => ({
      accessToken: "duffel_test_server-only-secret",
      mode: "test",
    }),
    fetchImpl: async () => {
      fetchCount += 1;
      return Response.json({ data: {} });
    },
  });

  for (const path of [
    "https://attacker.invalid/air/offers",
    "/air/../secrets",
    "/air/offers?redirect=https://attacker.invalid",
  ]) {
    await assert.rejects(
      () => client.request(path),
      (error) =>
        error instanceof DuffelProviderError &&
        error.code === "invalid_request",
    );
  }
  assert.equal(fetchCount, 0);
});

test("Duffel client rejects a token and mode mismatch", async () => {
  const client = createDuffelClient({
    getConfig: () => ({
      accessToken: "duffel_test_server-only-secret",
      mode: "live",
    }),
    fetchImpl: async () => Response.json({ data: {} }),
  });

  await assert.rejects(
    () => client.request("/air/offers"),
    (error) =>
      error instanceof DuffelProviderError &&
      error.code === "invalid_configuration" &&
      !error.message.includes("server-only-secret"),
  );
});

test("Duffel client bounds timeouts and does not expose provider detail", async () => {
  const client = createDuffelClient({
    getConfig: () => ({
      accessToken: "duffel_test_server-only-secret",
      mode: "test",
    }),
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
    () => client.request("/air/offers"),
    (error) =>
      error instanceof DuffelProviderError &&
      error.code === "timeout" &&
      error.status === 504 &&
      error.retryable === true &&
      !JSON.stringify(error).includes("server-only-secret"),
  );
});

test("Duffel client maps provider errors without copying raw messages", async () => {
  const client = createDuffelClient({
    getConfig: () => ({
      accessToken: "duffel_test_server-only-secret",
      mode: "test",
    }),
    fetchImpl: async () =>
      Response.json(
        {
          errors: [
            {
              code: "offer_no_longer_available",
              message: "secret provider detail about this passenger",
            },
          ],
        },
        { status: 422, headers: { "x-request-id": "req_rejected" } },
      ),
  });

  await assert.rejects(
    () => client.request("/air/offers/off_123"),
    (error) =>
      error instanceof DuffelProviderError &&
      error.code === "provider_rejected" &&
      error.providerStatus === 422 &&
      error.requestId === "req_rejected" &&
      !error.message.includes("passenger") &&
      !JSON.stringify(error).includes("provider detail"),
  );
});
