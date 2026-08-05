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
      departureDate: "2026-08-04",
      returnDate: "2026-08-03",
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
