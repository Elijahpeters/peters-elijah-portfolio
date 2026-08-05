import {
  d1Changes,
  initializeBookingStorage,
  type D1DatabaseLike,
} from "./d1.ts";
import type {
  BookingAttemptRecord,
  BookingAttemptState,
  BookingRecord,
  BookingSessionRecord,
  BookingStatus,
  OfferSelectionRecord,
  OfferSelectionStatus,
  PrivateBookingPayloadRecord,
  ProviderEnvironment,
  StoredFareSummary,
  StoredItinerarySummary,
  StoredRiskSummary,
  WebhookEventRecord,
  WebhookEventStatus,
} from "./types";

type SessionRow = {
  session_hash: string;
  status: BookingSessionRecord["status"];
  created_at: number;
  last_seen_at: number;
  expires_at: number;
};

type OfferSelectionRow = {
  id: string;
  session_hash: string;
  provider: string;
  provider_environment: ProviderEnvironment;
  provider_offer_id: string;
  status: OfferSelectionStatus;
  offer_expires_at: number | null;
  currency: string;
  total_amount_minor: number;
  itinerary_summary_json: string;
  fare_summary_json: string;
  risk_summary_json: string;
  provider_snapshot_hash: string;
  created_at: number;
  updated_at: number;
};

type BookingAttemptRow = {
  id: string;
  session_hash: string;
  offer_selection_id: string;
  idempotency_key_hash: string;
  request_fingerprint: string;
  provider: string;
  provider_environment: ProviderEnvironment;
  state: BookingAttemptState;
  currency: string;
  total_amount_minor: number;
  provider_request_id: string | null;
  payment_reference: string | null;
  failure_code: string | null;
  retryable: number;
  created_at: number;
  updated_at: number;
};

type PrivateBookingPayloadRow = {
  booking_attempt_id: string;
  ciphertext: string;
  iv: string;
  created_at: number;
  expires_at: number;
};

type BookingRow = {
  id: string;
  session_hash: string;
  booking_attempt_id: string;
  provider: string;
  provider_environment: ProviderEnvironment;
  provider_order_id: string;
  booking_reference: string;
  status: BookingStatus;
  currency: string;
  total_amount_minor: number;
  itinerary_summary_json: string;
  fare_summary_json: string;
  created_at: number;
  updated_at: number;
};

type WebhookEventRow = {
  id: string;
  provider: string;
  provider_event_id: string;
  event_type: string;
  payload_hash: string;
  signature_hash: string;
  related_provider_order_id: string | null;
  status: WebhookEventStatus;
  failure_code: string | null;
  received_at: number;
  processed_at: number | null;
};

export class BookingStorageConflictError extends Error {
  constructor(message = "The booking operation conflicts with an existing record.") {
    super(message);
    this.name = "BookingStorageConflictError";
  }
}

export class BookingStorageCorruptionError extends Error {
  constructor(field: string) {
    super(`Stored booking data is invalid in ${field}.`);
    this.name = "BookingStorageCorruptionError";
  }
}

export type SaveOfferSelectionInput = Omit<
  OfferSelectionRecord,
  "createdAt" | "updatedAt"
> & {
  now: number;
};

export type CreateBookingAttemptInput = {
  id: string;
  sessionHash: string;
  offerSelectionId: string;
  idempotencyKeyHash: string;
  requestFingerprint: string;
  provider: string;
  providerEnvironment: ProviderEnvironment;
  currency: string;
  totalAmountMinor: number;
  now: number;
};

export type TransitionBookingAttemptInput = {
  id: string;
  sessionHash: string;
  expectedStates: BookingAttemptState[];
  nextState: BookingAttemptState;
  providerRequestId?: string | null;
  paymentReference?: string | null;
  failureCode?: string | null;
  retryable?: boolean;
  now: number;
};

