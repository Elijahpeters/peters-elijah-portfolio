import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const badgeSource = await readFile(
  new URL("../app/skyeta/components/SkyetaRiskBadge.tsx", import.meta.url),
  "utf8",
);

test("full SkyETA coverage explains the late-arrival percentage plainly", () => {
  assert.match(badgeSource, /Late-arrival outlook/);
  assert.match(badgeSource, /chance of arriving 15\+ minutes late/);
  assert.match(badgeSource, /about \$\{roundedProbability\} in 100 similar flights/);
});

test("unavailable coverage is a neutral journey insight", () => {
  assert.match(badgeSource, /Journey insight/);
  assert.match(badgeSource, /Delay outlook not yet verified for this route/);
  assert.doesNotMatch(badgeSource, /Risk not available for this itinerary/);
});

test("partial coverage never presents a whole-itinerary percentage", () => {
  const partialBranch = badgeSource.slice(
    badgeSource.indexOf('risk.coverage === "partial"'),
    badgeSource.indexOf("const probability"),
  );

  assert.match(
    partialBranch,
    /\$\{risk\.scoredSegments\} of \$\{risk\.totalSegments\} flight segments analysed/,
  );
  assert.match(partialBranch, /whole-journey delay percentage is not shown/i);
  assert.doesNotMatch(partialBranch, /risk\.percentage/);
});
