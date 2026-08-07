import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import test from "node:test";

import {
  createAirportSearchHandler,
  searchAirports,
} from "../app/api/skyeta/airports/search.ts";

test("airport search resolves codes and global city names", () => {
  assert.equal(searchAirports("LOS")[0]?.code, "LOS");
  assert.ok(searchAirports("Lagos").some((airport) => airport.code === "LOS"));
  assert.ok(searchAirports("Abuja").some((airport) => airport.code === "ABV"));
  assert.ok(searchAirports("London").some((airport) => airport.code === "LHR"));
  assert.ok(
    searchAirports("Murtala Muhammed").some(
      (airport) => airport.code === "LOS",
    ),
  );
});

test("airport search is bounded, normalized and returns public static data", async () => {
  assert.ok(searchAirports("airport").length <= 8);
  assert.deepEqual(searchAirports("x"), []);
  assert.equal(searchAirports("  lagos  ")[0]?.code, "LOS");

  const handler = createAirportSearchHandler();
  const response = await handler(
    new Request("https://example.test/api/skyeta/airports?q=London"),
  );
  const payload = await response.json();
  assert.equal(response.status, 200);
  assert.equal(payload.ok, true);
  assert.ok(payload.airports.length <= 8);
  assert.match(response.headers.get("cache-control"), /^public,/);
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
});

test("airport endpoint rejects ambiguous and oversized queries", async () => {
  const handler = createAirportSearchHandler();
  const duplicate = await handler(
    new Request("https://example.test/api/skyeta/airports?q=Lagos&q=London"),
  );
  const oversized = await handler(
    new Request(
      `https://example.test/api/skyeta/airports?q=${"a".repeat(65)}`,
    ),
  );
  assert.equal(duplicate.status, 400);
  assert.equal(oversized.status, 400);
  assert.equal(duplicate.headers.get("cache-control"), "no-store");
});

test("global catalogue stays compact and out of the client component", async () => {
  const datasetPath = new URL(
    "../app/lib/skyeta/global-airports.json",
    import.meta.url,
  );
  const dataset = JSON.parse(await readFile(datasetPath, "utf8"));
  const datasetStats = await stat(datasetPath);
  const component = await readFile(
    new URL(
      "../app/skyeta/components/AirportCombobox.tsx",
      import.meta.url,
    ),
    "utf8",
  );
  const generator = await readFile(
    new URL("../scripts/build-skyeta-global-airports.mjs", import.meta.url),
    "utf8",
  );

  assert.ok(dataset.length > 5_000);
  assert.ok(datasetStats.size < 1_500_000);
  assert.doesNotMatch(component, /global-airports\.json/);
  assert.match(component, /\/api\/skyeta\/airports\?q=/);
  assert.match(generator, /mborsetti\/airportsdata/);
});

test("airport combobox exposes accessible keyboard, touch and status behavior", async () => {
  const component = await readFile(
    new URL(
      "../app/skyeta/components/AirportCombobox.tsx",
      import.meta.url,
    ),
    "utf8",
  );

  assert.match(component, /role="combobox"/);
  assert.match(component, /role="listbox"/);
  assert.match(component, /role="option"/);
  assert.match(component, /aria-activedescendant/);
  assert.match(component, /ArrowDown/);
  assert.match(component, /ArrowUp/);
  assert.match(component, /event\.key === "Enter"/);
  assert.match(component, /onPointerDown/);
  assert.match(component, /Searching airports…/);
  assert.match(component, /No matching airport found/);
  assert.match(component, /onChange\(option\.code\)/);
  assert.match(component, /type="hidden" name=\{name\} value=\{value\}/);
  assert.doesNotMatch(
    component,
    /selectedRef\.current = \{ code: typedCode, display: typedCode \}/,
  );
});
