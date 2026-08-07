import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import nextConfig, { securityHeaders } from "../next.config.ts";
import {
  approvedBookingHosts,
  approvedBookingUrl,
} from "../app/lib/flight-provider/approved-booking-url.ts";

const root = new URL("../", import.meta.url);

test("SkyETA publishes its own canonical and social URL metadata", async () => {
  const layout = await readFile(new URL("app/skyeta/layout.tsx", root), "utf8");

  assert.match(layout, /canonical:\s*["']\/skyeta["']/);
  assert.match(layout, /openGraph:[\s\S]*?url:\s*["']\/skyeta["']/);
  assert.match(layout, /siteName:\s*["']SkyETA["']/);
  assert.match(layout, /twitter:[\s\S]*?summary_large_image/);
  assert.match(layout, /\/skyeta\/opengraph-image/);
});

test("baseline security headers and explicit asset caching are configured", async () => {
  const rules = await nextConfig.headers?.();
  const globalRule = rules?.find((rule) => rule.source === "/:path*");
  const staticRule = rules?.find((rule) => rule.source === "/_next/static/:path*");
  const assetRule = rules?.find((rule) => rule.source === "/assets/:path*");
  assert.ok(globalRule);
  assert.match(
    staticRule?.headers.find((header) => header.key === "Cache-Control")?.value ?? "",
    /max-age=31536000, immutable/,
  );
  assert.match(
    assetRule?.headers.find((header) => header.key === "Cache-Control")?.value ?? "",
    /stale-while-revalidate/,
  );

  const headers = new Map(securityHeaders.map(({ key, value }) => [key, value]));
  assert.equal(headers.get("X-Content-Type-Options"), "nosniff");
  assert.equal(headers.get("X-Frame-Options"), "DENY");
  assert.equal(headers.get("Referrer-Policy"), "strict-origin-when-cross-origin");
  assert.match(headers.get("Strict-Transport-Security") ?? "", /max-age=31536000/);
  assert.match(headers.get("Content-Security-Policy") ?? "", /frame-ancestors 'none'/);
  assert.match(headers.get("Content-Security-Policy") ?? "", /object-src 'none'/);
});

test("booking handoffs accept only reviewed HTTPS hosts", () => {
  const approved = new Set(["airline.example"]);

  assert.equal(
    approvedBookingUrl("https://book.airline.example/trip?id=123", approved),
    "https://book.airline.example/trip?id=123",
  );
  for (const unsafe of [
    "http://airline.example/trip",
    "https://airline.example:8443/trip",
    "https://user:secret@airline.example/trip",
    "https://airline.example.evil.test/trip",
    "https://unreviewed.example/trip",
    "javascript:alert(1)",
  ]) {
    assert.equal(approvedBookingUrl(unsafe, approved), null, unsafe);
  }
});

test("configured booking hosts extend rather than weaken the reviewed allowlist", () => {
  const hosts = approvedBookingHosts(
    " airline.example, https://invalid.example, com, airline.example ",
  );

  assert.equal(hosts.has("airline.example"), true);
  assert.equal(hosts.has("rwandair.com"), true);
  assert.equal(hosts.has("https://invalid.example"), false);
  assert.equal(hosts.has("com"), false);
});