export type FinalizeBookingInput = {
  id: string;
  sessionHash: string;
  bookingAttemptId: string;
  offerSelectionId: string;
  provider: string;
  providerEnvironment: ProviderEnvironment;
  providerOrderId: string;
  bookingReference: string;
  status: BookingStatus;
  currency: string;
  totalAmountMinor: number;
  itinerary: StoredItinerarySummary;
  fare: StoredFareSummary;
  now: number;
};

export type RecordWebhookEventInput = {
  id: string;
  provider: string;
  providerEventId: string;
  eventType: string;
  payloadHash: string;
  signatureHash: string;
  relatedProviderOrderId: string | null;
  receivedAt: number;
};

function parseStoredJson<T>(value: string, field: string): T {
  try {
    return JSON.parse(value) as T;
  } catch {
    throw new BookingStorageCorruptionError(field);
  }
}

function mapSession(row: SessionRow): BookingSessionRecord {
  return {
    sessionHash: row.session_hash,
    status: row.status,
    createdAt: row.created_at,
    lastSeenAt: row.last_seen_at,
    expiresAt: row.expires_at,
  };
}

function mapOfferSelection(row: OfferSelectionRow): OfferSelectionRecord {
  return {
    id: row.id,
    sessionHash: row.session_hash,
    provider: row.provider,
    providerEnvironment: row.provider_environment,
    providerOfferId: row.provider_offer_id,
    status: row.status,
    offerExpiresAt: row.offer_expires_at,
    currency: row.currency,
    totalAmountMinor: row.total_amount_minor,
    itinerary: parseStoredJson<StoredItinerarySummary>(
      row.itinerary_summary_json,
      "offer_selections.itinerary_summary_json",
    ),
    fare: parseStoredJson<StoredFareSummary>(
      row.fare_summary_json,
      "offer_selections.fare_summary_json",
    ),
    risk: parseStoredJson<StoredRiskSummary>(
      row.risk_summary_json,
      "offer_selections.risk_summary_json",
    ),
    providerSnapshotHash: row.provider_snapshot_hash,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

function mapBookingAttempt(row: BookingAttemptRow): BookingAttemptRecord {
  return {
    id: row.id,
    sessionHash: row.session_hash,
    offerSelectionId: row.offer_selection_id,
    idempotencyKeyHash: row.idempotency_key_hash,
    requestFingerprint: row.request_fingerprint,
    provider: row.provider,
    providerEnvironment: row.provider_environment,
    state: row.state,
    currency: row.currency,
    totalAmountMinor: row.total_amount_minor,
    providerRequestId: row.provider_request_id,
    paymentReference: row.payment_reference,
    failureCode: row.failure_code,
    retryable: row.retryable === 1,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

function mapPrivateBookingPayload(
  row: PrivateBookingPayloadRow,
): PrivateBookingPayloadRecord {
  return {
    bookingAttemptId: row.booking_attempt_id,
    ciphertext: row.ciphertext,
    iv: row.iv,
    createdAt: row.created_at,
    expiresAt: row.expires_at,
  };
}

function mapBooking(row: BookingRow): BookingRecord {
  return {
    id: row.id,
    sessionHash: row.session_hash,
    bookingAttemptId: row.booking_attempt_id,
    provider: row.provider,
    providerEnvironment: row.provider_environment,
    providerOrderId: row.provider_order_id,
    bookingReference: row.booking_reference,
    status: row.status,
    currency: row.currency,
    totalAmountMinor: row.total_amount_minor,
    itinerary: parseStoredJson<StoredItinerarySummary>(
      row.itinerary_summary_json,
      "bookings.itinerary_summary_json",
    ),
    fare: parseStoredJson<StoredFareSummary>(
      row.fare_summary_json,
      "bookings.fare_summary_json",
    ),
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
}

function mapWebhookEvent(row: WebhookEventRow): WebhookEventRecord {
  return {
    id: row.id,
    provider: row.provider,
    providerEventId: row.provider_event_id,
    eventType: row.event_type,
    payloadHash: row.payload_hash,
    signatureHash: row.signature_hash,
    relatedProviderOrderId: row.related_provider_order_id,
    status: row.status,
    failureCode: row.failure_code,
    receivedAt: row.received_at,
    processedAt: row.processed_at,
  };
}

function placeholders(count: number): string {
  return Array.from({ length: count }, () => "?").join(", ");
}

export class BookingRepository {
  private readonly db: D1DatabaseLike;

  constructor(db: D1DatabaseLike) {
    this.db = db;
  }

  private async ready(): Promise<void> {
    await initializeBookingStorage(this.db);
  }

  async createSession(
    record: BookingSessionRecord,
  ): Promise<BookingSessionRecord> {
    await this.ready();
    const row = await this.db
      .prepare(
        `INSERT INTO booking_sessions (
          session_hash, status, created_at, last_seen_at, expires_at
        ) VALUES (?, ?, ?, ?, ?)
        RETURNING *`,
      )
      .bind(
        record.sessionHash,
        record.status,
        record.createdAt,
        record.lastSeenAt,
        record.expiresAt,
      )
      .first<SessionRow>();
    if (!row) throw new Error("The booking session could not be created.");
    return mapSession(row);
  }

  async getActiveSession(
    sessionHash: string,
    now: number,
  ): Promise<BookingSessionRecord | null> {
    await this.ready();
    const row = await this.db
      .prepare(
        `SELECT * FROM booking_sessions
        WHERE session_hash = ? AND status = 'active' AND expires_at > ?`,
      )
      .bind(sessionHash, now)
      .first<SessionRow>();
    return row ? mapSession(row) : null;
  }

  async touchActiveSession(sessionHash: string, now: number): Promise<boolean> {
    await this.ready();
    const result = await this.db
      .prepare(
        `UPDATE booking_sessions
        SET last_seen_at = ?
        WHERE session_hash = ? AND status = 'active' AND expires_at > ?`,
      )
      .bind(now, sessionHash, now)
      .run();
    return d1Changes(result) === 1;
  }

  async revokeSession(sessionHash: string, now: number): Promise<boolean> {
    await this.ready();
    const result = await this.db
      .prepare(
        `UPDATE booking_sessions
        SET status = 'revoked', last_seen_at = ?
        WHERE session_hash = ? AND status = 'active'`,
      )
      .bind(now, sessionHash)
      .run();
    return d1Changes(result) === 1;
  }

  async deleteExpiredSessions(now: number, limit = 100): Promise<number> {
    await this.ready();
    const boundedLimit = Math.max(1, Math.min(500, Math.trunc(limit)));
    const result = await this.db
      .prepare(
        `DELETE FROM booking_sessions
        WHERE session_hash IN (
          SELECT session_hash FROM booking_sessions
          WHERE expires_at <= ?
            AND NOT EXISTS (
              SELECT 1 FROM bookings
              WHERE bookings.session_hash = booking_sessions.session_hash
            )
          ORDER BY expires_at ASC
          LIMIT ?
        )`,
      )
      .bind(now, boundedLimit)
      .run();
    return d1Changes(result);
  }

  async saveOfferSelection(
    input: SaveOfferSelectionInput,
  ): Promise<OfferSelectionRecord> {
    await this.ready();
    const row = await this.db
      .prepare(
        `INSERT INTO offer_selections (
          id, session_hash, provider, provider_environment, provider_offer_id,
          status, offer_expires_at, currency, total_amount_minor,
          itinerary_summary_json, fare_summary_json, risk_summary_json,
          provider_snapshot_hash, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_hash, provider, provider_offer_id) DO UPDATE SET
          provider_environment = excluded.provider_environment,
          status = excluded.status,
          offer_expires_at = excluded.offer_expires_at,
          currency = excluded.currency,
          total_amount_minor = excluded.total_amount_minor,
          itinerary_summary_json = excluded.itinerary_summary_json,
          fare_summary_json = excluded.fare_summary_json,
          risk_summary_json = excluded.risk_summary_json,
          provider_snapshot_hash = excluded.provider_snapshot_hash,
          updated_at = excluded.updated_at
        RETURNING *`,
      )
      .bind(
        input.id,
        input.sessionHash,
        input.provider,
        input.providerEnvironment,
        input.providerOfferId,
        input.status,
        input.offerExpiresAt,
        input.currency.toUpperCase(),
        input.totalAmountMinor,
        JSON.stringify(input.itinerary),
        JSON.stringify(input.fare),
        JSON.stringify(input.risk),
        input.providerSnapshotHash,
        input.now,
        input.now,
      )
      .first<OfferSelectionRow>();
    if (!row) throw new Error("The selected flight offer could not be saved.");
    return mapOfferSelection(row);
  }

  async getOfferSelectionForSession(
    id: string,
    sessionHash: string,
  ): Promise<OfferSelectionRecord | null> {
    await this.ready();
    const row = await this.db
      .prepare(
        `SELECT * FROM offer_selections
        WHERE id = ? AND session_hash = ?`,
      )
      .bind(id, sessionHash)
      .first<OfferSelectionRow>();
    return row ? mapOfferSelection(row) : null;
  }

  async transitionOfferSelection(
    id: string,
    sessionHash: string,
    expectedStatus: OfferSelectionStatus,
    nextStatus: OfferSelectionStatus,
    now: number,
  ): Promise<OfferSelectionRecord | null> {
    await this.ready();
    const row = await this.db
      .prepare(
        `UPDATE offer_selections
        SET status = ?, updated_at = ?
        WHERE id = ? AND session_hash = ? AND status = ?
        RETURNING *`,
      )
      .bind(nextStatus, now, id, sessionHash, expectedStatus)
      .first<OfferSelectionRow>();
    return row ? mapOfferSelection(row) : null;
  }

  async acquireBookingAttempt(
    input: CreateBookingAttemptInput,
  ): Promise<{ attempt: BookingAttemptRecord; created: boolean }> {
    await this.ready();
    const inserted = await this.db
      .prepare(
        `INSERT INTO booking_attempts (
          id, session_hash, offer_selection_id, idempotency_key_hash,
          request_fingerprint, provider, provider_environment, state,
          currency, total_amount_minor, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'created', ?, ?, ?, ?)
        ON CONFLICT(idempotency_key_hash) DO NOTHING
        RETURNING *`,
      )
      .bind(
        input.id,
        input.sessionHash,
        input.offerSelectionId,
        input.idempotencyKeyHash,
        input.requestFingerprint,
        input.provider,
        input.providerEnvironment,
        input.currency.toUpperCase(),
        input.totalAmountMinor,
        input.now,
        input.now,
      )
      .first<BookingAttemptRow>();

    if (inserted) {
      return { attempt: mapBookingAttempt(inserted), created: true };
    }

    const existing = await this.db
      .prepare(
        `SELECT * FROM booking_attempts
        WHERE idempotency_key_hash = ? AND session_hash = ?`,
      )
      .bind(input.idempotencyKeyHash, input.sessionHash)
      .first<BookingAttemptRow>();
    if (!existing || existing.request_fingerprint !== input.requestFingerprint) {
      throw new BookingStorageConflictError(
        "The idempotency key was already used for a different booking request.",
      );
    }
    return { attempt: mapBookingAttempt(existing), created: false };
  }

  async getBookingAttemptForSession(
    id: string,
    sessionHash: string,
  ): Promise<BookingAttemptRecord | null> {
    await this.ready();
    const row = await this.db
      .prepare(
        `SELECT * FROM booking_attempts
        WHERE id = ? AND session_hash = ?`,
      )
      .bind(id, sessionHash)
      .first<BookingAttemptRow>();
    return row ? mapBookingAttempt(row) : null;
  }

  async getBookingAttemptByPaymentReference(
    paymentReference: string,
  ): Promise<BookingAttemptRecord | null> {
    await this.ready();
    const row = await this.db
      .prepare(
        `SELECT * FROM booking_attempts
        WHERE payment_reference = ?`,
      )
      .bind(paymentReference)
      .first<BookingAttemptRow>();
    return row ? mapBookingAttempt(row) : null;
  }

  async savePrivatePayload(
    record: PrivateBookingPayloadRecord,
  ): Promise<PrivateBookingPayloadRecord> {
    await this.ready();
    const row = await this.db
      .prepare(
        `INSERT INTO booking_private_payloads (
          booking_attempt_id, ciphertext, iv, created_at, expires_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(booking_attempt_id) DO UPDATE SET
          ciphertext = excluded.ciphertext,
          iv = excluded.iv,
          created_at = excluded.created_at,
          expires_at = excluded.expires_at
        RETURNING *`,
      )
      .bind(
        record.bookingAttemptId,
        record.ciphertext,
        record.iv,
        record.createdAt,
        record.expiresAt,
      )
      .first<PrivateBookingPayloadRow>();
    if (!row) throw new Error("The private booking payload could not be saved.");
    return mapPrivateBookingPayload(row);
  }

  async getPrivatePayload(
    bookingAttemptId: string,
    now: number,
  ): Promise<PrivateBookingPayloadRecord | null> {
    await this.ready();
    const row = await this.db
      .prepare(
        `SELECT * FROM booking_private_payloads
        WHERE booking_attempt_id = ? AND expires_at > ?`,
      )
      .bind(bookingAttemptId, now)
      .first<PrivateBookingPayloadRow>();
    return row ? mapPrivateBookingPayload(row) : null;
  }

  async deletePrivatePayload(bookingAttemptId: string): Promise<boolean> {
    await this.ready();
    const result = await this.db
      .prepare(
        `DELETE FROM booking_private_payloads
        WHERE booking_attempt_id = ?`,
      )
      .bind(bookingAttemptId)
      .run();
    return d1Changes(result) === 1;
  }

  async deleteExpiredPrivatePayloads(
    now: number,
    limit = 100,
  ): Promise<number> {
    await this.ready();
    const boundedLimit = Math.max(1, Math.min(500, Math.trunc(limit)));
    const result = await this.db
      .prepare(
        `DELETE FROM booking_private_payloads
        WHERE booking_attempt_id IN (
          SELECT booking_attempt_id FROM booking_private_payloads
          WHERE expires_at <= ?
          ORDER BY expires_at ASC
          LIMIT ?
        )`,
      )
      .bind(now, boundedLimit)
      .run();
    return d1Changes(result);
  }

  async transitionBookingAttempt(
    input: TransitionBookingAttemptInput,
  ): Promise<BookingAttemptRecord | null> {
    await this.ready();
    if (input.expectedStates.length === 0) {
      throw new TypeError("At least one current booking state is required.");
    }

    const providerRequestWasProvided = input.providerRequestId !== undefined;
    const paymentReferenceWasProvided = input.paymentReference !== undefined;
    const failureCodeWasProvided = input.failureCode !== undefined;
    const retryableWasProvided = input.retryable !== undefined;
    const row = await this.db
      .prepare(
        `UPDATE booking_attempts SET
          state = ?,
          provider_request_id = CASE WHEN ? = 1 THEN ? ELSE provider_request_id END,
          payment_reference = CASE WHEN ? = 1 THEN ? ELSE payment_reference END,
          failure_code = CASE WHEN ? = 1 THEN ? ELSE failure_code END,
          retryable = CASE WHEN ? = 1 THEN ? ELSE retryable END,
          updated_at = ?
        WHERE id = ? AND session_hash = ?
          AND state IN (${placeholders(input.expectedStates.length)})
        RETURNING *`,
      )
      .bind(
        input.nextState,
        providerRequestWasProvided ? 1 : 0,
        input.providerRequestId ?? null,
        paymentReferenceWasProvided ? 1 : 0,
        input.paymentReference ?? null,
        failureCodeWasProvided ? 1 : 0,
        input.failureCode ?? null,
        retryableWasProvided ? 1 : 0,
        input.retryable ? 1 : 0,
        input.now,
        input.id,
        input.sessionHash,
        ...input.expectedStates,
      )
      .first<BookingAttemptRow>();
    return row ? mapBookingAttempt(row) : null;
  }

  async finalizeBooking(input: FinalizeBookingInput): Promise<BookingRecord> {
    await this.ready();
    const attemptState: BookingAttemptState =
      input.status === "confirmed" ? "confirmed" : "manual_review";
    const itineraryJson = JSON.stringify(input.itinerary);
    const fareJson = JSON.stringify(input.fare);

    await this.db.batch([
      this.db
        .prepare(
          `INSERT INTO bookings (
            id, session_hash, booking_attempt_id, provider,
            provider_environment, provider_order_id, booking_reference, status,
            currency, total_amount_minor, itinerary_summary_json,
            fare_summary_json, created_at, updated_at
          )
          SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
          FROM booking_attempts
          WHERE id = ? AND session_hash = ?
            AND provider = ? AND provider_environment = ?
            AND currency = ? AND total_amount_minor = ?
            AND state IN ('payment_authorized', 'submitting', 'manual_review', 'confirmed')
          ON CONFLICT(booking_attempt_id) DO NOTHING`,
        )
        .bind(
          input.id,
          input.sessionHash,
          input.bookingAttemptId,
          input.provider,
          input.providerEnvironment,
          input.providerOrderId,
          input.bookingReference,
          input.status,
          input.currency.toUpperCase(),
          input.totalAmountMinor,
          itineraryJson,
          fareJson,
          input.now,
          input.now,
          input.bookingAttemptId,
          input.sessionHash,
          input.provider,
          input.providerEnvironment,
          input.currency.toUpperCase(),
          input.totalAmountMinor,
        ),
      this.db
        .prepare(
          `UPDATE booking_attempts
          SET state = ?, updated_at = ?
          WHERE id = ? AND session_hash = ?
            AND EXISTS (
              SELECT 1 FROM bookings
              WHERE bookings.booking_attempt_id = booking_attempts.id
            )`,
        )
        .bind(attemptState, input.now, input.bookingAttemptId, input.sessionHash),
      this.db
        .prepare(
          `UPDATE offer_selections
          SET status = 'booked', updated_at = ?
          WHERE id = ? AND session_hash = ?
            AND EXISTS (
              SELECT 1 FROM bookings
              WHERE bookings.booking_attempt_id = ?
                AND bookings.session_hash = offer_selections.session_hash
            )`,
        )
        .bind(
          input.now,
          input.offerSelectionId,
          input.sessionHash,
          input.bookingAttemptId,
        ),
    ]);

    const booking = await this.getBookingByAttempt(
      input.bookingAttemptId,
      input.sessionHash,
    );
    if (!booking) {
      throw new BookingStorageConflictError(
        "The booking attempt was not ready to be finalized.",
      );
    }
    if (
      booking.providerOrderId !== input.providerOrderId ||
      booking.bookingReference !== input.bookingReference
    ) {
      throw new BookingStorageConflictError(
        "The booking attempt is already linked to a different provider order.",
      );
    }
    return booking;
  }

  async getBookingForSession(
    id: string,
    sessionHash: string,
  ): Promise<BookingRecord | null> {
    await this.ready();
    const row = await this.db
      .prepare(`SELECT * FROM bookings WHERE id = ? AND session_hash = ?`)
      .bind(id, sessionHash)
      .first<BookingRow>();
    return row ? mapBooking(row) : null;
  }

  async getBookingByAttempt(
    bookingAttemptId: string,
    sessionHash: string,
  ): Promise<BookingRecord | null> {
    await this.ready();
    const row = await this.db
      .prepare(
        `SELECT * FROM bookings
        WHERE booking_attempt_id = ? AND session_hash = ?`,
      )
      .bind(bookingAttemptId, sessionHash)
      .first<BookingRow>();
    return row ? mapBooking(row) : null;
  }

  async getBookingByProviderOrder(
    provider: string,
    providerOrderId: string,
  ): Promise<BookingRecord | null> {
    await this.ready();
    const row = await this.db
      .prepare(
        `SELECT * FROM bookings
        WHERE provider = ? AND provider_order_id = ?`,
      )
      .bind(provider, providerOrderId)
      .first<BookingRow>();
    return row ? mapBooking(row) : null;
  }

  async transitionBookingStatus(input: {
    provider: string;
    providerOrderId: string;
    expectedStatuses: BookingStatus[];
    nextStatus: BookingStatus;
    now: number;
  }): Promise<BookingRecord | null> {
    await this.ready();
    if (input.expectedStatuses.length === 0) {
      throw new TypeError("At least one current booking status is required.");
    }
    const row = await this.db
      .prepare(
        `UPDATE bookings SET status = ?, updated_at = ?
        WHERE provider = ? AND provider_order_id = ?
          AND status IN (${placeholders(input.expectedStatuses.length)})
        RETURNING *`,
      )
      .bind(
        input.nextStatus,
        input.now,
        input.provider,
        input.providerOrderId,
        ...input.expectedStatuses,
      )
      .first<BookingRow>();
    return row ? mapBooking(row) : null;
  }

  async recordWebhookEvent(
    input: RecordWebhookEventInput,
  ): Promise<{ event: WebhookEventRecord; created: boolean }> {
    await this.ready();
    const inserted = await this.db
      .prepare(
        `INSERT INTO webhook_events (
          id, provider, provider_event_id, event_type, payload_hash,
          signature_hash, related_provider_order_id, status, received_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'received', ?)
        ON CONFLICT(provider, provider_event_id) DO NOTHING
        RETURNING *`,
      )
      .bind(
        input.id,
        input.provider,
        input.providerEventId,
        input.eventType,
        input.payloadHash,
        input.signatureHash,
        input.relatedProviderOrderId,
        input.receivedAt,
      )
      .first<WebhookEventRow>();
    if (inserted) {
      return { event: mapWebhookEvent(inserted), created: true };
    }

    const existing = await this.db
      .prepare(
        `SELECT * FROM webhook_events
        WHERE provider = ? AND provider_event_id = ?`,
      )
      .bind(input.provider, input.providerEventId)
      .first<WebhookEventRow>();
    if (
      !existing ||
      existing.payload_hash !== input.payloadHash ||
      existing.signature_hash !== input.signatureHash
    ) {
      throw new BookingStorageConflictError(
        "The webhook event identifier was reused with different content.",
      );
    }
    return { event: mapWebhookEvent(existing), created: false };
  }

  async transitionWebhookEvent(input: {
    provider: string;
    providerEventId: string;
    expectedStatuses: WebhookEventStatus[];
    nextStatus: WebhookEventStatus;
    failureCode?: string | null;
    processedAt?: number | null;
  }): Promise<WebhookEventRecord | null> {
    await this.ready();
    if (input.expectedStatuses.length === 0) {
      throw new TypeError("At least one current webhook status is required.");
    }
    const failureCodeWasProvided = input.failureCode !== undefined;
    const processedAtWasProvided = input.processedAt !== undefined;
    const row = await this.db
      .prepare(
        `UPDATE webhook_events SET
          status = ?,
          failure_code = CASE WHEN ? = 1 THEN ? ELSE failure_code END,
          processed_at = CASE WHEN ? = 1 THEN ? ELSE processed_at END
        WHERE provider = ? AND provider_event_id = ?
          AND status IN (${placeholders(input.expectedStatuses.length)})
        RETURNING *`,
      )
      .bind(
        input.nextStatus,
        failureCodeWasProvided ? 1 : 0,
        input.failureCode ?? null,
        processedAtWasProvided ? 1 : 0,
        input.processedAt ?? null,
        input.provider,
        input.providerEventId,
        ...input.expectedStatuses,
      )
      .first<WebhookEventRow>();
    return row ? mapWebhookEvent(row) : null;
  }
}
