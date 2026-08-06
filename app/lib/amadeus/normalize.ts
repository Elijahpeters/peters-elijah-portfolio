import type {
  AirlineSummary,
  AirportSummary,
  BaggageAllowance,
  FareConditions,
  FlightOffer,
  FlightPassengerSummary,
  FlightSegment,
  FlightSlice,
  FlightStop,
  Money,
} from "../../types/flight-booking.ts";
import type { AmadeusMode } from "./client.ts";
import airportSource from "../skyeta/us-airports.json" with { type: "json" };

const IATA_AIRPORT = /^[A-Z]{3}$/;
const IATA_AIRLINE = /^[A-Z0-9]{2}$/;
const ISO_CURRENCY = /^[A-Z]{3}$/;
const MONEY_AMOUNT = /^(?:0|[1-9]\d*)(?:\.\d{1,6})?$/;
const PROVIDER_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?$/;
const ISO_DURATION = /^P(?=\d|T\d)(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?$/;

type Dictionaries = {
  carriers: Record<string, string>;
  aircraft: Record<string, string>;
  locations: Record<string, Record<string, unknown>>;
};

type LocalAirport = {
  name: string | null;
  cityName: string | null;
  countryCode: string | null;
  timeZone: string | null;
  latitude: number;
  longitude: number;
};

const localAirports = airportSource as Record<string, LocalAirport>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown, maxLength = 500): string | null {
  return typeof value === "string" &&
    value.length > 0 &&
    value.length <= maxLength
    ? value
    : null;
}

function patternedString(
  value: unknown,
  pattern: RegExp,
  maxLength = 500,
): string | null {
  const text = stringValue(value, maxLength);
  return text && pattern.test(text) ? text : null;
}

function dictionaries(value: unknown): Dictionaries {
  if (!isRecord(value)) {
    return { carriers: {}, aircraft: {}, locations: {} };
  }
  const strings = (entry: unknown): Record<string, string> => {
    if (!isRecord(entry)) return {};
    return Object.fromEntries(
      Object.entries(entry).filter(
        (item): item is [string, string] =>
          item[0].length <= 20 &&
          typeof item[1] === "string" &&
          item[1].length > 0 &&
          item[1].length <= 200,
      ),
    );
  };
  const locations: Record<string, Record<string, unknown>> = {};
  if (isRecord(value.locations)) {
    for (const [key, entry] of Object.entries(value.locations)) {
      if (key.length <= 20 && isRecord(entry)) locations[key] = entry;
    }
  }
  return {
    carriers: strings(value.carriers),
    aircraft: strings(value.aircraft),
    locations,
  };
}

export function compactAmadeusDictionaries(
  value: unknown,
  source: unknown,
): Dictionaries {
  const lookup = dictionaries(source);
  const carrierCodes = new Set<string>();
  const aircraftCodes = new Set<string>();
  const locationCodes = new Set<string>();
  const addCarrier = (entry: unknown) => {
    const code = patternedString(entry, IATA_AIRLINE, 2);
    if (code) carrierCodes.add(code);
  };
  const addAircraft = (entry: unknown) => {
    const code = patternedString(entry, /^[A-Z0-9]{1,5}$/, 5);
    if (code) aircraftCodes.add(code);
  };
  const addLocation = (entry: unknown) => {
    const code = patternedString(entry, IATA_AIRPORT, 3);
    if (code) locationCodes.add(code);
  };

  if (isRecord(value)) {
    if (Array.isArray(value.validatingAirlineCodes)) {
      for (const code of value.validatingAirlineCodes) addCarrier(code);
    }
    if (Array.isArray(value.itineraries)) {
      for (const itinerary of value.itineraries) {
        if (!isRecord(itinerary) || !Array.isArray(itinerary.segments)) continue;
        for (const currentSegment of itinerary.segments) {
          if (!isRecord(currentSegment)) continue;
          addCarrier(currentSegment.carrierCode);
          if (isRecord(currentSegment.operating)) {
            addCarrier(currentSegment.operating.carrierCode);
          }
          if (isRecord(currentSegment.aircraft)) {
            addAircraft(currentSegment.aircraft.code);
          }
          if (isRecord(currentSegment.departure)) {
            addLocation(currentSegment.departure.iataCode);
          }
          if (isRecord(currentSegment.arrival)) {
            addLocation(currentSegment.arrival.iataCode);
          }
          if (Array.isArray(currentSegment.stops)) {
            for (const currentStop of currentSegment.stops) {
              if (isRecord(currentStop)) addLocation(currentStop.iataCode);
            }
          }
        }
      }
    }
  }

  const carriers = Object.fromEntries(
    [...carrierCodes]
      .filter((code) => lookup.carriers[code])
      .map((code) => [code, lookup.carriers[code]]),
  );
  const aircraft = Object.fromEntries(
    [...aircraftCodes]
      .filter((code) => lookup.aircraft[code])
      .map((code) => [code, lookup.aircraft[code]]),
  );
  const locations: Dictionaries["locations"] = {};
  for (const code of locationCodes) {
    const entry = lookup.locations[code];
    if (!entry) continue;
    const cityCode = patternedString(entry.cityCode, IATA_AIRPORT, 3);
    const countryCode = patternedString(entry.countryCode, /^[A-Z]{2}$/, 2);
    locations[code] = {
      ...(cityCode ? { cityCode } : {}),
      ...(countryCode ? { countryCode } : {}),
    };
  }
  return { carriers, aircraft, locations };
}

