export type ProviderEnvironment = "test" | "live";

export type BookingSessionStatus = "active" | "revoked";
export type OfferSelectionStatus =
  | "selected"
  | "refreshed"
  | "expired"
  | "booked";
export type BookingAttemptState =
  | "created"
  | "price_changed"
  | "awaiting_payment"
  | "payment_authorized"
  | "submitting"
  | "confirmed"
  | "failed"
  | "manual_review";
export type BookingStatus =
  | "pending"
  | "confirmed"
  | "cancelled"
  | "refunded"
  | "manual_review";
export type WebhookEventStatus =
  | "received"
  | "processing"
  | "processed"
  | "ignored"
  | "failed";

/** Deliberately excludes passenger names, contact details, and documents. */
export type StoredJourneySummary = {
  origin: string;
  destination: string;
  departureAt: string;
  arrivalAt: string;
  segmentCount: number;
  marketingCarriers: string[];
};

/** Safe itinerary fields that may be retained for a receipt or support lookup. */
export type StoredItinerarySummary = {
  journeys: StoredJourneySummary[];
  totalSegments: number;
  totalStops: number;
};

export type StoredBaggageAllowance = {
  type: "carry_on" | "checked";
  quantity: number | null;
  weightKilograms: number | null;
};

/** Fare metadata only; payment-card and passenger data never belongs here. */
export type StoredFareSummary = {
  cabinClass: string | null;
  fareBrand: string | null;
  passengerTypes: Array<"adult" | "child" | "infant_with_seat" | "infant_without_seat">;
  /** Provider-owned passenger identifiers; never expose these in public responses. */
  providerPassengers: Array<{
    id: string;
    type: "adult" | "child" | "infant_with_seat" | "infant_without_seat";
  }>;
  identityDocumentsRequired: boolean;
  supportedIdentityDocumentTypes: string[];
  changeable: boolean | null;
  refundable: boolean | null;
  baggage: StoredBaggageAllowance[];
};

export type StoredRiskSummary = {
  coverage: "full" | "partial" | "unavailable";
  delayRiskPercent: number | null;
  coveredSegments: number;
  totalSegments: number;
  modelVersion: string | null;
};

export type BookingSessionRecord = {
  sessionHash: string;
  status: BookingSessionStatus;
  createdAt: number;
  lastSeenAt: number;
  expiresAt: number;
};

export type OfferSelectionRecord = {
  id: string;
  sessionHash: string;
  provider: string;
  providerEnvironment: ProviderEnvironment;
  providerOfferId: string;
  status: OfferSelectionStatus;
  offerExpiresAt: number | null;
  currency: string;
  totalAmountMinor: number;
  itinerary: StoredItinerarySummary;
  fare: StoredFareSummary;
  risk: StoredRiskSummary;
  providerSnapshotHash: string;
  createdAt: number;
  updatedAt: number;
};

export type BookingAttemptRecord = {
  id: string;
  sessionHash: string;
  offerSelectionId: string;
  idempotencyKeyHash: string;
  requestFingerprint: string;
  provider: string;
  providerEnvironment: ProviderEnvironment;
  state: BookingAttemptState;
  currency: string;
  totalAmountMinor: number;
  providerRequestId: string | null;
  paymentReference: string | null;
  failureCode: string | null;
  retryable: boolean;
  createdAt: number;
  updatedAt: number;
};

/** Opaque encrypted booking details retained only until the attempt is submitted. */
export type PrivateBookingPayloadRecord = {
  bookingAttemptId: string;
  ciphertext: string;
  iv: string;
  createdAt: number;
  expiresAt: number;
};

export type BookingRecord = {
  id: string;
  sessionHash: string;
  bookingAttemptId: string;
  provider: string;
  providerEnvironment: ProviderEnvironment;
  providerOrderId: string;
  bookingReference: string;
  status: BookingStatus;
  currency: string;
  totalAmountMinor: number;
  itinerary: StoredItinerarySummary;
  fare: StoredFareSummary;
  createdAt: number;
  updatedAt: number;
};

export type WebhookEventRecord = {
  id: string;
  provider: string;
  providerEventId: string;
  eventType: string;
  payloadHash: string;
  signatureHash: string;
  relatedProviderOrderId: string | null;
  status: WebhookEventStatus;
  failureCode: string | null;
  receivedAt: number;
  processedAt: number | null;
};
