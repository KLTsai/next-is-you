-- Risk: rebuild
-- Data at risk: visits, visit_recipients, outbound_events (rebuilt and refilled; cascade from visits)
-- Compatibility: previous code runs on the new schema; new code needs it to store card_not_found and substitute_doctor
-- Issue #135: two new source-read reasons for the visit-day card match.
--
-- `card_not_found`: the hospital's list of the day's cards has no card for the
-- visit. `substitute_doctor`: the card in the visit's room and session names a
-- substitute doctor. visits.latest_source_read_reason limited the reasons with
-- a CHECK, and SQLite cannot alter a CHECK, so the visits table is rebuilt with
-- the two reasons added and every row copied back, the same way 0007 did it.
--
-- Dropping visits would cascade-delete every visit_recipients and
-- outbound_events row (both reference visits with ON DELETE CASCADE). So the two
-- dependent tables are copied aside, dropped, and recreated after visits, with
-- their current definitions, indexes and trigger, then refilled with every row.
-- Needs a Staging rehearsal before Promote (docs/CI-CD.md).

CREATE TABLE visit_recipients_keep AS SELECT * FROM visit_recipients;
CREATE TABLE outbound_events_keep AS SELECT * FROM outbound_events;

DROP TABLE outbound_events;
DROP TABLE visit_recipients;

CREATE TABLE visits_v2 (
    id TEXT PRIMARY KEY NOT NULL,
    hospital TEXT NOT NULL,
    visit_date TEXT NOT NULL,
    department_code TEXT NOT NULL,
    clinic_code TEXT NOT NULL,
    clinic_session TEXT NOT NULL CHECK (clinic_session IN ('morning', 'afternoon', 'evening')),
    doctor_code TEXT,
    room_code TEXT,
    patient_number INTEGER NOT NULL CHECK (patient_number > 0),
    state TEXT NOT NULL CHECK (state IN ('draft', 'active', 'stopping', 'stopped', 'expired')),
    roster_frozen INTEGER NOT NULL DEFAULT 0 CHECK (roster_frozen IN (0, 1)),
    consecutive_unusable_reads INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_unusable_reads >= 0),
    near_last_current_number INTEGER,
    latest_observed_at TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    stopped_at TEXT,
    draft_expires_at TEXT,
    delete_after TEXT,
    latest_source_read_status TEXT NOT NULL DEFAULT 'unavailable'
        CHECK (latest_source_read_status IN ('usable', 'unavailable', 'stale', 'untrusted', 'scope_mismatch', 'invalid')),
    latest_source_read_reason TEXT NOT NULL DEFAULT 'no_observation'
        CHECK (latest_source_read_reason IN ('none', 'no_observation', 'timeout', 'stale_sample', 'untrusted_source', 'scope_mismatch', 'empty_result', 'schema_drift', 'access_denied', 'ambiguous_match', 'invalid_data', 'card_not_found', 'substitute_doctor')),
    near_prev_observed_number INTEGER,
    preflight_last_checked_date TEXT
);

INSERT INTO visits_v2 (
    id, hospital, visit_date, department_code, clinic_code, clinic_session,
    doctor_code, room_code, patient_number, state, roster_frozen,
    consecutive_unusable_reads, near_last_current_number, latest_observed_at,
    created_at, started_at, stopped_at, draft_expires_at, delete_after,
    latest_source_read_status, latest_source_read_reason,
    near_prev_observed_number, preflight_last_checked_date
)
SELECT
    id, hospital, visit_date, department_code, clinic_code, clinic_session,
    doctor_code, room_code, patient_number, state, roster_frozen,
    consecutive_unusable_reads, near_last_current_number, latest_observed_at,
    created_at, started_at, stopped_at, draft_expires_at, delete_after,
    latest_source_read_status, latest_source_read_reason,
    near_prev_observed_number, preflight_last_checked_date
FROM visits;

DROP TABLE visits;
ALTER TABLE visits_v2 RENAME TO visits;

CREATE UNIQUE INDEX one_active_visit_per_appointment
    ON visits (hospital, visit_date, department_code, clinic_code, clinic_session, patient_number)
    WHERE state IN ('active', 'stopping');
CREATE INDEX visits_cleanup_due ON visits (delete_after) WHERE delete_after IS NOT NULL;
CREATE INDEX visits_drafts_due ON visits (draft_expires_at) WHERE state = 'draft';

CREATE TABLE visit_recipients (
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    recipient_id TEXT NOT NULL REFERENCES recipients(id) ON DELETE CASCADE,
    selected_at TEXT NOT NULL,
    PRIMARY KEY (visit_id, recipient_id)
);

INSERT INTO visit_recipients (visit_id, recipient_id, selected_at)
SELECT visit_id, recipient_id, selected_at FROM visit_recipients_keep;

CREATE TABLE outbound_events (
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

-- The near cap trigger is created after the refill so restoring rows that
-- already sit at the cap is not blocked.
INSERT INTO outbound_events (
    id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome,
    created_at, request_started_at, settled_at, error_code, first_request_at,
    attempt_count
)
SELECT
    id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome,
    created_at, request_started_at, settled_at, error_code, first_request_at,
    attempt_count
FROM outbound_events_keep;

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

DROP TABLE outbound_events_keep;
DROP TABLE visit_recipients_keep;
