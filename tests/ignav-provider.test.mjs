import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  createIgnavClient,
  IgnavProviderError,
} from "../app/lib/ignav/client.ts";
import {
  isIgnavProviderId,
  isIgnavCacheId,
} from "../app/lib/ignav/offer-cache.ts";
import {
  ignavOfferIdentity,
  normalizeIgnavItinerary,
} from "../app/lib/ignav/normalize.ts";
import {
  configuredFlightProviderEnvironment,
  selectedFlightProvider,
} from "../app/lib/flight-provider/config.ts";
import {
  buildIgnavSearchRequest,
  createIgnavOfferSearchHandler,
} from "../app/api/skyeta/offers/search/ignav-search.ts";
import {
  createIgnavOfferRefreshHandler,
  normalizeIgnavBookingLinks,
} from "../app/api/skyeta/offers/[offerId]/refresh/ignav-refresh.ts";

const PROVIDER_ID = "a".repeat(32);
const CACHE_ID = `ign_${"b".repeat(32)}`;
const NOW = new Date("2026-08-06T10:00:00.000Z");

function segment(overrides = {}) {
  return {
    marketing_carrier_code: "WB",
    flight_number: "701",
    operating_carrier_name: "RwandAir",
    departure_airport: "LOS",
    departure_time_local: "2026-09-15T12:15:00",
    departure_timezone: "Africa/Lagos",
    departure_time_utc: "2026-09-15T11:15:00Z",
    arrival_airport: "KGL",
    arrival_time_local: "2026-09-15T18:45:00",
    arrival_timezone: "Africa/Kigali",
    arrival_time_utc: "2026-09-15T16:45:00Z",
    duration_minutes: 330,
    aircraft: "Airbus A330",
    ...overrides,
  };
}

function itinerary(overrides = {}) {
  return {
    price: { amount: 569217, currency: "NGN", status: "verified" },
    outbound: {
      carrier: "RwandAir",
      duration_minutes: 720,
      segments: [
        segment(),
        segment({
          flight_number: "700",
          departure_airport: "KGL",
          departure_time_local: "2026-09-15T20:00:00",
          departure_timezone: "Africa/Kigali",
          departure_time_utc: "2026-09-15T18:00:00Z",
          arrival_airport: "LHR",
          arrival_time_local: "2026-09-16T06:15:00",
          arrival_timezone: "Europe/London",
          arrival_time_utc: "2026-09-16T05:15:00Z",
          duration_minutes: 675,
        }),
      ],
    },
    cabin_class: "economy",
    bags: { carry_on: 1, checked: 1 },
    requires_self_transfer: false,
    ignav_id: PROVIDER_ID,
    ...overrides,
  };
}

const validatedSearch = {
  origin: "LOS",
  destination: "LHR",
  departureDate: "2026-09-15",
  returnDate: null,
  passengers: { adults: 1, children: 1, infantsWithoutSeat: 1 },
  cabinClass: "economy",
};

function searchRequest(search = validatedSearch) {
  return new Request("https://peterselijah.name.ng/api/skyeta/offers/search", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "CF-Connecting-IP": "203.0.113.14",
    },
    body: JSON.stringify(search),
  });
}

function normalized(value = itinerary(), expectReturn = false) {
  return normalizeIgnavItinerary({
    value,
    cacheId: CACHE_ID,
    now: NOW,
    expiresAt: new Date(NOW.getTime() + 600_000),
    passengers: validatedSearch.passengers,
    expected: {
      origin: validatedSearch.origin,
      destination: validatedSearch.destination,
      departureDate: validatedSearch.departureDate,
      returnDate: expectReturn ? "2026-09-22" : null,
      cabinClass: validatedSearch.cabinClass,
    },
  });
}

