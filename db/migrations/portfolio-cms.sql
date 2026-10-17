-- Apply ONLY to the separate CMS_DB database; never to SkyETA's DB.
CREATE TABLE IF NOT EXISTS portfolio_content (
 id INTEGER PRIMARY KEY CHECK (id = 1), draft TEXT NOT NULL, published TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 0, published_at TEXT
);
CREATE TABLE IF NOT EXISTS portfolio_versions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS portfolio_login_limits (
 bucket TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires INTEGER NOT NULL
);

-- Small public uploads; 1 MiB per file, 100 MiB total raw file bytes.
-- Reapplying this idempotent migration also upgrades an existing CMS database.
CREATE TABLE IF NOT EXISTS portfolio_media (
  key TEXT PRIMARY KEY,
  content_type TEXT NOT NULL,
  data TEXT NOT NULL,
  size INTEGER NOT NULL CHECK (size > 0 AND size <= 1048576)
);
CREATE TRIGGER IF NOT EXISTS portfolio_media_capacity
BEFORE INSERT ON portfolio_media
WHEN (SELECT COALESCE(SUM(size), 0) FROM portfolio_media) + NEW.size > 104857600
BEGIN
  SELECT RAISE(ABORT, 'MEDIA_CAPACITY');
END;
