import type {
  AirlineSummary,
  AirportSummary,
  BaggageAllowance,
  FareConditions,
  FlightOffer,
  FlightPassengerSummary,
  FlightSegment,
  FlightSlice,
  Money,
} from "../../types/flight-booking.ts";
import airportSource from "../skyeta/us-airports.json" with { type: "json" };

const IATA_AIRPORT = /^[A-Z]{3}$/;
const IATA_AIRLINE = /^[A-Z0-9]{2}$/;
const ISO_CURRENCY = /^[A-Z]{3}$/;
const LOCAL_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?$/;

type LocalAirport = {
  name: string | null;
  cityName: string | null;
  countryCode: string | null;
  timeZone: string | null;
  latitude: number;
  longitude: number;
};

type PassengerCounts = {
  adults: number;
  children: number;
  infantsWithoutSeat: number;
};

export type IgnavTripExpectation = {
  origin: string;
  destination: string;
  departureDate: string;
  returnDate: string | null;
  cabinClass: string;
};

const localAirports = airportSource as Record<string, LocalAirport>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown, maxLength = 300): string | null {
  return typeof value === "string" &&
    value.trim().length > 0 &&
    value.length <= maxLength
    ? value.trim()
    : null;
}

function patternedString(
  value: unknown,
  pattern: RegExp,
  maxLength = 300,
): string | null {
  const text = stringValue(value, maxLength);
  return text && pattern.test(text) ? text : null;
}

function safeInteger(value: unknown, minimum: number, maximum: number) {
  return typeof value === "number" &&
    Number.isInteger(value) &&
    value >= minimum &&
    value <= maximum
    ? value
    : null;
}

function money(value: unknown): Money | null {
  if (!isRecord(value) || value.status !== "verified") return null;
  const amount = value.amount;
  const currency = patternedString(value.currency, ISO_CURRENCY, 3);
  if (
    typeof amount !== "number" ||
    !Number.isFinite(amount) ||
    amount < 0 ||
    amount > 1_000_000_000_000 ||
    !currency
  ) {
    return null;
  }
  return { amount: String(amount), currency };
}

function minutesDuration(value: unknown): string | null {
  const minutes = safeInteger(value, 1, 14_400);
  if (minutes === null) return null;
  const days = Math.floor(minutes / 1_440);
  const remaining = minutes % 1_440;
  const hours = Math.floor(remaining / 60);
  const mins = remaining % 60;
  const date = days ? `${days}D` : "";
  const time = `${hours ? `${hours}H` : ""}${mins ? `${mins}M` : ""}`;
  return `P${date}${time ? `T${time}` : ""}`;
}

function airport(codeValue: unknown, timeZoneValue: unknown): AirportSummary | null {
  const code = patternedString(codeValue, IATA_AIRPORT, 3);
  if (!code) return null;
  const local = localAirports[code];
  return {
    iataCode: code,
    name: local?.name ?? null,
    cityName: local?.cityName ?? null,
    countryCode: local?.countryCode ?? null,
    timeZone: stringValue(timeZoneValue, 100) ?? local?.timeZone ?? null,
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
  const startLatitude = radians(origin.latitude);
  const endLatitude = radians(destination.latitude);
  const a =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(startLatitude) *
      Math.cos(endLatitude) *
      Math.sin(longitudeDelta / 2) ** 2;
  return Math.round(6_371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a)));
}

function airline(
  codeValue: unknown,
  preferredName: unknown,
  fallbackName: unknown,
): AirlineSummary | null {
  const code = patternedString(codeValue, IATA_AIRLINE, 2);
  const name =
    stringValue(preferredName, 200) ??
    stringValue(fallbackName, 200) ??
    code;
  if (!name) return null;
  return {
    iataCode: code,
    name,
    logoUrl: null,
    conditionsOfCarriageUrl: null,
  };
}

