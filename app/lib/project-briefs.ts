export type ProjectBrief = {
  id: string;
  project: string;
  problem: string;
  why: string;
  built: string;
  found: readonly string[];
  next: readonly string[];
  tradeoff: string;
};

// Each brief answers the same six questions. Every figure comes from the
// evidence already published with the project; none is an estimate.
export const projectBriefs = {
  aurapass: {
    id: "aurapass-brief",
    project: "AuraPass",
    problem:
      "Confirm that the person entering an exam hall is the registered student, is eligible for that course and has not already entered.",
    why: "Impersonation undermines the result for every candidate, and the check has to work where there is no reliable internet.",
    built:
      "Course form and face samples → Python, OpenCV and SQLite → access decision → simulated Proteus gate.",
    found: [
      "0 of 5,000 non-enrolled face attempts were granted access.",
      "1,207 attempts (24%) were rejected for image quality before any matching.",
      "Blur was hardest: 383 of 500 blurred attempts were quality-rejected.",
    ],
    next: [
      "Measure how often genuine enrolled students are wrongly refused.",
      "Test with a live camera in real hall lighting.",
      "Replace the simulated gate with physical hardware.",
    ],
    tradeoff:
      "I prioritised stopping impostors over convenience. Admitting the wrong person compromises an exam; a wrongly refused student can be checked again by a person. The test therefore measures false grants only, not overall biometric accuracy.",
  },
  skyeta: {
    id: "skyeta-brief",
    project: "SkyETA",
    problem:
      "Travellers compare flights on price and time, but cannot see how likely a flight is to arrive late.",
    why: "About 1 in 5 U.S. domestic flights in the 2025 records arrived 15 or more minutes late, so reliability belongs beside the fare.",
    built:
      "Official flight records → Python, pandas and LightGBM → calibrated delay probability → TypeScript app on Cloudflare Workers.",
    found: [
      "Schedule data alone is a weak predictor: ROC-AUC 0.64 on validation, 0.61 on the untouched test month.",
      "Delay rates shift by season: 26.7% late in December against 20.5% in validation.",
      "A yes/no label would mislead, so the app shows a probability instead.",
    ],
    next: [
      "Bring pre-departure NOAA observations into the served model.",
      "Recalibrate by season so winter risk is not understated.",
      "Keep the Brazilian model out of production until it passes a forward-in-time test.",
    ],
    tradeoff:
      "I split the data by time, not at random. Scores are lower than a random split would give, but it matches real use: predicting flights that have not happened yet. A route with fewer than five completed flights shows no percentage at all.",
  },
  incubator: {
    id: "incubator-brief",
    project: "Incubator interface carrier",
    problem:
      "An Arduino Mega incubator controller needs its sensor, relay-control and status connections brought into one organised interface.",
    why: "A single board with defined terminals is easier to assemble, inspect and service than point-to-point wiring, and its layout can be checked before anything is built.",
    built:
      "Schematic → placement and routing → ERC, DRC and pin-map checks, all in KiCad (96 × 76 mm, two layers, Rev C).",
    found: [
      "0 ERC errors, 0 DRC violations and 0 unconnected pads under the saved check configuration.",
      "71 matching electrical pin assignments in a separate pin-map audit.",
      "Signal traces are 0.30 mm; coil supply and return are 1.50 mm and 1.20 mm.",
    ],
    next: [
      "Fabricate the board and bench-test it with the actual relay module.",
      "Confirm connector fit with the purchased parts.",
      "Correct and re-simulate the KHN filter from the circuit studies.",
    ],
    tradeoff:
      "Clean design checks are not proof that a board works. They confirm the rules, not thermal behaviour, safety or function, so the project is labelled as not bench-tested and the images as KiCad renders.",
  },
} as const satisfies Record<string, ProjectBrief>;
