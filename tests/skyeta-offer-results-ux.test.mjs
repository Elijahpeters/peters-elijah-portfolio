import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const component = (name) =>
  readFile(
    new URL(`../app/skyeta/components/${name}`, import.meta.url),
    "utf8",
  );

test("flight results provide understandable sorting and practical filters", async () => {
  const source = await component("OfferResults.tsx");

  assert.match(source, /Best balances price, journey time and stops/);
  assert.match(source, />\s*Cheapest\s*</);
  assert.match(source, />\s*Fastest\s*</);
  assert.match(source, /Direct only/);
  assert.match(source, /Up to 1 stop/);
  assert.match(source, /maximumStopsOnOneLeg\(offer\)/);
  assert.match(source, /Any airline/);
  assert.match(source, /Morning · 5 AM–12 PM/);
  assert.match(source, /Fares with stated baggage/);
  assert.match(source, /Journey duration/);
  assert.match(source, /No flights match every selected filter/);
  assert.match(source, /disabled=\{!comparablePrices\}/);
  assert.match(source, /Cancel search/);
  assert.match(source, /displayCurrency=\{displayCurrency\}/);
});

test("offer cards state price provenance, itemization and handoff responsibility", async () => {
  const source = await component("OfferCard.tsx");

  assert.match(source, /flightProviderLabel\(offer\.source\.provider\)/);
  assert.match(source, /Price source/);
  assert.match(source, /currencyDisplay: "code"/);
  assert.match(source, /average per traveler/);
  assert.match(source, /Taxes and fees were not itemized separately by the provider/);
  assert.match(source, /Provider-reported tax component/);
  assert.match(source, /Last checked/);
  assert.match(source, /Layover at/);
  assert.match(source, /duration not supplied/);
  assert.match(source, /handles[\s\S]*payment, ticketing, changes, refunds and support/);
  assert.match(source, /never receives your card details/);
  assert.match(source, /No affiliate payment is[\s\S]*currently configured/);
  assert.doesNotMatch(source, /rel="noopener noreferrer sponsored"/);
});

test("currency preference never replaces the provider total", async () => {
  const [card, converter] = await Promise.all([
    component("OfferCard.tsx"),
    component("CurrencyEquivalents.tsx"),
  ]);

  assert.match(card, /<strong>\{formatMoney\(offer\.total\)\}<\/strong>/);
  assert.match(card, /preferredCurrency=\{displayCurrency\}/);
  assert.match(converter, /Approximate total in \{preferredTarget\}/);
  assert.match(converter, /the NGN provider price is unchanged/);
  assert.match(converter, /airline, booking partner or card provider sets/);
});
