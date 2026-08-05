"use client";

import Image from "next/image";
import {
  type FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

type TreeNode = {
  split_feature?: number;
  threshold?: number | string;
  decision_type?: string;
  default_left?: boolean;
  left_child?: TreeNode;
  right_child?: TreeNode;
  leaf_value?: number;
};

type RoutePreset = {
  carrier: string;
  origin: string;
  destination: string;
  scheduledDurationMinutes: number;
  distanceMiles: number;
  trainingFlights?: number;
};

type WeatherMetadata = {
  status: "included" | "not_available";
  source: string;
  cutoffHours: number;
  maxObservationAgeHours: number;
  featureNames: string[];
  coverage?: {
    airportCount: number;
    januaryEndpointShare: number;
    januaryAtLeastOneEndpointFlightShare: number;
    januaryBothEndpointsFlightShare: number;
  };
};

type ScheduleContextMetadata = {
  featureNames: string[];
  maps: {
    route: Record<string, number>;
    carrierRoute: Record<string, number>;
    originBank: Record<string, number>;
  };
};

type CalibrationMetadata = {
  method: "identity_sigmoid" | "platt_sigmoid";
  input: "lightgbm_raw_score";
  slope: number;
  intercept: number;
};

type ValidationEvidence = {
  validationRocAuc: number;
  validationRows: number;
  testRocAuc: number;
  testBrierScore: number;
  testRows: number;
  calibrationMethod: string;
  calibrated: boolean;
  validationAucGainVsCore?: number;
};

type SkyetaModel = {
  formatVersion: number;
  featureSet: "core" | "context";
  featureNames: string[];
  booster: {
    objective: string;
    average_output: boolean;
    tree_info: Array<{ tree_structure?: TreeNode }>;
  };
  rates: {
    global: number;
    carrier: Record<string, number>;
    origin: Record<string, number>;
    destination: Record<string, number>;
    route: Record<string, number>;
  };
  presets: RoutePreset[];
  parityCases: Array<{
    features: number[];
    probability: number;
  }>;
  calibration: CalibrationMetadata;
  scheduleContext?: ScheduleContextMetadata;
  validationEvidence?: ValidationEvidence;
  weather?: WeatherMetadata;
};

type FactorInsight = {
  label: string;
  delta: number;
  comparison: string;
};

type ReliabilityMetric = {
  label: string;
  code: string;
  reliability: number;
};

type DepartureWindow = {
  offsetHours: number;
  date: string;
  time: string;
  label: string;
  probability: number;
};

type Prediction = {
  probability: number;
  carrier: string;
  origin: string;
  destination: string;
  departure: string;
  departureDate: string;
  factors: FactorInsight[];
  reliability: ReliabilityMetric[];
  nearbyWindows: DepartureWindow[];
  bestWindow: DepartureWindow;
  networkBaseline: number;
  historicalFallbackCount: number;
  inferenceTimeMs: number;
};

type LiveFlightEndpoint = {
  scheduledLocal: string | null;
  scheduledUtc: string | null;
  estimatedLocal: string | null;
  estimatedUtc: string | null;
};

type LiveFlight = {
  id: string;
  airlineIata: string | null;
  flightIata: string | null;
  flightNumber: string | null;
  origin: string;
  destination: string;
  departure: LiveFlightEndpoint;
  arrival: LiveFlightEndpoint;
  status: string | null;
  durationMinutes: number | null;
  departureDelayMinutes: number | null;
  arrivalDelayMinutes: number | null;
};

type LiveFlightsPayload =
  | {
      configured: false;
      message: string;
    }
  | {
      configured: true;
      source: "airlabs";
      flights: LiveFlight[];
      fetchedAt: string;
    }
  | {
      configured: true;
      source: "airlabs";
      flights: [];
      error: { code: string; message: string };
    };

type LiveFlightsState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "not-configured"; message: string }
  | { status: "error"; message: string }
  | { status: "empty"; source: "airlabs"; fetchedAt: string }
  | {
      status: "ready";
      source: "airlabs";
      fetchedAt: string;
      flights: LiveFlight[];
    };