test("Ignav is selected explicitly and is live only when its server key exists", () => {
  const environment = {
    SKYETA_FLIGHT_PROVIDER: "ignav",
    IGNAV_API_KEY: "ignav_server_key",
    AMADEUS_API_KEY: "old",
    AMADEUS_API_SECRET: "old-secret",
    AMADEUS_MODE: "live",
  };
  assert.equal(selectedFlightProvider(environment), "ignav");
  assert.equal(configuredFlightProviderEnvironment(environment), "live");
  assert.equal(
    configuredFlightProviderEnvironment({ SKYETA_FLIGHT_PROVIDER: "ignav" }),
    null,
  );
  assert.equal(
    selectedFlightProvider({ IGNAV_API_KEY: "key", DUFFEL_ACCESS_TOKEN: "token" }),
    "ignav",
  );
});

test("Ignav request mapping preserves passengers, cabin, NG market and return endpoint fields", () => {
  assert.deepEqual(buildIgnavSearchRequest(validatedSearch, "NG"), {
    origin: "LOS",
    destination: "LHR",
    departure_date: "2026-09-15",
    adults: 1,
    children: 1,
    infants_on_lap: 1,
    cabin_class: "economy",
    max_stops: 2,
    allow_self_transfer: false,
    market: "NG",
  });
  assert.equal(
    buildIgnavSearchRequest(
      { ...validatedSearch, returnDate: "2026-09-22" },
      "NG",
    ).return_date,
    "2026-09-22",
  );
});

test("Ignav client keeps its key server-side and only calls allowlisted HTTPS paths", async () => {
  const calls = [];
  const secret = "ignav_server_only_secret";
  const client = createIgnavClient({
    getConfig: () => ({ apiKey: secret }),
    fetchImpl: async (input, init) => {
      calls.push({ url: new URL(input), init });
      return Response.json({ itineraries: [] }, {
        headers: { "x-request-id": "ignav-request-1" },
      });
    },
  });
  const result = await client.request("/api/fares/one-way", {
    origin: "LOS",
    destination: "LHR",
    departure_date: "2026-09-15",
  });
  assert.equal(result.mode, "live");
  assert.equal(result.requestId, "ignav-request-1");
  assert.equal(calls[0].url.origin, "https://ignav.com");
  assert.equal(calls[0].url.pathname, "/api/fares/one-way");
  assert.equal(calls[0].init.redirect, "manual");
  assert.equal(calls[0].init.cache, undefined);
  assert.equal(calls[0].init.headers["X-Api-Key"], secret);
  assert.doesNotMatch(calls[0].url.toString(), new RegExp(secret));

  let externalCalls = 0;
  const guarded = createIgnavClient({
    getConfig: () => ({ apiKey: secret }),
    fetchImpl: async () => {
      externalCalls += 1;
      return Response.json({});
    },
  });
  await assert.rejects(
    guarded.request("https://attacker.example/api/fares/one-way", {}),
    (error) =>
      error instanceof IgnavProviderError && error.code === "invalid_request",
  );
  assert.equal(externalCalls, 0);
});

test("Ignav client timeout covers a stalled response body", async () => {
  const client = createIgnavClient({
    getConfig: () => ({ apiKey: "key" }),
    fetchImpl: async (_input, init) =>
      new Response(
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
      ),
  });
  await assert.rejects(
    client.request("/api/fares/one-way", {}, { timeoutMs: 25 }),
    (error) =>
      error instanceof IgnavProviderError &&
      error.code === "timeout" &&
      error.status === 504,
  );
});

test("Ignav client classifies exhausted allowance and retryable upstream failure", async () => {
  for (const [providerStatus, code, retryable] of [
    [302, "provider_rejected", false],
    [402, "allowance_exhausted", false],
    [429, "spend_limit_reached", false],
    [424, "unavailable", true],
  ]) {
    const client = createIgnavClient({
      getConfig: () => ({ apiKey: "key" }),
      fetchImpl: async () => Response.json({ error: {} }, { status: providerStatus }),
    });
    await assert.rejects(
      client.request("/api/fares/one-way", {}),
      (error) =>
        error instanceof IgnavProviderError &&
        error.code === code &&
        error.providerStatus === providerStatus &&
        error.retryable === retryable,
    );
  }
});

