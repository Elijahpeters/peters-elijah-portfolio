export type BookingPassengerType =
  | "adult"
  | "child"
  | "infant_with_seat"
  | "infant_without_seat";

export type ExpectedProviderPassenger = {
  id: string;
  type: BookingPassengerType;
};

export type ValidatedIdentityDocument = {
  type: "passport";
  unique_identifier: string;
  expires_on: string;
  issuing_country_code: string;
};

export type ValidatedOrderPassenger = {
  id: string;
  title: "mr" | "ms" | "mrs" | "miss" | "dr";
  given_name: string;
  family_name: string;
  born_on: string;
  gender: "m" | "f";
  email: string;
  phone_number: string;
  identity_documents?: ValidatedIdentityDocument[];
  infant_passenger_id?: string;
};

export type ValidatedPassengerPayload = {
  paymentEmail: string;
  passengers: ValidatedOrderPassenger[];
};

export class PassengerValidationError extends Error {
  readonly field: string;

  constructor(field: string, message: string) {
    super(message);
    this.name = "PassengerValidationError";
    this.field = field;
  }
}

const TITLES = new Set(["mr", "ms", "mrs", "miss", "dr"]);
const GENDERS = new Set(["m", "f"]);
const PASSENGER_TYPES = new Set<BookingPassengerType>([
  "adult",
  "child",
  "infant_with_seat",
  "infant_without_seat",
]);
const PROVIDER_PASSENGER_ID = /^pas_[A-Za-z0-9_-]{1,190}$/;
const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const COUNTRY_CODE = /^[A-Z]{2}$/;
const PHONE = /^\+[1-9]\d{6,14}$/;
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const CONTROL_CHARACTERS = /[\u0000-\u001F\u007F]/u;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(
  value: unknown,
  field: string,
  minimum: number,
  maximum: number,
): string {
  if (typeof value !== "string") {
    throw new PassengerValidationError(field, "Enter all required passenger details.");
  }
  const normalized = value.trim();
  if (
    normalized.length < minimum ||
    normalized.length > maximum ||
    CONTROL_CHARACTERS.test(normalized)
  ) {
    throw new PassengerValidationError(field, "Enter valid passenger details.");
  }
  return normalized;
}

function optionalString(
  value: unknown,
  field: string,
  maximum: number,
): string {
  if (value === undefined || value === null || value === "") return "";
  return requiredString(value, field, 1, maximum);
}

function parseDate(value: unknown, field: string): { value: string; time: number } {
  const date = requiredString(value, field, 10, 10);
  const match = ISO_DATE.exec(date);
  if (!match) {
    throw new PassengerValidationError(field, "Enter a valid date.");
  }
  const time = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const parsed = new Date(time);
  if (
    parsed.getUTCFullYear() !== Number(match[1]) ||
    parsed.getUTCMonth() !== Number(match[2]) - 1 ||
    parsed.getUTCDate() !== Number(match[3])
  ) {
    throw new PassengerValidationError(field, "Enter a valid date.");
  }
  return { value: date, time };
}

function ageOnDate(bornOn: string, travelDate: string): number {
  const [birthYear, birthMonth, birthDay] = bornOn.split("-").map(Number);
  const [travelYear, travelMonth, travelDay] = travelDate.split("-").map(Number);
  let age = travelYear - birthYear;
  if (
    travelMonth < birthMonth ||
    (travelMonth === birthMonth && travelDay < birthDay)
  ) {
    age -= 1;
  }
  return age;
}

function assertAgeMatchesType(
  type: BookingPassengerType,
  bornOn: string,
  departureDate: string,
  field: string,
): void {
  const age = ageOnDate(bornOn, departureDate);
  const valid =
    type === "adult"
      ? age >= 12 && age <= 120
      : type === "child"
        ? age >= 2 && age < 12
        : age >= 0 && age < 2;
  if (!valid) {
    throw new PassengerValidationError(
      field,
      type === "adult"
        ? "An adult must be at least 12 on the travel date."
        : type === "child"
          ? "A child must be between 2 and 11 on the travel date."
          : "An infant must be under 2 on the travel date.",
    );
  }
}

function validateExpectedPassengers(
  expected: readonly ExpectedProviderPassenger[],
): void {
  if (expected.length < 1 || expected.length > 9) {
    throw new TypeError("A booking must contain between one and nine passengers.");
  }
  const ids = new Set<string>();
  for (const passenger of expected) {
    if (
      !PROVIDER_PASSENGER_ID.test(passenger.id) ||
      !PASSENGER_TYPES.has(passenger.type) ||
      ids.has(passenger.id)
    ) {
      throw new TypeError("The selected offer contains invalid passenger data.");
    }
    ids.add(passenger.id);
  }
  const adults = expected.filter((passenger) => passenger.type === "adult").length;
  const lapInfants = expected.filter(
    (passenger) => passenger.type === "infant_without_seat",
  ).length;
  if (lapInfants > adults) {
    throw new TypeError("Each infant without a seat requires a responsible adult.");
  }
}

