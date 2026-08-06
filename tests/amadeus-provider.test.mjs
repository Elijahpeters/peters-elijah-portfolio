import assert from "node:assert/strict";
import test from "node:test";

import {
  AmadeusProviderError,
  createAmadeusClient,
} from "../app/lib/amadeus/client.ts";
import {
  compactAmadeusDictionaries,
  normalizeAmadeusOffer,
} from "../app/lib/amadeus/normalize.ts";
import { AmadeusOfferTooLargeError } from "../app/lib/amadeus/offer-cache.ts";
import {
  createQuotaKey,
  DurableRequestLimiter,
} from "../app/lib/amadeus/rate-limit.ts";
import { isoDurationMinutes } from "../app/lib/flight-provider/duration.ts";
import { flightDateParts } from "../app/lib/flight-provider/display-time.ts";
import {
  configuredFlightProviderEnvironment,
  selectedFlightProvider,
} from "../app/lib/flight-provider/config.ts";
import {
  buildAmadeusSearchQuery,
  createAmadeusOfferSearchHandler,
} from "../app/api/skyeta/offers/search/amadeus-search.ts";
import { createAmadeusOfferRefreshHandler } from "../app/api/skyeta/offers/[offerId]/refresh/amadeus-refresh.ts";

const dictionaries = {
  carriers: { HA: "Hawaiian Airlines" },
  aircraft: { "321": "Airbus A321" },
  locations: {
    HNL: { cityCode: "HNL", countryCode: "US" },
    OGG: { cityCode: "OGG", countryCode: "US" },
  },
};

function providerOffer(overrides = {}) {
  return {
    type: "flight-offer",
    id: "1",
    source: "GDS",
    numberOfBookableSeats: 4,
    validatingAirlineCodes: ["HA"],
    itineraries: [
      {
        duration: "PT42M",
        segments: [
          {
            id: "1",
            departure: { iataCode: "HNL", terminal: "1", at: "2026-09-10T09:30:00" },
            arrival: { iataCode: "OGG", at: "2026-09-10T10:12:00" },
            carrierCode: "HA",
            number: "101",
            aircraft: { code: "321" },
            operating: { carrierCode: "HA" },
            duration: "PT42M",
            numberOfStops: 0,
          },
        ],
      },
    ],
    price: { currency: "USD", total: "95.40", base: "80.00", grandTotal: "95.40" },
    travelerPricings: [
      {
        travelerId: "1",
        fareOption: "STANDARD",
        travelerType: "ADULT",
        fareDetailsBySegment: [
          {
            segmentId: "1",
            cabin: "ECONOMY",
            brandedFareLabel: "Main Cabin",
            includedCheckedBags: { quantity: 1 },
          },
        ],
      },
    ],
    ...overrides,
  };
}

const validatedSearch = {
  origin: "HNL",
  destination: "OGG",
  departureDate: "2026-09-10",
  returnDate: null,
  passengers: { adults: 1, children: 0, infantsWithoutSeat: 0 },
  cabinClass: "economy",
};

function searchRequest() {
  return new Request("https://peterselijah.name.ng/api/skyeta/offers/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(validatedSearch),
  });
}

function inMemoryQuotaDatabase() {
  const quotas = new Map();
  const statement = (sql) => {
    let values = [];
    return {
      bind(...input) {
        values = input;
        return this;
      },
      async first() {
        if (sql.includes("INSERT INTO provider_request_quotas")) {
          const [key, now, expiresAt, , , , , limit] = values;
          const current = quotas.get(key);
          if (!current || current.expiresAt <= now) {
            const next = { count: 1, expiresAt };
            quotas.set(key, next);
            return { request_count: next.count, expires_at: next.expiresAt };
          }
          if (current.count >= limit) return null;
          current.count += 1;
          return {
            request_count: current.count,
            expires_at: current.expiresAt,
          };
        }
        if (sql.includes("SELECT request_count, expires_at")) {
          const current = quotas.get(values[0]);
          return current
            ? { request_count: current.count, expires_at: current.expiresAt }
            : null;
        }
        return null;
      },
      async run() {
        if (sql.includes("DELETE FROM provider_request_quotas")) {
          const [now, limit] = values;
          let removed = 0;
          for (const [key, current] of quotas) {
            if (removed >= limit) break;
            if (current.expiresAt <= now) {
              quotas.delete(key);
              removed += 1;
            }
          }
        }
        return { success: true, meta: { changes: 0 } };
      },
      async all() {
        return { success: true, results: [] };
      },
    };
  };
  return {
    prepare: statement,
    async batch(statements) {
      return statements.map(() => ({ success: true }));
    },
  };
}

