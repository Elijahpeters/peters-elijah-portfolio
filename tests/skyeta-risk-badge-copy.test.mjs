import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const badgeSource = await readFile(
  new URL("../app/skyeta/components/SkyetaRiskBadge.tsx", import.meta.url),
  "utf8",
);

test("single-flight U.S. coverage explains the late-arrival percentage plainly", () => {
  assert.match(badgeSource, /U\.S\. schedule model/);
  assert.match(badgeSource, /chance this flight arrives 15\+ minutes late/);
  assert.match(badgeSource, /about \$\{roundedProbability\} in 100 comparable flights/);
});

test("unavailable U.S. coverage points to the separate worldwide history", () => {
  assert.match(badgeSource, /U\.S\. schedule model/);
  assert.match(badgeSource, /Not available outside selected U\.S\. routes/);
  assert.match(badgeSource, /Worldwide flight history is checked separately/);
  assert.doesNotMatch(badgeSource, /Risk not available for this itinerary/);
});

test("multi-segment coverage never presents one leg as a whole-itinerary percentage", () => {
  const partialBranch = badgeSource.slice(
    badgeSource.indexOf('risk.scope === "highest_scored_segment"'),
    badgeSource.indexOf("const probability"),
  );

  assert.match(
    partialBranch,
    /\$\{risk\.scoredSegments\} of \$\{risk\.totalSegments\} flight segments analysed/,
  );
  assert.match(partialBranch, /whole-journey delay percentage is not shown/i);
  assert.doesNotMatch(partialBranch, /risk\.percentage/);
});
