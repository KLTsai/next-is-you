-- Issue #33: send repeat near reminders as the called number moves inside the window.
--
-- 1. Track the previously observed scheduled number per visit. This is distinct
--    from near_last_current_number (a display value that the UI Start observation
--    sets and that an unusable read clears). near_prev_observed_number only moves
--    on a usable scheduled read, so the first scheduled in-window read after Start
--    still differs from it and a read repeated after an outage does not.
-- 2. Allow up to 20 near reminders per logical visit and recipient while keeping a
--    single unavailable warning, enforced by stored constraints rather than only
--    by application code.

ALTER TABLE visits ADD COLUMN near_prev_observed_number INTEGER;

-- Rebuild outbound_events to drop the one-event-per-kind UNIQUE table constraint
-- (which capped near reminders at one) and to admit the 'superseded' outcome used
-- when a newer near reminder retracts an earlier unsent one. A partial unique index
-- keeps the single unavailable warning; a BEFORE INSERT trigger caps near reminders
-- at 20 per visit and recipient in stored data.
CREATE TABLE outbound_events_v2 (
    id TEXT PRIMARY KEY NOT NULL,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    recipient_id TEXT NOT NULL REFERENCES recipients(id) ON DELETE CASCADE,
    event_kind TEXT NOT NULL CHECK (event_kind IN ('near', 'unavailable')),
    retry_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('pending', 'in_flight', 'accepted', 'failed', 'unknown', 'superseded')),
    created_at TEXT NOT NULL,
    request_started_at TEXT,
    settled_at TEXT,
    error_code TEXT,
    first_request_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0)
);

INSERT INTO outbound_events_v2 (
    id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome,
    created_at, request_started_at, settled_at, error_code, first_request_at, attempt_count
)
SELECT id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome,
    created_at, request_started_at, settled_at, error_code, first_request_at, attempt_count
FROM outbound_events;

DROP TABLE outbound_events;
ALTER TABLE outbound_events_v2 RENAME TO outbound_events;

CREATE INDEX outbound_events_pending ON outbound_events (outcome, created_at);

CREATE UNIQUE INDEX one_unavailable_per_visit_recipient
    ON outbound_events (visit_id, recipient_id)
    WHERE event_kind = 'unavailable';

CREATE TRIGGER outbound_events_near_cap
BEFORE INSERT ON outbound_events
WHEN NEW.event_kind = 'near'
BEGIN
    SELECT CASE WHEN (
        SELECT COUNT(*) FROM outbound_events
        WHERE visit_id = NEW.visit_id AND recipient_id = NEW.recipient_id
            AND event_kind = 'near'
    ) >= 20 THEN RAISE(ABORT, 'near reminder cap of 20 reached for visit recipient') END;
END;