test("provider selection prefers an explicitly configured production provider", () => {
  const environment = {
    SKYETA_FLIGHT_PROVIDER: "amadeus",
    AMADEUS_API_KEY: "key",
    AMADEUS_API_SECRET: "secret",
    AMADEUS_MODE: "live",
    DUFFEL_ACCESS_TOKEN: "duffel_live_other",
    DUFFEL_MODE: "live",
  };
  assert.equal(selectedFlightProvider(environment), "amadeus");
  assert.equal(configuredFlightProviderEnvironment(environment), "live");
  assert.equal(
    configuredFlightProviderEnvironment({
      SKYETA_FLIGHT_PROVIDER: "amadeus",
      AMADEUS_API_KEY: "key",
    }),
    null,
  );
});

test("durable request quota is shared through storage and resets after its window", async () => {
  const limiter = new DurableRequestLimiter(inMemoryQuotaDatabase());
  const key = await createQuotaKey("amadeus-search", "203.0.113.4");
  const differentScope = await createQuotaKey(
    "amadeus-refresh-client",
    "203.0.113.4",
  );
  assert.notEqual(key, differentScope);
  assert.deepEqual(
    await limiter.consume({ key, now: 1_800_000, windowMs: 60_000, limit: 2 }),
    { allowed: true, retryAfterSeconds: 0 },
  );
  assert.deepEqual(
    await limiter.consume({ key, now: 1_801_000, windowMs: 60_000, limit: 2 }),
    { allowed: true, retryAfterSeconds: 0 },
  );
  assert.deepEqual(
    await limiter.consume({ key, now: 1_802_000, windowMs: 60_000, limit: 2 }),
    { allowed: false, retryAfterSeconds: 58 },
  );
  assert.deepEqual(
    await limiter.consume({ key, now: 1_860_000, windowMs: 60_000, limit: 2 }),
    { allowed: true, retryAfterSeconds: 0 },
  );
});

test("Amadeus client exchanges credentials server-side and calls only its allowlisted origin", async () => {
  const calls = [];
  const client = createAmadeusClient({
    getConfig: () => ({ apiKey: "client-key", apiSecret: "client-secret", mode: "live" }),
    now: () => 1_000_000,
    fetchImpl: async (input, init) => {
      const url = new URL(input);
      calls.push({ url, init });
      if (url.pathname === "/v1/security/oauth2/token") {
        return Response.json({ access_token: "server-token", expires_in: 1799 });
      }
      return Response.json({ data: [providerOffer()], dictionaries });
    },
  });

  const result = await client.request("/v2/shopping/flight-offers", {
    query: { originLocationCode: "HNL", destinationLocationCode: "OGG" },
  });
  assert.equal(result.mode, "live");
  assert.equal(calls.length, 2);
  assert.equal(calls[0].url.origin, "https://api.amadeus.com");
  assert.equal(calls[0].init.redirect, "error");
  assert.match(String(calls[0].init.body), /client_secret=client-secret/);
  assert.equal(calls[1].url.origin, "https://api.amadeus.com");
  assert.equal(calls[1].init.redirect, "error");
  assert.equal(calls[1].init.headers.Authorization, "Bearer server-token");
  assert.doesNotMatch(calls[1].url.toString(), /client-secret|server-token/);
});

test("Amadeus client rejects external paths before sending credentials", async () => {
  let calls = 0;
  const client = createAmadeusClient({
    getConfig: () => ({ apiKey: "key", apiSecret: "secret", mode: "test" }),
    fetchImpl: async () => {
      calls += 1;
      return Response.json({ access_token: "token", expires_in: 1799 });
    },
  });
  await assert.rejects(
    client.request("https://attacker.example/v2/shopping/flight-offers"),
    (error) => error instanceof AmadeusProviderError && error.code === "invalid_request",
  );
  assert.equal(calls, 0);
});

