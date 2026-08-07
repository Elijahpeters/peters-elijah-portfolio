import assert from "node:assert/strict";
import test from "node:test";

import {
  isSameOriginRequest,
  validateFlightSearch,
} from "../app/lib/http/validation.ts";

const now = new Date("2026-08-05T12:00:00.000Z");

function validSearch(overrides = {}) {
  return {
    origin: "LOS",
    destination: "LHR",
    departureDate: "2026-09-10",
    returnDate: "2026-09-17",
    passengers: { adults: 1, children: 0, infantsWithoutSeat: 0 },
    cabinClass: "economy",
    ...overrides,
  };
}

test("flight search validates and normalizes an itinerary", () => {
  const result = validateFlightSearch(
    validSearch({ origin: " los ", destination: "lhr" }),
    now,
  );

  assert.equal(result.ok, true);
  assert.deepEqual(result.value, validSearch());
});

test("flight search rejects impossible dates and passenger mixes", () => {
  const result = validateFlightSearch(
    validSearch({
      destination: "LOS",
      departureDate: "2026-08-03",
      returnDate: "2026-08-02",
      passengers: { adults: 1, children: 8, infantsWithoutSeat: 2 },
    }),
    now,
  );

  assert.equal(result.ok, false);
  assert.ok(result.fields.destination);
  assert.ok(result.fields.departureDate);
  assert.ok(result.fields.returnDate);
  assert.ok(result.fields.infantsWithoutSeat);
  assert.ok(result.fields.passengers);
});

test("flight search permits the previous UTC date for western local-time overlap", () => {
  const result = validateFlightSearch(
    {
      origin: "LAX",
      destination: "JFK",
      departureDate: "2026-08-07",
      passengers: { adults: 1, children: 0, infantsWithoutSeat: 0 },
      cabinClass: "economy",
    },
    new Date("2026-08-08T00:30:00.000Z"),
  );

  assert.equal(result.ok, true);

  const tooOld = validateFlightSearch(
    {
      origin: "LAX",
      destination: "JFK",
      departureDate: "2026-08-06",
      passengers: { adults: 1, children: 0, infantsWithoutSeat: 0 },
      cabinClass: "economy",
    },
    new Date("2026-08-08T00:30:00.000Z"),
  );

  assert.equal(tooOld.ok, false);
  assert.ok(tooOld.fields.departureDate);
});

test("flight search permits the eastern local-date overlap at the 330-day edge", () => {
  const localHorizon = validateFlightSearch(
    validSearch({
      departureDate: "2027-07-02",
      returnDate: null,
    }),
    now,
  );

  assert.equal(localHorizon.ok, true);

  const beyondGrace = validateFlightSearch(
    validSearch({
      departureDate: "2027-07-03",
      returnDate: null,
    }),
    now,
  );

  assert.equal(beyondGrace.ok, false);
  assert.ok(beyondGrace.fields.departureDate);
});

test("state-changing requests require the portfolio origin", () => {
  assert.equal(
    isSameOriginRequest(
      new Request("https://peterselijah.name.ng/api/skyeta/bookings", {
        headers: { Origin: "https://peterselijah.name.ng" },
      }),
    ),
    true,
  );
  assert.equal(
    isSameOriginRequest(
      new Request("https://peterselijah.name.ng/api/skyeta/bookings", {
        headers: { Origin: "https://attacker.example" },
      }),
    ),
    false,
  );
});