test("Ignav normalizer keeps verified NGN fare, local schedule, baggage and passengers", () => {
  const offer = normalized();
  assert.ok(offer);
  assert.deepEqual(offer.source, {
    provider: "ignav",
    environment: "live",
    isLive: true,
    label: "Live fare",
  });
  assert.deepEqual(offer.total, { amount: "569217", currency: "NGN" });
  assert.equal(offer.slices[0].segments[0].departingAt, "2026-09-15T12:15:00");
  assert.equal(offer.slices[0].segments[0].origin.timeZone, "Africa/Lagos");
  assert.equal(offer.slices[0].duration, "PT12H");
  assert.equal(offer.slices[0].connectionCount, 1);
  assert.equal(offer.passengerCount, 3);
  assert.deepEqual(
    offer.passengers.map((entry) => entry.type),
    ["adult", "child", "infant_without_seat"],
  );
  assert.deepEqual(
    offer.baggage.map((entry) => [entry.type, entry.quantity]),
    [["carry_on", 1], ["checked", 1]],
  );
  assert.equal(offer.fareConditions.changeBeforeDeparture.status, "unknown");
  assert.equal(offer.isBookable, true);
});

test("Ignav normalizer rejects unverified hints, self-transfers and incomplete returns", () => {
  assert.equal(
    normalized(itinerary({ price: { amount: 200, currency: "USD", status: "unverified" } })),
    null,
  );
  assert.equal(normalized(itinerary({ requires_self_transfer: true })), null);
  assert.equal(normalized(itinerary(), true), null);
  assert.equal(
    normalized(
      itinerary({
        outbound: {
          carrier: "RwandAir",
          duration_minutes: 330,
          segments: [segment({ departure_airport: "ABV" })],
        },
      }),
    ),
    null,
  );
  assert.equal(normalized(itinerary({ cabin_class: "business" })), null);
});

test("Ignav cache IDs are opaque and never equal provider handoff tokens", () => {
  assert.equal(isIgnavCacheId(CACHE_ID), true);
  assert.equal(isIgnavCacheId(PROVIDER_ID), false);
  assert.notEqual(CACHE_ID, PROVIDER_ID);
  assert.equal(isIgnavProviderId("opaque-provider_id.2026~one"), true);
});

test("Ignav live search stores opaque offers and returns no invented alternatives", async () => {
  let providerCall;
  const saved = [];
  const handler = createIgnavOfferSearchHandler({
    now: () => NOW,
    market: () => "NG",
    checkRateLimit: () => ({ allowed: true, retryAfterSeconds: 0 }),
    createClient: () => ({
      async request(path, body) {
        providerCall = { path, body };
        return {
          data: {
            origin: "LOS",
            destination: "LHR",
            departure_date: "2026-09-15",
            return_date: null,
            itineraries: [
              itinerary(),
              itinerary({
                ignav_id: "c".repeat(32),
                price: { amount: 1, currency: "NGN", status: "unverified" },
              }),
              itinerary({
                ignav_id: "d".repeat(32),
                requires_self_transfer: true,
              }),
            ],
          },
          mode: "live",
          providerStatus: 200,
          requestId: "request-7",
        };
      },
    }),
    createCache: () => ({
      async save(value) {
        saved.push(value);
        return CACHE_ID;
      },
      async get() { return null; },
      async deleteExpired() { return 0; },
    }),
  });
  const response = await handler(searchRequest());
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(providerCall.path, "/api/fares/one-way");
  assert.equal(providerCall.body.market, "NG");
  assert.equal(providerCall.body.allow_self_transfer, false);
  assert.equal(body.provider, "ignav");
  assert.equal(body.mode, "live");
  assert.equal(body.bookingEnabled, false);
  assert.equal(body.offers.length, 1);
  assert.equal(body.offers[0].id, CACHE_ID);
  assert.equal(saved.length, 1);
  assert.equal(saved[0].ignavId, PROVIDER_ID);
  assert.doesNotMatch(JSON.stringify(body), new RegExp(PROVIDER_ID));
});

