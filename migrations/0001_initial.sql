PRAGMA foreign_keys = ON;

CREATE TABLE recipients (
    id TEXT PRIMARY KEY NOT NULL,
    line_subject TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    consented_at TEXT NOT NULL,
    friendship_checked_at TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE invitations (
    token_hash TEXT PRIMARY KEY NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE visits (
    id TEXT PRIMARY KEY NOT NULL,
    hospital TEXT NOT NULL CHECK (hospital IN ('ntuh-main', 'shin-kong-taipei')),
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
    delete_after TEXT
);

CREATE UNIQUE INDEX one_active_visit_per_appointment
    ON visits (hospital, visit_date, department_code, clinic_code, clinic_session, patient_number)
    WHERE state IN ('active', 'stopping');

CREATE TABLE visit_recipients (
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    recipient_id TEXT NOT NULL REFERENCES recipients(id) ON DELETE CASCADE,
    selected_at TEXT NOT NULL,
    PRIMARY KEY (visit_id, recipient_id)
);

CREATE TABLE outbound_events (
    id TEXT PRIMARY KEY NOT NULL,
    visit_id TEXT NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    recipient_id TEXT NOT NULL REFERENCES recipients(id) ON DELETE CASCADE,
    event_kind TEXT NOT NULL CHECK (event_kind IN ('near', 'unavailable')),
    retry_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('pending', 'in_flight', 'accepted', 'failed', 'unknown')),
    created_at TEXT NOT NULL,
    request_started_at TEXT,
    settled_at TEXT,
    error_code TEXT,
    UNIQUE (visit_id, recipient_id, event_kind)
);

CREATE INDEX visits_cleanup_due ON visits (delete_after) WHERE delete_after IS NOT NULL;
CREATE INDEX visits_drafts_due ON visits (draft_expires_at) WHERE state = 'draft';
CREATE INDEX outbound_events_pending ON outbound_events (outcome, created_at);