function money(amount: unknown, currency: unknown): Money | null {
  const safeAmount = patternedString(amount, MONEY_AMOUNT, 50);
  const safeCurrency = patternedString(currency, ISO_CURRENCY, 3);
  return safeAmount && safeCurrency
    ? { amount: safeAmount, currency: safeCurrency }
    : null;
}

function airport(value: unknown, lookup: Dictionaries): AirportSummary | null {
  if (!isRecord(value)) return null;
  const iataCode = patternedString(value.iataCode, IATA_AIRPORT, 3);
  if (!iataCode) return null;
  const location = lookup.locations[iataCode] ?? {};
  const local = localAirports[iataCode];
  return {
    iataCode,
    name: local?.name ?? null,
    cityName: local?.cityName ?? stringValue(location.cityCode, 3),
    countryCode:
      local?.countryCode ??
      patternedString(location.countryCode, /^[A-Z]{2}$/, 2),
    timeZone: local?.timeZone ?? null,
    latitude: local?.latitude ?? null,
    longitude: local?.longitude ?? null,
  };
}

function distanceKilometres(
  origin: AirportSummary,
  destination: AirportSummary,
): number | null {
  if (
    origin.latitude === null ||
    origin.longitude === null ||
    destination.latitude === null ||
    destination.longitude === null
  ) {
    return null;
  }
  const radians = (degrees: number) => (degrees * Math.PI) / 180;
  const latitudeDelta = radians(destination.latitude - origin.latitude);
  const longitudeDelta = radians(destination.longitude - origin.longitude);
  const originLatitude = radians(origin.latitude);
  const destinationLatitude = radians(destination.latitude);
  const haversine =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(originLatitude) *
      Math.cos(destinationLatitude) *
      Math.sin(longitudeDelta / 2) ** 2;
  const distance = 2 * 6_371.0088 * Math.asin(Math.min(1, Math.sqrt(haversine)));
  return Number.isFinite(distance) && distance > 0 ? distance : null;
}

function airline(codeValue: unknown, lookup: Dictionaries): AirlineSummary | null {
  const code = patternedString(codeValue, IATA_AIRLINE, 2);
  if (!code) return null;
  return {
    iataCode: code,
    name: lookup.carriers[code] ?? code,
    logoUrl: null,
    conditionsOfCarriageUrl: null,
  };
}

function fareDetailsBySegment(
  offer: Record<string, unknown>,
): Map<string, Array<Record<string, unknown>>> {
  const result = new Map<string, Array<Record<string, unknown>>>();
  if (!Array.isArray(offer.travelerPricings)) return result;
  for (const traveler of offer.travelerPricings) {
    if (!isRecord(traveler) || !Array.isArray(traveler.fareDetailsBySegment)) {
      continue;
    }
    for (const detail of traveler.fareDetailsBySegment) {
      if (!isRecord(detail)) continue;
      const segmentId = stringValue(detail.segmentId, 100);
      if (!segmentId) continue;
      const current = result.get(segmentId) ?? [];
      current.push({ ...detail, travelerId: traveler.travelerId });
      result.set(segmentId, current);
    }
  }
  return result;
}

