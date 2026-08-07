import skyetaModelSource from "../../../public/assets/skyeta-model.json" with {
  type: "json",
};

type TreeNode = {
  split_feature?: number;
  threshold?: number | string;
  decision_type?: string;
  default_left?: boolean;
  left_child?: TreeNode;
  right_child?: TreeNode;
  leaf_value?: number;
};

type SkyetaModel = {
  featureNames: string[];
  featureSet: "core" | "context";
  booster: {
    average_output: false;
    tree_info: Array<{ tree_structure?: TreeNode }>;
  };
  rates: {
    global: number;
    carrier: Record<string, number>;
    origin: Record<string, number>;
    destination: Record<string, number>;
    route: Record<string, number>;
  };
  calibration: {
    slope: number;
    intercept: number;
  };
};

export type SkyetaRiskLevel = "lower" | "moderate" | "higher";

export type SkyetaSegmentRisk =
  | {
      status: "available";
      probability: number;
      percentage: number;
      level: SkyetaRiskLevel;
      summary: string;
    }
  | {
      status: "unavailable";
      reason: string;
    };

export type SkyetaItineraryRisk =
  | {
      status: "available";
      probability: number;
      percentage: number;
      level: SkyetaRiskLevel;
      summary: string;
      scope: "single_segment" | "highest_scored_segment";
      coverage: "complete" | "partial";
      scoredSegments: number;
      totalSegments: number;
      segmentRisks: SkyetaSegmentRisk[];
    }
  | {
      status: "unavailable";
      reason: string;
      scoredSegments: 0;
      totalSegments: number;
      segmentRisks: SkyetaSegmentRisk[];
    };

export type ScorableFlightSegment = {
  origin: string;
  destination: string;
  carrierIata: string;
  departureLocal: string;
  durationMinutes: number | null;
  distanceMiles: number | null;
};

const model = skyetaModelSource as unknown as SkyetaModel;
const EXPECTED_CORE_FEATURES = [
  "month_sin",
  "month_cos",
  "weekday_sin",
  "weekday_cos",
  "day_of_month_sin",
  "day_of_month_cos",
  "departure_hour_sin",
  "departure_hour_cos",
  "departure_minute_fraction",
  "is_weekend",
  "scheduled_duration_minutes",
  "distance_miles",
  "carrier_delay_rate",
  "origin_delay_rate",
  "destination_delay_rate",
  "route_delay_rate",
] as const;

function hasOwn(map: Record<string, number>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(map, key);
}

function modelReady(): boolean {
  return (
    model.featureSet === "core" &&
    model.booster?.average_output === false &&
    Array.isArray(model.booster.tree_info) &&
    model.booster.tree_info.length > 0 &&
    model.featureNames.length === EXPECTED_CORE_FEATURES.length &&
    model.featureNames.every((name, index) => name === EXPECTED_CORE_FEATURES[index]) &&
    Number.isFinite(model.rates?.global) &&
    Number.isFinite(model.calibration?.slope) &&
    Number.isFinite(model.calibration?.intercept)
  );
}

function traverseTree(root: TreeNode, features: number[]): number {
  let node: TreeNode | undefined = root;
  for (let depth = 0; depth < 512 && node; depth += 1) {
    if (typeof node.leaf_value === "number" && Number.isFinite(node.leaf_value)) {
      return node.leaf_value;
    }

    const featureIndex: number | undefined = node.split_feature;
    const threshold: number = Number(node.threshold);
    if (
      featureIndex === undefined ||
      !Number.isInteger(featureIndex) ||
      featureIndex < 0 ||
      featureIndex >= features.length ||
      !Number.isFinite(threshold) ||
      !node.left_child ||
      !node.right_child
    ) {
      throw new Error("SkyETA evaluator is unavailable.");
    }

    const featureValue: number = features[featureIndex];
    const decisionType = node.decision_type ?? "<=";
    let goLeft: boolean;
    if (!Number.isFinite(featureValue)) {
      goLeft = node.default_left === true;
    } else if (decisionType === "<=") {
      goLeft = featureValue <= threshold;
    } else if (decisionType === "<") {
      goLeft = featureValue < threshold;
    } else if (decisionType === ">") {
      goLeft = featureValue > threshold;
    } else if (decisionType === ">=") {
      goLeft = featureValue >= threshold;
    } else {
      throw new Error("SkyETA evaluator is unavailable.");
    }
    node = goLeft ? node.left_child : node.right_child;
  }
  throw new Error("SkyETA evaluator is unavailable.");
}

function sigmoid(value: number): number {
  if (value >= 0) return 1 / (1 + Math.exp(-value));
  const exponential = Math.exp(value);
  return exponential / (1 + exponential);
}

function riskLevel(probability: number): SkyetaRiskLevel {
  if (probability < 0.16) return "lower";
  if (probability < 0.28) return "moderate";
  return "higher";
}

function riskSummary(level: SkyetaRiskLevel, percentage: number): string {
  const range =
    level === "lower"
      ? "a lower delay-risk range"
      : level === "higher"
        ? "a higher delay-risk range"
        : "a moderate delay-risk range";
  return `SkyETA places this flight segment in ${range} at ${percentage}%.`;
}

