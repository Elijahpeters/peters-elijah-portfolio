import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  NOAA_LIVE_CONTEXT_SOURCE,
  buildNoaaUrl,
  createLiveContextHandler,
  parseLiveContextQuery,
} from "../app/api/skyeta/live-context/live-context.ts";
import {
  assessForecastCoverage,
  createLiveContextRequestCache,
  forecastCoverageCopy,
  retryCountdownLabel,
  scheduledOccurrences,
  selectLiveContextAirports,
} from "../app/skyeta/components/live-context-client.ts";

const allowUpstream = () => ({ allowed: true, retryAfterSeconds: 0 });

function request(query) {
  return new Request(`https://portfolio.test/api/skyeta/live-context?${query}`);
}

function segment(id, origin, destination, departingAt, arrivingAt) {
  return {
    id,
    origin: { iataCode: origin },
    destination: { iataCode: destination },
    departingAt,
    arrivingAt,
  };
}

function controllableQuotaDatabase() {
  const quotas = new Map();
  let failed = false;
  const statement = (sql) => {
    let values = [];
    return {
      bind(...input) {
        values = input;
        return this;
      },
      async first() {
        if (failed) throw new Error("D1 unavailable");
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
        if (failed) throw new Error("D1 unavailable");
        return { success: true, meta: { changes: 0 } };
      },
      async all() {
        if (failed) throw new Error("D1 unavailable");
        return { success: true, results: [] };
      },
    };
  };
  return {
    prepare: statement,
    async batch(statements) {
      if (failed) throw new Error("D1 unavailable");
      return statements.map(() => ({ success: true }));
    },
    setFailed(value) {
      failed = value;
    },
  };
}

test("live-context query accepts only one to four unique uppercase IATA codes", async () => {
  let fetchCount = 0;
  const handler = createLiveContextHandler({
    fetchImpl: async () => {
      fetchCount += 1;
      throw new Error("fetch must not run");
    },
  });

  for (const query of [
    "",
    "airports=",
    "airports=jfk",
    "airports=JFK%2C%20LHR",
    "airports=JFK,JFK",
    "airports=JFK,LHR,LOS,LAX,SFO",
    "airports=JFK&airports=LHR",
    "airports=JFK&url=https://example.com",
  ]) {
    const response = await handler(request(query));
    const body = await response.json();
    assert.equal(response.status, 400, query);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(body.ok, false);
    assert.equal(body.error.code, "invalid_query");
  }
  assert.equal(fetchCount, 0);

  assert.deepEqual(
    parseLiveContextQuery(
      new URL(
        "https://portfolio.test/api/skyeta/live-context?airports=LOS,LHR,JFK",
      ),
    ),
    { ok: true, airports: ["LOS", "LHR", "JFK"] },
  );
});

test("AWC URLs are fixed to the allowlisted aviation-weather endpoints", () => {
  const metar = buildNoaaUrl("metar", ["KJFK", "EGLL"]);
  assert.equal(metar.origin, "https://aviationweather.gov");
  assert.equal(metar.pathname, "/api/data/metar");
  assert.equal(metar.searchParams.get("ids"), "EGLL,KJFK");
  assert.equal(metar.searchParams.get("format"), "json");
  assert.equal(metar.searchParams.get("hours"), "2");

  const taf = buildNoaaUrl("taf", ["DNMM"]);
  assert.equal(taf.origin, "https://aviationweather.gov");
  assert.equal(taf.pathname, "/api/data/taf");
  assert.equal(taf.searchParams.get("ids"), "DNMM");
  assert.equal(taf.searchParams.get("format"), "json");
  assert.equal(taf.searchParams.has("hours"), false);
});