function baggage(
  segmentId: string,
  details: Map<string, Array<Record<string, unknown>>>,
): BaggageAllowance[] {
  const result: BaggageAllowance[] = [];
  for (const detail of details.get(segmentId) ?? []) {
    if (!isRecord(detail.includedCheckedBags)) continue;
    const quantity = detail.includedCheckedBags.quantity;
    const safeQuantity =
      typeof quantity !== "number" ||
      !Number.isInteger(quantity) ||
      quantity < 0 ||
      quantity > 20
        ? null
        : quantity;
    const rawWeight = detail.includedCheckedBags.weight;
    const rawWeightUnit = detail.includedCheckedBags.weightUnit;
    const safeWeight =
      typeof rawWeight === "number" &&
      Number.isFinite(rawWeight) &&
      rawWeight > 0 &&
      rawWeight <= 100
        ? rawWeight
        : null;
    const weightKilograms =
      safeWeight === null
        ? null
        : rawWeightUnit === "KG"
          ? safeWeight
          : rawWeightUnit === "LB"
            ? Number((safeWeight * 0.45359237).toFixed(2))
            : null;
    if (safeQuantity === null && weightKilograms === null) continue;
    result.push({
      passengerId: stringValue(detail.travelerId, 100),
      segmentId,
      type: "checked",
      providerType: "checked",
      quantity: safeQuantity,
      weightKilograms,
    });
  }
  return result;
}

function stop(value: unknown, lookup: Dictionaries): FlightStop | null {
  if (!isRecord(value)) return null;
  const stopAirport = airport({ iataCode: value.iataCode }, lookup);
  if (!stopAirport) return null;
  return {
    id: null,
    airport: stopAirport,
    arrivingAt: patternedString(value.arrivalAt, PROVIDER_DATETIME, 50),
    departingAt: patternedString(value.departureAt, PROVIDER_DATETIME, 50),
    duration: patternedString(value.duration, ISO_DURATION, 50),
  };
}

function segment(
  value: unknown,
  lookup: Dictionaries,
  details: Map<string, Array<Record<string, unknown>>>,
): FlightSegment | null {
  if (!isRecord(value)) return null;
  const id = stringValue(value.id, 100);
  const origin = airport(value.departure, lookup);
  const destination = airport(value.arrival, lookup);
  const departingAt = isRecord(value.departure)
    ? patternedString(value.departure.at, PROVIDER_DATETIME, 50)
    : null;
  const arrivingAt = isRecord(value.arrival)
    ? patternedString(value.arrival.at, PROVIDER_DATETIME, 50)
    : null;
  const marketingCarrier = airline(value.carrierCode, lookup);
  const operatingCarrier = isRecord(value.operating)
    ? airline(value.operating.carrierCode, lookup) ?? marketingCarrier
    : marketingCarrier;
  if (
    !id ||
    !origin ||
    !destination ||
    !departingAt ||
    !arrivingAt ||
    !marketingCarrier ||
    !operatingCarrier
  ) {
    return null;
  }

  const firstFareDetail = details.get(id)?.[0];
  const aircraftCode = isRecord(value.aircraft)
    ? patternedString(value.aircraft.code, /^[A-Z0-9]{1,5}$/, 5)
    : null;
  const stops = Array.isArray(value.stops)
    ? value.stops
        .map((entry) => stop(entry, lookup))
        .filter((entry): entry is FlightStop => entry !== null)
    : [];

  return {
    id,
    origin,
    destination,
    departingAt,
    arrivingAt,
    duration: patternedString(value.duration, ISO_DURATION, 50),
    distanceKilometres: distanceKilometres(origin, destination),
    originTerminal: isRecord(value.departure)
      ? stringValue(value.departure.terminal, 20)
      : null,
    destinationTerminal: isRecord(value.arrival)
      ? stringValue(value.arrival.terminal, 20)
      : null,
    marketingCarrier,
    operatingCarrier,
    marketingFlightNumber: stringValue(value.number, 20),
    operatingFlightNumber: isRecord(value.operating)
      ? stringValue(value.operating.flightNumber, 20)
      : null,
    aircraftName: aircraftCode
      ? lookup.aircraft[aircraftCode] ?? aircraftCode
      : null,
    cabinClass: firstFareDetail
      ? stringValue(firstFareDetail.cabin, 50)?.toLowerCase() ?? null
      : null,
    cabinName: firstFareDetail
      ? stringValue(firstFareDetail.cabin, 50)?.toLowerCase() ?? null
      : null,
    fareBrandName: firstFareDetail
      ? stringValue(
          firstFareDetail.brandedFareLabel ?? firstFareDetail.brandedFare,
          100,
        )
      : null,
    stops,
    baggage: baggage(id, details),
  };
}

