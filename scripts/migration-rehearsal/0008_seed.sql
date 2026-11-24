-- Synthetic rows for rehearsing migration 0008 on a database at 0007 (issue #135).
-- Staging or local only. Every id starts with `rehearsal-8-` so the rows can be
-- found and removed afterwards.
--
-- Seed only while the database is in a recovery hold. Under it, scheduled
-- cleanup deletes nothing but expired drafts, and the drafts below expire in
-- 2027. Without the hold, the scheduler would settle the in-flight event,
-- finalize the stopping visit and erase the inactive recipient, and the
-- comparison would report changes that 0008 did not cause.
--
-- 0008 rebuilds visits, visit_recipients and outbound_events to widen the
-- source-read reason CHECK. Shapes covered: the 0007 seed's (every visit state,
-- nullable columns both set and NULL, an inactive recipient, a visit recipient
-- at the cap of 20 near reminders, an unavailable warning, every outbound
-- outcome) plus every source-read reason the CHECK allowed before 0008.

-- Clear every earlier rehearsal first, children before parents, so this seed
-- never collides with rows another seed left behind. GLOB is case-sensitive,
-- unlike LIKE, so only ids that start with exactly `rehearsal-` match.
DELETE FROM outbound_events
WHERE id GLOB 'rehearsal-*' OR visit_id GLOB 'rehearsal-*' OR recipient_id GLOB 'rehearsal-*';
DELETE FROM visit_recipients WHERE visit_id GLOB 'rehearsal-*' OR recipient_id GLOB 'rehearsal-*';
DELETE FROM visits WHERE id GLOB 'rehearsal-*';
DELETE FROM recipients WHERE id GLOB 'rehearsal-*';

INSERT INTO recipients (id, line_subject, display_name, consented_at, friendship_checked_at, active, created_at) VALUES
    ('rehearsal-8-r-1', 'rehearsal-8-line-1', 'Rehearsal One', '2026-11-19T00:00:00Z', '2026-11-19T00:00:00Z', 1, '2026-11-19T00:00:00Z'),
    ('rehearsal-8-r-2', 'rehearsal-8-line-2', 'Rehearsal Two', '2026-11-19T00:00:00Z', NULL, 1, '2026-11-19T00:00:00Z'),
    ('rehearsal-8-r-3', 'rehearsal-8-line-3', 'Rehearsal Three', NULL, NULL, 0, '2026-11-19T00:00:00Z');

INSERT INTO visits (
    id, hospital, visit_date, department_code, clinic_code, clinic_session,
    doctor_code, room_code, patient_number, state, roster_frozen,
    consecutive_unusable_reads, near_last_current_number, latest_observed_at,
    created_at, started_at, stopped_at, draft_expires_at, delete_after,
    latest_source_read_status, latest_source_read_reason,
    near_prev_observed_number, preflight_last_checked_date
) VALUES
    ('rehearsal-8-v-draft', 'ntuh-main', '2027-06-01', 'MED', 'MED-1', 'morning',
     NULL, NULL, 11, 'draft', 0,
     0, NULL, NULL,
     '2026-11-19T00:00:00Z', NULL, NULL, '2027-06-01T00:00:00Z', NULL,
     'unavailable', 'no_observation',
     NULL, NULL),
    ('rehearsal-8-v-active', 'ntuh-main', '2027-06-01', 'MED', 'MED-1', 'afternoon',
     'D001', 'R12', 22, 'active', 1,
     2, 15, '2027-06-01T06:00:00Z',
     '2026-11-19T00:00:00Z', '2027-06-01T05:00:00Z', NULL, NULL, NULL,
     'usable', 'none',
     14, '2027-06-01'),
    ('rehearsal-8-v-stopping', 'shin-kong-taipei', '2027-06-01', 'SUR', 'SUR-2', 'evening',
     'D002', NULL, 33, 'stopping', 1,
     0, 30, '2027-06-01T10:00:00Z',
     '2026-11-19T00:00:00Z', '2027-06-01T09:00:00Z', '2027-06-01T10:30:00Z', NULL, NULL,
     'stale', 'stale_sample',
     29, '2027-06-01'),
    ('rehearsal-8-v-stopped', 'shin-kong-taipei', '2027-06-02', 'SUR', 'SUR-2', 'morning',
     NULL, 'R3', 44, 'stopped', 1,
     5, NULL, '2027-06-02T03:00:00Z',
     '2026-11-19T00:00:00Z', '2027-06-02T01:00:00Z', '2027-06-02T04:00:00Z', NULL, '2027-06-04T04:00:00Z',
     'untrusted', 'untrusted_source',
     NULL, '2027-06-02'),
    ('rehearsal-8-v-expired', 'ntuh-main', '2027-06-03', 'PED', 'PED-1', 'afternoon',
     NULL, NULL, 55, 'expired', 0,
     0, NULL, NULL,
     '2026-11-19T00:00:00Z', NULL, NULL, '2027-06-03T00:00:00Z', '2027-06-05T00:00:00Z',
     'invalid', 'schema_drift',
     NULL, NULL);

