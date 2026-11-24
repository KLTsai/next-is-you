-- Synthetic rows for rehearsing migration 0009 on a database at 0008 (issue #164).
-- Staging or local only. Every id starts with `rehearsal-9-` so the rows can be
-- found and removed afterwards.
--
-- Seed only while the database is in a recovery hold (see 0008_seed.sql): without
-- it the scheduler would settle the in-flight events and the comparison would
-- report changes that 0009 did not cause.
--
-- 0009 rebuilds outbound_events. Shapes covered: both kinds that exist before it
-- in every outcome, a visit recipient at the cap of 20 near reminders, and every
-- nullable column both set and NULL.

-- Clear every earlier rehearsal first, children before parents, so this seed
-- never collides with rows another seed left behind. GLOB is case-sensitive,
-- unlike LIKE, so only ids that start with exactly `rehearsal-` match.
DELETE FROM outbound_events
WHERE id GLOB 'rehearsal-*' OR visit_id GLOB 'rehearsal-*' OR recipient_id GLOB 'rehearsal-*';
DELETE FROM visit_recipients WHERE visit_id GLOB 'rehearsal-*' OR recipient_id GLOB 'rehearsal-*';
DELETE FROM visits WHERE id GLOB 'rehearsal-*';
DELETE FROM recipients WHERE id GLOB 'rehearsal-*';

INSERT INTO recipients (id, line_subject, display_name, consented_at, friendship_checked_at, active, created_at) VALUES
    ('rehearsal-9-r-1', 'rehearsal-9-line-1', 'Rehearsal One', '2026-11-22T00:00:00Z', '2026-11-22T00:00:00Z', 1, '2026-11-22T00:00:00Z'),
    ('rehearsal-9-r-2', 'rehearsal-9-line-2', 'Rehearsal Two', '2026-11-22T00:00:00Z', NULL, 1, '2026-11-22T00:00:00Z');

INSERT INTO visits (
    id, hospital, visit_date, department_code, clinic_code, clinic_session,
    patient_number, state, created_at, started_at, stopped_at, delete_after
) VALUES
    ('rehearsal-9-v-active', 'ntuh-main', '2027-06-01', 'MED', 'MED-1', 'afternoon',
     22, 'active', '2026-11-22T00:00:00Z', '2026-11-22T05:00:00Z', NULL, NULL),
    ('rehearsal-9-v-stopping', 'ntuh-main', '2027-06-01', 'OPH', 'OPH-1', 'morning',
     33, 'stopping', '2026-11-22T00:00:00Z', '2026-11-22T05:00:00Z', NULL, NULL),
    ('rehearsal-9-v-stopped', 'ntuh-main', '2027-06-02', 'OPH', 'OPH-2', 'morning',
     44, 'stopped', '2026-11-22T00:00:00Z', '2026-11-22T05:00:00Z', '2026-11-22T06:00:00Z', '2027-06-04T06:00:00Z');

INSERT INTO visit_recipients (visit_id, recipient_id, selected_at) VALUES
    ('rehearsal-9-v-active', 'rehearsal-9-r-1', '2026-11-22T00:01:00Z'),
    ('rehearsal-9-v-active', 'rehearsal-9-r-2', '2026-11-22T00:01:00Z'),
    ('rehearsal-9-v-stopping', 'rehearsal-9-r-1', '2026-11-22T00:01:00Z'),
    ('rehearsal-9-v-stopping', 'rehearsal-9-r-2', '2026-11-22T00:01:00Z'),
    ('rehearsal-9-v-stopped', 'rehearsal-9-r-1', '2026-11-22T00:01:00Z'),
    ('rehearsal-9-v-stopped', 'rehearsal-9-r-2', '2026-11-22T00:01:00Z');

-- Twenty near reminders for one visit recipient: the cap the trigger enforces.
INSERT INTO outbound_events (
    id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome,
    created_at, request_started_at, settled_at, error_code, first_request_at,
    attempt_count
)
WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 20)
SELECT
    printf('rehearsal-9-e-near-%02d', i), 'rehearsal-9-v-active', 'rehearsal-9-r-1', 'near',
    printf('rehearsal-9-key-near-%02d', i), printf('{"current_number":%d}', i),
    CASE WHEN i < 20 THEN 'superseded' ELSE 'accepted' END,
    printf('2027-06-01T06:%02d:00Z', i), printf('2027-06-01T06:%02d:01Z', i),
    printf('2027-06-01T06:%02d:02Z', i),
    CASE WHEN i < 20 THEN 'superseded_by_newer_near' END,
    printf('2027-06-01T06:%02d:01Z', i), 1
