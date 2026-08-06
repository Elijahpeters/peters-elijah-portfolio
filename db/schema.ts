/**
 * Runtime D1 schema for SkyETA's booking workflow.
 *
 * Keep every entry to exactly one SQL statement. Sites can then pass each
 * statement to D1.prepare() without relying on D1.exec()'s newline splitting.
 */
export const BOOKING_SCHEMA_STATEMENTS = [
  `CREATE TABLE IF NOT EXISTS provider_offer_cache (
    cache_id TEXT PRIMARY KEY NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('amadeus')),
    provider_environment TEXT NOT NULL CHECK (provider_environment IN ('test', 'live')),
    provider_payload_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    CHECK (expires_at > created_at)
  )`,
  `CREATE TABLE IF NOT EXISTS provider_request_quotas (
    quota_key TEXT PRIMARY KEY NOT NULL,
    window_started_at INTEGER NOT NULL,
    request_count INTEGER NOT NULL CHECK (request_count >= 1),
    expires_at INTEGER NOT NULL,
    CHECK (expires_at > window_started_at)
  )`,
  `CREATE TABLE IF NOT EXISTS booking_sessions (
    session_hash TEXT PRIMARY KEY NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
    created_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    CHECK (expires_at > created_at),
    CHECK (last_seen_at >= created_at)
  )`,
  `CREATE TABLE IF NOT EXISTS offer_selections (
    id TEXT PRIMARY KEY NOT NULL,
    session_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_environment TEXT NOT NULL CHECK (provider_environment IN ('test', 'live')),
    provider_offer_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('selected', 'refreshed', 'expired', 'booked')),
    offer_expires_at INTEGER,
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    total_amount_minor INTEGER NOT NULL CHECK (total_amount_minor >= 0),
    itinerary_summary_json TEXT NOT NULL,
    fare_summary_json TEXT NOT NULL,
    risk_summary_json TEXT NOT NULL,
    provider_snapshot_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (session_hash) REFERENCES booking_sessions(session_hash) ON DELETE CASCADE,
    CHECK (updated_at >= created_at)
  )`,
  `CREATE TABLE IF NOT EXISTS booking_attempts (
    id TEXT PRIMARY KEY NOT NULL,
    session_hash TEXT NOT NULL,
    offer_selection_id TEXT NOT NULL,
    idempotency_key_hash TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_environment TEXT NOT NULL CHECK (provider_environment IN ('test', 'live')),
    state TEXT NOT NULL CHECK (state IN ('created', 'price_changed', 'awaiting_payment', 'payment_authorized', 'submitting', 'confirmed', 'failed', 'manual_review')),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    total_amount_minor INTEGER NOT NULL CHECK (total_amount_minor >= 0),
    provider_request_id TEXT,
    payment_reference TEXT,
    failure_code TEXT,
    retryable INTEGER NOT NULL DEFAULT 0 CHECK (retryable IN (0, 1)),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (session_hash) REFERENCES booking_sessions(session_hash) ON DELETE CASCADE,
    FOREIGN KEY (offer_selection_id) REFERENCES offer_selections(id) ON DELETE RESTRICT,
    CHECK (updated_at >= created_at)
  )`,
  `CREATE TABLE IF NOT EXISTS booking_private_payloads (
    booking_attempt_id TEXT PRIMARY KEY NOT NULL,
    ciphertext TEXT NOT NULL,
    iv TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    FOREIGN KEY (booking_attempt_id) REFERENCES booking_attempts(id) ON DELETE CASCADE,
    CHECK (expires_at > created_at)
  )`,
  `CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY NOT NULL,
    session_hash TEXT NOT NULL,
    booking_attempt_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    provider_environment TEXT NOT NULL CHECK (provider_environment IN ('test', 'live')),
    provider_order_id TEXT NOT NULL,
    booking_reference TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'cancelled', 'refunded', 'manual_review')),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    total_amount_minor INTEGER NOT NULL CHECK (total_amount_minor >= 0),
    itinerary_summary_json TEXT NOT NULL,
    fare_summary_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (session_hash) REFERENCES booking_sessions(session_hash) ON DELETE RESTRICT,
    FOREIGN KEY (booking_attempt_id) REFERENCES booking_attempts(id) ON DELETE RESTRICT,
    CHECK (updated_at >= created_at)
  )`,
  `CREATE TABLE IF NOT EXISTS webhook_events (
    id TEXT PRIMARY KEY NOT NULL,
    provider TEXT NOT NULL,
    provider_event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    signature_hash TEXT NOT NULL,
    related_provider_order_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('received', 'processing', 'processed', 'ignored', 'failed')),
    failure_code TEXT,
    received_at INTEGER NOT NULL,
    processed_at INTEGER
  )`,
  `CREATE INDEX IF NOT EXISTS idx_booking_sessions_expires_at
    ON booking_sessions(expires_at)`,
  `CREATE INDEX IF NOT EXISTS idx_provider_offer_cache_expires_at
    ON provider_offer_cache(expires_at)`,
  `CREATE INDEX IF NOT EXISTS idx_provider_request_quotas_expires_at
    ON provider_request_quotas(expires_at)`,
  `CREATE UNIQUE INDEX IF NOT EXISTS idx_offer_selections_session_provider_offer
    ON offer_selections(session_hash, provider, provider_offer_id)`,
  `CREATE INDEX IF NOT EXISTS idx_offer_selections_session_created
    ON offer_selections(session_hash, created_at DESC)`,
  `CREATE UNIQUE INDEX IF NOT EXISTS idx_booking_attempts_idempotency_hash
    ON booking_attempts(idempotency_key_hash)`,
  `CREATE UNIQUE INDEX IF NOT EXISTS idx_booking_attempts_payment_reference
    ON booking_attempts(payment_reference)
    WHERE payment_reference IS NOT NULL`,
  `CREATE INDEX IF NOT EXISTS idx_booking_attempts_session_created
    ON booking_attempts(session_hash, created_at DESC)`,
  `CREATE INDEX IF NOT EXISTS idx_booking_attempts_open_state
    ON booking_attempts(state, updated_at)
    WHERE state IN ('created', 'price_changed', 'awaiting_payment', 'payment_authorized', 'submitting', 'manual_review')`,
  `CREATE INDEX IF NOT EXISTS idx_booking_private_payloads_expires_at
    ON booking_private_payloads(expires_at)`,
  `CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_attempt
    ON bookings(booking_attempt_id)`,
  `CREATE UNIQUE INDEX IF NOT EXISTS idx_bookings_provider_order
    ON bookings(provider, provider_order_id)`,
  `CREATE INDEX IF NOT EXISTS idx_bookings_session_created
    ON bookings(session_hash, created_at DESC)`,
  `CREATE UNIQUE INDEX IF NOT EXISTS idx_webhook_events_provider_event
    ON webhook_events(provider, provider_event_id)`,
  `CREATE INDEX IF NOT EXISTS idx_webhook_events_pending
    ON webhook_events(status, received_at)
    WHERE status IN ('received', 'processing', 'failed')`,
  `CREATE INDEX IF NOT EXISTS idx_webhook_events_provider_order
    ON webhook_events(provider, related_provider_order_id)
    WHERE related_provider_order_id IS NOT NULL`,
] as const;

export const BOOKING_SCHEMA_OPTIMIZE_STATEMENT = "PRAGMA optimize";
