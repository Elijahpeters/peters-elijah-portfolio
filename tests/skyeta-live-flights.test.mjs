import assert from "node:assert/strict";
import test from "node:test";

import {
  AIRLABS_SCHEDULE_FIELDS,
  createLiveFlightsHandler,
} from "../app/api/skyeta/live-flights/airlabs.ts";

function request(query) {
  return new Request(`https://portfolio.test/api/skyeta/live-flights?${query}`);
}

test("live-flight route rejects malformed queries before configuration or fetch", async () => {
  let fetchCount = 0;
  const handler = createLiveFlightsHandler({
    getApiKey: () => "server-only-key",
    fetchImpl: async () => {
      fetchCount += 1;
      throw new Error("fetch must not run");
    },
  });

  for (const query of [
    "origin=jfk&destination=LAX&airline=AA",
    "origin=JFK&destination=LAX&airline=AAL",
    "origin=JFK&destination=JFK",
    "origin=JFK&origin=BOS&destination=LAX",
  ]) {
    const response = await handler(request(query));
    const body = await response.json();

    assert.equal(response.status, 400);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(body.configured, false);
    assert.equal(body.error.code, "invalid_query");
  }
  assert.equal(fetchCount, 0);
});

test("live-flight route reports an absent server key without fallback flights", async () => {
  const handler = createLiveFlightsHandler({
    getApiKey: () => undefined,
    fetchImpl: async () => {
      throw new Error("fetch must not run");
    },
  });

  const response = await handler(request("origin=JFK&destination=LAX"));
  const body = await response.json();

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.deepEqual(body, {
    configured: false,
    source: "airlabs",
    query: { origin: "JFK", destination: "LAX", airline: null },
    flights: [],
    message: "Live flight lookup is not configured.",
  });
});

test("live-flight route requests minimal fields, filters defensively, and sanitizes", async () => {
  const secret = "server-only-key-that-must-not-leak";
  let requestedUrl;
  const handler = createLiveFlightsHandler({
    getApiKey: () => secret,
    now: () => Date.parse("2026-08-03T12:00:00Z"),
    fetchImpl: async (input, init) => {
      requestedUrl = new URL(input);
      assert.equal(init.method, "GET");
      assert.equal(init.cache, "no-store");
      assert.equal(init.headers.Accept, "application/json");
      assert.ok(init.signal instanceof AbortSignal);
      return Response.json({
        response: [
          {
            airline_iata: "AA",
            flight_iata: "AA100",
            flight_number: "100",
            dep_iata: "JFK",
            arr_iata: "LAX",
            dep_time: "2026-08-03 09:30",
            dep_time_utc: "2026-08-03 13:30",
            dep_estimated: "2026-08-03 09:45",
            dep_estimated_utc: "2026-08-03 13:45",
            arr_time: "2026-08-03 12:30",
            arr_time_utc: "2026-08-03 19:30",
            arr_estimated: "2026-08-03 12:42",
            arr_estimated_utc: "2026-08-03 19:42",
            status: "scheduled",
            duration: 360,
            dep_delayed: 15,
            arr_delayed: 12,
            provider_private_field: secret,
          },
          {
            airline_iata: "AA",
            flight_iata: "AA200",
            dep_iata: "JFK",
            arr_iata: "SFO",
            dep_time_utc: "2026-08-03 14:30",
          },
          {
            airline_iata: "DL",
            flight_iata: "DL300",
            dep_iata: "JFK",
            arr_iata: "LAX",
            dep_time_utc: "2026-08-03 15:30",
          },
        ],
      });
    },
  });

  const response = await handler(
    request("origin=JFK&destination=LAX&airline=AA"),
  );
  const responseText = await response.text();
  const body = JSON.parse(responseText);

  assert.equal(requestedUrl.origin, "https://airlabs.co");
  assert.equal(requestedUrl.pathname, "/api/v9/schedules");
  assert.equal(requestedUrl.searchParams.get("dep_iata"), "JFK");
  assert.equal(requestedUrl.searchParams.get("arr_iata"), "LAX");
  assert.equal(requestedUrl.searchParams.get("airline_iata"), "AA");
  assert.equal(requestedUrl.searchParams.get("api_key"), secret);
  assert.equal(
    requestedUrl.searchParams.get("_fields"),
    AIRLABS_SCHEDULE_FIELDS.join(","),
  );
  assert.equal(requestedUrl.searchParams.get("limit"), "50");

  assert.equal(response.status, 200);
  assert.equal(body.configured, true);
  assert.equal(body.source, "airlabs");
  assert.equal(body.fetchedAt, "2026-08-03T12:00:00.000Z");
  assert.equal(body.flights.length, 1);
  assert.deepEqual(body.flights[0], {
    id: "AA100:2026-08-03 13:30:0",
    airlineIata: "AA",
    flightIata: "AA100",
    flightNumber: "100",
    origin: "JFK",
    destination: "LAX",
    departure: {
      scheduledLocal: "2026-08-03 09:30",
      scheduledUtc: "2026-08-03 13:30",
      estimatedLocal: "2026-08-03 09:45",
      estimatedUtc: "2026-08-03 13:45",
    },
    arrival: {
      scheduledLocal: "2026-08-03 12:30",
      scheduledUtc: "2026-08-03 19:30",
      estimatedLocal: "2026-08-03 12:42",
      estimatedUtc: "2026-08-03 19:42",
    },
    status: "scheduled",
    durationMinutes: 360,
    departureDelayMinutes: 15,
    arrivalDelayMinutes: 12,
  });
  assert.doesNotMatch(responseText, /server-only-key/);
  assert.doesNotMatch(responseText, /provider_private_field/);
});

test("live-flight route caches successful route queries briefly", async () => {
  let clock = 1_000;
  let fetchCount = 0;
  const handler = createLiveFlightsHandler({
    getApiKey: () => "server-only-key",
    now: () => clock,
    cacheTtlMs: 1_000,
    fetchImpl: async () => {
      fetchCount += 1;
      return Response.json([]);
    },
  });

  await handler(request("origin=JFK&destination=LAX"));
  clock = 1_500;
  await handler(request("origin=JFK&destination=LAX"));
  assert.equal(fetchCount, 1);

  clock = 2_001;
  await handler(request("origin=JFK&destination=LAX"));
  assert.equal(fetchCount, 2);
});

test("live-flight route converts an abort into a bounded timeout response", async () => {
  const handler = createLiveFlightsHandler({
    getApiKey: () => "server-only-key",
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

  const response = await handler(request("origin=JFK&destination=LAX"));
  const body = await response.json();

  assert.equal(response.status, 504);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(body.configured, true);
  assert.equal(body.flights.length, 0);
  assert.equal(body.error.code, "upstream_timeout");
});

test("live-flight route does not echo provider errors", async () => {
  const handler = createLiveFlightsHandler({
    getApiKey: () => "server-only-key",
    fetchImpl: async () =>
      Response.json({
        error: {
          code: "unknown_api_key",
          message: "provider detail must stay private",
        },
      }),
  });

  const response = await handler(request("origin=JFK&destination=LAX"));
  const responseText = await response.text();
  const body = JSON.parse(responseText);

  assert.equal(response.status, 502);
  assert.equal(body.error.code, "upstream_error");
  assert.equal(body.error.message, "Live schedule authentication is unavailable.");
  assert.doesNotMatch(responseText, /provider detail/);
});
