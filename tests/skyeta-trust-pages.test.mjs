import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function source(path) {
  return readFile(new URL(path, root), "utf8");
}

test("SkyETA trust pages publish distinct canonical routes and cross-navigation", async () => {
  for (const route of ["help", "privacy", "terms"]) {
    const page = await source(`app/skyeta/${route}/page.tsx`);

    assert.match(page, new RegExp(`canonical: ["']\\/skyeta\\/${route}["']`));
    assert.match(page, /href="\/skyeta\/help"/);
    assert.match(page, /href="\/skyeta\/privacy"/);
    assert.match(page, /href="\/skyeta\/terms"/);
    assert.match(page, /href="\/skyeta"/);
  }
});

test("help page explains search, worldwide history and the U.S. model scope", async () => {
  const page = await source("app/skyeta/help/page.tsx");

  assert.match(page, /beta comparison product/);
  assert.match(page, /not an airline or travel\s+agency/);
  assert.match(page, /currently iGNav/);
  assert.match(page, /handles payment,\s*ticketing, changes/);
  assert.match(page, /does not collect\s+card data/);
  assert.match(page, /15\+, 30\+ and 60\+ minute late-arrival history/);
  assert.match(page, /trained model of U\.S\. domestic carrier/);
  assert.match(page, /not live flight status/);
  assert.match(page, /No\s+affiliate payment is currently configured/);
});

test("privacy page documents provider sharing, brief caching and aggregate analytics", async () => {
  const page = await source("app/skyeta/privacy/page.tsx");

  assert.match(page, /connected flight\s+provider, currently iGNav/);
  assert.match(page, /short-lived server cache/);
  assert.match(page, /approximately ten minutes/);
  assert.match(page, /never\s+beyond thirty minutes/);
  assert.match(page, /uses Umami for aggregate information/);
  assert.match(page, /Do Not Track/);
  assert.match(page, /does not collect card data/);
  assert.match(page, /provider&apos;s privacy terms/);
  assert.match(page, /flight number, origin and destination/);
  assert.match(page, /to AirLabs/);
  assert.match(page, /one-way SHA-256 quota key/);
  assert.match(page, /raw IP address\s+is not written/);
  assert.match(page, /expire\s+after ten minutes/);
  assert.match(page, /up to 24 hours/);
});

test("terms state SkyETA's beta role and the provider's booking responsibility", async () => {
  const page = await source("app/skyeta/terms/page.tsx");

  assert.match(page, /beta comparison service, not a travel agency/);
  assert.match(page, /does not sell or issue\s+tickets, accept payment/);
  assert.match(page, /handles payment, ticketing, schedule changes/);
  assert.match(page, /No affiliate payment or commission is currently configured/);
  assert.match(page, /Historical outlook, not live status/);
  assert.match(page, /route-matched completed-flight\s+history supplied by AirLabs/);
  assert.match(page, /not live flight status, a\s+guarantee or travel advice/);
});

test("every trust page identifies the operator and direct contact", async () => {
  for (const route of ["help", "privacy", "terms"]) {
    const page = await source(`app/skyeta/${route}/page.tsx`);

    assert.match(page, /Peters Elijah Temidayo/);
    assert.match(page, /Nigeria/);
    assert.match(page, /mailto:peterselijah11@gmail\.com/);
  }
});

test("trust-page navigation and mobile layout retain accessible target sizes", async () => {
  const styles = await source("app/skyeta/info.module.css");

  assert.match(styles, /\.brand,\s*\.backLink\s*\{[\s\S]*?min-height:\s*44px/);
  assert.match(styles, /\.pageNav a\s*\{[\s\S]*?min-height:\s*44px/);
  assert.match(styles, /@media \(max-width:\s*680px\)[\s\S]*?\.sectionGrid\s*\{[\s\S]*?grid-template-columns:\s*1fr/);
  assert.match(styles, /@media \(prefers-reduced-motion:\s*reduce\)/);
});