test("the weather mapping pins both reviewed catalogue sources", async () => {
  const [mappingText, generator] = await Promise.all([
    readFile(
      new URL(
        "../app/lib/skyeta/aviation-weather-airports.json",
        import.meta.url,
      ),
      "utf8",
    ),
    readFile(
      new URL("../scripts/build-skyeta-global-airports.mjs", import.meta.url),
      "utf8",
    ),
  ]);
  const mapping = JSON.parse(mappingText);

  assert.equal(mapping.schemaVersion, 1);
  assert.deepEqual(mapping.provenance, {
    sourceName: "NOAA Aviation Weather Center station catalogue",
    sourceUrl:
      "https://www.connect.aviationweather.gov/data/cache/stations.cache.json.gz",
    catalogueVersion: "2026-08-09",
    compressedBytes: 355855,
    compressedSha256:
      "bac107a0b678647efd8591d594ed1eb1de817d185365d0f0b8fe1f38a59a1723",
    uncompressedBytes: 1939590,
    sourceRecords: 9873,
    airportIdentitySource: {
      name: "mborsetti/airportsdata airports.csv",
      url: "https://raw.githubusercontent.com/mborsetti/airportsdata/671fa36e373faa3068e15bb453dac96a41087e19/airportsdata/airports.csv",
      commit: "671fa36e373faa3068e15bb453dac96a41087e19",
      bytes: 3076463,
      sha256:
        "fca6a89a336c154e86174ba933372de118d15e09a1cfa01559e0b9fd2b1e7fe0",
    },
    validatedMappings: 4719,
    validation:
      "Exact unambiguous IATA/ICAO pair in airportsdata and the pinned AWC catalogue; METAR/TAF capability copied from AWC siteType.",
  });
  assert.equal(mapping.airports.length, 4719);
  const byIata = new Map(mapping.airports.map((row) => [row[0], row]));
  assert.deepEqual(byIata.get("LOS"), ["LOS", "DNMM", true, true]);
  assert.deepEqual(byIata.get("LHR"), ["LHR", "EGLL", true, true]);
  assert.deepEqual(byIata.get("JFK"), ["JFK", "KJFK", true, true]);
  assert.deepEqual(byIata.get("LAX"), ["LAX", "KLAX", true, true]);
  assert.equal(new Set(mapping.airports.map((row) => row[0])).size, 4719);
  assert.equal(
    mapping.airports.every(
      (row) =>
        row.length === 4 &&
        /^[A-Z]{3}$/.test(row[0]) &&
        /^[A-Z0-9]{4}$/.test(row[1]) &&
        (row[2] === true || row[3] === true),
    ),
    true,
  );
  assert.match(generator, /createHash\("sha256"\)/);
  assert.match(generator, /AWC_STATIONS_PIN\.compressedSha256/);
  assert.match(generator, /AWC_STATIONS_PIN\.compressedBytes/);
  assert.match(generator, /671fa36e373faa3068e15bb453dac96a41087e19/);
  assert.match(generator, /AIRPORTS_SOURCE_PIN\.bytes/);
  assert.match(generator, /AIRPORTS_SOURCE_PIN\.sha256/);
  assert.doesNotMatch(
    generator,
    /raw\.githubusercontent\.com\/mborsetti\/airportsdata\/main\//,
  );
});

