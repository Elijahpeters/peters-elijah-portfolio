CREATE TABLE IF NOT EXISTS provider_request_quotas (
  quota_key TEXT PRIMARY KEY NOT NULL,
  window_started_at INTEGER NOT NULL,
  request_count INTEGER NOT NULL CHECK (request_count >= 1),
  expires_at INTEGER NOT NULL,
  CHECK (expires_at > window_started_at)
);

CREATE INDEX IF NOT EXISTS idx_provider_request_quotas_expires_at
ON provider_request_quotas(expires_at);

PRAGMA optimize;
