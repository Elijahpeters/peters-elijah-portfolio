import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeDuffelOffer,
  normalizeDuffelOffers,
} from "../app/lib/duffel/normalize.ts";

function offer(overrides = {}) {
  return {
    id: "off_123",
    live_mode: true,
    partial: false,
    expires_at: "2026-08-06T12:30:00Z",
    created_at: "2026-08-05T12:00:00Z",
    updated_at: "2026-08-05T12:01:00Z",
    total_amount: "245.60",
    total_currency: "USD",
    base_amount: "200.00",
    base_currency: "USD",
    tax_amount: "45.60",
    tax_currency: "USD",
    total_emissions_kg: "118.4",
    owner: {
      name: "Delta Air Lines",
      iata_code: "DL",
      logo_symbol_url: "https://assets.duffel.com/dl.svg",
      conditions_of_carriage_url: "https://www.delta.com/conditions",
    },
    passengers: [{ id: "pas_1", type: "adult" }],
    passenger_identity_documents_required: true,
    supported_passenger_identity_document_types: ["passport", "passport"],
    payment_requirements: {
      price_guarantee_expires_at: "2026-08-05T12:20:00Z",
      payment_required_by: "2026-08-05T12:25:00Z",
    },
    conditions: {
      change_before_departure: {
        allowed: true,
        penalty_amount: "75.00",
        penalty_currency: "USD",
      },
      refund_before_departure: { allowed: false },
    },
    slices: [
      {
        id: "sli_1",
        duration: "PT8H20M",
        origin: {
          iata_code: "JFK",
          name: "John F Kennedy International Airport",
          city_name: "New York",
          iata_country_code: "US",
          time_zone: "America/New_York",
          latitude: 40.6413,
          longitude: -73.7781,
        },
        destination: {
          iata_code: "LAX",
          name: "Los Angeles International Airport",
          city_name: "Los Angeles",
          iata_country_code: "US",
          time_zone: "America/Los_Angeles",
          latitude: 33.9416,
          longitude: -118.4085,
        },
        segments: [
          {
            id: "seg_1",
            departing_at: "2026-08-06T08:00:00",
            arriving_at: "2026-08-06T10:15:00",
            duration: "PT2H15M",
            distance: "1220.5",
            origin_terminal: "4",
            destination_terminal: "S",
            origin: {
              iata_code: "JFK",
              name: "John F Kennedy International Airport",
              city_name: "New York",
              iata_country_code: "US",
              time_zone: "America/New_York",
            },
            destination: {
              iata_code: "ATL",
              name: "Hartsfield-Jackson Atlanta International Airport",
              city_name: "Atlanta",
              iata_country_code: "US",
              time_zone: "America/New_York",
            },
            marketing_carrier: { name: "Delta Air Lines", iata_code: "DL" },
            operating_carrier: { name: "Delta Air Lines", iata_code: "DL" },
            marketing_carrier_flight_number: "110",
            operating_carrier_flight_number: "110",
            aircraft: { name: "Airbus A321" },
            stops: [],
            passengers: [
              {
                passenger_id: "pas_1",
                cabin_class: "economy",
                cabin_class_marketing_name: "Main Cabin",
                cabin: { name: "economy", marketing_name: "Main Cabin" },
                baggages: [
                  { type: "carry_on", quantity: 1 },
                  { type: "checked", quantity: 1 },
                ],
              },
            ],
          },
          {
            id: "seg_2",
            departing_at: "2026-08-06T12:00:00",
            arriving_at: "2026-08-06T15:20:00",
            duration: "PT5H20M",
            distance: "3120.2",
            origin: {
              iata_code: "ATL",
              name: "Hartsfield-Jackson Atlanta International Airport",
              city_name: "Atlanta",
              iata_country_code: "US",
              time_zone: "America/New_York",
            },
            destination: {
              iata_code: "LAX",
              name: "Los Angeles International Airport",
              city_name: "Los Angeles",
              iata_country_code: "US",
              time_zone: "America/Los_Angeles",
            },
            marketing_carrier: { name: "Delta Air Lines", iata_code: "DL" },
            operating_carrier: {
              name: "SkyWest Airlines",
              iata_code: "OO",
              logo_symbol_url: "javascript:alert(1)",
            },
            marketing_carrier_flight_number: "220",
            operating_carrier_flight_number: "5220",
            stops: [
              {
                id: "sto_1",
                airport: {
                  iata_code: "DFW",
                  name: "Dallas Fort Worth International Airport",
                  city_name: "Dallas",
                  iata_country_code: "US",
                  time_zone: "America/Chicago",
                },
                arriving_at: "2026-08-06T13:00:00",
                departing_at: "2026-08-06T13:30:00",
                duration: "PT30M",
              },
            ],
            passengers: [
              {
                passenger_id: "pas_1",
                cabin_class: "economy",
                baggages: [{ type: "carry_on", quantity: 1 }],
              },
            ],
          },
        ],
      },
    ],
    ...overrides,
  };
}