test("Ignav empty search result is successful and rate limiting stops before provider calls", async () => {
  let providerCalls = 0;
  const emptyHandler = createIgnavOfferSearchHandler({
    now: () => NOW,
    checkRateLimit: () => ({ allowed: true, retryAfterSeconds: 0 }),
    createClient: () => ({
      async request() {
        providerCalls += 1;
        return {
          data: {
            origin: "LOS",
            destination: "LHR",
            departure_date: "2026-09-15",
            return_date: null,
            itineraries: [],
          },
          mode: "live",
          providerStatus: 200,
          requestId: null,
        };
      },
    }),
    createCache: () => ({
      async save() { throw new Error("must not save"); },
      async get() { return null; },
      async deleteExpired() { return 0; },
    }),
  });
  const emptyResponse = await emptyHandler(searchRequest());
  assert.deepEqual((await emptyResponse.json()).offers, []);
  assert.equal(providerCalls, 1);

  const limited = createIgnavOfferSearchHandler({
    now: () => NOW,
    checkRateLimit: () => ({ allowed: false, retryAfterSeconds: 45 }),
    createClient: () => ({
      async request() {
        providerCalls += 1;
        throw new Error("must not call");
      },
    }),
  });
  const limitedResponse = await limited(searchRequest());
  assert.equal(limitedResponse.status, 429);
  assert.equal(limitedResponse.headers.get("Retry-After"), "45");
  assert.equal(providerCalls, 1);
});

test("Ignav refresh sends only the private handoff token and returns safe external links", async () => {
  const currentOffer = normalized();
  assert.ok(currentOffer);
  const cached = {
    id: CACHE_ID,
    mode: "live",
    itinerary: itinerary(),
    ignavId: PROVIDER_ID,
    passengers: validatedSearch.passengers,
    expected: {
      origin: "LOS",
      destination: "LHR",
      departureDate: "2026-09-15",
      returnDate: null,
      cabinClass: "economy",
    },
    identity: ignavOfferIdentity(currentOffer),
    createdAt: NOW.getTime() - 60_000,
    expiresAt: NOW.getTime() + 540_000,
  };
  let providerCall;
  let saved;
  const refreshedItinerary = itinerary({
    price: { amount: 571000, currency: "NGN", status: "verified" },
  });
  const handler = createIgnavOfferRefreshHandler({
    now: () => NOW,
    checkRateLimit: () => ({ allowed: true, retryAfterSeconds: 0 }),
    createClient: () => ({
      async request(path, body) {
        providerCall = { path, body };
        return {
          data: {
            itinerary: refreshedItinerary,
            booking_options: [
              {
                legs: ["outbound"],
                links: [
                  {
                    provider_name: "RwandAir",
                    provider_type: "airline",
                    fare_name: "Economy",
                    price: { amount: 571000, currency: "NGN", status: "verified" },
                    url: "https://www.rwandair.com/booking?flight=WB701",
                  },
                  {
                    provider_name: "Unsafe",
                    provider_type: "third_party",
                    url: "javascript:alert(1)",
                  },
                ],
              },
            ],
          },
          mode: "live",
          providerStatus: 200,
          requestId: "refresh-1",
        };
      },
    }),
    createCache: () => ({
      async get() { return cached; },
      async save(value) { saved = value; return CACHE_ID; },
    }),
  });
  const response = await handler(
    new Request(`https://peterselijah.name.ng/api/skyeta/offers/${CACHE_ID}/refresh`, {
      method: "POST",
    }),
    CACHE_ID,
  );
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.deepEqual(providerCall, {
    path: "/api/fares/booking-links",
    body: { ignav_id: PROVIDER_ID },
  });
  assert.equal(body.offer.total.amount, "571000");
  assert.equal(body.priceReconfirmed, true);
  assert.equal(body.bookingEnabled, false);
  assert.deepEqual(body.bookingLinks, [
    {
      providerName: "RwandAir",
      providerType: "airline",
      fareName: "Economy",
      price: { amount: "571000", currency: "NGN" },
      url: "https://www.rwandair.com/booking?flight=WB701",
    },
  ]);
  assert.equal(saved.id, CACHE_ID);
  assert.equal(saved.ignavId, PROVIDER_ID);
  assert.doesNotMatch(JSON.stringify(body), new RegExp(PROVIDER_ID));
});