test("live-context maps global airports and returns only sanitized cited facts", async () => {
  const hidden = "provider-private-field-must-not-leak";
  const calls = [];
  const handler = createLiveContextHandler({
    now: () => Date.parse("2026-08-09T10:00:00Z"),
    userAgent: "SkyETA test agent",
    reserveUpstreamRequest: allowUpstream,
    fetchImpl: async (input, init) => {
      const url = new URL(input);
      calls.push(url);
      assert.equal(url.origin, "https://aviationweather.gov");
      assert.equal(url.searchParams.get("ids"), "DNMM,EGLL,KJFK");
      assert.equal(init.method, "GET");
      assert.equal(init.cache, "no-store");
      assert.equal(init.redirect, "error");
      assert.equal(init.headers.Accept, "application/json");
      assert.equal(init.headers["User-Agent"], "SkyETA test agent");
      assert.ok(init.signal instanceof AbortSignal);

      if (url.pathname === "/api/data/metar") {
        return Response.json([
          {
            icaoId: "DNMM",
            obsTime: "2026-08-09T09:30:00Z",
            rawOb: "DNMM 090930Z 22008KT 9999 SCT018 27/23 Q1012",
            fltCat: "MVFR",
            temp: 27,
            dewp: 23,
            wdir: 220,
            wspd: 8,
            visib: "6+",
            hidden,
          },
          {
            icaoId: "EGLL",
            obsTime: 1_786_267_200,
            rawOb: "EGLL 090920Z 25012KT 9999 FEW025 20/12 Q1018",
            fltCat: "VFR",
            temp: 20,
            wdir: 250,
            wspd: 12,
            wgst: 19,
            visib: 10,
          },
          {
            icaoId: "XXXX",
            obsTime: "2026-08-09T09:30:00Z",
            rawOb: hidden,
          },
        ]);
      }

      return Response.json([
        {
          icaoId: "EGLL",
          issueTime: "2026-08-09T08:00:00Z",
          validTimeFrom: "2026-08-09T09:00:00Z",
          validTimeTo: "2026-08-10T12:00:00Z",
          rawTAF: "TAF EGLL 090800Z 0909/1012 25012KT 9999 SCT025",
          hidden,
        },
        {
          icaoId: "KJFK",
          issueTime: "2026-08-09T08:00:00Z",
          validTimeFrom: "2026-08-09T09:00:00Z",
          validTimeTo: "2026-08-10T12:00:00Z",
          rawTAF: "TAF KJFK 090800Z 0909/1012 18010KT P6SM SCT030",
        },
      ]);
    },
  });

  const response = await handler(request("airports=LOS,LHR,JFK"));
  const responseText = await response.text();
  const body = JSON.parse(responseText);

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.equal(calls.length, 2);
  assert.deepEqual(body.source, NOAA_LIVE_CONTEXT_SOURCE);
  assert.deepEqual(
    body.airports.map(({ iata, icao }) => ({ iata, icao })),
    [
      { iata: "LOS", icao: "DNMM" },
      { iata: "LHR", icao: "EGLL" },
      { iata: "JFK", icao: "KJFK" },
    ],
  );
  assert.deepEqual(body.airports[0].observation, {
    observedAt: "2026-08-09T09:30:00.000Z",
    rawText: "DNMM 090930Z 22008KT 9999 SCT018 27/23 Q1012",
    flightCategory: "MVFR",
    temperatureC: 27,
    dewpointC: 23,
    windDirectionDegrees: 220,
    windSpeedKnots: 8,
    windGustKnots: null,
    visibilityMiles: "6+",
  });
  assert.equal(body.airports[0].forecast, null);
  assert.deepEqual(body.airports[0].datasetFetchedAt, {
    metar: "2026-08-09T10:00:00.000Z",
    taf: "2026-08-09T10:00:00.000Z",
  });
  assert.equal(body.airports[1].observation.flightCategory, "VFR");
  assert.equal(body.airports[1].forecast.rawText.startsWith("TAF EGLL"), true);
  assert.equal(body.airports[2].observation, null);
  assert.equal(body.airports[2].forecast.rawText.startsWith("TAF KJFK"), true);
  assert.equal(
    new URL(body.airports[0].sourceLinks.observation).origin,
    "https://aviationweather.gov",
  );
  assert.doesNotMatch(responseText, /provider-private-field|hidden/);
  assert.doesNotMatch(responseText, /retrievedAt/);
});

test("per-station caches reuse overlapping routes and preserve each dataset fetch time", async () => {
  let clock = Date.parse("2026-08-09T10:00:00Z");
  const calls = [];
  const handler = createLiveContextHandler({
    now: () => clock,
    metarCacheTtlMs: 1_000,
    tafCacheTtlMs: 10_000,
    reserveUpstreamRequest: allowUpstream,
    fetchImpl: async (input) => {
      const url = new URL(input);
      calls.push({
        kind: url.pathname.endsWith("metar") ? "metar" : "taf",
        ids: url.searchParams.get("ids"),
      });
      return Response.json([]);
    },
  });

  const first = await handler(request("airports=JFK,LHR"));
  assert.equal(first.status, 200);
  assert.equal(calls.length, 2);
  assert.deepEqual(new Set(calls.map((call) => call.ids)), new Set(["EGLL,KJFK"]));

  clock += 500;
  const second = await handler(request("airports=LHR,LOS"));
  const secondBody = await second.json();
  assert.equal(second.status, 200);
  assert.equal(calls.length, 4);
  assert.deepEqual(calls.slice(2).map((call) => call.ids), ["DNMM", "DNMM"]);
  assert.deepEqual(secondBody.airports[0].datasetFetchedAt, {
    metar: "2026-08-09T10:00:00.000Z",
    taf: "2026-08-09T10:00:00.000Z",
  });
  assert.deepEqual(secondBody.airports[1].datasetFetchedAt, {
    metar: "2026-08-09T10:00:00.500Z",
    taf: "2026-08-09T10:00:00.500Z",
  });

  clock += 501;
  await handler(request("airports=LHR,LOS"));
  assert.equal(calls.length, 5);
  assert.deepEqual(calls[4], { kind: "metar", ids: "EGLL" });
});