function segment(
  value: unknown,
  legCarrier: unknown,
  sliceIndex: number,
  segmentIndex: number,
  cabinClass: string,
): FlightSegment | null {
  if (!isRecord(value)) return null;
  const origin = airport(value.departure_airport, value.departure_timezone);
  const destination = airport(value.arrival_airport, value.arrival_timezone);
  const departingAt = patternedString(
    value.departure_time_local,
    LOCAL_DATETIME,
    30,
  );
  const arrivingAt = patternedString(
    value.arrival_time_local,
    LOCAL_DATETIME,
    30,
  );
  const marketingCarrier = airline(
    value.marketing_carrier_code,
    legCarrier,
    value.operating_carrier_name,
  );
  const operatingCarrier = airline(
    value.marketing_carrier_code,
    value.operating_carrier_name,
    legCarrier,
  );
  const duration = minutesDuration(value.duration_minutes);
  if (
    !origin ||
    !destination ||
    !departingAt ||
    !arrivingAt ||
    !marketingCarrier ||
    !operatingCarrier ||
    !duration
  ) {
    return null;
  }
  return {
    id: `ign_segment_${sliceIndex + 1}_${segmentIndex + 1}`,
    origin,
    destination,
    departingAt,
    arrivingAt,
    duration,
    distanceKilometres: distanceKilometres(origin, destination),
    originTerminal: null,
    destinationTerminal: null,
    marketingCarrier,
    operatingCarrier,
    marketingFlightNumber: stringValue(value.flight_number, 20),
    operatingFlightNumber: stringValue(value.flight_number, 20),
    aircraftName: stringValue(value.aircraft, 200),
    cabinClass,
    cabinName: cabinClass.replaceAll("_", " "),
    fareBrandName: null,
    stops: [],
    baggage: [],
  };
}

function slice(
  value: unknown,
  index: number,
  cabinClass: string,
): FlightSlice | null {
  if (!isRecord(value) || !Array.isArray(value.segments) || value.segments.length === 0) {
    return null;
  }
  const segments = value.segments
    .map((entry, segmentIndex) =>
      segment(entry, value.carrier, index, segmentIndex, cabinClass),
    )
    .filter((entry): entry is FlightSegment => entry !== null);
  if (segments.length !== value.segments.length) return null;
  return {
    id: `ign_slice_${index + 1}`,
    origin: segments[0].origin,
    destination: segments.at(-1)!.destination,
    duration:
      minutesDuration(value.duration_minutes) ??
      minutesDuration(
        value.segments.reduce((total, entry) => {
          if (!isRecord(entry)) return total;
          return total + (safeInteger(entry.duration_minutes, 1, 14_400) ?? 0);
        }, 0),
      ),
    connectionCount: Math.max(0, segments.length - 1),
    segments,
  };
}

function passengerList(counts: PassengerCounts): FlightPassengerSummary[] {
  return [
    ...Array.from({ length: counts.adults }, (_, index) => ({
      id: `ign_adult_${index + 1}`,
      type: "adult" as const,
    })),
    ...Array.from({ length: counts.children }, (_, index) => ({
      id: `ign_child_${index + 1}`,
      type: "child" as const,
    })),
    ...Array.from({ length: counts.infantsWithoutSeat }, (_, index) => ({
      id: `ign_infant_${index + 1}`,
      type: "infant_without_seat" as const,
    })),
  ];
}

function baggage(
  value: unknown,
  firstSegmentId: string,
): BaggageAllowance[] {
  if (!isRecord(value)) return [];
  const result: BaggageAllowance[] = [];
  const add = (key: "carry_on" | "checked", type: "carry_on" | "checked") => {
    const quantity = safeInteger(value[key], 0, 20);
    if (quantity === null) return;
    result.push({
      passengerId: null,
      segmentId: firstSegmentId,
      type,
      providerType: `ignav_${key}`,
      quantity,
      weightKilograms: null,
    });
  };
  add("carry_on", "carry_on");
  add("checked", "checked");
  return result;
}

function uniqueAirlines(owner: AirlineSummary, slices: FlightSlice[]) {
  const entries = new Map<string, AirlineSummary>();
  const add = (value: AirlineSummary) => {
    const key = `${value.iataCode ?? ""}|${value.name}`;
    if (!entries.has(key)) entries.set(key, value);
  };
  add(owner);
  for (const currentSlice of slices) {
    for (const currentSegment of currentSlice.segments) {
      add(currentSegment.marketingCarrier);
      add(currentSegment.operatingCarrier);
    }
  }
  return [...entries.values()];
}

function unknownConditions(): FareConditions {
  return {
    changeBeforeDeparture: { status: "unknown", penalty: null },
    refundBeforeDeparture: { status: "unknown", penalty: null },
  };
}