function slice(
  value: unknown,
  index: number,
  lookup: Dictionaries,
  details: Map<string, Array<Record<string, unknown>>>,
): FlightSlice | null {
  if (!isRecord(value) || !Array.isArray(value.segments) || value.segments.length === 0) {
    return null;
  }
  const segments = value.segments
    .map((entry) => segment(entry, lookup, details))
    .filter((entry): entry is FlightSegment => entry !== null);
  if (segments.length !== value.segments.length) return null;
  return {
    id: `ama_slice_${index + 1}_${segments[0].id}`,
    origin: segments[0].origin,
    destination: segments[segments.length - 1].destination,
    duration: patternedString(value.duration, ISO_DURATION, 50),
    connectionCount: Math.max(0, segments.length - 1),
    segments,
  };
}

function passengerType(value: unknown): FlightPassengerSummary["type"] | null {
  if (value === "ADULT") return "adult";
  if (value === "CHILD") return "child";
  if (value === "HELD_INFANT") return "infant_without_seat";
  if (value === "SEATED_INFANT") return "infant_with_seat";
  return null;
}

function passengers(offer: Record<string, unknown>): FlightPassengerSummary[] {
  if (!Array.isArray(offer.travelerPricings)) return [];
  const result: FlightPassengerSummary[] = [];
  for (const traveler of offer.travelerPricings) {
    if (!isRecord(traveler)) continue;
    const id = stringValue(traveler.travelerId, 100);
    const type = passengerType(traveler.travelerType);
    if (id && type) result.push({ id, type });
  }
  return result;
}

function uniqueAirlines(owner: AirlineSummary, slices: FlightSlice[]) {
  const result = new Map<string, AirlineSummary>();
  const add = (entry: AirlineSummary) => {
    const key = `${entry.iataCode ?? ""}|${entry.name}`;
    if (!result.has(key)) result.set(key, entry);
  };
  add(owner);
  for (const currentSlice of slices) {
    for (const currentSegment of currentSlice.segments) {
      add(currentSegment.marketingCarrier);
      add(currentSegment.operatingCarrier);
    }
  }
  return [...result.values()];
}

function totalEmissions(offer: Record<string, unknown>): number | null {
  if (!Array.isArray(offer.itineraries)) return null;
  let total = 0;
  let found = false;
  for (const itinerary of offer.itineraries) {
    if (!isRecord(itinerary) || !Array.isArray(itinerary.segments)) continue;
    for (const currentSegment of itinerary.segments) {
      if (!isRecord(currentSegment) || !Array.isArray(currentSegment.co2Emissions)) {
        continue;
      }
      for (const emission of currentSegment.co2Emissions) {
        if (!isRecord(emission) || emission.weightUnit !== "KG") continue;
        if (
          typeof emission.weight === "number" &&
          Number.isFinite(emission.weight) &&
          emission.weight >= 0
        ) {
          total += emission.weight;
          found = true;
        }
      }
    }
  }
  return found ? total : null;
}

const unknownConditions: FareConditions = {
  changeBeforeDeparture: { status: "unknown", penalty: null },
  refundBeforeDeparture: { status: "unknown", penalty: null },
};

