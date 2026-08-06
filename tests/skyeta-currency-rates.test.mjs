import assert from "node:assert/strict";
import test from "node:test";

import {
  CONVERSION_CURRENCIES,
  createCurrencyRatesHandler,
} from "../app/api/skyeta/currency-rates/rates.ts";

const NOW = Date.parse("2026-08-07T12:00:00.000Z");
const providerRows = [
  { date: "2026-08-06", base: "EUR", quote: "GBP", rate: 0.85676 },
  { date: "2026-08-06", base: "EUR", quote: "NGN", rate: 1574.227 },
  { date: "2026-08-06", base: "EUR", quote: "USD", rate: 1.1538 },
];

test("currency rates derive precise NGN equivalents from one CBN snapshot", async () => {
  const calls = [];
  const handler = createCurrencyRatesHandler({
    now: () => NOW,
    fetchImpl: async (input, init) => {
      calls.push({ url: new URL(input), init });
      return Response.json(providerRows);
    },
  });

  const response = await handler();
  const body = await response.json();
  assert.equal(response.status, 200);
  assert.equal(body.ok, true);
  assert.equal(body.base, "NGN");
  assert.equal(body.asOf, "2026-08-06");
  assert.deepEqual(Object.keys(body.rates).sort(), [...CONVERSION_CURRENCIES].sort());
  assert.ok(Math.abs(body.rates.USD - 1.1538 / 1574.227) < 1e-12);
  assert.ok(Math.abs(body.rates.GBP - 0.85676 / 1574.227) < 1e-12);
  assert.ok(Math.abs(body.rates.EUR - 1 / 1574.227) < 1e-12);
  assert.equal(calls[0].url.origin, "https://api.frankfurter.dev");
  assert.equal(calls[0].url.pathname, "/v2/rates");
  assert.equal(calls[0].url.searchParams.get("providers"), "CBN");
  assert.equal(calls[0].init.redirect, "manual");
  assert.match(response.headers.get("cache-control"), /s-maxage=43200/);

  const cached = await handler();
  assert.equal(cached.status, 200);
  assert.equal(calls.length, 1);
});

test("currency rates fail safely for redirects, missing rows or mixed dates", async () => {
  const mixedDateRows = providerRows.map((row) =>
    row.quote === "USD" ? { ...row, date: "2026-08-05" } : row,
  );
  for (const response of [
    new Response(null, { status: 302 }),
    Response.json(providerRows.filter((row) => row.quote !== "GBP")),
    Response.json(mixedDateRows),
  ]) {
    const handler = createCurrencyRatesHandler({
      now: () => NOW,
      fetchImpl: async () => response,
    });
    const result = await handler();
    const body = await result.json();
    assert.equal(result.status, 502);
    assert.deepEqual(body, {
      ok: false,
      error: {
        code: "rates_unavailable",
        message: "Currency equivalents are unavailable right now.",
      },
    });
  }
});

test("currency rates can serve a clearly marked recent snapshot during an outage", async () => {
  let current = NOW;
  let available = true;
  const handler = createCurrencyRatesHandler({
    now: () => current,
    fetchImpl: async () => {
      if (!available) throw new Error("offline");
      return Response.json(providerRows);
    },
  });

  const fresh = await (await handler()).json();
  assert.equal(fresh.stale, false);

  current += 13 * 60 * 60 * 1_000;
  available = false;
  const staleResponse = await handler();
  const stale = await staleResponse.json();
  assert.equal(staleResponse.status, 200);
  assert.equal(stale.stale, true);
  assert.equal(stale.asOf, "2026-08-06");
  assert.equal(stale.rates.USD, fresh.rates.USD);
});

test("currency conversion failure never changes the original NGN fare", async () => {
  const [offerCard, converter] = await Promise.all([
    import("node:fs/promises").then(({ readFile }) =>
      readFile(new URL("../app/skyeta/components/OfferCard.tsx", import.meta.url), "utf8"),
    ),
    import("node:fs/promises").then(({ readFile }) =>
      readFile(
        new URL("../app/skyeta/components/CurrencyEquivalents.tsx", import.meta.url),
        "utf8",
      ),
    ),
  ]);
  assert.match(offerCard, /<strong>\{formatMoney\(offer\.total\)\}<\/strong>/);
  assert.match(offerCard, /<CurrencyEquivalents money=\{offer\.total\} \/>/);
  assert.match(converter, /View other currencies/);
  assert.match(converter, /For comparison only/);
  assert.match(converter, /money\.currency !== "NGN"/);
  assert.doesNotMatch(converter, /bookingLinks|onSelect/);
});
