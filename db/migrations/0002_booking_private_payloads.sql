CREATE TABLE IF NOT EXISTS booking_private_payloads (
  booking_attempt_id TEXT PRIMARY KEY NOT NULL,
  ciphertext TEXT NOT NULL,
  iv TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  FOREIGN KEY (booking_attempt_id) REFERENCES booking_attempts(id) ON DELETE CASCADE,
  CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS idx_booking_private_payloads_expires_at
ON booking_private_payloads(expires_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_booking_attempts_payment_reference
ON booking_attempts(payment_reference)
WHERE payment_reference IS NOT NULL;

PRAGMA optimize;
