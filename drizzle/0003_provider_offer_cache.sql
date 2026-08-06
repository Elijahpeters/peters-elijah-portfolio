CREATE TABLE IF NOT EXISTS provider_offer_cache (
  cache_id TEXT PRIMARY KEY NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('amadeus')),
  provider_environment TEXT NOT NULL CHECK (provider_environment IN ('test', 'live')),
  provider_payload_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  CHECK (expires_at > created_at)
);

CREATE INDEX IF NOT EXISTS idx_provider_offer_cache_expires_at
ON provider_offer_cache(expires_at);

PRAGMA optimize;
