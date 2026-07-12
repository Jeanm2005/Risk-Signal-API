-- One-time migration: add an optional expiry to api_keys so demo keys can self-expire.
-- Existing (non-demo) keys have NULL expires_at, meaning "never expires".
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS expires_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_api_keys_expires_at ON api_keys (expires_at)
    WHERE expires_at IS NOT NULL;