test("Amadeus timeout remains active while a provider response body is streaming", async () => {
  const client = createAmadeusClient({
    getConfig: () => ({ apiKey: "key", apiSecret: "secret", mode: "live" }),
    timeoutMs: 1_000,
    fetchImpl: async (input, init) => {
      const url = new URL(input);
      if (url.pathname === "/v1/security/oauth2/token") {
        return Response.json({ access_token: "token", expires_in: 1799 });
      }
      return new Response(
        new ReadableStream({
          start(controller) {
            init.signal.addEventListener(
              "abort",
              () => controller.error(new Error("aborted")),
              { once: true },
            );
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    },
  });
  await assert.rejects(
    client.request("/v2/shopping/flight-offers", { timeoutMs: 25 }),
    (error) =>
      error instanceof AmadeusProviderError &&
      error.code === "timeout" &&
      error.status === 504,
  );
});

test("Amadeus normalizer preserves live provenance, schedule, price and baggage", () => {
  const result = normalizeAmadeusOffer({
    value: providerOffer(),
    dictionaries,
    configuredMode: "live",
    cacheId: `ama_${"1".repeat(32)}`,
    now: new Date("2026-08-06T00:00:00Z"),
    expiresAt: new Date("2026-08-06T00:15:00Z"),
  });
  assert.ok(result);
  assert.deepEqual(result.source, {
    provider: "amadeus",
    environment: "live",
    isLive: true,
    label: "Live fare",
  });
  assert.equal(result.owner.name, "Hawaiian Airlines");
  assert.equal(result.slices[0].segments[0].aircraftName, "Airbus A321");
  assert.equal(result.slices[0].segments[0].fareBrandName, "Main Cabin");
  assert.ok(result.slices[0].segments[0].distanceKilometres > 100);
  assert.deepEqual(result.total, { amount: "95.40", currency: "USD" });
  assert.equal(result.baggage[0].quantity, 1);
  assert.equal(result.baggage[0].weightKilograms, null);
  assert.equal(result.isBookable, true);
});

test("Amadeus normalizer maps only explicit structured exchange and refund rules", () => {
  const result = normalizeAmadeusOffer({
    value: providerOffer({
      fareRules: {
        currency: "USD",
        rules: [
          {
            category: "EXCHANGE",
            notApplicable: false,
            maxPenaltyAmount: "50.00",
          },
          { category: "REFUND", notApplicable: true },
          {
            category: "CANCELLATION",
            notApplicable: false,
            maxPenaltyAmount: "10.00",
          },
        ],
      },
    }),
    dictionaries,
    configuredMode: "live",
    cacheId: `ama_${"5".repeat(32)}`,
    now: new Date("2026-08-06T00:00:00Z"),
    expiresAt: new Date("2026-08-06T00:15:00Z"),
  });
  assert.ok(result);
  assert.deepEqual(result.fareConditions, {
    changeBeforeDeparture: {
      status: "allowed",
      penalty: { amount: "50.00", currency: "USD" },
    },
    refundBeforeDeparture: { status: "not_allowed", penalty: null },
  });
});

test("Amadeus normalizer preserves weight-based checked baggage", () => {
  const weightedOffer = providerOffer();
  weightedOffer.travelerPricings[0].fareDetailsBySegment[0].includedCheckedBags = {
    weight: 50,
    weightUnit: "LB",
  };
  const result = normalizeAmadeusOffer({
    value: weightedOffer,
    dictionaries,
    configuredMode: "live",
    cacheId: `ama_${"6".repeat(32)}`,
    now: new Date("2026-08-06T00:00:00Z"),
    expiresAt: new Date("2026-08-06T00:15:00Z"),
  });
  assert.ok(result);
  assert.equal(result.baggage[0].quantity, null);
  assert.equal(result.baggage[0].weightKilograms, 22.68);
});

test("flight duration parsing keeps day-long connections in the displayed total", () => {
  assert.equal(isoDurationMinutes("P1DT2H35M"), 1_595);
  assert.equal(isoDurationMinutes("PT42M"), 42);
  assert.equal(isoDurationMinutes("not-a-duration"), null);
});

test("offsetless provider schedules keep their airport-local wall time", () => {
  const result = flightDateParts(
    "2026-09-10T09:30:00",
    "Pacific/Honolulu",
    "en-US",
  );
  assert.match(result.time, /09:30|9:30/);
  assert.equal(result.date, "Thu, Sep 10");
});

test("Amadeus search query maps the validated itinerary without passenger inflation", () => {
  assert.deepEqual(buildAmadeusSearchQuery(validatedSearch), {
    originLocationCode: "HNL",
    destinationLocationCode: "OGG",
    departureDate: "2026-09-10",
    returnDate: undefined,
    adults: 1,
    children: undefined,
    infants: undefined,
    travelClass: "ECONOMY",
    currencyCode: undefined,
    max: 12,
  });
});

test("Amadeus cache dictionaries include only values used by one offer", () => {
  const result = compactAmadeusDictionaries(providerOffer(), {
    carriers: { HA: "Hawaiian Airlines", AA: "American Airlines" },
    aircraft: { "321": "Airbus A321", "738": "Boeing 737-800" },
    locations: {
      HNL: { cityCode: "HNL", countryCode: "US", extra: "discarded" },
      OGG: { cityCode: "OGG", countryCode: "US" },
      DFW: { cityCode: "DFW", countryCode: "US" },
    },
  });
  assert.deepEqual(result, dictionaries);
});

test("Amadeus live search stores opaque offers and returns real-provider provenance without enabling payment", async () => {
  let saved;
  const cache = {
    deleteExpired: async () => 0,
    get: async () => null,
    save: async (input) => {
      saved = input;
      return `ama_${"2".repeat(32)}`;
    },
  };
  const handler = createAmadeusOfferSearchHandler({
    now: () => new Date("2026-08-06T00:00:00Z"),
    createCache: () => cache,
    createClient: () => ({
      getMode: () => "live",
      request: async () => ({
        data: [providerOffer()],
        dictionaries,
        mode: "live",
        providerStatus: 200,
        requestId: "req_1",
      }),
    }),
  });
  const response = await handler(searchRequest());
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(body.provider, "amadeus");
  assert.equal(body.mode, "live");
  assert.equal(body.bookingEnabled, false);
  assert.equal(body.offers[0].source.isLive, true);
  assert.equal(body.offers[0].isBookable, true);
  assert.equal(body.offers[0].skyetaRisk.status, "available");
  assert.equal(body.offers[0].id, `ama_${"2".repeat(32)}`);
  assert.equal(saved.mode, "live");
  assert.deepEqual(saved.offer, providerOffer());
  assert.deepEqual(saved.dictionaries, dictionaries);
});

test("Amadeus search stops before provider and storage calls when rate limited", async () => {
  let providerCalled = false;
  let storageCalled = false;
  const handler = createAmadeusOfferSearchHandler({
    now: () => new Date("2026-08-06T00:00:00Z"),
    checkRateLimit: () => ({ allowed: false, retryAfterSeconds: 90 }),
    createCache: () => {
      storageCalled = true;
      throw new Error("must not create cache");
    },
    createClient: () => ({
      getMode: () => "live",
      request: async () => {
        providerCalled = true;
        throw new Error("must not call provider");
      },
    }),
  });
  const response = await handler(searchRequest());
  const body = await response.json();
  assert.equal(response.status, 429);
  assert.equal(response.headers.get("retry-after"), "90");
  assert.equal(body.error.code, "rate_limited");
  assert.equal(providerCalled, false);
  assert.equal(storageCalled, false);
});

test("Amadeus search enforces its body limit without trusting Content-Length", async () => {
  let providerCalled = false;
  const handler = createAmadeusOfferSearchHandler({
    checkRateLimit: () => ({ allowed: true, retryAfterSeconds: 0 }),
    createClient: () => ({
      getMode: () => "live",
      request: async () => {
        providerCalled = true;
        throw new Error("must not call provider");
      },
    }),
  });
  const response = await handler(
    new Request("https://peterselijah.name.ng/api/skyeta/offers/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...validatedSearch, padding: "x".repeat(30_000) }),
    }),
  );
  const body = await response.json();
  assert.equal(response.status, 413);
  assert.equal(body.error.code, "payload_too_large");
  assert.equal(providerCalled, false);
});

test("Amadeus search skips one oversized provider offer without hiding valid fares", async () => {
  let saveCount = 0;
  const handler = createAmadeusOfferSearchHandler({
    now: () => new Date("2026-08-06T00:00:00Z"),
    checkRateLimit: () => ({ allowed: true, retryAfterSeconds: 0 }),
    createCache: () => ({
      deleteExpired: async () => 0,
      get: async () => null,
      save: async () => {
        saveCount += 1;
        if (saveCount === 1) throw new AmadeusOfferTooLargeError();
        return `ama_${"7".repeat(32)}`;
      },
    }),
    createClient: () => ({
      getMode: () => "live",
      request: async () => ({
        data: [providerOffer({ id: "large" }), providerOffer({ id: "valid" })],
        dictionaries,
        mode: "live",
        providerStatus: 200,
        requestId: "req_two",
      }),
    }),
  });
  const response = await handler(searchRequest());
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(saveCount, 2);
  assert.equal(body.offers.length, 1);
  assert.equal(body.offers[0].id, `ama_${"7".repeat(32)}`);
});

test("Amadeus fare recheck submits the stored provider offer and updates its opaque cache entry", async () => {
  const offerId = `ama_${"3".repeat(32)}`;
  let providerRequest;
  let saved;
  const handler = createAmadeusOfferRefreshHandler({
    now: () => new Date("2026-08-06T00:05:00Z"),
    checkRateLimit: () => ({ allowed: true, retryAfterSeconds: 0 }),
    createCache: () => ({
      get: async () => ({
        id: offerId,
        mode: "live",
        offer: providerOffer(),
        dictionaries,
        createdAt: Date.parse("2026-08-06T00:00:00Z"),
        expiresAt: Date.parse("2026-08-06T00:15:00Z"),
      }),
      save: async (input) => {
        saved = input;
        return offerId;
      },
    }),
    createClient: () => ({
      request: async (path, options) => {
        providerRequest = { path, options };
        return {
          data: { flightOffers: [providerOffer({ price: { currency: "USD", total: "109.20", base: "90.00", grandTotal: "109.20" } })] },
          dictionaries,
          mode: "live",
          providerStatus: 200,
          requestId: "req_price",
        };
      },
    }),
  });
  const response = await handler(
    new Request(`https://peterselijah.name.ng/api/skyeta/offers/${offerId}/refresh`, { method: "POST" }),
    offerId,
  );
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(providerRequest.path, "/v1/shopping/flight-offers/pricing");
  assert.equal(providerRequest.options.headers["X-HTTP-Method-Override"], "GET");
  assert.deepEqual(providerRequest.options.body.data.flightOffers, [providerOffer()]);
  assert.deepEqual(body.offer.total, { amount: "109.20", currency: "USD" });
  assert.equal(body.bookingEnabled, false);
  assert.equal(saved.id, offerId);
  assert.equal(saved.now, Date.parse("2026-08-06T00:00:00Z"));
  assert.equal(saved.expiresAt, Date.parse("2026-08-06T00:20:00Z"));
});

test("Amadeus fare recheck stops before the provider when its durable quota is exhausted", async () => {
  const offerId = `ama_${"4".repeat(32)}`;
  let providerCalled = false;
  const handler = createAmadeusOfferRefreshHandler({
    now: () => new Date("2026-08-06T00:05:00Z"),
    checkRateLimit: () => ({ allowed: false, retryAfterSeconds: 20 }),
    createCache: () => ({
      get: async () => ({
        id: offerId,
        mode: "live",
        offer: providerOffer(),
        dictionaries,
        createdAt: Date.parse("2026-08-06T00:00:00Z"),
        expiresAt: Date.parse("2026-08-06T00:15:00Z"),
      }),
      save: async () => offerId,
    }),
    createClient: () => ({
      request: async () => {
        providerCalled = true;
        throw new Error("must not call provider");
      },
    }),
  });
  const response = await handler(
    new Request(`https://peterselijah.name.ng/api/skyeta/offers/${offerId}/refresh`, {
      method: "POST",
    }),
    offerId,
  );
  const body = await response.json();
  assert.equal(response.status, 429);
  assert.equal(response.headers.get("retry-after"), "20");
  assert.equal(body.error.code, "rate_limited");
  assert.equal(providerCalled, false);
});
