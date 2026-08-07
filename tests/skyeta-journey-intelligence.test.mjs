import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("journey intelligence keeps worldwide evidence types honest and separate", async () => {
  const [panel, offerCard] = await Promise.all([
    readFile(
      new URL("../app/skyeta/components/JourneyIntelligence.tsx", import.meta.url),
      "utf8",
    ),
    readFile(
      new URL("../app/skyeta/components/OfferCard.tsx", import.meta.url),
      "utf8",
    ),
  ]);

  assert.match(
    offerCard,
    /<JourneyIntelligence[\s\S]*key=\{journeyIntelligenceKey\}[\s\S]*segments=\{segments\}[\s\S]*risk=\{offer\.skyetaRisk\}/,
  );
  assert.match(panel, /Worldwide historical outlook/);
  assert.match(panel, /How each flight has performed before/);
  assert.match(panel, /Current itinerary/);
  assert.match(panel, /U\.S\. schedule model · selected routes only/);
  assert.match(panel, /Worldwide AirLabs history/);
  assert.match(
    panel,
    /The U\.S\. schedule model estimates that about \$\{percentage\} in 100 comparable single-flight journeys/,
  );
  assert.match(panel, /completed-flight history from/);
  assert.match(panel, /not live flight status or a promise/);
  assert.match(panel, /\/api\/skyeta\/recent-performance\?flights=/);
  assert.doesNotMatch(panel, /trained global model|worldwide prediction|AI prediction/i);
});

test("journey intelligence cannot reuse observations after a flight changes", async () => {
  const [panel, offerCard] = await Promise.all([
    readFile(
      new URL("../app/skyeta/components/JourneyIntelligence.tsx", import.meta.url),
      "utf8",
    ),
    readFile(
      new URL("../app/skyeta/components/OfferCard.tsx", import.meta.url),
      "utf8",
    ),
  ]);

  assert.match(
    panel,
    /const requestKey = lookupPlan\.identifiers\.join\(","\)/,
  );
  assert.match(panel, /state\.requestKey === requestKey/);
  assert.match(panel, /controller\.current\?\.abort\(\)/);
  assert.match(panel, /controller\.current !== nextController/);
  assert.match(panel, /<details[\s\S]*key=\{requestKey\}/);
  assert.match(
    offerCard,
    /const journeyIntelligenceKey = segments[\s\S]*segment\.marketingFlightNumber[\s\S]*segment\.departingAt/,
  );
});

test("recent-history lookups are route-qualified and limited transparently", async () => {
  const panel = await readFile(
    new URL("../app/skyeta/components/JourneyIntelligence.tsx", import.meta.url),
    "utf8",
  );

  assert.match(
    panel,
    /\? `\$\{flightIata\}:\$\{originIata\}:\$\{destinationIata\}`/,
  );
  assert.match(
    panel,
    /identifiers = uniqueIdentifiers\.slice\(0, MAX_HISTORY_LOOKUPS\)/,
  );
  assert.match(
    panel,
    /isLimited: uniqueIdentifiers\.length > MAX_HISTORY_LOOKUPS/,
  );
  assert.match(
    panel,
    /only the first \{MAX_HISTORY_LOOKUPS\} distinct/,
  );
  assert.match(panel, /validAirportIata\(value\.originIata\)/);
  assert.match(panel, /validAirportIata\(value\.destinationIata\)/);
  assert.match(
    panel,
    /function evidenceKey\(evidence: Evidence\)/,
  );
});

test("worldwide outlook requires a useful sample and separates every itinerary leg", async () => {
  const panel = await readFile(
    new URL("../app/skyeta/components/JourneyIntelligence.tsx", import.meta.url),
    "utf8",
  );

  assert.match(panel, /!evidence\.arrivalDataSufficient/);
  assert.match(panel, /At[\s\S]*least 5 are required/);
  assert.match(panel, /lookupPlan\.legs\.map/);
  assert.match(panel, /15\+ min:/);
  assert.match(panel, /30\+ min:/);
  assert.match(panel, /60\+ min:/);
  assert.match(panel, /Typical[\s\S]*delay when that happened/);
  assert.match(panel, /arrivalSampleConfidence/);
  assert.match(panel, /uncertainty range shows how much/);
  assert.match(panel, /treats the\s*legs as independent/);
  assert.match(
    panel,
    /A journey-wide percentage appears only when every leg has enough usable arrival records/,
  );
});