FROM n;

INSERT INTO outbound_events (
    id, visit_id, recipient_id, event_kind, retry_key, payload_json, outcome,
    created_at, request_started_at, settled_at, error_code, first_request_at,
    attempt_count
) VALUES
    ('rehearsal-9-e-near-pending', 'rehearsal-9-v-active', 'rehearsal-9-r-2', 'near', 'rehearsal-9-key-np', '{"text":"a"}', 'pending',
     '2027-06-01T06:30:00Z', NULL, NULL, NULL, NULL, 0),
    ('rehearsal-9-e-near-flight', 'rehearsal-9-v-stopping', 'rehearsal-9-r-1', 'near', 'rehearsal-9-key-nf', '{"text":"a"}', 'in_flight',
     '2027-06-01T06:31:00Z', '2027-06-01T06:31:01Z', NULL, NULL, '2027-06-01T06:31:01Z', 1),
    ('rehearsal-9-e-near-failed', 'rehearsal-9-v-stopped', 'rehearsal-9-r-1', 'near', 'rehearsal-9-key-nx', '{"text":"a"}', 'failed',
     '2027-06-01T06:32:00Z', '2027-06-01T06:32:01Z', '2027-06-01T06:32:02Z', 'line_400', '2027-06-01T06:32:01Z', 1),
    ('rehearsal-9-e-near-unknown', 'rehearsal-9-v-stopped', 'rehearsal-9-r-2', 'near', 'rehearsal-9-key-nu', '{"text":"a"}', 'unknown',
     '2027-06-01T06:33:00Z', '2027-06-01T06:33:01Z', '2027-06-01T06:33:02Z', 'timeout', '2027-06-01T06:33:01Z', 4),
    ('rehearsal-9-e-un-pending', 'rehearsal-9-v-active', 'rehearsal-9-r-1', 'unavailable', 'rehearsal-9-key-up', '{"text":"b"}', 'pending',
     '2027-06-01T06:34:00Z', NULL, NULL, NULL, NULL, 0),
    ('rehearsal-9-e-un-accepted', 'rehearsal-9-v-active', 'rehearsal-9-r-2', 'unavailable', 'rehearsal-9-key-ua', '{"text":"b"}', 'accepted',
     '2027-06-01T06:35:00Z', '2027-06-01T06:35:01Z', '2027-06-01T06:35:02Z', NULL, '2027-06-01T06:35:01Z', 1),
    ('rehearsal-9-e-un-flight', 'rehearsal-9-v-stopping', 'rehearsal-9-r-1', 'unavailable', 'rehearsal-9-key-uf', '{"text":"b"}', 'in_flight',
     '2027-06-01T06:36:00Z', '2027-06-01T06:36:01Z', NULL, NULL, '2027-06-01T06:36:01Z', 1),
    ('rehearsal-9-e-un-unknown', 'rehearsal-9-v-stopping', 'rehearsal-9-r-2', 'unavailable', 'rehearsal-9-key-uu', '{"text":"b"}', 'unknown',
     '2027-06-01T06:37:00Z', '2027-06-01T06:37:01Z', '2027-06-01T06:37:02Z', 'timeout', '2027-06-01T06:37:01Z', 2),
    ('rehearsal-9-e-un-failed', 'rehearsal-9-v-stopped', 'rehearsal-9-r-1', 'unavailable', 'rehearsal-9-key-ux', '{"text":"b"}', 'failed',
     '2027-06-01T06:38:00Z', '2027-06-01T06:38:01Z', '2027-06-01T06:38:02Z', 'line_400', '2027-06-01T06:38:01Z', 1),
    ('rehearsal-9-e-un-superseded', 'rehearsal-9-v-stopped', 'rehearsal-9-r-2', 'unavailable', 'rehearsal-9-key-us', '{"text":"b"}', 'superseded',
     '2027-06-01T06:39:00Z', NULL, '2027-06-01T06:39:02Z', NULL, NULL, 0);
