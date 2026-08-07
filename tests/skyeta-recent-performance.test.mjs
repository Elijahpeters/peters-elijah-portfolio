import assert from "node:assert/strict";
import test from "node:test";

import {
  RECENT_PERFORMANCE_COVERAGE_NOTICE,
  RECENT_PERFORMANCE_SOURCE,
  aggregateHistoricalRows,
  createRecentPerformanceHandler,
  historicalDelayProbability,
  parseRecentPerformanceQuery,
} from "../app/api/skyeta/recent-performance/recent-performance.ts";

const ALLOW_REQUEST = () => ({ allowed: true, retryAfterSeconds: 0 });

function request(query, address) {
  return new Request(
    `https://portfolio.test/api/skyeta/recent-performance?${query}`,
    address ? { headers: { "CF-Connecting-IP": address } } : undefined,
  );
}

function recentHandler(options = {}) {
  return createRecentPerformanceHandler({
    checkRateLimit: ALLOW_REQUEST,
    ...options,
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

test("recent-performance query requires route-qualified flight identifiers", async () => {
  let fetchCount = 0;
  const handler = recentHandler({
    getApiKey: () => "server-only-key",
    fetchImpl: async () => {
      fetchCount += 1;
      throw new Error("fetch must not run");
    },
  });

  for (const query of [
    "",
    "flights=",
    "flights=AA6",
    "flights=aa6:JFK:LHR",
    "flights=AA6:jfk:LHR",
    "flights=AA:JFK:LHR",
    "flights=AAA6:JFK:LHR",
    "flights=AA12345:JFK:LHR",
    "flights=AA6:JFK:JFK",
    "flights=AA6:JFK",
    "flights=AA6:JFK:LHR:EXTRA",
    "flights=AA6:JFK:LHR%2C%20BA7:LHR:JFK",
    "flights=AA6:JFK:LHR,BA7:LHR:JFK,DL8:ATL:LAX,UA9:SFO:EWR,AF10:CDG:JFK,LH11:FRA:LOS,VS12:LHR:LOS",
    "flights=AA6:JFK:LHR,AA6:JFK:LHR",
    "flights=AA6:JFK:LHR&flights=BA7:LHR:JFK",
    "flights=AA6:JFK:LHR&extra=true",
  ]) {
    const response = await handler(request(query));
    const body = await response.json();

    assert.equal(response.status, 400, query);
    assert.equal(body.ok, false);
    assert.equal(body.error.code, "invalid_query");
  }
  assert.equal(fetchCount, 0);

  const parsed = parseRecentPerformanceQuery(
    new URL(
      "https://portfolio.test/api/skyeta/recent-performance?flights=AA6:JFK:LHR,AA6:LAX:LHR",
    ),
  );
  assert.deepEqual(parsed, {
    ok: true,
    routes: [
      { flightIata: "AA6", originIata: "JFK", destinationIata: "LHR" },
      { flightIata: "AA6", originIata: "LAX", destinationIata: "LHR" },
    ],
  });
});

test("recent-performance filters reused flight numbers by route and derives missing delays", async () => {
  const secret = "server-only-key-that-must-not-leak";
  const handler = recentHandler({
    getApiKey: () => secret,
    fetchImpl: async (input, init) => {
      const url = new URL(input);
      assert.equal(url.origin, "https://airlabs.co");
      assert.equal(url.pathname, "/api/v10/historical");
      assert.equal(url.searchParams.get("flight_iata"), "AA6");
      assert.equal(url.searchParams.get("api_key"), secret);
      assert.deepEqual([...url.searchParams.keys()].sort(), [
        "api_key",
        "flight_iata",
      ]);
      assert.equal(init.method, "GET");
      assert.equal(init.headers.Accept, "application/json");
      assert.equal(init.redirect, "manual");
      assert.ok(init.signal instanceof AbortSignal);

      return Response.json([
        {
          dep_iata: "JFK",
          arr_iata: "LHR",
          dep_time: "2026-05-05 17:42",
          arr_time: "2026-05-06 06:00",
          dep_delayed: 20,
          arr_delayed: 0,
          status: "landed",
          raw_private_field: secret,
        },
        {
          dep_iata: "JFK",
          arr_iata: "LHR",
          dep_time: "2026-05-03 17:42",
          dep_actual: "2026-05-03 17:45",
          arr_time: "2026-05-04 06:00",
          arr_actual: "2026-05-04 06:18",
          dep_delayed: null,
          arr_delayed: null,
        },
        {
          dep_iata: "JFK",
          arr_iata: "LHR",
          dep_time: "2026-05-04 17:42:00",
          dep_actual: "2026-05-04 17:42:00",
          arr_time: "2026-05-05 06:00:00",
          arr_actual: "2026-05-05 05:50:00",
          dep_delayed: null,
          arr_delayed: null,
        },
        {
          dep_iata: "JFK",
          arr_iata: "LHR",
          dep_time: "2026-05-02 17:42",
          arr_time: "2026-05-03 06:00",
          dep_delayed: 90,
          arr_delayed: 120,
          status: "cancelled",
        },
        {
          dep_iata: "LAX",
          arr_iata: "LHR",
          dep_time: "2026-05-02 17:42",
          arr_time: "2026-05-03 12:00",
          dep_delayed: 90,
          arr_delayed: 120,
        },
        {
          dep_time: "2026-05-01 17:42",
          arr_time: "2026-05-02 06:00",
          dep_delayed: 300,
          arr_delayed: 300,
        },
      ]);
    },
  });

  const response = await handler(request("flights=AA6:JFK:LHR"));
  const responseText = await response.text();
  const body = JSON.parse(responseText);

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.deepEqual(body, {
    ok: true,
    partial: false,
    source: RECENT_PERFORMANCE_SOURCE,
    coverageNotice: RECENT_PERFORMANCE_COVERAGE_NOTICE,
    flights: [
      {
        flightIata: "AA6",
        originIata: "JFK",
        destinationIata: "LHR",
        observations: 3,
        arrivalDelayKnown: 3,
        arrived15PlusLate: 1,
        arrived30PlusLate: 0,
        arrived60PlusLate: 0,
        arrival15Plus: historicalDelayProbability(1, 3),
        arrival30Plus: historicalDelayProbability(0, 3),
        arrival60Plus: historicalDelayProbability(0, 3),
        typicalLateArrivalMinutes: 18,
        arrivalDataSufficient: false,
        arrivalSampleConfidence: "insufficient",
        departureDelayKnown: 3,
        departed15PlusLate: 1,
        earliestObservedDate: "2026-05-03",
        latestObservedDate: "2026-05-05",
      },
    ],
    unavailable: [],
  });
  assert.doesNotMatch(responseText, /server-only-key|raw_private_field|status/);
  assert.equal("prediction" in body.flights[0], false);
  assert.equal("probability" in body.flights[0], false);
});

test("historical outlook calculates three thresholds, typical delay and honest confidence", () => {
  const route = {
    flightIata: "BA74",
    originIata: "LOS",
    destinationIata: "LHR",
  };
  const rows = [0, 14, 15, 30, 60, 90].map((arrDelayed, index) => ({
    dep_iata: "LOS",
    arr_iata: "LHR",
    dep_time: `2026-06-${String(index + 1).padStart(2, "0")} 09:00`,
    arr_time: `2026-06-${String(index + 1).padStart(2, "0")} 15:00`,
    arr_delayed: arrDelayed,
    status: "landed",
  }));

  const evidence = aggregateHistoricalRows(route, rows);
  assert.equal(evidence.arrivalDelayKnown, 6);
  assert.equal(evidence.arrived15PlusLate, 4);
  assert.equal(evidence.arrived30PlusLate, 3);
  assert.equal(evidence.arrived60PlusLate, 2);
  assert.equal(evidence.arrival15Plus.laplaceProbabilityPercent, 62.5);
  assert.equal(evidence.arrival30Plus.laplaceProbabilityPercent, 50);
  assert.equal(evidence.arrival60Plus.laplaceProbabilityPercent, 37.5);
  assert.equal(evidence.typicalLateArrivalMinutes, 45);
  assert.equal(evidence.arrivalDataSufficient, true);
  assert.equal(evidence.arrivalSampleConfidence, "limited");
  assert.ok(
    evidence.arrival15Plus.wilson95LowPercent <
      evidence.arrival15Plus.wilson95HighPercent,
  );
});

test("Laplace smoothing does not publish absolute probabilities from small samples", () => {
  assert.deepEqual(historicalDelayProbability(0, 0), {
    observedLate: 0,
    laplaceProbabilityPercent: null,
    wilson95LowPercent: null,
    wilson95HighPercent: null,
  });
  assert.equal(
    historicalDelayProbability(0, 5).laplaceProbabilityPercent,
    14.3,
  );
  assert.equal(
    historicalDelayProbability(5, 5).laplaceProbabilityPercent,
    85.7,
  );
});

test("derived delays reject invalid timestamps and differences beyond safe bounds", () => {
  const route = {
    flightIata: "AA6",
    originIata: "JFK",
    destinationIata: "LHR",
  };
  const evidence = aggregateHistoricalRows(route, [
    {
      dep_iata: "JFK",
      arr_iata: "LHR",
      dep_time: "2026-05-01 10:00",
      arr_time: "2026-05-01 22:00",
      arr_actual: "2026-05-03 22:00",
    },
    {
      dep_iata: "JFK",
      arr_iata: "LHR",
      dep_time: "2026-05-02 10:00",
      arr_time: "2026-02-30 22:00",
      arr_actual: "2026-03-02 22:00",
    },
    {
      dep_iata: "JFK",
      arr_iata: "LHR",
      dep_time: "2026-05-03 10:00",
      arr_time: "2026-05-03 23:55",
      arr_actual: "2026-05-04 00:05",
    },
  ]);
  assert.equal(evidence.observations, 3);
  assert.equal(evidence.arrivalDelayKnown, 1);
  assert.equal(evidence.arrived15PlusLate, 0);
});

test("recent-performance cache and in-flight keys include the complete route", async () => {
  let clock = 1_000;
  let fetchCount = 0;
  const handler = recentHandler({
    getApiKey: () => "server-only-key",
    now: () => clock,
    cacheTtlMs: 1_000,
    fetchImpl: async () => {
      fetchCount += 1;
      return Response.json([]);
    },
  });

  await handler(request("flights=AA6:JFK:LHR"));
  clock = 1_500;
  await handler(request("flights=AA6:JFK:LHR"));
  assert.equal(fetchCount, 1);

  await handler(request("flights=AA6:LAX:LHR"));
  assert.equal(fetchCount, 2);

  clock = 2_001;
  await handler(request("flights=AA6:JFK:LHR"));
  assert.equal(fetchCount, 3);
});

test("recent-performance returns successful routes when another provider lookup fails", async () => {
  const handler = recentHandler({
    getApiKey: () => "server-only-key",
    fetchImpl: async (input) => {
      const flight = new URL(input).searchParams.get("flight_iata");
      if (flight === "BA7") return new Response("unavailable", { status: 503 });
      return Response.json({
        response: [
          {
            dep_iata: "JFK",
            arr_iata: "LHR",
            dep_time: "2026-05-05 17:42",
            arr_time: "2026-05-06 06:00",
            arr_delayed: 0,
          },
        ],
      });
    },
  });

  const response = await handler(
    request("flights=AA6:JFK:LHR,BA7:LHR:JFK"),
  );
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(body.ok, true);
  assert.equal(body.partial, true);
  assert.deepEqual(body.flights.map((flight) => flight.flightIata), ["AA6"]);
  assert.deepEqual(body.unavailable, [
    { flightIata: "BA7", originIata: "LHR", destinationIata: "JFK" },
  ]);
});

test("recent-performance rate limiting stops before provider calls", async () => {
  const database = inMemoryQuotaDatabase();
  let fetchCount = 0;
  const handler = createRecentPerformanceHandler({
    getApiKey: () => "server-only-key",
    getDatabase: () => database,
    now: () => 1_000_000,
    fetchImpl: async () => {
      fetchCount += 1;
      return Response.json([]);
    },
  });

  for (let index = 0; index < 6; index += 1) {
    const response = await handler(
      request("flights=AA6:JFK:LHR", "203.0.113.10"),
    );
    assert.equal(response.status, 200);
  }
  const limited = await handler(
    request("flights=AA6:JFK:LHR", "203.0.113.10"),
  );
  const body = await limited.json();
  assert.equal(limited.status, 429);
  assert.equal(limited.headers.get("Retry-After"), "600");
  assert.equal(body.error.code, "rate_limited");
  assert.equal(fetchCount, 1);
});

test("recent-performance global quota applies even when client identity is absent", async () => {
  const database = inMemoryQuotaDatabase();
  const handler = createRecentPerformanceHandler({
    getApiKey: () => "server-only-key",
    getDatabase: () => database,
    now: () => 5_000_000,
    fetchImpl: async () => Response.json([]),
  });

  for (let index = 0; index < 30; index += 1) {
    const response = await handler(request("flights=AA6:JFK:LHR"));
    assert.equal(response.status, 200, index);
  }
  const limited = await handler(request("flights=AA6:JFK:LHR"));
  assert.equal(limited.status, 429);
  assert.equal((await limited.json()).error.code, "rate_limited");
});

test("recent-performance handles missing configuration and provider failures safely", async () => {
  const unconfigured = recentHandler({
    getApiKey: () => undefined,
    fetchImpl: async () => {
      throw new Error("fetch must not run");
    },
  });
  const missingResponse = await unconfigured(
    request("flights=AA6:JFK:LHR"),
  );
  assert.equal(missingResponse.status, 503);
  assert.equal((await missingResponse.json()).error.code, "not_configured");

  const rejected = recentHandler({
    getApiKey: () => "server-only-key",
    fetchImpl: async () =>
      new Response("provider secret detail", {
        status: 302,
        headers: { location: "https://attacker.test/" },
      }),
  });
  const rejectedResponse = await rejected(request("flights=AA6:JFK:LHR"));
  const rejectedText = await rejectedResponse.text();
  assert.equal(rejectedResponse.status, 502);
  assert.equal(JSON.parse(rejectedText).error.code, "upstream_unavailable");
  assert.doesNotMatch(rejectedText, /provider secret|attacker/);

  let providerCalled = false;
  const noQuotaStorage = createRecentPerformanceHandler({
    getApiKey: () => "server-only-key",
    getDatabase: async () => {
      throw new Error("private storage detail");
    },
    fetchImpl: async () => {
      providerCalled = true;
      return Response.json([]);
    },
  });
  const storageResponse = await noQuotaStorage(
    request("flights=AA6:JFK:LHR"),
  );
  const storageText = await storageResponse.text();
  assert.equal(storageResponse.status, 503);
  assert.equal(JSON.parse(storageText).error.code, "service_unavailable");
  assert.equal(providerCalled, false);
  assert.doesNotMatch(storageText, /private storage detail/);
});

test("recent-performance timeout remains active while the response body is read", async () => {
  const handler = recentHandler({
    getApiKey: () => "server-only-key",
    timeoutMs: 5,
    fetchImpl: async (_input, init) =>
      new Response(
        new ReadableStream({
          start(controller) {
            init.signal.addEventListener(
              "abort",
              () => controller.error(new DOMException("Aborted", "AbortError")),
              { once: true },
            );
          },
        }),
        { headers: { "content-type": "application/json" } },
      ),
  });

  const response = await handler(request("flights=AA6:JFK:LHR"));
  const body = await response.json();
  assert.equal(response.status, 504);
  assert.equal(body.error.code, "upstream_timeout");
});

test("recent-performance rejects oversized and provider-error payloads", async () => {
  for (const fetchImpl of [
    async () =>
      new Response("[]", {
        headers: { "content-length": "999999999" },
      }),
    async () =>
      Response.json({
        error: { code: "month_limit_exceeded", detail: "private detail" },
      }),
  ]) {
    const handler = recentHandler({
      getApiKey: () => "server-only-key",
      fetchImpl,
    });
    const response = await handler(request("flights=AA6:JFK:LHR"));
    const text = await response.text();
    assert.equal(response.status, 502);
    assert.equal(JSON.parse(text).error.code, "upstream_unavailable");
    assert.doesNotMatch(text, /month_limit|private detail/);
  }
});