const CORE_FEATURES = [
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

const CONTEXT_FEATURES = [
  "route_frequency_log1p",
  "carrier_route_frequency_log1p",
  "origin_bank_frequency_log1p",
  "is_major_holiday_window",
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function readNullableText(value: unknown, label: string): string | null {
  if (value === null) return null;
  if (typeof value !== "string") {
    throw new Error(`Live route data contains an invalid ${label}.`);
  }
  return value;
}

function readNullableMinutes(value: unknown, label: string): number | null {
  if (value === null) return null;
  if (!isFiniteNumber(value) || value < 0) {
    throw new Error(`Live route data contains an invalid ${label}.`);
  }
  return value;
}

function readLiveFlightEndpoint(
  value: unknown,
  label: string,
): LiveFlightEndpoint {
  if (!isRecord(value)) {
    throw new Error(`Live route data is missing ${label} timing.`);
  }
  return {
    scheduledLocal: readNullableText(
      value.scheduledLocal,
      `${label} scheduled local time`,
    ),
    scheduledUtc: readNullableText(
      value.scheduledUtc,
      `${label} scheduled UTC time`,
    ),
    estimatedLocal: readNullableText(
      value.estimatedLocal,
      `${label} estimated local time`,
    ),
    estimatedUtc: readNullableText(
      value.estimatedUtc,
      `${label} estimated UTC time`,
    ),
  };
}

function readLiveFlight(value: unknown): LiveFlight {
  if (!isRecord(value)) {
    throw new Error("Live route data contains an invalid flight row.");
  }
  if (
    typeof value.id !== "string" ||
    typeof value.origin !== "string" ||
    typeof value.destination !== "string"
  ) {
    throw new Error("Live route data contains an incomplete flight row.");
  }
  return {
    id: value.id,
    airlineIata: readNullableText(value.airlineIata, "airline code"),
    flightIata: readNullableText(value.flightIata, "flight code"),
    flightNumber: readNullableText(value.flightNumber, "flight number"),
    origin: value.origin,
    destination: value.destination,
    departure: readLiveFlightEndpoint(value.departure, "departure"),
    arrival: readLiveFlightEndpoint(value.arrival, "arrival"),
    status: readNullableText(value.status, "flight status"),
    durationMinutes: readNullableMinutes(value.durationMinutes, "duration"),
    departureDelayMinutes: readNullableMinutes(
      value.departureDelayMinutes,
      "departure delay",
    ),
    arrivalDelayMinutes: readNullableMinutes(
      value.arrivalDelayMinutes,
      "arrival delay",
    ),
  };
}

function parseLiveFlightsPayload(value: unknown): LiveFlightsPayload {
  if (!isRecord(value) || typeof value.configured !== "boolean") {
    throw new Error("Live route data returned an unexpected response.");
  }

  if (!value.configured) {
    const errorMessage = isRecord(value.error) && typeof value.error.message === "string"
      ? value.error.message
      : null;
    return {
      configured: false,
      message:
        typeof value.message === "string"
          ? value.message
          : errorMessage ?? "Live flight lookup is not configured.",
    };
  }

  if (value.source !== "airlabs" || !Array.isArray(value.flights)) {
    throw new Error("Live route data returned an unexpected response.");
  }
  if (isRecord(value.error)) {
    if (
      typeof value.error.code !== "string" ||
      typeof value.error.message !== "string"
    ) {
      throw new Error("Live route data returned an invalid provider error.");
    }
    return {
      configured: true,
      source: "airlabs",
      flights: [],
      error: {
        code: value.error.code,
        message: value.error.message,
      },
    };
  }
  if (typeof value.fetchedAt !== "string") {
    throw new Error("Live route data is missing its retrieval timestamp.");
  }
  return {
    configured: true,
    source: "airlabs",
    fetchedAt: value.fetchedAt,
    flights: value.flights.map(readLiveFlight),
  };
}

function readRateMap(value: unknown): Record<string, number> {
  if (!isRecord(value)) {
    throw new Error("SkyETA rate data is incomplete.");
  }

  const entries = Object.entries(value);
  if (entries.some(([, rate]) => !isFiniteNumber(rate))) {
    throw new Error("SkyETA rate data contains an invalid value.");
  }

  return Object.fromEntries(entries) as Record<string, number>;
}

function readCountMap(value: unknown): Record<string, number> {
  if (!isRecord(value)) {
    throw new Error("SkyETA schedule-context data is incomplete.");
  }

  const entries = Object.entries(value);
  if (
    entries.some(
      ([, count]) =>
        !isFiniteNumber(count) || !Number.isInteger(count) || count < 0,
    )
  ) {
    throw new Error("SkyETA schedule-context data contains an invalid count.");
  }

  return Object.fromEntries(entries) as Record<string, number>;
}

function matchesFeatureContract(
  value: unknown,
  expected: readonly string[],
): value is string[] {
  return (
    Array.isArray(value) &&
    value.length === expected.length &&
    value.every((name, index) => name === expected[index])
  );
}

function parseModel(value: unknown): SkyetaModel {
  if (
    !isRecord(value) ||
    (value.formatVersion !== 1 && value.formatVersion !== 2)
  ) {
    throw new Error("This SkyETA data format is not supported.");
  }

  const featureSet = value.featureSet ?? "core";
  if (featureSet !== "core" && featureSet !== "context") {
    throw new Error(
      "This SkyETA feature set requires serving inputs unavailable in the browser demo.",
    );
  }
  const expectedFeatures =
    featureSet === "context"
      ? [...CORE_FEATURES, ...CONTEXT_FEATURES]
      : CORE_FEATURES;

  if (!matchesFeatureContract(value.featureNames, expectedFeatures)) {
    throw new Error("SkyETA data does not match this interface.");
  }

  if (
    !isRecord(value.booster) ||
    !Array.isArray(value.booster.tree_info) ||
    value.booster.tree_info.length === 0
  ) {
    throw new Error("SkyETA is temporarily unavailable.");
  }

  const objective = value.booster.objective;
  const sigmoidMatch =
    typeof objective === "string"
      ? objective.match(/(?:^|\s)sigmoid:([^\s]+)/)
      : null;
  if (
    typeof objective !== "string" ||
    !/^binary(?:\s|$)/.test(objective) ||
    value.booster.average_output !== false ||
    (sigmoidMatch !== null && Number(sigmoidMatch[1]) !== 1)
  ) {
    throw new Error("This SkyETA inference contract is not supported.");
  }

  if (!isRecord(value.rates) || !isFiniteNumber(value.rates.global)) {
    throw new Error("SkyETA route information is unavailable.");
  }

  if (!Array.isArray(value.presets) || value.presets.length === 0) {
    throw new Error("SkyETA route presets are unavailable.");
  }

  if (!Array.isArray(value.parityCases) || value.parityCases.length === 0) {
    throw new Error("SkyETA evaluator checks are unavailable.");
  }

  const presets = value.presets.map((preset) => {
    if (
      !isRecord(preset) ||
      typeof preset.carrier !== "string" ||
      typeof preset.origin !== "string" ||
      typeof preset.destination !== "string" ||
      !isFiniteNumber(preset.scheduledDurationMinutes) ||
      !isFiniteNumber(preset.distanceMiles) ||
      (preset.trainingFlights !== undefined &&
        !isFiniteNumber(preset.trainingFlights))
    ) {
      throw new Error("A SkyETA route preset is invalid.");
    }

    return {
      carrier: preset.carrier,
      origin: preset.origin,
      destination: preset.destination,
      scheduledDurationMinutes: preset.scheduledDurationMinutes,
      distanceMiles: preset.distanceMiles,
      trainingFlights: preset.trainingFlights,
    };
  });

  const parityCases = value.parityCases.map((parityCase) => {
    if (
      !isRecord(parityCase) ||
      !Array.isArray(parityCase.features) ||
      parityCase.features.length !== expectedFeatures.length ||
      parityCase.features.some((feature) => !isFiniteNumber(feature)) ||
      !isFiniteNumber(parityCase.probability) ||
      parityCase.probability < 0 ||
      parityCase.probability > 1
    ) {
      throw new Error("A SkyETA evaluator check is invalid.");
    }

    return {
      features: parityCase.features as number[],
      probability: parityCase.probability,
    };
  });

  let calibration: CalibrationMetadata = {
    method: "identity_sigmoid",
    input: "lightgbm_raw_score",
    slope: 1,
    intercept: 0,
  };
  if (value.formatVersion === 2) {
    if (
      !isRecord(value.calibration) ||
      value.calibration.method !== "platt_sigmoid" ||
      value.calibration.input !== "lightgbm_raw_score" ||
      !isFiniteNumber(value.calibration.slope) ||
      value.calibration.slope <= 0 ||
      !isFiniteNumber(value.calibration.intercept)
    ) {
      throw new Error("SkyETA probability calibration is unavailable.");
    }
    calibration = {
      method: "platt_sigmoid",
      input: "lightgbm_raw_score",
      slope: value.calibration.slope,
      intercept: value.calibration.intercept,
    };
  }

  let scheduleContext: ScheduleContextMetadata | undefined;
  if (featureSet === "context") {
    if (
      !isRecord(value.scheduleContext) ||
      !matchesFeatureContract(
        value.scheduleContext.featureNames,
        CONTEXT_FEATURES,
      ) ||
      !isRecord(value.scheduleContext.maps)
    ) {
      throw new Error("SkyETA schedule-context metadata is unavailable.");
    }
    scheduleContext = {
      featureNames: [...CONTEXT_FEATURES],
      maps: {
        route: readCountMap(value.scheduleContext.maps.route),
        carrierRoute: readCountMap(
          value.scheduleContext.maps.carrierRoute,
        ),
        originBank: readCountMap(value.scheduleContext.maps.originBank),
      },
    };
  }

  let validationEvidence: ValidationEvidence | undefined;
  if (
    isRecord(value.modelCard) &&
    isRecord(value.modelCard.metrics) &&
    isRecord(value.modelCard.metrics.validation) &&
    isRecord(value.modelCard.metrics.test)
  ) {
    const validation = value.modelCard.metrics.validation;
    const test = value.modelCard.metrics.test;
    const ablationGain =
      isRecord(value.modelCard.ablation) &&
      isRecord(value.modelCard.ablation.acceptance) &&
      value.modelCard.ablation.acceptance.accepted === true &&
      isFiniteNumber(
        value.modelCard.ablation.acceptance.observedSelectedMinusCore,
      )
        ? value.modelCard.ablation.acceptance.observedSelectedMinusCore
        : undefined;
    if (
      isFiniteNumber(validation.rocAuc) &&
      isFiniteNumber(validation.rows) &&
      isFiniteNumber(test.rocAuc) &&
      isFiniteNumber(test.brierScore) &&
      isFiniteNumber(test.rows)
    ) {
      validationEvidence = {
        validationRocAuc: validation.rocAuc,
        validationRows: validation.rows,
        testRocAuc: test.rocAuc,
        testBrierScore: test.brierScore,
        testRows: test.rows,
        calibrationMethod:
          calibration.method === "platt_sigmoid"
            ? "validation-fitted Platt sigmoid"
            : "LightGBM raw sigmoid",
        calibrated: calibration.method === "platt_sigmoid",
        validationAucGainVsCore: ablationGain,
      };
    }
  }

  let weather: WeatherMetadata | undefined;
  if (value.weather !== undefined) {
    if (
      !isRecord(value.weather) ||
      (value.weather.status !== "included" &&
        value.weather.status !== "not_available") ||
      typeof value.weather.source !== "string" ||
      !isFiniteNumber(value.weather.cutoffHours) ||
      value.weather.cutoffHours < 0 ||
      !isFiniteNumber(value.weather.maxObservationAgeHours) ||
      value.weather.maxObservationAgeHours < 0 ||
      !Array.isArray(value.weather.featureNames) ||
      value.weather.featureNames.some((name) => typeof name !== "string")
    ) {
      throw new Error("SkyETA weather metadata is invalid.");
    }

    let coverage: WeatherMetadata["coverage"];
    if (value.weather.coverage !== undefined) {
      if (
        !isRecord(value.weather.coverage) ||
        !isFiniteNumber(value.weather.coverage.airportCount) ||
        value.weather.coverage.airportCount < 0 ||
        !isFiniteNumber(value.weather.coverage.januaryEndpointShare) ||
        value.weather.coverage.januaryEndpointShare < 0 ||
        value.weather.coverage.januaryEndpointShare > 1 ||
        !isFiniteNumber(
          value.weather.coverage.januaryAtLeastOneEndpointFlightShare,
        ) ||
        value.weather.coverage.januaryAtLeastOneEndpointFlightShare < 0 ||
        value.weather.coverage.januaryAtLeastOneEndpointFlightShare > 1 ||
        !isFiniteNumber(
          value.weather.coverage.januaryBothEndpointsFlightShare,
        ) ||
        value.weather.coverage.januaryBothEndpointsFlightShare < 0 ||
        value.weather.coverage.januaryBothEndpointsFlightShare > 1
      ) {
        throw new Error("SkyETA weather coverage metadata is invalid.");
      }
      coverage = {
        airportCount: value.weather.coverage.airportCount,
        januaryEndpointShare: value.weather.coverage.januaryEndpointShare,
        januaryAtLeastOneEndpointFlightShare:
          value.weather.coverage.januaryAtLeastOneEndpointFlightShare,
        januaryBothEndpointsFlightShare:
          value.weather.coverage.januaryBothEndpointsFlightShare,
      };
    }

    weather = {
      status: value.weather.status,
      source: value.weather.source,
      cutoffHours: value.weather.cutoffHours,
      maxObservationAgeHours: value.weather.maxObservationAgeHours,
      featureNames: value.weather.featureNames as string[],
      coverage,
    };
  }

  return {
    formatVersion: value.formatVersion,
    featureSet,
    featureNames: value.featureNames as string[],
    booster: {
      objective,
      average_output: false,
      tree_info: value.booster.tree_info as Array<{ tree_structure?: TreeNode }>,
    },
    rates: {
      global: value.rates.global,
      carrier: readRateMap(value.rates.carrier),
      origin: readRateMap(value.rates.origin),
      destination: readRateMap(value.rates.destination),
      route: readRateMap(value.rates.route),
    },
    presets,
    parityCases,
    calibration,
    scheduleContext,
    validationEvidence,
    weather,
  };
}

function traverseTree(root: TreeNode, features: number[]): number {
  let node: TreeNode | undefined = root;

  for (let depth = 0; depth < 512 && node; depth += 1) {
    if (isFiniteNumber(node.leaf_value)) return node.leaf_value;

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
      throw new Error("A SkyETA decision tree is malformed.");
    }

    const featureValue: number = features[featureIndex];
    let goLeft: boolean;
    if (!Number.isFinite(featureValue)) {
      goLeft = node.default_left === true;
    } else {
      const decisionType = node.decision_type ?? "<=";
      if (decisionType === "<=") goLeft = featureValue <= threshold;
      else if (decisionType === "<") goLeft = featureValue < threshold;
      else if (decisionType === ">") goLeft = featureValue > threshold;
      else if (decisionType === ">=") goLeft = featureValue >= threshold;
      else throw new Error(`Unsupported SkyETA split: ${decisionType}`);
    }

    node = goLeft ? node.left_child : node.right_child;
  }

  throw new Error("A SkyETA decision tree could not be evaluated.");
}

function sigmoid(rawScore: number): number {
  if (rawScore >= 0) return 1 / (1 + Math.exp(-rawScore));
  const exponential = Math.exp(rawScore);
  return exponential / (1 + exponential);
}

function predict(model: SkyetaModel, featureMap: Record<string, number>): number {
  const features = model.featureNames.map((name) => {
    const value = featureMap[name];
    if (!Number.isFinite(value)) {
      throw new Error(`SkyETA could not prepare ${name}.`);
    }
    return Math.fround(value);
  });

  const rawScore = model.booster.tree_info.reduce((score, tree) => {
    if (!tree.tree_structure) {
      throw new Error("A SkyETA decision tree is missing.");
    }
    return score + traverseTree(tree.tree_structure, features);
  }, 0);

  return sigmoid(
    model.calibration.slope * rawScore + model.calibration.intercept,
  );
}

function defaultDepartureDate(): string {
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const year = tomorrow.getFullYear();
  const month = String(tomorrow.getMonth() + 1).padStart(2, "0");
  const day = String(tomorrow.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function rateFor(map: Record<string, number>, key: string, fallback: number) {
  const rate = map[key];
  return Number.isFinite(rate) ? rate : fallback;
}

function thanksgivingDayOfMonth(year: number): number {
  const firstDay = new Date(Date.UTC(year, 10, 1)).getUTCDay();
  return 1 + ((4 - firstDay + 7) % 7) + 21;
}

function isMajorHolidayWindow(
  year: number,
  month: number,
  dayOfMonth: number,
): number {
  const candidate = Date.UTC(year, month - 1, dayOfMonth);
  const holidays = [
    Date.UTC(year, 0, 1),
    Date.UTC(year, 6, 4),
    Date.UTC(year, 10, thanksgivingDayOfMonth(year)),
    Date.UTC(year, 11, 25),
  ];
  const millisecondsPerDay = 86_400_000;
  return holidays.some(
    (holiday) =>
      Math.abs(candidate - holiday) / millisecondsPerDay <= 2,
  )
    ? 1
    : 0;
}

function historicalFallbackCount(
  model: SkyetaModel,
  preset: RoutePreset,
): number {
  const lookups: Array<[Record<string, number>, string]> = [
    [model.rates.carrier, preset.carrier],
    [model.rates.origin, preset.origin],
    [model.rates.destination, preset.destination],
    [model.rates.route, `${preset.origin}_${preset.destination}`],
  ];

  return lookups.reduce(
    (count, [map, key]) =>
      count + (Object.prototype.hasOwnProperty.call(map, key) ? 0 : 1),
    0,
  );
}

function buildFeatureMap(
  model: SkyetaModel,
  preset: RoutePreset,
  departureDate: string,
  departureTime: string,
  duration: number,
  distance: number,
): Record<string, number> {
  const [year, month, dayOfMonth] = departureDate.split("-").map(Number);
  const [hour, minute] = departureTime.split(":").map(Number);
  const date = new Date(year, month - 1, dayOfMonth);

  if (
    !Number.isInteger(year) ||
    !Number.isInteger(month) ||
    !Number.isInteger(dayOfMonth) ||
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== dayOfMonth ||
    !Number.isInteger(hour) ||
    hour < 0 ||
    hour > 23 ||
    !Number.isInteger(minute) ||
    minute < 0 ||
    minute > 59 ||
    !Number.isFinite(duration) ||
    duration <= 0 ||
    !Number.isFinite(distance) ||
    distance <= 0
  ) {
    throw new Error("Check the departure date, time, duration and distance.");
  }

  const jsWeekday = date.getDay();
  const isoWeekday = jsWeekday === 0 ? 7 : jsWeekday;
  const globalRate = model.rates.global;

  const featureMap: Record<string, number> = {
    month_sin: Math.sin((2 * Math.PI * month) / 12),
    month_cos: Math.cos((2 * Math.PI * month) / 12),
    weekday_sin: Math.sin((2 * Math.PI * isoWeekday) / 7),
    weekday_cos: Math.cos((2 * Math.PI * isoWeekday) / 7),
    day_of_month_sin: Math.sin((2 * Math.PI * dayOfMonth) / 31),
    day_of_month_cos: Math.cos((2 * Math.PI * dayOfMonth) / 31),
    departure_hour_sin: Math.sin((2 * Math.PI * hour) / 24),
    departure_hour_cos: Math.cos((2 * Math.PI * hour) / 24),
    departure_minute_fraction: minute / 60,
    is_weekend: isoWeekday >= 6 ? 1 : 0,
    scheduled_duration_minutes: duration,
    distance_miles: distance,
    carrier_delay_rate: rateFor(model.rates.carrier, preset.carrier, globalRate),
    origin_delay_rate: rateFor(model.rates.origin, preset.origin, globalRate),
    destination_delay_rate: rateFor(
      model.rates.destination,
      preset.destination,
      globalRate,
    ),
    route_delay_rate: rateFor(
      model.rates.route,
      `${preset.origin}_${preset.destination}`,
      globalRate,
    ),
  };

  if (model.featureSet === "context") {
    if (!model.scheduleContext) {
      throw new Error("SkyETA schedule-context metadata is unavailable.");
    }
    const route = `${preset.origin}_${preset.destination}`;
    const carrierRoute = `${preset.carrier}|${route}`;
    const halfHour = Math.floor((hour * 60 + minute) / 30);
    const originBank = `${preset.origin}|${isoWeekday}|${halfHour}`;
    featureMap.route_frequency_log1p = Math.log1p(
      model.scheduleContext.maps.route[route] ?? 0,
    );
    featureMap.carrier_route_frequency_log1p = Math.log1p(
      model.scheduleContext.maps.carrierRoute[carrierRoute] ?? 0,
    );
    featureMap.origin_bank_frequency_log1p = Math.log1p(
      model.scheduleContext.maps.originBank[originBank] ?? 0,
    );
    featureMap.is_major_holiday_window = isMajorHolidayWindow(
      year,
      month,
      dayOfMonth,
    );
  }

  return featureMap;
}

function describeDeparture(date: string, time: string): string {
  const value = new Date(`${date}T${time}:00`);
  if (Number.isNaN(value.getTime())) return `${date} at ${time}`;
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(value);
}

function shiftSchedule(
  departureDate: string,
  departureTime: string,
  offsetHours: number,
): Omit<DepartureWindow, "probability"> {
  const [year, month, day] = departureDate.split("-").map(Number);
  const [hour, minute] = departureTime.split(":").map(Number);
  const shifted = new Date(year, month - 1, day, hour + offsetHours, minute);
  const shiftedMonth = String(shifted.getMonth() + 1).padStart(2, "0");
  const shiftedDay = String(shifted.getDate()).padStart(2, "0");
  const shiftedHour = String(shifted.getHours()).padStart(2, "0");
  const shiftedMinute = String(shifted.getMinutes()).padStart(2, "0");

  return {
    offsetHours,
    date: `${shifted.getFullYear()}-${shiftedMonth}-${shiftedDay}`,
    time: `${shiftedHour}:${shiftedMinute}`,
    label: new Intl.DateTimeFormat("en", {
      weekday: "short",
      hour: "numeric",
      minute: "2-digit",
    }).format(shifted),
  };
}

function createNearbyWindows(
  model: SkyetaModel,
  preset: RoutePreset,
  departureDate: string,
  departureTime: string,
  duration: number,
  distance: number,
): DepartureWindow[] {
  return [-3, -2, -1, 0, 1, 2, 3].map((offsetHours) => {
    const schedule = shiftSchedule(departureDate, departureTime, offsetHours);
    const probability = predict(
      model,
      buildFeatureMap(
        model,
        preset,
        schedule.date,
        schedule.time,
        duration,
        distance,
      ),
    );
    return { ...schedule, probability };
  });
}

function createReliabilityMetrics(
  model: SkyetaModel,
  preset: RoutePreset,
): ReliabilityMetric[] {
  const globalRate = model.rates.global;
  const metrics = [
    {
      label: "Carrier",
      code: preset.carrier,
      rate: rateFor(model.rates.carrier, preset.carrier, globalRate),
    },
    {
      label: "Origin",
      code: preset.origin,
      rate: rateFor(model.rates.origin, preset.origin, globalRate),
    },
    {
      label: "Destination",
      code: preset.destination,
      rate: rateFor(model.rates.destination, preset.destination, globalRate),
    },
    {
      label: "Route",
      code: `${preset.origin}-${preset.destination}`,
      rate: rateFor(
        model.rates.route,
        `${preset.origin}_${preset.destination}`,
        globalRate,
      ),
    },
  ];

  return metrics.map(({ label, code, rate }) => ({
    label,
    code,
    reliability: Math.max(0, Math.min(1, 1 - rate)),
  }));
}

function createFactorInsights(
  model: SkyetaModel,
  preset: RoutePreset,
  featureMap: Record<string, number>,
  probability: number,
  bestWindow: DepartureWindow,
  duration: number,
  distance: number,
): FactorInsight[] {
  const globalRate = model.rates.global;
  const comparisons: Array<{
    label: string;
    comparison: string;
    changes: Record<string, number>;
  }> = [
    {
      label: "Route history",
      comparison: `${preset.origin}-${preset.destination} compared with similar SkyETA patterns`,
      changes: { route_delay_rate: globalRate },
    },
    {
      label: "Carrier history",
      comparison: `${preset.carrier} compared with similar SkyETA patterns`,
      changes: { carrier_delay_rate: globalRate },
    },
    {
      label: "Origin pattern",
      comparison: `${preset.origin} compared with similar SkyETA patterns`,
      changes: { origin_delay_rate: globalRate },
    },
    {
      label: "Destination pattern",
      comparison: `${preset.destination} compared with similar SkyETA patterns`,
      changes: { destination_delay_rate: globalRate },
    },
  ];

  if (Math.abs(duration - preset.scheduledDurationMinutes) >= 1) {
    comparisons.push({
      label: "Flight duration",
      comparison: "Entered duration versus this route preset",
      changes: {
        scheduled_duration_minutes: preset.scheduledDurationMinutes,
      },
    });
  }

  if (Math.abs(distance - preset.distanceMiles) >= 1) {
    comparisons.push({
      label: "Flight distance",
      comparison: "Entered distance versus this route preset",
      changes: { distance_miles: preset.distanceMiles },
    });
  }

  const insights = comparisons.map(({ label, comparison, changes }) => {
    const baselineProbability = predict(model, { ...featureMap, ...changes });
    return {
      label,
      delta: probability - baselineProbability,
      comparison,
    };
  });

  if (
    bestWindow.offsetHours !== 0 &&
    probability - bestWindow.probability > 0.0005
  ) {
    insights.push({
      label: "Departure window",
      delta: probability - bestWindow.probability,
      comparison: `Selected time versus ${bestWindow.label}`,
    });
  }

  return insights
    .sort((left, right) => Math.abs(right.delta) - Math.abs(left.delta))
    .slice(0, 3);
}

const LIVE_LOCAL_DATE_FORMATTER = new Intl.DateTimeFormat("en", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

const LIVE_FETCHED_AT_FORMATTER = new Intl.DateTimeFormat("en", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZoneName: "short",
});

function formatLiveLocalTime(value: string | null): string {
  if (!value) return "Not reported";
  const match = value.match(
    /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})(?::\d{2})?$/,
  );
  if (!match) return value;
  const [, year, month, day, hour, minute] = match;
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  return `${LIVE_LOCAL_DATE_FORMATTER.format(date)} · ${hour}:${minute}`;
}

function formatFetchedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : LIVE_FETCHED_AT_FORMATTER.format(date);
}

