ALTER TABLE outbound_events ADD COLUMN first_request_at TEXT;
ALTER TABLE outbound_events ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0);
