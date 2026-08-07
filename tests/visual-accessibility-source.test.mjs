import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

function luminance(hex) {
  const channels = hex
    .slice(1)
    .match(/.{2}/g)
    .map((channel) => Number.parseInt(channel, 16) / 255)
    .map((channel) =>
      channel <= 0.04045
        ? channel / 12.92
        : ((channel + 0.055) / 1.055) ** 2.4,
    );

  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}

function contrastRatio(first, second) {
  const light = Math.max(luminance(first), luminance(second));
  const dark = Math.min(luminance(first), luminance(second));
  return (light + 0.05) / (dark + 0.05);
}

test("portfolio muted text passes AA against its deepest cream surface", async () => {
  const css = await readFile(new URL("app/globals.css", root), "utf8");
  const muted = css.match(/--muted:\s*(#[0-9a-f]{6})/i)?.[1];

  assert.ok(muted, "the shared muted colour should be declared");
  assert.ok(
    contrastRatio(muted, "#ebe7df") >= 4.5,
    "muted normal text should have at least 4.5:1 contrast",
  );
});

test("SkyETA keeps low-emphasis interface text readable", async () => {
  const [pageCss, bookingCss, airportCss] = await Promise.all([
    readFile(new URL("app/skyeta/skyeta.module.css", root), "utf8"),
    readFile(new URL("app/skyeta/booking.module.css", root), "utf8"),
    readFile(
      new URL("app/skyeta/components/AirportCombobox.module.css", root),
      "utf8",
    ),
  ]);

  for (const css of [pageCss, bookingCss, airportCss]) {
    assert.match(css, /color:\s*#(?:9aa9c8|aab6d0)/i);
  }

  assert.ok(
    contrastRatio("#9aa9c8", "#171743") >= 4.5,
    "subtle SkyETA text should pass AA on its lightest dark surface",
  );
});

test("fill images have layout space reserved before they load", async () => {
  const css = await readFile(new URL("app/globals.css", root), "utf8");
  const selectors = [
    "portrait-shell",
    "feature-image",
    "process-diagram",
    "state-gallery figure",
    "circuit-image",
    "profile-portrait > div",
  ];

  for (const selector of selectors) {
    const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    assert.match(
      css,
      new RegExp(`\\.${escaped}\\s*\\{[^}]*aspect-ratio`, "s"),
      `${selector} should reserve its image ratio`,
    );
  }
});