INSERT INTO visit_recipients (visit_id, recipient_id, selected_at) VALUES
    ('rehearsal-8-v-draft', 'rehearsal-8-r-1', '2026-11-19T00:01:00Z'),
    ('rehearsal-8-v-active', 'rehearsal-8-r-1', '2026-11-19T00:01:00Z'),
    ('rehearsal-8-v-active', 'rehearsal-8-r-2', '2026-11-19T00:01:00Z'),
    ('rehearsal-8-v-stopping', 'rehearsal-8-r-2', '2026-11-19T00:01:00Z'),
    ('rehearsal-8-v-stopped', 'rehearsal-8-r-1', '2026-11-19T00:01:00Z'),
    ('rehearsal-8-v-expired', 'rehearsal-8-r-3', '2026-11-19T00:01:00Z');

-- Twenty near reminders for one visit recipient: the cap the trigger enforces.
INSERT INTO outbound_events (
    id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome,
    created_at, request_started_at, settled_at, error_code, first_request_at,
    attempt_count
)
WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 20)
SELECT
    printf('rehearsal-8-8-e-near-%02d', i),
    'rehearsal-8-v-active',
    'rehearsal-8-r-1',
    'near',
    printf('rehearsal-8-8-key-near-%02d', i),
    printf('{"current_number":%d}', i),
    CASE WHEN i < 20 THEN 'superseded' ELSE 'accepted' END,
    printf('2027-06-01T06:%02d:00Z', i),
    printf('2027-06-01T06:%02d:01Z', i),
    printf('2027-06-01T06:%02d:02Z', i),
    NULL,
    printf('2027-06-01T06:%02d:01Z', i),
    1
FROM n;

INSERT INTO outbound_events (
    id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome,
    created_at, request_started_at, settled_at, error_code, first_request_at,
    attempt_count
) VALUES
    ('rehearsal-8-e-unavailable', 'rehearsal-8-v-active', 'rehearsal-8-r-2', 'unavailable',
     'rehearsal-8-key-unavailable', '{"reason":"timeout"}', 'failed',
     '2027-06-01T06:30:00Z', '2027-06-01T06:30:01Z', '2027-06-01T06:30:05Z', 'line_500', '2027-06-01T06:30:01Z', 3),
    ('rehearsal-8-e-pending', 'rehearsal-8-v-stopping', 'rehearsal-8-r-2', 'near',
     'rehearsal-8-key-pending', '{"current_number":31}', 'pending',
     '2027-06-01T10:00:00Z', NULL, NULL, NULL, NULL, 0),
    ('rehearsal-8-e-in-flight', 'rehearsal-8-v-stopping', 'rehearsal-8-r-2', 'near',
     'rehearsal-8-key-in-flight', '{"current_number":32}', 'in_flight',
     '2027-06-01T10:01:00Z', '2027-06-01T10:01:01Z', NULL, NULL, '2027-06-01T10:01:01Z', 1),
    ('rehearsal-8-e-unknown', 'rehearsal-8-v-stopped', 'rehearsal-8-r-1', 'near',
     'rehearsal-8-key-unknown', '{"current_number":43}', 'unknown',
     '2027-06-02T03:00:00Z', '2027-06-02T03:00:01Z', NULL, 'timeout', '2027-06-02T03:00:01Z', 2);

-- One draft for each source-read reason the visits above leave out.
INSERT INTO visits (
    id, hospital, visit_date, department_code, clinic_code, clinic_session,
    patient_number, state, created_at, draft_expires_at,
    latest_source_read_status, latest_source_read_reason
) VALUES
    ('rehearsal-8-v-timeout', 'ntuh-main', '2027-06-04', 'OPH', 'OPH-1', 'morning',
     61, 'draft', '2026-11-20T00:00:00Z', '2027-06-04T00:00:00Z', 'unavailable', 'timeout'),
    ('rehearsal-8-v-scope', 'ntuh-main', '2027-06-04', 'OPH', 'OPH-2', 'morning',
     62, 'draft', '2026-11-20T00:00:00Z', '2027-06-04T00:00:00Z', 'scope_mismatch', 'scope_mismatch'),
    ('rehearsal-8-v-empty', 'ntuh-main', '2027-06-04', 'OPH', 'OPH-3', 'morning',
     63, 'draft', '2026-11-20T00:00:00Z', '2027-06-04T00:00:00Z', 'unavailable', 'empty_result'),
    ('rehearsal-8-v-denied', 'ntuh-main', '2027-06-04', 'OPH', 'OPH-4', 'morning',
     64, 'draft', '2026-11-20T00:00:00Z', '2027-06-04T00:00:00Z', 'unavailable', 'access_denied'),
    ('rehearsal-8-v-ambiguous', 'ntuh-main', '2027-06-04', 'OPH', 'OPH-5', 'morning',
     65, 'draft', '2026-11-20T00:00:00Z', '2027-06-04T00:00:00Z', 'invalid', 'ambiguous_match'),
    ('rehearsal-8-v-invalid', 'ntuh-main', '2027-06-04', 'OPH', 'OPH-6', 'morning',
     66, 'draft', '2026-11-20T00:00:00Z', '2027-06-04T00:00:00Z', 'invalid', 'invalid_data');