test("concurrent identical requests share one AWC request per dataset", async () => {
  let fetchCount = 0;
  const handler = createLiveContextHandler({
    allowLocalLimiterFallback: true,
    getDatabase: async () => {
      throw new Error("D1 intentionally unavailable in local test");
    },
    fetchImpl: async () => {
      fetchCount += 1;
      await new Promise((resolve) => setTimeout(resolve, 5));
      return Response.json([]);
    },
  });

  const responses = await Promise.all([
    handler(request("airports=JFK,LHR")),
    handler(request("airports=JFK,LHR")),
  ]);
  assert.deepEqual(responses.map((response) => response.status), [200, 200]);
  assert.equal(fetchCount, 2);
});

test("default handlers fail closed when the initial D1 binding is unavailable", async () => {
  let fetchCount = 0;
  const options = {
    getDatabase: async () => {
      throw new Error("D1 binding unavailable");
    },
    fetchImpl: async () => {
      fetchCount += 1;
      return new Response(null, { status: 204 });
    },
  };
  const firstHandler = createLiveContextHandler(options);
  const secondHandler = createLiveContextHandler(options);

  const responses = await Promise.all([
    firstHandler(request("airports=JFK")),
    secondHandler(request("airports=LHR")),
  ]);
  assert.deepEqual(responses.map((response) => response.status), [429, 429]);
  assert.deepEqual(
    responses.map((response) => response.headers.get("retry-after")),
    ["60", "60"],
  );
  assert.equal(fetchCount, 0);
});

test("shared D1 quota spans handlers and fails closed after an operational outage", async () => {
  let clock = Date.parse("2026-08-09T10:00:00Z");
  let fetchCount = 0;
  const database = controllableQuotaDatabase();
  const options = {
    now: () => clock,
    getDatabase: async () => database,
    fetchImpl: async () => {
      fetchCount += 1;
      return new Response(null, { status: 204 });
    },
  };
  const firstHandler = createLiveContextHandler(options);
  const secondHandler = createLiveContextHandler(options);

  assert.equal((await firstHandler(request("airports=JFK"))).status, 200);
  assert.equal(fetchCount, 2);
  const otherIsolate = await secondHandler(request("airports=LHR"));
  assert.equal(otherIsolate.status, 429);
  assert.equal(fetchCount, 2);

  clock += 61_000;
  assert.equal((await firstHandler(request("airports=LHR"))).status, 200);
  assert.equal(fetchCount, 4);
  database.setFailed(true);
  clock += 1_000;
  const outage = await firstHandler(request("airports=LOS"));
  assert.equal(outage.status, 429);
  assert.equal(outage.headers.get("retry-after"), "60");
  assert.equal(fetchCount, 4);
});

test("server station cache remains bounded and refetches the oldest evicted station", async () => {
  const calls = [];
  const handler = createLiveContextHandler({
    maxCacheEntries: 4,
    metarCacheTtlMs: 100_000,
    tafCacheTtlMs: 100_000,
    reserveUpstreamRequest: allowUpstream,
    fetchImpl: async (input) => {
      const url = new URL(input);
      calls.push({
        kind: url.pathname.endsWith("metar") ? "metar" : "taf",
        ids: url.searchParams.get("ids"),
      });
      return new Response(null, { status: 204 });
    },
  });

  for (const iata of ["JFK", "LHR", "LOS"]) {
    assert.equal((await handler(request(`airports=${iata}`))).status, 200);
  }
  assert.equal(calls.length, 6);
  assert.equal((await handler(request("airports=JFK"))).status, 200);
  assert.equal(calls.length, 8);
  assert.deepEqual(
    new Set(calls.slice(-2).map((call) => `${call.kind}:${call.ids}`)),
    new Set(["metar:KJFK", "taf:KJFK"]),
  );
});