function parseLocalDeparture(value: string): {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
} | null {
  const match = value.match(
    /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::\d{2})?/,
  );
  if (!match) return null;
  const [, yearText, monthText, dayText, hourText, minuteText] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const check = new Date(Date.UTC(year, month - 1, day));
  if (
    check.getUTCFullYear() !== year ||
    check.getUTCMonth() !== month - 1 ||
    check.getUTCDate() !== day ||
    hour < 0 ||
    hour > 23 ||
    minute < 0 ||
    minute > 59
  ) {
    return null;
  }
  return { year, month, day, hour, minute };
}

function featureVector(segment: ScorableFlightSegment): number[] | null {
  const departure = parseLocalDeparture(segment.departureLocal);
  if (
    !departure ||
    !segment.durationMinutes ||
    segment.durationMinutes <= 0 ||
    !segment.distanceMiles ||
    segment.distanceMiles <= 0
  ) {
    return null;
  }

  const date = new Date(
    Date.UTC(departure.year, departure.month - 1, departure.day),
  );
  const weekday = date.getUTCDay() === 0 ? 7 : date.getUTCDay();
  const route = `${segment.origin}_${segment.destination}`;
  const globalRate = model.rates.global;
  const values: Record<(typeof EXPECTED_CORE_FEATURES)[number], number> = {
    month_sin: Math.sin((2 * Math.PI * departure.month) / 12),
    month_cos: Math.cos((2 * Math.PI * departure.month) / 12),
    weekday_sin: Math.sin((2 * Math.PI * weekday) / 7),
    weekday_cos: Math.cos((2 * Math.PI * weekday) / 7),
    day_of_month_sin: Math.sin((2 * Math.PI * departure.day) / 31),
    day_of_month_cos: Math.cos((2 * Math.PI * departure.day) / 31),
    departure_hour_sin: Math.sin((2 * Math.PI * departure.hour) / 24),
    departure_hour_cos: Math.cos((2 * Math.PI * departure.hour) / 24),
    departure_minute_fraction: departure.minute / 60,
    is_weekend: weekday >= 6 ? 1 : 0,
    scheduled_duration_minutes: segment.durationMinutes,
    distance_miles: segment.distanceMiles,
    carrier_delay_rate: model.rates.carrier[segment.carrierIata] ?? globalRate,
    origin_delay_rate: model.rates.origin[segment.origin] ?? globalRate,
    destination_delay_rate:
      model.rates.destination[segment.destination] ?? globalRate,
    route_delay_rate: model.rates.route[route] ?? globalRate,
  };
  return model.featureNames.map((name) =>
    Math.fround(values[name as keyof typeof values]),
  );
}

export function scoreSkyetaSegment(
  segment: ScorableFlightSegment,
): SkyetaSegmentRisk {
  const route = `${segment.origin}_${segment.destination}`;
  if (
    !modelReady() ||
    !/^[A-Z0-9]{2}$/.test(segment.carrierIata) ||
    !/^[A-Z]{3}$/.test(segment.origin) ||
    !/^[A-Z]{3}$/.test(segment.destination) ||
    !hasOwn(model.rates.carrier, segment.carrierIata) ||
    !hasOwn(model.rates.origin, segment.origin) ||
    !hasOwn(model.rates.destination, segment.destination) ||
    !hasOwn(model.rates.route, route)
  ) {
    return {
      status: "unavailable",
      reason: "SkyETA currently covers supported U.S. domestic routes.",
    };
  }

  const features = featureVector(segment);
  if (!features) {
    return {
      status: "unavailable",
      reason: "This itinerary does not include enough schedule detail for SkyETA.",
    };
  }

  try {
    const rawScore = model.booster.tree_info.reduce((sum, tree) => {
      if (!tree.tree_structure) throw new Error("missing tree");
      return sum + traverseTree(tree.tree_structure, features);
    }, 0);
    const probability = sigmoid(
      model.calibration.slope * rawScore + model.calibration.intercept,
    );
    const percentage = Math.round(probability * 100);
    const level = riskLevel(probability);
    return {
      status: "available",
      probability,
      percentage,
      level,
      summary: riskSummary(level, percentage),
    };
  } catch {
    return {
      status: "unavailable",
      reason: "SkyETA could not evaluate this itinerary right now.",
    };
  }
}

export function scoreSkyetaItinerary(
  segments: ScorableFlightSegment[],
): SkyetaItineraryRisk {
  const segmentRisks = segments.map(scoreSkyetaSegment);
  const available = segmentRisks.filter(
    (risk): risk is Extract<SkyetaSegmentRisk, { status: "available" }> =>
      risk.status === "available",
  );
  if (available.length === 0) {
    return {
      status: "unavailable",
      reason: "SkyETA currently covers supported U.S. domestic routes.",
      scoredSegments: 0,
      totalSegments: segments.length,
      segmentRisks,
    };
  }

  const highest = available.reduce((current, risk) =>
    risk.probability > current.probability ? risk : current,
  );
  const scope = segments.length === 1 ? "single_segment" : "highest_scored_segment";
  return {
    ...highest,
    scope,
    summary:
      scope === "single_segment"
        ? highest.summary
        : `The highest scored flight segment is ${highest.percentage}%. SkyETA does not treat that value as a whole-journey probability.`,
    coverage: available.length === segments.length ? "complete" : "partial",
    scoredSegments: available.length,
    totalSegments: segments.length,
    segmentRisks,
  };
}
