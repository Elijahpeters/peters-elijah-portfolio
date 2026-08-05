export type FlightProviderEnvironment = "test" | "live";

export type Money = {
  amount: string;
  currency: string;
};

export type FlightDataProvenance = {
  provider: "duffel";
  environment: FlightProviderEnvironment;
  isLive: boolean;
  label: "Test fare" | "Live fare";
};

export type AirportSummary = {
  iataCode: string;
  name: string | null;
  cityName: string | null;
  countryCode: string | null;
  timeZone: string | null;
  latitude: number | null;
  longitude: number | null;
};

export type AirlineSummary = {
  iataCode: string | null;
  name: string;
  logoUrl: string | null;
  conditionsOfCarriageUrl: string | null;
};

export type FlightStop = {
  id: string | null;
  airport: AirportSummary;
  arrivingAt: string | null;
  departingAt: string | null;
  duration: string | null;
};

export type BaggageAllowance = {
  passengerId: string | null;
  segmentId: string;
  type: "carry_on" | "checked" | "other";
  providerType: string;
  quantity: number;
};

export type FlightSegment = {
  id: string;
  origin: AirportSummary;
  destination: AirportSummary;
  departingAt: string;
  arrivingAt: string;
  duration: string | null;
  distanceKilometres: number | null;
  originTerminal: string | null;
  destinationTerminal: string | null;
  marketingCarrier: AirlineSummary;
  operatingCarrier: AirlineSummary;
  marketingFlightNumber: string | null;
  operatingFlightNumber: string | null;
  aircraftName: string | null;
  cabinClass: string | null;
  cabinName: string | null;
  fareBrandName: string | null;
  stops: FlightStop[];
  baggage: BaggageAllowance[];
};

export type FlightSlice = {
  id: string;
  origin: AirportSummary;
  destination: AirportSummary;
  duration: string | null;
  connectionCount: number;
  segments: FlightSegment[];
};

export type FareRule = {
  status: "allowed" | "not_allowed" | "unknown";
  penalty: Money | null;
};

export type FareConditions = {
  changeBeforeDeparture: FareRule;
  refundBeforeDeparture: FareRule;
};

export type FlightPassengerSummary = {
  id: string;
  type: "adult" | "child" | "infant_with_seat" | "infant_without_seat";
};

export type FlightOffer = {
  id: string;
  source: FlightDataProvenance;
  isBookable: boolean;
  expiresAt: string;
  createdAt: string | null;
  updatedAt: string | null;
  total: Money;
  base: Money | null;
  tax: Money | null;
  totalEmissionsKg: number | null;
  owner: AirlineSummary;
  airlines: AirlineSummary[];
  slices: FlightSlice[];
  connectionCount: number;
  baggage: BaggageAllowance[];
  fareConditions: FareConditions;
  passengers: FlightPassengerSummary[];
  passengerCount: number;
  passengerIdentityDocumentsRequired: boolean;
  supportedIdentityDocumentTypes: string[];
  priceGuaranteeExpiresAt: string | null;
  paymentRequiredBy: string | null;
};
