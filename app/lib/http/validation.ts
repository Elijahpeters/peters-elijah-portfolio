const IATA_AIRPORT = /^[A-Z]{3}$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export const CABIN_CLASSES = [
  "economy",
  "premium_economy",
  "business",
  "first",
] as const;

export type CabinClass = (typeof CABIN_CLASSES)[number];

export type ValidatedFlightSearch = {
  origin: string;
  destination: string;
  departureDate: string;
  returnDate: string | null;
  passengers: {
    adults: number;
    children: number;
    infantsWithoutSeat: number;
  };
  cabinClass: CabinClass;
};

export type ValidationResult<T> =
  | { ok: true; value: T }
  | { ok: false; fields: Record<string, string> };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function cleanAirport(value: unknown): string {
  return typeof value === "string" ? value.trim().toUpperCase() : "";
}

function integer(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

function parseCalendarDate(value: unknown): Date | null {
  if (typeof value !== "string" || !ISO_DATE.test(value)) return null;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value
    ? null
    : parsed;
}

function utcDateOnly(now: Date): Date {
  return new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()),
  );
}

export function validateFlightSearch(
  input: unknown,
  now: Date = new Date(),
): ValidationResult<ValidatedFlightSearch> {
  if (!isRecord(input)) {
    return { ok: false, fields: { form: "Enter the flight search details." } };
  }

  const fields: Record<string, string> = {};
  const origin = cleanAirport(input.origin);
  const destination = cleanAirport(input.destination);
  const departure = parseCalendarDate(input.departureDate);
  const returnDate =
    input.returnDate === "" || input.returnDate == null
      ? null
      : parseCalendarDate(input.returnDate);

  if (!IATA_AIRPORT.test(origin)) {
    fields.origin = "Enter a three-letter airport code.";
  }
  if (!IATA_AIRPORT.test(destination)) {
    fields.destination = "Enter a three-letter airport code.";
  } else if (origin === destination) {
    fields.destination = "Choose a different destination airport.";
  }

  const today = utcDateOnly(now);
  const latest = new Date(today);
  latest.setUTCDate(latest.getUTCDate() + 330);
  if (!departure) {
    fields.departureDate = "Choose a valid departure date.";
  } else if (departure < today) {
    fields.departureDate = "Departure cannot be in the past.";
  } else if (departure > latest) {
    fields.departureDate = "Choose a departure within the next 330 days.";
  }

  if (input.returnDate != null && input.returnDate !== "" && !returnDate) {
    fields.returnDate = "Choose a valid return date.";
  } else if (returnDate && departure && returnDate < departure) {
    fields.returnDate = "Return must be on or after departure.";
  } else if (returnDate && returnDate > latest) {
    fields.returnDate = "Choose a return within the next 330 days.";
  }

  const passengers = isRecord(input.passengers) ? input.passengers : {};
  const adults = integer(passengers.adults);
  const children = integer(passengers.children);
  const infantsWithoutSeat = integer(passengers.infantsWithoutSeat);

  if (adults === null || adults < 1 || adults > 9) {
    fields.adults = "Choose between 1 and 9 adults.";
  }
  if (children === null || children < 0 || children > 8) {
    fields.children = "Choose between 0 and 8 children.";
  }
  if (
    infantsWithoutSeat === null ||
    infantsWithoutSeat < 0 ||
    infantsWithoutSeat > 8
  ) {
    fields.infantsWithoutSeat = "Choose between 0 and 8 infants.";
  } else if (adults !== null && infantsWithoutSeat > adults) {
    fields.infantsWithoutSeat = "Each infant needs an accompanying adult.";
  }

  if (
    adults !== null &&
    children !== null &&
    infantsWithoutSeat !== null &&
    adults + children + infantsWithoutSeat > 9
  ) {
    fields.passengers = "Search for no more than 9 passengers at a time.";
  }

  const cabinClass = input.cabinClass;
  if (
    typeof cabinClass !== "string" ||
    !CABIN_CLASSES.includes(cabinClass as CabinClass)
  ) {
    fields.cabinClass = "Choose a valid cabin class.";
  }

  if (Object.keys(fields).length > 0) return { ok: false, fields };

  return {
    ok: true,
    value: {
      origin,
      destination,
      departureDate: input.departureDate as string,
      returnDate: returnDate ? (input.returnDate as string) : null,
      passengers: {
        adults: adults as number,
        children: children as number,
        infantsWithoutSeat: infantsWithoutSeat as number,
      },
      cabinClass: cabinClass as CabinClass,
    },
  };
}

export function hasJsonContentType(request: Request): boolean {
  return (request.headers.get("content-type") ?? "")
    .toLowerCase()
    .startsWith("application/json");
}

export function isSameOriginRequest(request: Request): boolean {
  const expected = new URL(request.url).origin;
  const origin = request.headers.get("origin");
  if (origin) return origin === expected;

  const referer = request.headers.get("referer");
  if (!referer) return false;
  try {
    return new URL(referer).origin === expected;
  } catch {
    return false;
  }
}