test("normalizer exposes a complete live offer only when both modes are live", () => {
  const result = normalizeDuffelOffer(offer(), "live");
  assert.ok(result);
  assert.deepEqual(result.source, {
    provider: "duffel",
    environment: "live",
    isLive: true,
    label: "Live fare",
  });
  assert.equal(result.isBookable, true);
  assert.deepEqual(result.total, { amount: "245.60", currency: "USD" });
  assert.deepEqual(result.base, { amount: "200.00", currency: "USD" });
  assert.deepEqual(result.tax, { amount: "45.60", currency: "USD" });
  assert.equal(result.connectionCount, 1);
  assert.equal(result.slices[0].segments.length, 2);
  assert.equal(result.slices[0].segments[1].stops[0].airport.iataCode, "DFW");
  assert.equal(result.slices[0].segments[1].operatingCarrier.name, "SkyWest Airlines");
  assert.equal(result.slices[0].segments[1].operatingCarrier.logoUrl, null);
  assert.equal(result.baggage.length, 3);
  assert.deepEqual(result.fareConditions.changeBeforeDeparture, {
    status: "allowed",
    penalty: { amount: "75.00", currency: "USD" },
  });
  assert.deepEqual(result.fareConditions.refundBeforeDeparture, {
    status: "not_allowed",
    penalty: null,
  });
  assert.deepEqual(result.supportedIdentityDocumentTypes, ["passport"]);
  assert.deepEqual(
    result.airlines.map((entry) => entry.name),
    ["Delta Air Lines", "SkyWest Airlines"],
  );
});

test("normalizer never labels either side of a test/live mismatch as live", () => {
  const configuredTest = normalizeDuffelOffer(offer(), "test");
  const providerTest = normalizeDuffelOffer(
    offer({ live_mode: false }),
    "live",
  );

  for (const result of [configuredTest, providerTest]) {
    assert.ok(result);
    assert.deepEqual(result.source, {
      provider: "duffel",
      environment: "test",
      isLive: false,
      label: "Test fare",
    });
    assert.equal(result.isBookable, false);
  }
});

test("normalizer rejects partial or malformed offers from production booking", () => {
  const partial = normalizeDuffelOffer(offer({ partial: true }), "live");
  assert.ok(partial);
  assert.equal(partial.isBookable, false);

  assert.equal(
    normalizeDuffelOffer(offer({ total_amount: "free" }), "live"),
    null,
  );
  assert.equal(
    normalizeDuffelOffer(
      offer({
        slices: [
          {
            id: "sli_bad",
            segments: [{ id: "seg_bad", origin: { iata_code: "JFK" } }],
          },
        ],
      }),
      "live",
    ),
    null,
  );
});

test("normalizer filters invalid rows when handling an offer collection", () => {
  const results = normalizeDuffelOffers([offer(), null, { id: "broken" }], "live");
  assert.equal(results.length, 1);
  assert.equal(results[0].id, "off_123");
});
