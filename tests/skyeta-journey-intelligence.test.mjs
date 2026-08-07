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
  assert.match(panel, /View SkyETA journey intelligence/);
  assert.match(panel, /Evidence, not guesswork/);
  assert.match(panel, /Provider itinerary/);
  assert.match(panel, /Verified delay outlook/);
  assert.match(panel, /Recent observed performance/);
  assert.match(
    panel,
    /SkyETA estimates that about \$\{percentage\} in 100 comparable flights would arrive/,
  );
  assert.match(panel, /will not invent a percentage/);
  assert.match(panel, /observed history from/);
  assert.match(panel, /not a prediction of this future flight/);
  assert.match(panel, /\/api\/skyeta\/recent-performance\?flights=/);
  assert.doesNotMatch(panel, /global prediction|worldwide prediction|AI prediction/i);
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
    /return `\$\{flightIata\}:\$\{originIata\}:\$\{destinationIata\}`/,
  );
  assert.match(panel, /identifiers: uniqueIdentifiers\.slice\(0, 3\)/);
  assert.match(panel, /isLimited: uniqueIdentifiers\.length > 3/);
  assert.match(
    panel,
    /Only the first 3 distinct flight segments are checked for recent/,
  );
  assert.match(panel, /validAirportIata\(value\.originIata\)/);
  assert.match(panel, /validAirportIata\(value\.destinationIata\)/);
  assert.match(
    panel,
    /key=\{`\$\{evidence\.flightIata\}:\$\{evidence\.originIata\}:\$\{evidence\.destinationIata\}`\}/,
  );
});

test("recent observations require a useful sample before showing a comparison", async () => {
  const panel = await readFile(
    new URL("../app/skyeta/components/JourneyIntelligence.tsx", import.meta.url),
    "utf8",
  );

  assert.match(panel, /evidence\.arrivalDelayKnown >= 3/);
  assert.match(panel, /evidence\.departureDelayKnown >= 3/);
  assert.match(panel, /Not enough verified recent delay records/);
});