test("dataset limiter applies across airport combinations while cached facts remain usable", async () => {
  let clock = Date.parse("2026-08-09T10:00:00Z");
  let fetchCount = 0;
  const handler = createLiveContextHandler({
    now: () => clock,
    allowLocalLimiterFallback: true,
    getDatabase: async () => {
      throw new Error("D1 intentionally unavailable in local test");
    },
    fetchImpl: async (input) => {
      fetchCount += 1;
      const url = new URL(input);
      const ids = url.searchParams.get("ids").split(",");
      return Response.json(
        ids.map((icaoId) =>
          url.pathname.endsWith("metar")
            ? {
                icaoId,
                obsTime: "2026-08-09T09:30:00Z",
                rawOb: `${icaoId} test observation`,
              }
            : {
                icaoId,
                issueTime: "2026-08-09T09:00:00Z",
                rawTAF: `TAF ${icaoId} test forecast`,
              },
        ),
      );
    },
  });

  assert.equal((await handler(request("airports=JFK"))).status, 200);
  assert.equal(fetchCount, 2);

  clock += 1_000;
  const mixed = await handler(request("airports=JFK,LHR"));
  const mixedBody = await mixed.json();
  assert.equal(mixed.status, 200);
  assert.equal(mixed.headers.get("cache-control"), "no-store");
  assert.equal(mixed.headers.get("retry-after"), "59");
  assert.equal(mixedBody.partial, true);
  assert.equal(mixedBody.retryAfterSeconds, 59);
  assert.equal(mixedBody.airports[0].observation.rawText.includes("KJFK"), true);
  assert.equal(mixedBody.airports[1].observation, null);
  assert.equal(fetchCount, 2);

  const uncached = await handler(request("airports=LHR"));
  assert.equal(uncached.status, 429);
  assert.equal(uncached.headers.get("retry-after"), "59");
  assert.equal((await uncached.json()).error.code, "upstream_rate_limited");
  assert.equal(fetchCount, 2);

  clock += 60_000;
  assert.equal((await handler(request("airports=LHR"))).status, 200);
  assert.equal(fetchCount, 4);
});

test("live-context keeps a one-dataset AWC failure factual and independent", async () => {
  const handler = createLiveContextHandler({
    now: () => Date.parse("2026-08-09T10:00:00Z"),
    reserveUpstreamRequest: allowUpstream,
    fetchImpl: async (input) => {
      const url = new URL(input);
      if (url.pathname.endsWith("/metar")) {
        return new Response("upstream unavailable", { status: 503 });
      }
      return Response.json([
        {
          icaoId: "KJFK",
          issueTime: "2026-08-09T08:00:00Z",
          rawTAF: "TAF KJFK 090800Z 0909/1012 18010KT P6SM SCT030",
        },
      ]);
    },
  });

  const response = await handler(request("airports=JFK"));
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(body.partial, true);
  assert.equal(body.retryAfterSeconds, 0);
  assert.deepEqual(body.unavailable, ["metar"]);
  assert.equal(body.airports[0].observation, null);
  assert.equal(body.airports[0].forecast.rawText.startsWith("TAF KJFK"), true);
});

test("AWC 204 is valid no-data and is cached with the actual dataset check time", async () => {
  let fetchCount = 0;
  const handler = createLiveContextHandler({
    now: () => Date.parse("2026-08-09T10:00:00Z"),
    reserveUpstreamRequest: allowUpstream,
    fetchImpl: async () => {
      fetchCount += 1;
      return new Response(null, { status: 204 });
    },
  });

  const first = await handler(request("airports=LOS"));
  const body = await first.json();
  assert.equal(first.status, 200);
  assert.equal(body.airports[0].observation, null);
  assert.equal(body.airports[0].forecast, null);
  assert.deepEqual(body.airports[0].datasetFetchedAt, {
    metar: "2026-08-09T10:00:00.000Z",
    taf: "2026-08-09T10:00:00.000Z",
  });
  assert.equal((await handler(request("airports=LOS"))).status, 200);
  assert.equal(fetchCount, 2);
});