export function normalizeIgnavItinerary(options: {
  value: unknown;
  cacheId: string;
  now: Date;
  expiresAt: Date;
  passengers: PassengerCounts;
  expected: IgnavTripExpectation;
}): FlightOffer | null {
  if (!isRecord(options.value) || options.value.requires_self_transfer === true) {
    return null;
  }
  const itinerary = options.value;
  const total = money(itinerary.price);
  const returnedCabinClass = stringValue(itinerary.cabin_class, 50);
  if (
    returnedCabinClass &&
    returnedCabinClass !== options.expected.cabinClass
  ) {
    return null;
  }
  const cabinClass = returnedCabinClass ?? options.expected.cabinClass;
  const expectReturn = options.expected.returnDate !== null;
  const rawSlices = [
    itinerary.outbound,
    ...(itinerary.inbound ? [itinerary.inbound] : []),
  ];
  if (
    !total ||
    !isRecord(itinerary.outbound) ||
    (expectReturn && !isRecord(itinerary.inbound)) ||
    (!expectReturn && itinerary.inbound !== undefined && itinerary.inbound !== null)
  ) {
    return null;
  }
  const slices = rawSlices
    .map((entry, index) => slice(entry, index, cabinClass))
    .filter((entry): entry is FlightSlice => entry !== null);
  if (slices.length !== rawSlices.length) return null;
  const outboundFirst = slices[0].segments[0];
  const outboundLast = slices[0].segments.at(-1)!;
  if (
    outboundFirst.origin.iataCode !== options.expected.origin ||
    outboundLast.destination.iataCode !== options.expected.destination ||
    outboundFirst.departingAt.slice(0, 10) !== options.expected.departureDate
  ) {
    return null;
  }
  if (expectReturn) {
    const inbound = slices[1];
    const inboundFirst = inbound?.segments[0];
    const inboundLast = inbound?.segments.at(-1);
    if (
      !inboundFirst ||
      !inboundLast ||
      inboundFirst.origin.iataCode !== options.expected.destination ||
      inboundLast.destination.iataCode !== options.expected.origin ||
      inboundFirst.departingAt.slice(0, 10) !== options.expected.returnDate
    ) {
      return null;
    }
  }
  const normalizedPassengers = passengerList(options.passengers);
  if (normalizedPassengers.length === 0) return null;
  const firstSegment = slices[0].segments[0];
  const owner = firstSegment.marketingCarrier;
  const allowances = baggage(itinerary.bags, firstSegment.id);

  return {
    id: options.cacheId,
    source: {
      provider: "ignav",
      environment: "live",
      isLive: true,
      label: "Live fare",
    },
    isBookable: true,
    expiresAt: options.expiresAt.toISOString(),
    createdAt: options.now.toISOString(),
    updatedAt: options.now.toISOString(),
    total,
    base: null,
    tax: null,
    totalEmissionsKg: null,
    owner,
    airlines: uniqueAirlines(owner, slices),
    slices,
    connectionCount: slices.reduce(
      (count, current) => count + current.connectionCount,
      0,
    ),
    baggage: allowances,
    fareConditions: unknownConditions(),
    passengers: normalizedPassengers,
    passengerCount: normalizedPassengers.length,
    passengerIdentityDocumentsRequired: false,
    supportedIdentityDocumentTypes: [],
    priceGuaranteeExpiresAt: null,
    paymentRequiredBy: null,
  };
}

export function ignavOfferIdentity(offer: FlightOffer): string {
  return offer.slices
    .map((currentSlice, sliceIndex) => {
      const segments = currentSlice.segments
        .map((currentSegment) =>
          [
            currentSegment.origin.iataCode,
            currentSegment.destination.iataCode,
            currentSegment.marketingCarrier.iataCode ?? "",
            currentSegment.marketingFlightNumber ?? "",
            currentSegment.departingAt,
            currentSegment.arrivingAt,
            currentSegment.cabinClass ?? "",
          ].join(":"),
        )
        .join("|");
      return [
        `slice-${sliceIndex + 1}`,
        currentSlice.origin.iataCode,
        currentSlice.destination.iataCode,
        segments,
      ].join("|");
    })
    .join("||");
}