function fareRuleFromAmadeus(
  fareRules: Record<string, unknown>,
  category: "EXCHANGE" | "REFUND",
): FareConditions["changeBeforeDeparture"] {
  if (!Array.isArray(fareRules.rules)) {
    return { status: "unknown", penalty: null };
  }
  const candidates = fareRules.rules.filter((entry) => {
    if (!isRecord(entry) || entry.category !== category) return false;
    if (entry.circumstances === undefined || entry.circumstances === null) {
      return true;
    }
    return (
      typeof entry.circumstances === "string" &&
      entry.circumstances.trim().length === 0
    );
  });
  if (candidates.length === 0) {
    return { status: "unknown", penalty: null };
  }
  if (candidates.some((entry) => entry.notApplicable === true)) {
    return { status: "not_allowed", penalty: null };
  }
  const permitted = candidates.filter(
    (entry) =>
      entry.notApplicable === false ||
      patternedString(entry.maxPenaltyAmount, MONEY_AMOUNT, 50) !== null,
  );
  if (permitted.length === 0) {
    return { status: "unknown", penalty: null };
  }
  const currency = patternedString(fareRules.currency, ISO_CURRENCY, 3);
  const penalties = currency
    ? permitted
        .map((entry) => money(entry.maxPenaltyAmount, currency))
        .filter((entry): entry is Money => entry !== null)
    : [];
  const penalty = penalties.reduce<Money | null>((largest, current) => {
    if (!largest) return current;
    return Number(current.amount) > Number(largest.amount) ? current : largest;
  }, null);
  return { status: "allowed", penalty };
}

function fareConditions(offer: Record<string, unknown>): FareConditions {
  if (!isRecord(offer.fareRules)) return unknownConditions;
  return {
    changeBeforeDeparture: fareRuleFromAmadeus(offer.fareRules, "EXCHANGE"),
    refundBeforeDeparture: fareRuleFromAmadeus(offer.fareRules, "REFUND"),
  };
}

export function normalizeAmadeusOffer(options: {
  value: unknown;
  dictionaries?: unknown;
  configuredMode: AmadeusMode;
  cacheId: string;
  now: Date;
  expiresAt: Date;
}): FlightOffer | null {
  if (!isRecord(options.value)) return null;
  const offer = options.value;
  const lookup = dictionaries(options.dictionaries);
  const price = isRecord(offer.price) ? offer.price : null;
  const total = price
    ? money(price.grandTotal ?? price.total, price.currency)
    : null;
  const base = price ? money(price.base, price.currency) : null;
  if (!total || !Array.isArray(offer.itineraries) || offer.itineraries.length === 0) {
    return null;
  }

  const details = fareDetailsBySegment(offer);
  const slices = offer.itineraries
    .map((entry, index) => slice(entry, index, lookup, details))
    .filter((entry): entry is FlightSlice => entry !== null);
  if (slices.length !== offer.itineraries.length) return null;
  const ownerCode =
    Array.isArray(offer.validatingAirlineCodes) &&
    typeof offer.validatingAirlineCodes[0] === "string"
      ? offer.validatingAirlineCodes[0]
      : slices[0].segments[0].marketingCarrier.iataCode;
  const owner = airline(ownerCode, lookup);
  if (!owner) return null;

  const normalizedPassengers = passengers(offer);
  if (normalizedPassengers.length === 0) return null;
  const isLive = options.configuredMode === "live";
  const availableSeats = offer.numberOfBookableSeats;
  const providerBookable =
    typeof availableSeats !== "number" || availableSeats > 0;
  const offerBaggage = slices.flatMap((entry) =>
    entry.segments.flatMap((currentSegment) => currentSegment.baggage),
  );

  return {
    id: options.cacheId,
    source: {
      provider: "amadeus",
      environment: isLive ? "live" : "test",
      isLive,
      label: isLive ? "Live fare" : "Test fare",
    },
    isBookable: isLive && providerBookable,
    expiresAt: options.expiresAt.toISOString(),
    createdAt: options.now.toISOString(),
    updatedAt: options.now.toISOString(),
    total,
    base,
    tax: null,
    totalEmissionsKg: totalEmissions(offer),
    owner,
    airlines: uniqueAirlines(owner, slices),
    slices,
    connectionCount: slices.reduce(
      (count, entry) => count + entry.connectionCount,
      0,
    ),
    baggage: offerBaggage,
    fareConditions: fareConditions(offer),
    passengers: normalizedPassengers,
    passengerCount: normalizedPassengers.length,
    passengerIdentityDocumentsRequired: false,
    supportedIdentityDocumentTypes: [],
    priceGuaranteeExpiresAt: null,
    paymentRequiredBy: null,
  };
}