function liveDateTimeAttribute(value: string | null): string | undefined {
  return value ? value.replace(" ", "T") : undefined;
}

function formatFlightStatus(value: string | null): string {
  if (!value) return "Status unavailable";
  return value
    .replace("-", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function flightStatusTone(value: string | null): string {
  if (value === "cancelled") return "is-cancelled";
  if (value === "landed") return "is-landed";
  if (value === "active" || value === "en-route") return "is-active";
  if (value === "scheduled") return "is-scheduled";
  return "is-unknown";
}

function formatDelay(value: number): string {
  return value === 0 ? "0 min" : `+${value} min`;
}

function formatDuration(value: number): string {
  const hours = Math.floor(value / 60);
  const minutes = value % 60;
  if (!hours) return `${minutes} min`;
  return minutes ? `${hours}h ${minutes}m` : `${hours}h`;
}

function liveFlightLabel(flight: LiveFlight): string {
  if (flight.flightIata) return flight.flightIata;
  const combined = [flight.airlineIata, flight.flightNumber]
    .filter((part): part is string => Boolean(part))
    .join(" ");
  return combined || "Flight number unavailable";
}

function LiveEndpointTimes({
  label,
  endpoint,
  delayMinutes,
}: {
  label: "Departure" | "Arrival";
  endpoint: LiveFlightEndpoint;
  delayMinutes: number | null;
}) {
  return (
    <section className="skyeta-demo__live-endpoint">
      <span>{label} · local time</span>
      <dl>
        <div>
          <dt>Scheduled</dt>
          <dd>
            <time dateTime={liveDateTimeAttribute(endpoint.scheduledLocal)}>
              {formatLiveLocalTime(endpoint.scheduledLocal)}
            </time>
          </dd>
        </div>
        <div>
          <dt>Estimated</dt>
          <dd>
            <time dateTime={liveDateTimeAttribute(endpoint.estimatedLocal)}>
              {formatLiveLocalTime(endpoint.estimatedLocal)}
            </time>
          </dd>
        </div>
      </dl>
      {delayMinutes !== null ? (
        <p>
          Reported {label.toLowerCase()} delay
          <strong>{formatDelay(delayMinutes)}</strong>
        </p>
      ) : null}
    </section>
  );
}

function LiveRouteBoard({
  state,
  prediction,
  panelHeading: PanelHeading,
  itemHeading: ItemHeading,
}: {
  state: LiveFlightsState;
  prediction: Prediction;
  panelHeading: "h3" | "h5";
  itemHeading: "h4" | "h6";
}) {
  const stateLabel =
    state.status === "loading"
      ? "Checking live data"
      : state.status === "ready"
        ? `${state.flights.length} current ${state.flights.length === 1 ? "flight" : "flights"}`
        : state.status === "empty"
          ? "No current rows"
          : state.status === "not-configured"
            ? "Provider not configured"
            : state.status === "error"
              ? "Live data unavailable"
              : "Preparing lookup";
  const stateTone =
    state.status === "ready"
      ? "is-ready"
      : state.status === "loading" || state.status === "idle"
        ? "is-loading"
        : state.status === "empty"
          ? "is-empty"
          : "is-unavailable";
  const hasFetchMetadata = state.status === "ready" || state.status === "empty";

  return (
    <article
      className="skyeta-demo__live-card"
      aria-labelledby="skyeta-live-route-title"
      aria-busy={state.status === "loading"}
    >
      <div className="skyeta-demo__live-heading">
        <div>
          <span>Real current schedule/status data</span>
          <PanelHeading id="skyeta-live-route-title">Live route board</PanelHeading>
          <p>
            AirLabs&apos; schedule window is current and extends up to about 10
            hours. It may differ from the prediction&apos;s selected future date,
            {" "}
            {prediction.departureDate}.
          </p>
        </div>
        <span className={`skyeta-demo__live-state ${stateTone}`} role="status">
          <i aria-hidden="true" />
          {stateLabel}
        </span>
      </div>

      <p className="skyeta-demo__live-scope">
        <strong>
          {prediction.carrier} · {prediction.origin} to {prediction.destination}
        </strong>
        This board is real current schedule/status data, not fares, seats, or
        booking availability.
      </p>

      {hasFetchMetadata ? (
        <div className="skyeta-demo__live-meta" aria-label="Live data provenance">
          <span>
            Source <strong>AirLabs</strong>
          </span>
          <span>
            Fetched{" "}
            <time dateTime={state.fetchedAt}>{formatFetchedAt(state.fetchedAt)}</time>
          </span>
        </div>
      ) : null}

      <div className="skyeta-demo__live-content">
        {state.status === "loading" || state.status === "idle" ? (
          <p className="skyeta-demo__live-message is-loading" role="status">
            Checking the current route schedule and status. Live-board results
            remain separate from the SkyETA estimate.
          </p>
        ) : null}

        {state.status === "not-configured" ? (
          <p className="skyeta-demo__live-message is-unavailable" role="status">
            {state.message} No substitute or hypothetical flights are shown.
          </p>
        ) : null}

        {state.status === "error" ? (
          <p className="skyeta-demo__live-message is-unavailable" role="status">
            {state.message} No substitute or hypothetical flights are shown.
          </p>
        ) : null}

        {state.status === "empty" ? (
          <p className="skyeta-demo__live-message is-empty" role="status">
            AirLabs returned no current flights for this carrier and route in its
            schedule window. No substitute or hypothetical flights are shown.
          </p>
        ) : null}

        {state.status === "ready" ? (
          <div
            className="skyeta-demo__live-list"
            role="list"
            aria-label={`${prediction.origin} to ${prediction.destination} current flights`}
          >
            {state.flights.map((flight) => (
              <article className="skyeta-demo__live-flight" role="listitem" key={flight.id}>
                <header>
                  <div>
                    <ItemHeading>{liveFlightLabel(flight)}</ItemHeading>
                    <span>
                      {flight.origin} <i aria-hidden="true">→</i>{" "}
                      {flight.destination}
                    </span>
                    {flight.durationMinutes !== null ? (
                      <small>{formatDuration(flight.durationMinutes)}</small>
                    ) : null}
                  </div>
                  <span
                    className={`skyeta-demo__flight-status ${flightStatusTone(flight.status)}`}
                  >
                    {formatFlightStatus(flight.status)}
                  </span>
                </header>
                <div className="skyeta-demo__live-times">
                  <LiveEndpointTimes
                    label="Departure"
                    endpoint={flight.departure}
                    delayMinutes={flight.departureDelayMinutes}
                  />
                  <LiveEndpointTimes
                    label="Arrival"
                    endpoint={flight.arrival}
                    delayMinutes={flight.arrivalDelayMinutes}
                  />
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </div>
    </article>
  );
}

export default function SkyetaDemo({
  headingLevel = "h4",
}: {
  headingLevel?: "h2" | "h4";
}) {
  const BrandHeading = headingLevel;
  const PanelHeading = headingLevel === "h2" ? "h3" : "h5";
  const ItemHeading = headingLevel === "h2" ? "h4" : "h6";
  const [model, setModel] = useState<SkyetaModel | null>(null);
  const [modelState, setModelState] = useState<
    "loading" | "ready" | "unavailable"
  >("loading");
  const [parityState, setParityState] = useState<
    "checking" | "passed" | "failed" | "unavailable"
  >("checking");
  const [presetIndex, setPresetIndex] = useState<number | null>(null);
  const [departureDate, setDepartureDate] = useState(defaultDepartureDate);
  const [departureTime, setDepartureTime] = useState("09:30");
  const [duration, setDuration] = useState("");
  const [distance, setDistance] = useState("");
  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const [formError, setFormError] = useState("");
  const [whatIfOffset, setWhatIfOffset] = useState(0);
  const [liveFlightsState, setLiveFlightsState] = useState<LiveFlightsState>({
    status: "idle",
  });
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [shouldLoad, setShouldLoad] = useState(false);
  const liveRequestController = useRef<AbortController | null>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root || !("IntersectionObserver" in window)) {
      setShouldLoad(true);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setShouldLoad(true);
          observer.disconnect();
        }
      },
      { rootMargin: "700px 0px" },
    );

    observer.observe(root);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!shouldLoad) return;

    const controller = new AbortController();

    async function loadModel() {
      try {
        const response = await fetch("/assets/skyeta-model.json", {
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new Error(`Model request returned ${response.status}.`);
        }

        const parsed = parseModel(await response.json());
        const maximumParityError = parsed.parityCases.reduce(
          (maximumError, parityCase) => {
            const featureMap = Object.fromEntries(
              parsed.featureNames.map((name, index) => [
                name,
                parityCase.features[index],
              ]),
            ) as Record<string, number>;
            const clientProbability = predict(parsed, featureMap);
            return Math.max(
              maximumError,
              Math.abs(clientProbability - parityCase.probability),
            );
          },
          0,
        );
        if (maximumParityError > 1e-10) {
          setParityState("failed");
          throw new Error("SkyETA evaluator verification failed.");
        }

        setModel(parsed);
        setParityState("passed");
        setModelState("ready");
      } catch {
        if (controller.signal.aborted) return;
        setModelState("unavailable");
        setParityState((current) =>
          current === "failed" ? "failed" : "unavailable",
        );
      }
    }

    void loadModel();
    return () => {
      controller.abort();
      liveRequestController.current?.abort();
    };
  }, [shouldLoad]);

  const selectedPreset =
    presetIndex === null ? null : model?.presets[presetIndex] ?? null;
  const routeOptions = useMemo(() => model?.presets ?? [], [model]);
  const inputsComplete = Boolean(
    selectedPreset &&
      departureDate &&
      departureTime &&
      Number(duration) > 0 &&
      Number(distance) > 0,
  );
  function resetPrediction() {
    liveRequestController.current?.abort();
    setPrediction(null);
    setWhatIfOffset(0);
    setLiveFlightsState({ status: "idle" });
    setFormError("");
  }
  function selectPreset(index: number) {
    const nextPreset = model?.presets[index];
    if (!nextPreset) return;
    resetPrediction();
    setPresetIndex(index);
    setDuration(String(Math.round(nextPreset.scheduledDurationMinutes)));
    setDistance(String(Math.round(nextPreset.distanceMiles)));
  }

  async function loadLiveFlights(preset: RoutePreset) {
    liveRequestController.current?.abort();
    const controller = new AbortController();
    liveRequestController.current = controller;
    setLiveFlightsState({ status: "loading" });

    const query = new URLSearchParams({
      origin: preset.origin,
      destination: preset.destination,
      airline: preset.carrier,
    });

    try {
      const response = await fetch(
        `/api/skyeta/live-flights?${query.toString()}`,
        {
          method: "GET",
          headers: { Accept: "application/json" },
          signal: controller.signal,
          cache: "no-store",
        },
      );
      const payload = parseLiveFlightsPayload(await response.json());
      if (
        controller.signal.aborted ||
        liveRequestController.current !== controller
      ) {
        return;
      }

      if (!response.ok) {
        const message = payload.configured
          ? "error" in payload
            ? payload.error.message
            : "Live route data is temporarily unavailable."
          : payload.message;
        setLiveFlightsState({ status: "error", message });
        return;
      }
      if (!payload.configured) {
        setLiveFlightsState({
          status: "not-configured",
          message: payload.message,
        });
        return;
      }
      if ("error" in payload) {
        setLiveFlightsState({
          status: "error",
          message: payload.error.message,
        });
        return;
      }
      if (!payload.flights.length) {
        setLiveFlightsState({
          status: "empty",
          source: payload.source,
          fetchedAt: payload.fetchedAt,
        });
        return;
      }
      setLiveFlightsState({
        status: "ready",
        source: payload.source,
        fetchedAt: payload.fetchedAt,
        flights: payload.flights,
      });
    } catch (error) {
      if (
        controller.signal.aborted ||
        liveRequestController.current !== controller
      ) {
        return;
      }
      setLiveFlightsState({
        status: "error",
        message:
          error instanceof Error && error.message.startsWith("Live route data")
            ? error.message
            : "Live route data is temporarily unavailable.",
      });
    }
  }

  function runPrediction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");

    if (!model || !selectedPreset) {
      setFormError("SkyETA is not ready yet.");
      return;
    }

    try {
      const numericDuration = Number(duration);
      const numericDistance = Number(distance);
      const featureMap = buildFeatureMap(
        model,
        selectedPreset,
        departureDate,
        departureTime,
        numericDuration,
        numericDistance,
      );
      const inferenceStartedAt = performance.now();
      const probability = predict(model, featureMap);
      const inferenceTimeMs = performance.now() - inferenceStartedAt;
      if (!Number.isFinite(probability) || probability < 0 || probability > 1) {
        throw new Error("SkyETA produced an invalid probability.");
      }

      const nearbyWindows = createNearbyWindows(
        model,
        selectedPreset,
        departureDate,
        departureTime,
        numericDuration,
        numericDistance,
      );
      const selectedWindow =
        nearbyWindows.find((window) => window.offsetHours === 0) ??
        nearbyWindows[0];
      const bestWindow = nearbyWindows.reduce(
        (best, candidate) =>
          candidate.probability < best.probability - 1e-12 ? candidate : best,
        selectedWindow,
      );

      const nextPrediction: Prediction = {
        probability,
        carrier: selectedPreset.carrier,
        origin: selectedPreset.origin,
        destination: selectedPreset.destination,
        departure: describeDeparture(departureDate, departureTime),
        departureDate,
        factors: createFactorInsights(
          model,
          selectedPreset,
          featureMap,
          probability,
          bestWindow,
          numericDuration,
          numericDistance,
        ),
        reliability: createReliabilityMetrics(model, selectedPreset),
        nearbyWindows,
        bestWindow,
        networkBaseline: model.rates.global,
        historicalFallbackCount: historicalFallbackCount(model, selectedPreset),
        inferenceTimeMs,
      };

      setPrediction(nextPrediction);
      setWhatIfOffset(0);
      void loadLiveFlights(selectedPreset);
    } catch (error) {
      setFormError(
        error instanceof Error
          ? error.message
          : "SkyETA could not complete this estimate.",
      );
    }
  }

  const probabilityPercent = prediction ? prediction.probability * 100 : 0;
  const probabilityLabel = prediction ? probabilityPercent.toFixed(1) : "--";
  const networkDelta = prediction
    ? prediction.probability - prediction.networkBaseline
    : 0;
  const networkComparison =
    networkDelta > 0
      ? { label: "Above typical pattern", tone: "above" }
      : networkDelta < 0
        ? { label: "Below typical pattern", tone: "below" }
        : { label: "Near typical pattern", tone: "at" };
  const gaugeColor = networkDelta > 0 ? "#facc15" : "#4dff91";
  const inputsDisabled = modelState !== "ready";
  const whatIfWindow =
    prediction?.nearbyWindows.find(
      (window) => window.offsetHours === whatIfOffset,
    ) ?? null;
  const bestWindowReduction = prediction
    ? Math.max(
        0,
        (prediction.probability - prediction.bestWindow.probability) * 100,
      )
    : 0;
  const whatIfDelta =
    prediction && whatIfWindow
      ? (whatIfWindow.probability - prediction.probability) * 100
      : 0;
  return (
    <div
      ref={rootRef}
      className={`skyeta-demo${prediction ? " is-results-active" : ""}`}
    >
      <div className="skyeta-demo__network" aria-hidden="true">
        {Array.from({ length: 14 }, (_, index) => (
          <span key={index} />
        ))}
        <i className="skyeta-demo__radar">
          <em />
          <em />
          <em />
        </i>
        <b className="skyeta-demo__flight-path" />
        <b className="skyeta-demo__flight-path skyeta-demo__flight-path--secondary" />
      </div>

      <header className="skyeta-demo__header">
        <Image
          className="skyeta-demo__logo"
          src="/assets/skyeta-logo-clean.png"
          alt="SkyETA logo"
          width={104}
          height={104}
          unoptimized
        />
        <BrandHeading aria-label="SkyETA">
          {"SkyETA".split("").map((letter, index) => (
            <span key={`${letter}-${index}`}>{letter}</span>
          ))}
        </BrandHeading>
        <p>Flight-delay risk intelligence</p>
        <span className={`skyeta-demo__model-state is-${modelState}`}>
          <i aria-hidden="true" />
          {modelState === "loading"
            ? "Loading SkyETA"
            : modelState === "ready"
              ? "SkyETA ready"
              : "SkyETA unavailable"}
        </span>
      </header>

      <div className="skyeta-demo__signal-flow" aria-label="SkyETA signal flow">
        <div
          className={`skyeta-demo__signal-node ${modelState === "ready" ? "is-complete" : modelState === "unavailable" ? "is-error" : "is-pending"}`}
        >
          <span>01 / SkyETA</span>
          <strong>{modelState === "ready" ? "Ready" : modelState}</strong>
          <small>Flight intelligence engine</small>
        </div>
        <i aria-hidden="true" />
        <div
          className={`skyeta-demo__signal-node ${parityState === "passed" ? "is-complete" : parityState === "failed" || parityState === "unavailable" ? "is-error" : "is-pending"}`}
        >
          <span>02 / Signal check</span>
          <strong>{parityState === "passed" ? "Verified" : parityState}</strong>
          <small>Consistency check</small>
        </div>
        <i aria-hidden="true" />
        <div
          className={`skyeta-demo__signal-node ${inputsComplete ? "is-complete" : "is-pending"}`}
        >
          <span>03 / Inputs</span>
          <strong>{inputsComplete ? "Complete" : "Incomplete"}</strong>
          <small>Route and schedule ready</small>
        </div>
        <i aria-hidden="true" />
        <div
          className={`skyeta-demo__signal-node ${selectedPreset ? "is-complete" : "is-pending"}`}
        >
          <span>04 / Route context</span>
          <strong>{selectedPreset ? "Available" : "--"}</strong>
          <small>Carrier, airport and route patterns</small>
        </div>
        <i aria-hidden="true" />
        <div
          className={`skyeta-demo__signal-node ${prediction ? "is-complete" : "is-pending"}`}
        >
          <span>05 / Analysis</span>
          <strong>
            {prediction
              ? `${prediction.inferenceTimeMs.toFixed(prediction.inferenceTimeMs < 1 ? 2 : 1)} ms`
              : "--"}
          </strong>
          <small>Processed on device</small>
        </div>
        <i aria-hidden="true" />
        <div
          className={`skyeta-demo__signal-node ${prediction ? "is-complete" : "is-pending"}`}
        >
          <span>06 / Estimate</span>
          <strong>{prediction ? `${probabilityLabel}%` : "--"}</strong>
          <small>
            {prediction ? networkComparison.label : "Awaiting calculation"}
          </small>
        </div>
      </div>

      <div className="skyeta-demo__main">
        <div className="skyeta-demo__form-section">
          <form className="skyeta-demo__glass-form" onSubmit={runPrediction}>
            <label className="skyeta-demo__field skyeta-demo__route-field">
              <span>Select Route / Flight Pattern</span>
              <select
                value={presetIndex ?? ""}
                onChange={(event) => {
                  if (event.target.value) selectPreset(Number(event.target.value));
                }}
                disabled={inputsDisabled}
              >
                <option value="" disabled>
                  Choose a route
                </option>
                {routeOptions.length === 0 ? (
                  <option value={0}>Route data loading</option>
                ) : (
                  routeOptions.map((preset, index) => (
                    <option
                      key={`${preset.carrier}-${preset.origin}-${preset.destination}`}
                      value={index}
                    >
                      {preset.carrier} / {preset.origin} to {preset.destination}
                    </option>
                  ))
                )}
              </select>
            </label>

            <div className="skyeta-demo__field-grid">
              <label className="skyeta-demo__field">
                <span>Select Flight Date</span>
                <input
                  type="date"
                  value={departureDate}
                  onChange={(event) => {
                    resetPrediction();
                    setDepartureDate(event.target.value);
                  }}
                  required
                  disabled={inputsDisabled}
                />
              </label>
              <label className="skyeta-demo__field">
                <span>Departure Time</span>
                <input
                  type="time"
                  value={departureTime}
                  onChange={(event) => {
                    resetPrediction();
                    setDepartureTime(event.target.value);
                  }}
                  required
                  disabled={inputsDisabled}
                />
              </label>
              <label className="skyeta-demo__field">
                <span>Duration</span>
                <span className="skyeta-demo__input-unit">
                  <input
                    type="number"
                    min="20"
                    max="900"
                    step="1"
                    inputMode="numeric"
                    value={duration}
                    onChange={(event) => {
                      resetPrediction();
                      setDuration(event.target.value);
                    }}
                    required
                    disabled={inputsDisabled}
                  />
                  <em>min</em>
                </span>
              </label>
              <label className="skyeta-demo__field">
                <span>Distance</span>
                <span className="skyeta-demo__input-unit">
                  <input
                    type="number"
                    min="50"
                    max="6000"
                    step="1"
                    inputMode="numeric"
                    value={distance}
                    onChange={(event) => {
                      resetPrediction();
                      setDistance(event.target.value);
                    }}
                    required
                    disabled={inputsDisabled}
                  />
                  <em>mi</em>
                </span>
              </label>
            </div>

            {selectedPreset ? (
              <p className="skyeta-demo__route-note">
                Selected route pattern: {selectedPreset.carrier}, {selectedPreset.origin} to{" "}
                {selectedPreset.destination}
              </p>
            ) : null}

            <button type="submit" disabled={inputsDisabled || !inputsComplete}>
              {modelState === "loading"
                ? "Loading SkyETA..."
                : modelState === "unavailable"
                  ? "SkyETA Unavailable"
                  : "Calculate Delay Risk"}
            </button>

            {formError ? (
              <p className="skyeta-demo__error" role="alert">
                {formError}
              </p>
            ) : null}
            {modelState === "unavailable" ? (
              <p className="skyeta-demo__error" role="status">
                SkyETA is temporarily unavailable. The project case study remains
                available.
              </p>
            ) : null}
          </form>
        </div>

        {prediction ? (
          <section
            className="skyeta-demo__results"
            key={`${prediction.carrier}-${prediction.origin}-${prediction.destination}-${prediction.departureDate}-${prediction.probability}`}
          >
            <p className="visually-hidden" role="status">
              SkyETA estimate ready: {probabilityLabel}% delay risk for{" "}
              {prediction.origin} to {prediction.destination}.
            </p>
            <article className="skyeta-demo__result-card">
              <PanelHeading>
                <span aria-hidden="true">i</span> Flight Pattern &amp; Delay-Risk
                Estimate
              </PanelHeading>

              <div className="skyeta-demo__risk-summary">
                <span className={`is-${networkComparison.tone}`}>
                  {networkComparison.label}
                </span>
                <p>
                  {networkDelta === 0
                    ? "This estimate is close to the typical SkyETA pattern."
                    : `This route and schedule pattern sits ${networkDelta > 0 ? "above" : "below"} the typical SkyETA pattern.`}
                </p>
              </div>

              <div className="skyeta-demo__result-grid">
                <div className="skyeta-demo__facts">
                  <p>
                    <strong>Carrier:</strong>
                    <span>{prediction.carrier}</span>
                  </p>
                  <p>
                    <strong>Route:</strong>
                    <span className="skyeta-demo__route">
                      {prediction.origin}
                      <i aria-hidden="true" />
                      {prediction.destination}
                    </span>
                  </p>
                  <p>
                    <strong>Scheduled Departure:</strong>
                    <span>{prediction.departure}</span>
                  </p>
                  <p>
                    <strong>Pattern comparison:</strong>
                    <span className={`skyeta-demo__baseline is-${networkComparison.tone}`}>
                      {networkComparison.label}
                    </span>
                  </p>
                </div>

                <div className="skyeta-demo__gauge-card">
                  <span>Delay-Risk Estimate</span>
                  <div
                    className="skyeta-demo__gauge-window"
                    role="meter"
                    aria-label="Estimated arrival-delay probability"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Number(probabilityPercent.toFixed(1))}
                  >
                    <div
                      className="skyeta-demo__gauge-dial"
                      style={{
                        background: `conic-gradient(from 270deg, ${gaugeColor} 0deg ${probabilityPercent * 1.8}deg, rgba(255,255,255,0.12) ${probabilityPercent * 1.8}deg 180deg, transparent 180deg 360deg)`,
                      }}
                    />
                    <i
                      className="skyeta-demo__gauge-needle"
                      style={{
                        transform: `rotate(${180 + probabilityPercent * 1.8}deg)`,
                      }}
                    />
                    <i
                      className="skyeta-demo__gauge-baseline"
                      style={{
                        transform: `rotate(${180 + prediction.networkBaseline * 180}deg)`,
                      }}
                    />
                    <strong>{probabilityLabel}%</strong>
                  </div>
                  <div className="skyeta-demo__gauge-scale" aria-hidden="true">
                    <span>0</span>
                    <span>Typical SkyETA pattern</span>
                    <span>100</span>
                  </div>
                </div>
              </div>

              <div className="skyeta-demo__prediction-row">
                <strong>Delay-risk estimate for {prediction.departureDate}:</strong>
                <span className={`skyeta-demo__baseline is-${networkComparison.tone}`}>
                  {probabilityLabel}% / {networkComparison.label}
                </span>
              </div>
            </article>

            <div className="skyeta-demo__intelligence-grid">
              <article className="skyeta-demo__insight-card">
                <div className="skyeta-demo__module-heading">
                  <div>
                    <span>SkyETA analysis</span>
                    <PanelHeading>Strongest signals</PanelHeading>
                  </div>
                  <i aria-hidden="true">01</i>
                </div>
                <p className="skyeta-demo__module-intro">
                  See how the selected schedule and route compare with nearby
                  patterns considered by SkyETA.
                </p>
                <ol className="skyeta-demo__factor-list">
                  {prediction.factors.map((factor, index) => {
                    const pointChange = Math.abs(factor.delta * 100);
                    const tone =
                      factor.delta > 0.0005
                        ? "raises"
                        : factor.delta < -0.0005
                          ? "lowers"
                          : "neutral";
                    const changeLabel =
                      tone === "neutral"
                        ? "Close to comparison"
                        : `${tone === "raises" ? "+" : "-"}${pointChange.toFixed(1)} pts`;

                    return (
                      <li key={`${factor.label}-${index}`}>
                        <span>{String(index + 1).padStart(2, "0")}</span>
                        <div>
                          <strong>{factor.label}</strong>
                          <small>{factor.comparison}</small>
                        </div>
                        <em className={`is-${tone}`}>{changeLabel}</em>
                      </li>
                    );
                  })}
                </ol>
                <small className="skyeta-demo__method-note">
                  Shows how the estimate changes when one flight detail changes.
                </small>
              </article>

              <article className="skyeta-demo__reliability-card">
                <div className="skyeta-demo__module-heading">
                  <div>
                    <span>Route profile</span>
                    <PanelHeading>Route punctuality</PanelHeading>
                  </div>
                  <i aria-hidden="true">02</i>
                </div>
                <p className="skyeta-demo__module-intro">
                  SkyETA’s punctuality profile for the selected flight context.
                </p>
                <div className="skyeta-demo__reliability-list">
                  {prediction.reliability.map((metric) => {
                    const reliabilityPercent = Math.round(metric.reliability * 100);
                    return (
                      <div key={`${metric.label}-${metric.code}`}>
                        <p>
                          <span>
                            {metric.label} <small>{metric.code}</small>
                          </span>
                          <strong>{reliabilityPercent}%</strong>
                        </p>
                        <div aria-hidden="true">
                          <span style={{ width: `${reliabilityPercent}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </article>
            </div>

            <LiveRouteBoard
              state={liveFlightsState}
              prediction={prediction}
              panelHeading={PanelHeading}
              itemHeading={ItemHeading}
            />

            <article className="skyeta-demo__window-card">
              <div className="skyeta-demo__window-heading">
                <div>
                  <span>Schedule explorer</span>
                  <PanelHeading>Nearby time comparison</PanelHeading>
                  <p>
                    Seven nearby departure times compared by SkyETA. These are
                    schedule scenarios, not bookable flights.
                  </p>
                </div>
                <div className="skyeta-demo__window-recommendation">
                  <span>
                    {bestWindowReduction >= 0.1
                      ? "Lowest SkyETA estimate"
                      : "No material nearby difference"}
                  </span>
                  <strong>
                    {bestWindowReduction >= 0.1
                      ? prediction.bestWindow.label
                      : "Selected schedule"}
                  </strong>
                  <small>
                    {bestWindowReduction >= 0.1
                      ? `${bestWindowReduction.toFixed(1)} points below selected time`
                      : "Differences under 0.1 point are not ranked"}
                  </small>
                </div>
              </div>

              <div className="skyeta-demo__what-if">
                <label htmlFor="skyeta-what-if">
                  <span>Quick what-if</span>
                  <strong>
                    {whatIfOffset === 0
                      ? "Selected time"
                      : `${Math.abs(whatIfOffset)}h ${whatIfOffset < 0 ? "earlier" : "later"}`}
                  </strong>
                </label>
                <input
                  id="skyeta-what-if"
                  type="range"
                  min="-3"
                  max="3"
                  step="1"
                  value={whatIfOffset}
                  onChange={(event) => setWhatIfOffset(Number(event.target.value))}
                  aria-describedby="skyeta-what-if-result"
                />
                <div className="skyeta-demo__what-if-scale" aria-hidden="true">
                  <span>-3h</span>
                  <span>Selected</span>
                  <span>+3h</span>
                </div>
                {whatIfWindow ? (
                  <output id="skyeta-what-if-result" htmlFor="skyeta-what-if">
                    <span>{whatIfWindow.label}</span>
                    <strong>{(whatIfWindow.probability * 100).toFixed(1)}%</strong>
                    <small>
                      {Math.abs(whatIfDelta) < 0.05
                        ? "Current estimate"
                        : `${Math.abs(whatIfDelta).toFixed(1)} points ${whatIfDelta < 0 ? "lower" : "higher"}`}
                    </small>
                  </output>
                ) : null}
              </div>
            </article>

            <p className="skyeta-demo__method-note skyeta-demo__result-disclaimer">
              SkyETA provides an estimate, not live flight status or travel advice.
            </p>
          </section>
        ) : null}
      </div>
    </div>
  );
}
