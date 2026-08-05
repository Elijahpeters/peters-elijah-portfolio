import assert from "node:assert/strict";
import test from "node:test";

import { DuffelProviderError } from "../app/lib/duffel/client.ts";
import {
  buildDuffelOfferRequest,
  createOfferSearchHandler,
} from "../app/api/skyeta/offers/search/search.ts";
import { createOfferRefreshHandler } from "../app/api/skyeta/offers/[offerId]/refresh/refresh.ts";
import { createCheckoutSessionHandler } from "../app/api/skyeta/checkout/sessions/checkout-session.ts";

const search = {
  origin: "HNL",
  destination: "OGG",
  departureDate: "2026-09-10",
  returnDate: null,
  passengers: { adults: 1, children: 0, infantsWithoutSeat: 0 },
  cabinClass: "economy",
};

function request(body = search) {
  return new Request("https://peterselijah.name.ng/api/skyeta/offers/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function providerOffer(overrides = {}) {
  const hnl = { iata_code: "HNL", name: "Honolulu Airport", iata_country_code: "US" };
  const ogg = { iata_code: "OGG", name: "Kahului Airport", iata_country_code: "US" };
  const airline = { iata_code: "HA", name: "Hawaiian Airlines" };
  return {
    id: "off_live_1",
    live_mode: true,
    partial: false,
    expires_at: "2026-09-10T08:30:00Z",
    total_amount: "95.40",
    total_currency: "USD",
    owner: airline,
    passengers: [{ id: "pas_1", type: "adult" }],
    slices: [
      {
        id: "sli_1",
        origin: hnl,
        destination: ogg,
        duration: "PT42M",
        segments: [
          {
            id: "seg_1",
            origin: hnl,
            destination: ogg,
            departing_at: "2026-09-10T09:30:00",
            arriving_at: "2026-09-10T10:12:00",
            duration: "PT42M",
            distance: "160.934",
            marketing_carrier: airline,
            operating_carrier: airline,
            marketing_carrier_flight_number: "101",
            operating_carrier_flight_number: "101",
            passengers: [
              {
                passenger_id: "pas_1",
                cabin_class: "economy",
                baggages: [{ type: "carry_on", quantity: 1 }],
              },
            ],
            stops: [],
          },
        ],
      },
    ],
    ...overrides,
  };
}

test("offer request maps validated passengers and itinerary for Duffel", () => {
  assert.deepEqual(buildDuffelOfferRequest(search), {
    data: {
      slices: [
        { origin: "HNL", destination: "OGG", departure_date: "2026-09-10" },
      ],
      passengers: [{ type: "adult" }],
      cabin_class: "economy",
    },
  });
});

test("offer search returns genuine live provenance and SkyETA risk", async () => {
  let providerCall;
  const handler = createOfferSearchHandler({
    now: () => new Date("2026-08-05T12:00:00.000Z"),
    bookingEnabled: () => true,
    createClient: () => ({
      getMode: () => "live",
      request: async (path, options) => {
        providerCall = { path, options };
        return {
          data: { id: "orq_1", offers: [providerOffer()] },
          mode: "live",
          requestId: "req_1",
        };
      },
    }),
  });

  const response = await handler(request());
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(providerCall.path, "/air/offer_requests");
  assert.equal(providerCall.options.query.return_offers, true);
  assert.equal(body.mode, "live");
  assert.equal(body.bookingEnabled, true);
  assert.equal(body.offers[0].source.label, "Live fare");
  assert.equal(body.offers[0].isBookable, true);
  assert.equal(body.offers[0].skyetaRisk.status, "available");
  assert.ok(body.offers[0].skyetaRisk.percentage > 0);
});

test("test inventory stays visibly test-only and cannot be booked", async () => {
  const handler = createOfferSearchHandler({
    now: () => new Date("2026-08-05T12:00:00.000Z"),
    bookingEnabled: () => true,
    createClient: () => ({
      getMode: () => "test",
      request: async () => ({
        data: { id: "orq_test", offers: [providerOffer({ live_mode: false })] },
        mode: "test",
        requestId: null,
      }),
    }),
  });

  const body = await (await handler(request())).json();
  assert.equal(body.mode, "test");
  assert.equal(body.bookingEnabled, false);
  assert.equal(body.offers[0].source.label, "Test fare");
  assert.equal(body.offers[0].isBookable, false);
});

test("missing provider configuration never falls back to invented fares", async () => {
  const handler = createOfferSearchHandler({
    now: () => new Date("2026-08-05T12:00:00.000Z"),
    createClient: () => ({
      getMode: () => null,
      request: async () => {
        throw new DuffelProviderError({
          code: "not_configured",
          message: "Live flight search is not configured.",
          status: 503,
        });
      },
    }),
  });

  const response = await handler(request());
  const body = await response.json();
  assert.equal(response.status, 503);
  assert.equal(body.configured, false);
  assert.equal(body.error.code, "not_configured");
  assert.equal("offers" in body, false);
});

test("selected offers are fetched again and repriced before checkout", async () => {
  let requestedPath;
  const handler = createOfferRefreshHandler({
    now: () => new Date("2026-08-05T12:00:00.000Z"),
    bookingEnabled: () => true,
    createClient: () => ({
      request: async (path) => {
        requestedPath = path;
        return {
          data: providerOffer({ total_amount: "109.20" }),
          mode: "live",
          requestId: "req_refresh",
        };
      },
    }),
  });

  const response = await handler(
    new Request("https://peterselijah.name.ng/api/skyeta/offers/off_live_1/refresh", {
      method: "POST",
    }),
    "off_live_1",
  );
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(requestedPath, "/air/offers/off_live_1");
  assert.equal(body.priceReconfirmed, true);
  assert.deepEqual(body.offer.total, { amount: "109.20", currency: "USD" });
  assert.equal(body.offer.isBookable, true);
});

test("offer refresh rejects path injection before contacting Duffel", async () => {
  let called = false;
  const handler = createOfferRefreshHandler({
    createClient: () => ({
      request: async () => {
        called = true;
        throw new Error("must not run");
      },
    }),
  });
  const response = await handler(
    new Request("https://peterselijah.name.ng/api/skyeta/offers/bad/refresh"),
    "../orders",
  );
  assert.equal(response.status, 400);
  assert.equal(called, false);
});

test("checkout refuses test inventory before creating a session or database record", async () => {
  let databaseAccessed = false;
  const handler = createCheckoutSessionHandler({
    now: () => new Date("2026-08-05T12:00:00.000Z"),
    bookingEnabled: () => true,
    createClient: () => ({
      request: async () => ({
        data: providerOffer({ live_mode: false }),
        mode: "test",
        requestId: null,
      }),
    }),
    getDatabase: () => {
      databaseAccessed = true;
      throw new Error("must not access storage");
    },
  });
  const response = await handler(
    new Request("https://peterselijah.name.ng/api/skyeta/checkout/sessions", {
      method: "POST",
      headers: {
        Origin: "https://peterselijah.name.ng",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ offerId: "off_live_1" }),
    }),
  );
  const body = await response.json();
  assert.equal(response.status, 409);
  assert.equal(body.error.code, "booking_not_enabled");
  assert.equal(databaseAccessed, false);
});

test("checkout rejects cross-origin requests before contacting the provider", async () => {
  let providerCalled = false;
  const handler = createCheckoutSessionHandler({
    createClient: () => ({
      request: async () => {
        providerCalled = true;
        throw new Error("must not run");
      },
    }),
  });
  const response = await handler(
    new Request("https://peterselijah.name.ng/api/skyeta/checkout/sessions", {
      method: "POST",
      headers: {
        Origin: "https://attacker.example",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ offerId: "off_live_1" }),
    }),
  );
  assert.equal(response.status, 403);
  assert.equal(providerCalled, false);
});