test("malformed and oversized AWC responses fail closed without leaking bodies", async (t) => {
  await t.test("malformed JSON", async () => {
    const handler = createLiveContextHandler({
      reserveUpstreamRequest: allowUpstream,
      fetchImpl: async () =>
        new Response('{"private":"do-not-leak"', {
          headers: { "Content-Type": "application/json" },
        }),
    });
    const response = await handler(request("airports=JFK"));
    const text = await response.text();
    assert.equal(response.status, 502);
    assert.match(text, /upstream_unavailable/);
    assert.doesNotMatch(text, /do-not-leak/);
  });

  await t.test("oversized body", async () => {
    const handler = createLiveContextHandler({
      reserveUpstreamRequest: allowUpstream,
      fetchImpl: async () =>
        new Response("[]", {
          headers: {
            "Content-Type": "application/json",
            "Content-Length": "300000",
          },
        }),
    });
    const response = await handler(request("airports=JFK"));
    assert.equal(response.status, 502);
    assert.equal((await response.json()).error.code, "upstream_unavailable");
  });

  await t.test("oversized streaming body without Content-Length", async () => {
    const handler = createLiveContextHandler({
      reserveUpstreamRequest: allowUpstream,
      fetchImpl: async () =>
        new Response(
          new ReadableStream({
            start(controller) {
              for (let index = 0; index < 5; index += 1) {
                controller.enqueue(new Uint8Array(64 * 1_024).fill(97));
              }
              controller.close();
            },
          }),
          { headers: { "Content-Type": "application/json" } },
        ),
    });
    const response = await handler(request("airports=JFK"));
    assert.equal(response.status, 502);
    assert.equal((await response.json()).error.code, "upstream_unavailable");
  });
});

test("two aborted AWC calls become one bounded timeout response", async () => {
  const handler = createLiveContextHandler({
    timeoutMs: 5,
    reserveUpstreamRequest: allowUpstream,
    fetchImpl: async (_input, init) =>
      new Promise((_resolve, reject) => {
        init.signal.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      }),
  });

  const response = await handler(request("airports=JFK"));
  const body = await response.json();
  assert.equal(response.status, 504);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(body.error.code, "upstream_timeout");
});

test("airport selection prioritizes the first origin and final destination", () => {
  const segments = [
    segment("1", "LOS", "ACC", "2026-09-01T08:00:00Z", "2026-09-01T09:00:00Z"),
    segment("2", "ACC", "CDG", "2026-09-01T10:00:00Z", "2026-09-01T16:00:00Z"),
    segment("3", "CDG", "JFK", "2026-09-01T18:00:00Z", "2026-09-02T02:00:00Z"),
    segment("4", "JFK", "LAX", "2026-09-02T04:00:00Z", "2026-09-02T10:00:00Z"),
  ];
  assert.deepEqual(selectLiveContextAirports(segments), {
    codes: ["LOS", "LAX", "ACC", "CDG"],
    limited: true,
    totalUnique: 5,
  });
});

test("round trips assess every scheduled occurrence without guessing timezone offsets", () => {
  const segments = [
    segment("out", "LOS", "LHR", "2026-09-01T08:00:00Z", "2026-09-01T14:00:00Z"),
    segment("back", "LHR", "LOS", "2026-09-05T10:00:00", "2026-09-05T16:00:00Z"),
  ];
  const occurrences = scheduledOccurrences(segments, "LHR");
  assert.deepEqual(occurrences, [
    { kind: "arrival", at: "2026-09-01T14:00:00Z", segmentId: "out" },
    { kind: "departure", at: "2026-09-05T10:00:00", segmentId: "back" },
  ]);
  const coverage = assessForecastCoverage(
    "2026-09-01T12:00:00Z",
    "2026-09-02T12:00:00Z",
    occurrences,
  );
  assert.deepEqual(coverage, {
    total: 2,
    comparable: 1,
    covered: 1,
    uncomparable: 1,
    validityAvailable: true,
  });
  assert.equal(
    forecastCoverageCopy(coverage),
    "It covers all 1 comparable scheduled occurrence. 1 other scheduled time could not be compared safely because the timezone offset is missing.",
  );
});

test("retry countdown copy is plain-language and bounded", () => {
  assert.equal(
    retryCountdownLabel(59),
    "A fresh live-data check will be available in 59 seconds.",
  );
  assert.equal(
    retryCountdownLabel(61),
    "A fresh live-data check will be available in 1 minute 1 second.",
  );
  assert.equal(
    retryCountdownLabel(0),
    "A fresh live-data check is available now.",
  );
  assert.equal(
    retryCountdownLabel(Number.POSITIVE_INFINITY),
    "A fresh live-data check is available now.",
  );
  assert.equal(
    retryCountdownLabel(99_999),
    "A fresh live-data check will be available in 60 minutes.",
  );
});