export function validatePassengerPayload(
  value: unknown,
  expectedPassengers: readonly ExpectedProviderPassenger[],
  options: {
    identityDocumentsRequired: boolean;
    firstDepartureAt: string;
  },
): ValidatedPassengerPayload {
  validateExpectedPassengers(expectedPassengers);
  if (!Array.isArray(value) || value.length !== expectedPassengers.length) {
    throw new PassengerValidationError(
      "passengers",
      "Enter details for every passenger on this itinerary.",
    );
  }

  const firstDeparture = new Date(options.firstDepartureAt);
  if (!Number.isFinite(firstDeparture.getTime())) {
    throw new TypeError("The selected itinerary has an invalid departure time.");
  }
  const departureDate = firstDeparture.toISOString().slice(0, 10);
  const departureTime = Date.parse(`${departureDate}T00:00:00Z`);

  const passengers: ValidatedOrderPassenger[] = value.map((rawPassenger, index) => {
    const field = `passengers[${index}]`;
    if (!isRecord(rawPassenger)) {
      throw new PassengerValidationError(field, "Enter valid passenger details.");
    }
    const expected = expectedPassengers[index];
    if (rawPassenger.type !== expected.type) {
      throw new PassengerValidationError(
        `${field}.type`,
        "Passenger types must match the selected fare.",
      );
    }
    const title = requiredString(rawPassenger.title, `${field}.title`, 2, 4);
    if (!TITLES.has(title)) {
      throw new PassengerValidationError(`${field}.title`, "Choose a valid title.");
    }
    const gender = requiredString(rawPassenger.gender, `${field}.gender`, 1, 1);
    if (!GENDERS.has(gender)) {
      throw new PassengerValidationError(`${field}.gender`, "Choose a valid gender.");
    }
    const born = parseDate(rawPassenger.bornOn, `${field}.bornOn`);
    if (born.time >= departureTime) {
      throw new PassengerValidationError(`${field}.bornOn`, "Enter a valid date of birth.");
    }
    assertAgeMatchesType(expected.type, born.value, departureDate, `${field}.bornOn`);

    const email = optionalString(rawPassenger.email, `${field}.email`, 254).toLowerCase();
    const phoneNumber = optionalString(rawPassenger.phoneNumber, `${field}.phoneNumber`, 16);
    if ((index === 0 || email) && !EMAIL.test(email)) {
      throw new PassengerValidationError(`${field}.email`, "Enter a valid email address.");
    }
    if ((index === 0 || phoneNumber) && !PHONE.test(phoneNumber)) {
      throw new PassengerValidationError(
        `${field}.phoneNumber`,
        "Enter a phone number with its country code, such as +234…",
      );
    }

    let identityDocuments: ValidatedIdentityDocument[] | undefined;
    if (options.identityDocumentsRequired) {
      const document = rawPassenger.identityDocument;
      if (!isRecord(document) || document.type !== "passport") {
        throw new PassengerValidationError(
          `${field}.identityDocument`,
          "Enter a passport for every passenger.",
        );
      }
      const expires = parseDate(
        document.expiresOn,
        `${field}.identityDocument.expiresOn`,
      );
      if (expires.time <= departureTime) {
        throw new PassengerValidationError(
          `${field}.identityDocument.expiresOn`,
          "The passport must be valid on the travel date.",
        );
      }
      const issuingCountryCode = requiredString(
        document.issuingCountryCode,
        `${field}.identityDocument.issuingCountryCode`,
        2,
        2,
      ).toUpperCase();
      if (!COUNTRY_CODE.test(issuingCountryCode)) {
        throw new PassengerValidationError(
          `${field}.identityDocument.issuingCountryCode`,
          "Enter a two-letter issuing country code.",
        );
      }
      const uniqueIdentifier = requiredString(
        document.uniqueIdentifier,
        `${field}.identityDocument.uniqueIdentifier`,
        3,
        40,
      );
      if (!/^[A-Za-z0-9 -]+$/.test(uniqueIdentifier)) {
        throw new PassengerValidationError(
          `${field}.identityDocument.uniqueIdentifier`,
          "Enter a valid passport number.",
        );
      }
      identityDocuments = [
        {
          type: "passport",
          unique_identifier: uniqueIdentifier,
          expires_on: expires.value,
          issuing_country_code: issuingCountryCode,
        },
      ];
    }

    return {
      id: expected.id,
      title: title as ValidatedOrderPassenger["title"],
      given_name: requiredString(rawPassenger.givenName, `${field}.givenName`, 1, 100),
      family_name: requiredString(rawPassenger.familyName, `${field}.familyName`, 1, 100),
      born_on: born.value,
      gender: gender as "m" | "f",
      email,
      phone_number: phoneNumber,
      ...(identityDocuments ? { identity_documents: identityDocuments } : {}),
    } satisfies ValidatedOrderPassenger;
  });

  const adults = passengers.filter(
    (_, index) => expectedPassengers[index].type === "adult",
  );
  const lapInfants = expectedPassengers
    .map((passenger, index) => ({ passenger, index }))
    .filter(({ passenger }) => passenger.type === "infant_without_seat");
  lapInfants.forEach(({ passenger }, index) => {
    adults[index].infant_passenger_id = passenger.id;
  });

  return { paymentEmail: passengers[0].email, passengers };
}
