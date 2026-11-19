-- Read-only snapshot taken before and after a rehearsed migration (issue #111).
-- Every row of every table, in a fixed order, so two snapshots can be diffed.
-- Staging or local only: never run it against production, which holds LINE
-- identifiers. On production, count rows instead (docs/CI-CD.md).
SELECT name FROM d1_migrations ORDER BY id;
SELECT * FROM recipients ORDER BY id;
SELECT * FROM invitations ORDER BY token_hash;
SELECT * FROM visits ORDER BY id;
SELECT * FROM visit_recipients ORDER BY visit_id, recipient_id;
SELECT * FROM outbound_events ORDER BY id;
PRAGMA foreign_key_check;