test("Ignav booking-link normalizer rejects credentials, local hosts and duplicate URLs", () => {
  const approvedHosts = new Set(["airline.example"]);
  const valid = {
    provider_name: "Airline",
    provider_type: "airline",
    url: "https://airline.example/book",
  };
  const links = normalizeIgnavBookingLinks(
    [
      {
        legs: ["outbound"],
        links: [
          valid,
          valid,
          { ...valid, url: "https://user:pass@airline.example/book" },
          { ...valid, url: "https://127.0.0.1/book" },
          { ...valid, url: "https://airline.example.evil.test/book" },
        ],
      },
    ],
    false,
    approvedHosts,
  );
  assert.equal(links.length, 1);
  assert.equal(links[0].url, "https://airline.example/book");
});

test("round-trip handoff never presents one-leg links as a complete booking", () => {
  const approvedHosts = new Set(["airline.example"]);
  const outboundOnly = {
    legs: ["outbound"],
    links: [
      {
        provider_name: "Airline",
        provider_type: "airline",
        url: "https://airline.example/outbound",
      },
    ],
  };
  const complete = {
    legs: ["outbound", "inbound"],
    links: [
      {
        provider_name: "Airline",
        provider_type: "airline",
        url: "https://airline.example/round-trip",
      },
    ],
  };
  assert.deepEqual(
    normalizeIgnavBookingLinks([outboundOnly], true, approvedHosts),
    [],
  );
  assert.equal(
    normalizeIgnavBookingLinks(
      [outboundOnly, complete],
      true,
      approvedHosts,
    ).length,
    1,
  );
});

test("Ignav itinerary identity changes when a provider changes the selected schedule", () => {
  const original = normalized();
  const shifted = normalized(
    itinerary({
      outbound: {
        carrier: "RwandAir",
        duration_minutes: 720,
        segments: [
          segment({ departure_time_local: "2026-09-15T13:15:00" }),
          segment({
            flight_number: "700",
            departure_airport: "KGL",
            departure_time_local: "2026-09-15T20:00:00",
            departure_timezone: "Africa/Kigali",
            departure_time_utc: "2026-09-15T18:00:00Z",
            arrival_airport: "LHR",
            arrival_time_local: "2026-09-16T06:15:00",
            arrival_timezone: "Europe/London",
            arrival_time_utc: "2026-09-16T05:15:00Z",
            duration_minutes: 675,
          }),
        ],
      },
    }),
  );
  assert.ok(original && shifted);
  assert.notEqual(ignavOfferIdentity(original), ignavOfferIdentity(shifted));
});

test("D1 schema and migration permit both retained Amadeus and new Ignav cache rows", async () => {
  const schema = await readFile(new URL("../db/schema.ts", import.meta.url), "utf8");
  const migration = await readFile(
    new URL("../db/migrations/0005_ignav_provider_cache.sql", import.meta.url),
    "utf8",
  );
  assert.match(schema, /provider IN \('amadeus', 'ignav'\)/);
  assert.match(migration, /INSERT INTO provider_offer_cache_next/);
  assert.match(migration, /FROM provider_offer_cache/);
  assert.match(migration, /provider IN \('amadeus', 'ignav'\)/);
});