test("browser request cache times out safely, removes failures and permits retry", async () => {
  let fetchCount = 0;
  const cache = createLiveContextRequestCache({
    parse: (value) =>
      value && typeof value === "object" && value.ok === true ? value : null,
    timeoutMs: 5,
    fetchImpl: async (_input, init) => {
      fetchCount += 1;
      if (fetchCount === 1) {
        return new Promise((_resolve, reject) => {
          init.signal.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        });
      }
      return Response.json({ ok: true, attempt: fetchCount });
    },
  });

  await assert.rejects(cache.load(["JFK"]), /Abort|aborted/i);
  assert.equal(cache.size(), 0);
  assert.deepEqual(await cache.load(["JFK"]), { ok: true, attempt: 2 });
  assert.equal(fetchCount, 2);
});

test("browser request cache stays bounded and evicts its oldest route", async () => {
  let fetchCount = 0;
  const cache = createLiveContextRequestCache({
    parse: (value) => value,
    maxEntries: 2,
    ttlMs: 100_000,
    now: () => 1_000,
    fetchImpl: async () => {
      fetchCount += 1;
      return Response.json({ call: fetchCount });
    },
  });

  await cache.load(["JFK"]);
  await cache.load(["LHR"]);
  await cache.load(["LOS"]);
  assert.equal(cache.size(), 2);
  assert.equal(cache.has(["JFK"]), false);
  assert.equal(cache.has(["LHR"]), true);
  assert.equal(cache.has(["LOS"]), true);
  await cache.load(["JFK"]);
  assert.equal(fetchCount, 4);
  assert.equal(cache.size(), 2);
  await cache.load(["JFK"]);
  assert.equal(fetchCount, 4);
  await cache.load(["JFK"], { force: true });
  assert.equal(fetchCount, 5);
  assert.equal(cache.invalidate(["JFK"]), true);
  await cache.load(["JFK"]);
  assert.equal(fetchCount, 6);
});

test("offer cards lazy-load a truthful, accessible, separate AWC disclosure", async () => {
  const [offerCard, component, client, stylesheet] = await Promise.all([
    readFile(
      new URL("../app/skyeta/components/OfferCard.tsx", import.meta.url),
      "utf8",
    ),
    readFile(
      new URL(
        "../app/skyeta/components/LiveContextDisclosure.tsx",
        import.meta.url,
      ),
      "utf8",
    ),
    readFile(
      new URL(
        "../app/skyeta/components/live-context-client.ts",
        import.meta.url,
      ),
      "utf8",
    ),
    readFile(
      new URL("../app/skyeta/booking.module.css", import.meta.url),
      "utf8",
    ),
  ]);

  assert.match(offerCard, /<JourneyIntelligence[\s\S]*<LiveContextDisclosure/);
  assert.match(offerCard, /key={`live-context:\$\{journeyIntelligenceKey\}`}/);
  assert.match(component, /onToggle=/);
  assert.match(component, /useEffect/);
  assert.match(component, /requestSequence\.current \+= 1/);
  assert.match(component, /Not included in the delay percentage/);
  assert.match(component, /do not change SkyETA&apos;s trained delay percentage/);
  assert.match(component, /official AWC data documentation/);
  assert.match(component, /datasetFetchedAt/);
  assert.match(component, /AWC observation data/);
  assert.match(component, /retryAfterSeconds/);
  assert.match(component, /aria-live="polite"/);
  assert.match(component, /Refresh live airport context/);
  assert.match(component, /liveContextRequests\.invalidate/);
  assert.doesNotMatch(
    component,
    /state\.data\.partial && state\.data\.retryAfterSeconds > 0/,
  );
  assert.doesNotMatch(component, /retrievedAt|NOAA station/);
  assert.doesNotMatch(component, /addSkyetaRisk|scoreSkyeta|skyetaRisk/);
  assert.match(client, /timeoutMs \?\? 8_000/);
  assert.match(client, /maxEntries \?\? 40/);
  assert.match(client, /loadOptions: \{ force\?: boolean \}/);
  assert.match(stylesheet, /\.liveContextRaw > summary \{[\s\S]*min-height: 44px/);
  assert.match(stylesheet, /\.liveContextLinks a \{[\s\S]*min-height: 44px/);
  assert.match(stylesheet, /\.liveContextRetry button \{[\s\S]*min-height: 44px/);
  assert.match(stylesheet, /@media \(max-width: 720px\)[\s\S]*\.liveContextGrid/);
});
