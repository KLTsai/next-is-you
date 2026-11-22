-- Risk: rebuild
-- Data at risk: outbound_events (rebuilt and refilled)
-- Compatibility: previous code runs on the new schema; new code needs it to store the new reminder kinds and skipped reminders
-- Issue #164: the reminder kinds of #136, and a cap of 8 reminders.
--
-- Kinds (letters as in #136): check_in_soon (a), passed (b, also "being seen
-- while not checked in"), checked_in (c), getting_close (d), almost_turn (e),
-- check_in_order (f), left_list (g), left_list_not_checked_in (h), unavailable.
-- The legacy `near` kind, its cap of 20 and its rows stay until #147's rebuild.
--
-- Outcome `skipped` is a reminder that became due together with a more urgent
-- one: it counts as sent (it holds its kind) but not toward the cap, and is never
-- sent. It cannot become another outcome, and no other outcome can become it.
--
-- event_kind and outcome are limited by a CHECK, which SQLite cannot alter, so
-- the table is rebuilt with every row copied. Nothing references outbound_events.
-- Needs a Staging rehearsal before Promote (docs/CI-CD.md).

CREATE TABLE outbound_events_v2 (
    id TEXT PRIMARY KEY NOT NULL,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    recipient_id TEXT NOT NULL REFERENCES recipients(id) ON DELETE CASCADE,
    event_kind TEXT NOT NULL CHECK (event_kind IN (
        'near', 'unavailable', 'check_in_soon', 'passed', 'checked_in',
        'getting_close', 'almost_turn', 'check_in_order', 'left_list',
        'left_list_not_checked_in'
    )),
    retry_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('pending', 'in_flight', 'accepted', 'failed', 'unknown', 'superseded')
        OR (outcome = 'skipped' AND event_kind NOT IN ('near', 'unavailable'))
    ),
    created_at TEXT NOT NULL,
    request_started_at TEXT,
    settled_at TEXT,
    error_code TEXT,
    first_request_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0)
);

INSERT INTO outbound_events_v2 (
    id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome,
    created_at, request_started_at, settled_at, error_code, first_request_at,
    attempt_count
)
SELECT
    id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome,
    created_at, request_started_at, settled_at, error_code, first_request_at,
    attempt_count
FROM outbound_events;

DROP TABLE outbound_events;
ALTER TABLE outbound_events_v2 RENAME TO outbound_events;

CREATE INDEX outbound_events_pending ON outbound_events (outcome, created_at);

CREATE UNIQUE INDEX one_reminder_per_kind_visit_recipient
    ON outbound_events (visit_id, recipient_id, event_kind)
    WHERE event_kind != 'near';

-- The triggers are created after the refill so restoring rows that already sit
-- at a cap is not blocked.
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

CREATE TRIGGER outbound_events_reminder_cap
BEFORE INSERT ON outbound_events
WHEN NEW.event_kind != 'near' AND NEW.outcome != 'skipped'
BEGIN
    SELECT CASE WHEN (
        SELECT COUNT(*) FROM outbound_events
        WHERE visit_id = NEW.visit_id AND recipient_id = NEW.recipient_id
            AND event_kind != 'near' AND outcome != 'skipped'
    ) >= 8 THEN RAISE(ABORT, 'reminder cap of 8 reached for visit recipient') END;
END;

CREATE TRIGGER outbound_events_skipped_is_final
BEFORE UPDATE OF outcome ON outbound_events
WHEN (OLD.outcome = 'skipped') != (NEW.outcome = 'skipped')
BEGIN
    SELECT RAISE(ABORT, 'a skipped reminder stays skipped');
END;
