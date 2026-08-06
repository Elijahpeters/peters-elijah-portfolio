PRAGMA foreign_keys=OFF;

CREATE TABLE provider_offer_cache_next (
  cache_id TEXT PRIMARY KEY NOT NULL,
  provider TEXT NOT NULL CHECK (provider IN ('amadeus', 'ignav')),
  provider_environment TEXT NOT NULL CHECK (provider_environment IN ('test', 'live')),
  provider_payload_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  CHECK (expires_at > created_at)
);

INSERT INTO provider_offer_cache_next (
  cache_id, provider, provider_environment, provider_payload_json,
  created_at, expires_at
)
SELECT
  cache_id, provider, provider_environment, provider_payload_json,
  created_at, expires_at
FROM provider_offer_cache;

DROP TABLE provider_offer_cache;

ALTER TABLE provider_offer_cache_next RENAME TO provider_offer_cache;

CREATE INDEX idx_provider_offer_cache_expires_at
ON provider_offer_cache(expires_at);

PRAGMA foreign_keys=ON;

PRAGMA optimize;
