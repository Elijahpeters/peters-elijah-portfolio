import type {
  AirlineSummary,
  AirportSummary,
  BaggageAllowance,
  FareConditions,
  FareRule,
  FlightOffer,
  FlightPassengerSummary,
  FlightSegment,
  FlightSlice,
  FlightStop,
  Money,
} from "../../types/flight-booking";
import type {
  DuffelAirline,
  DuffelAirport,
  DuffelBaggage,
  DuffelCondition,
  DuffelMode,
  DuffelOffer,
  DuffelSegment,
  DuffelSegmentPassenger,
  DuffelSlice,
  DuffelStop,
} from "./contracts";

const IATA_AIRPORT = /^[A-Z]{3}$/;
const IATA_AIRLINE = /^[A-Z0-9]{2}$/;
const ISO_CURRENCY = /^[A-Z]{3}$/;
const MONEY_AMOUNT = /^(?:0|[1-9]\d*)(?:\.\d{1,6})?$/;
const DUFFEL_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?$/;
const ISO_DURATION = /^P(?=\d|T\d)(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?$/;

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
  return text !== null && pattern.test(text) ? text : null;
}

function safeUrl(value: unknown): string | null {
  const text = stringValue(value, 2_000);
  if (!text) return null;
  try {
    const url = new URL(text);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function safeCoordinate(value: unknown, minimum: number, maximum: number) {
  return typeof value === "number" &&
    Number.isFinite(value) &&
    value >= minimum &&
    value <= maximum
    ? value
    : null;
}

function airport(value: unknown): AirportSummary | null {
  if (!isRecord(value)) return null;
  const source = value as DuffelAirport;
  const iataCode = patternedString(source.iata_code, IATA_AIRPORT, 3);
  if (!iataCode) return null;
  return {
    iataCode,
    name: stringValue(source.name, 200),
    cityName: stringValue(source.city_name, 200),
    countryCode: patternedString(source.iata_country_code, /^[A-Z]{2}$/, 2),
    timeZone: patternedString(source.time_zone, /^[A-Za-z_+-]+(?:\/[A-Za-z_+-]+)*$/, 100),
    latitude: safeCoordinate(source.latitude, -90, 90),
    longitude: safeCoordinate(source.longitude, -180, 180),
  };
}

function airline(value: unknown): AirlineSummary | null {
  if (!isRecord(value)) return null;
  const source = value as DuffelAirline;
  const name = stringValue(source.name, 200);
  if (!name) return null;
  return {
    iataCode: patternedString(source.iata_code, IATA_AIRLINE, 2),
    name,
    logoUrl: safeUrl(source.logo_symbol_url),
    conditionsOfCarriageUrl: safeUrl(source.conditions_of_carriage_url),
  };
}

function money(amount: unknown, currency: unknown): Money | null {
  const safeAmount = patternedString(amount, MONEY_AMOUNT, 50);
  const safeCurrency = patternedString(currency, ISO_CURRENCY, 3);
  return safeAmount && safeCurrency
    ? { amount: safeAmount, currency: safeCurrency }
    : null;
}

function fareRule(value: unknown): FareRule {
  if (!isRecord(value)) return { status: "unknown", penalty: null };
  const condition = value as DuffelCondition;
  const status =
    condition.allowed === true
      ? "allowed"
      : condition.allowed === false
        ? "not_allowed"
        : "unknown";
  return {
    status,
    penalty: money(condition.penalty_amount, condition.penalty_currency),
  };
}

function fareConditions(offer: DuffelOffer): FareConditions {
  return {
    changeBeforeDeparture: fareRule(
      offer.conditions?.change_before_departure,
    ),
    refundBeforeDeparture: fareRule(
      offer.conditions?.refund_before_departure,
    ),
  };
}

function baggageType(value: string): BaggageAllowance["type"] {
  if (value === "carry_on" || value === "checked") return value;
  return "other";
}

function passengerBaggage(
  value: unknown,
  segmentId: string,
): BaggageAllowance[] {
  if (!Array.isArray(value)) return [];
  const result: BaggageAllowance[] = [];
  for (const entry of value) {
    if (!isRecord(entry)) continue;
    const passenger = entry as DuffelSegmentPassenger;
    const passengerId = stringValue(passenger.passenger_id, 200);
    if (!Array.isArray(passenger.baggages)) continue;
    for (const rawBaggage of passenger.baggages) {
      if (!isRecord(rawBaggage)) continue;
      const baggage = rawBaggage as DuffelBaggage;
      const providerType = stringValue(baggage.type, 100);
      const quantity = baggage.quantity;
      if (
        !providerType ||
        typeof quantity !== "number" ||
        !Number.isInteger(quantity) ||
        quantity < 0 ||
        quantity > 20
      ) {
        continue;
      }
      result.push({
        passengerId,
        segmentId,
        type: baggageType(providerType),
        providerType,
        quantity,
      });
    }
  }
  return result;
}

function stop(value: unknown): FlightStop | null {
  if (!isRecord(value)) return null;
  const source = value as DuffelStop;
  const stopAirport = airport(source.airport);
  if (!stopAirport) return null;
  return {
    id: stringValue(source.id, 200),
    airport: stopAirport,
    arrivingAt: patternedString(source.arriving_at, DUFFEL_DATETIME, 50),
    departingAt: patternedString(source.departing_at, DUFFEL_DATETIME, 50),
    duration: patternedString(source.duration, ISO_DURATION, 50),
  };
}

function segment(value: unknown): FlightSegment | null {
  if (!isRecord(value)) return null;
  const source = value as DuffelSegment;
  const id = stringValue(source.id, 200);
  const origin = airport(source.origin);
  const destination = airport(source.destination);
  const departingAt = patternedString(
    source.departing_at,
    DUFFEL_DATETIME,
    50,
  );
  const arrivingAt = patternedString(
    source.arriving_at,
    DUFFEL_DATETIME,
    50,
  );
  const marketingCarrier = airline(source.marketing_carrier);
  const operatingCarrier = airline(source.operating_carrier);
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

  const firstPassenger =
    Array.isArray(source.passengers) && isRecord(source.passengers[0])
      ? (source.passengers[0] as DuffelSegmentPassenger)
      : null;
  const cabin = firstPassenger?.cabin;
  const distance =
    typeof source.distance === "string" ? Number(source.distance) : NaN;
  const stops = Array.isArray(source.stops)
    ? source.stops
        .map((entry) => stop(entry))
        .filter((entry): entry is FlightStop => entry !== null)
    : [];

  return {
    id,
    origin,
    destination,
    departingAt,
    arrivingAt,
    duration: patternedString(source.duration, ISO_DURATION, 50),
    distanceKilometres:
      Number.isFinite(distance) && distance >= 0 && distance <= 50_000
        ? distance
        : null,
    originTerminal: stringValue(source.origin_terminal, 50),
    destinationTerminal: stringValue(source.destination_terminal, 50),
    marketingCarrier,
    operatingCarrier,
    marketingFlightNumber: stringValue(
      source.marketing_carrier_flight_number,
      20,
    ),
    operatingFlightNumber: stringValue(
      source.operating_carrier_flight_number,
      20,
    ),
    aircraftName:
      isRecord(source.aircraft) && typeof source.aircraft.name === "string"
        ? stringValue(source.aircraft.name, 200)
        : null,
    cabinClass: stringValue(firstPassenger?.cabin_class, 100),
    cabinName:
      cabin && typeof cabin === "object"
        ? stringValue(cabin.name, 100)
        : null,
    fareBrandName:
      (cabin && typeof cabin === "object"
        ? stringValue(cabin.marketing_name, 200)
        : null) ??
      stringValue(firstPassenger?.cabin_class_marketing_name, 200),
    stops,
    baggage: passengerBaggage(source.passengers, id),
  };
}

function slice(value: unknown): FlightSlice | null {
  if (!isRecord(value)) return null;
  const source = value as DuffelSlice;
  const id = stringValue(source.id, 200);
  if (!id || !Array.isArray(source.segments) || source.segments.length === 0) {
    return null;
  }
  const segments = source.segments
    .map((entry) => segment(entry))
    .filter((entry): entry is FlightSegment => entry !== null);
  if (segments.length !== source.segments.length) return null;

  const origin = airport(source.origin) ?? segments[0].origin;
  const destination =
    airport(source.destination) ?? segments[segments.length - 1].destination;
  return {
    id,
    origin,
    destination,
    duration: patternedString(source.duration, ISO_DURATION, 50),
    connectionCount: Math.max(0, segments.length - 1),
    segments,
  };
}

function uniqueAirlines(
  owner: AirlineSummary,
  slices: FlightSlice[],
): AirlineSummary[] {
  const result = new Map<string, AirlineSummary>();
  const add = (value: AirlineSummary) => {
    const key = `${value.iataCode ?? ""}|${value.name}`;
    if (!result.has(key)) result.set(key, value);
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

function supportedDocuments(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return [
    ...new Set(
      value
        .map((entry) => stringValue(entry, 100))
        .filter((entry): entry is string => entry !== null),
    ),
  ];
}

function passengerSummaries(value: unknown): FlightPassengerSummary[] {
  if (!Array.isArray(value)) return [];
  const allowed = new Set<FlightPassengerSummary["type"]>([
    "adult",
    "child",
    "infant_with_seat",
    "infant_without_seat",
  ]);
  const passengers: FlightPassengerSummary[] = [];
  for (const entry of value) {
    if (!isRecord(entry)) continue;
    const id = stringValue(entry.id, 200);
    const type = stringValue(entry.type, 50) as FlightPassengerSummary["type"] | null;
    if (id && type && allowed.has(type)) passengers.push({ id, type });
  }
  return passengers;
}

export function normalizeDuffelOffer(
  value: unknown,
  configuredMode: DuffelMode,
): FlightOffer | null {
  if (!isRecord(value)) return null;
  const offer = value as DuffelOffer;
  const id = stringValue(offer.id, 200);
  const expiresAt = patternedString(offer.expires_at, DUFFEL_DATETIME, 50);
  const total = money(offer.total_amount, offer.total_currency);
  const owner = airline(offer.owner);
  if (
    !id ||
    !expiresAt ||
    !total ||
    !owner ||
    !Array.isArray(offer.slices) ||
    offer.slices.length === 0
  ) {
    return null;
  }

  const slices = offer.slices
    .map((entry) => slice(entry))
    .filter((entry): entry is FlightSlice => entry !== null);
  if (slices.length !== offer.slices.length) return null;

  // A deployment setting alone is never enough to claim a fare is live.
  // Duffel's response must independently confirm live mode as well.
  const isLive = configuredMode === "live" && offer.live_mode === true;
  const baggage = slices.flatMap((entry) =>
    entry.segments.flatMap((currentSegment) => currentSegment.baggage),
  );
  const passengers = Array.isArray(offer.passengers) ? offer.passengers : [];
  const normalizedPassengers = passengerSummaries(passengers);

  return {
    id,
    source: {
      provider: "duffel",
      environment: isLive ? "live" : "test",
      isLive,
      label: isLive ? "Live fare" : "Test fare",
    },
    isBookable: isLive && offer.partial === false,
    expiresAt,
    createdAt: patternedString(offer.created_at, DUFFEL_DATETIME, 50),
    updatedAt: patternedString(offer.updated_at, DUFFEL_DATETIME, 50),
    total,
    base: money(offer.base_amount, offer.base_currency),
    tax: money(offer.tax_amount, offer.tax_currency),
    totalEmissionsKg: (() => {
      const amount =
        typeof offer.total_emissions_kg === "string"
          ? Number(offer.total_emissions_kg)
          : NaN;
      return Number.isFinite(amount) && amount >= 0 && amount <= 10_000_000
        ? amount
        : null;
    })(),
    owner,
    airlines: uniqueAirlines(owner, slices),
    slices,
    connectionCount: slices.reduce(
      (totalConnections, entry) =>
        totalConnections + entry.connectionCount,
      0,
    ),
    baggage,
    fareConditions: fareConditions(offer),
    passengers: normalizedPassengers,
    passengerCount: normalizedPassengers.length,
    passengerIdentityDocumentsRequired:
      offer.passenger_identity_documents_required === true,
    supportedIdentityDocumentTypes: supportedDocuments(
      offer.supported_passenger_identity_document_types,
    ),
    priceGuaranteeExpiresAt: patternedString(
      offer.payment_requirements?.price_guarantee_expires_at,
      DUFFEL_DATETIME,
      50,
    ),
    paymentRequiredBy: patternedString(
      offer.payment_requirements?.payment_required_by,
      DUFFEL_DATETIME,
      50,
    ),
  };
}

export function normalizeDuffelOffers(
  value: unknown,
  configuredMode: DuffelMode,
): FlightOffer[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((entry) => normalizeDuffelOffer(entry, configuredMode))
    .filter((entry): entry is FlightOffer => entry !== null);
}
