import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("SkyETA separates worldwide search from the selected-U.S. trained model", async () => {
  const [page, tabs] = await Promise.all([
    readFile(new URL("app/skyeta/page.tsx", root), "utf8"),
    readFile(new URL("app/skyeta/components/SkyetaToolTabs.tsx", root), "utf8"),
  ]);

  assert.match(page, /Compare current flights worldwide/);
  assert.match(page, /<SkyetaToolTabs/);
  assert.match(tabs, /Find flights worldwide/);
  assert.match(tabs, /U\.S\. delay research lab/);
  assert.match(tabs, /trained delay model[\s\S]*selected U\.S\. domestic routes/);
  assert.match(tabs, /recent observed reliability[\s\S]*verified flight history/);
  assert.match(tabs, /never invents a delay percentage/);
  assert.match(tabs, /role="tablist"/);
  assert.match(tabs, /handleTabKeyDown/);
});

test("SkyETA social image is route-specific and code generated", async () => {
  const image = await readFile(
    new URL("app/skyeta/opengraph-image.tsx", root),
    "utf8",
  );

  assert.match(image, /new ImageResponse/);
  assert.match(image, /width: 1200, height: 630/);
  assert.match(image, /Compare current flights worldwide/);
  assert.match(image, /peterselijah\.name\.ng\/skyeta/);
});
