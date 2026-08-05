import assert from "node:assert/strict";
import test from "node:test";

import {
  scoreSkyetaItinerary,
  scoreSkyetaSegment,
} from "../app/lib/skyeta/server-risk.ts";

const supportedSegment = {
  origin: "HNL",
  destination: "OGG",
  carrierIata: "HA",
  departureLocal: "2026-09-10T09:30:00",
  durationMinutes: 42,
  distanceMiles: 100,
};

test("SkyETA scores a supported U.S. itinerary with a bounded probability", () => {
  const risk = scoreSkyetaSegment(supportedSegment);

  assert.equal(risk.status, "available");
  assert.ok(risk.probability > 0 && risk.probability < 1);
  assert.equal(risk.percentage, Math.round(risk.probability * 100));
  assert.match(risk.summary, /^SkyETA places this itinerary/);
});

test("SkyETA clearly declines routes outside its evidence coverage", () => {
  const risk = scoreSkyetaSegment({
    ...supportedSegment,
    origin: "LOS",
    destination: "LHR",
    carrierIata: "BA",
  });

  assert.deepEqual(risk, {
    status: "unavailable",
    reason: "SkyETA currently covers supported U.S. domestic routes.",
  });
});

test("itinerary risk uses the highest supported segment and reports coverage", () => {
  const risk = scoreSkyetaItinerary([
    supportedSegment,
    { ...supportedSegment, origin: "LOS", destination: "LHR", carrierIata: "BA" },
  ]);

  assert.equal(risk.status, "available");
  assert.equal(risk.coverage, "partial");
  assert.equal(risk.scoredSegments, 1);
  assert.equal(risk.totalSegments, 2);
});
