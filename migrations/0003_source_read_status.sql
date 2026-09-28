ALTER TABLE visits ADD COLUMN latest_source_read_status TEXT NOT NULL DEFAULT 'unavailable'
    CHECK (latest_source_read_status IN ('usable', 'unavailable', 'stale', 'untrusted', 'scope_mismatch', 'invalid'));
ALTER TABLE visits ADD COLUMN latest_source_read_reason TEXT NOT NULL DEFAULT 'no_observation'
    CHECK (latest_source_read_reason IN ('none', 'no_observation', 'timeout', 'stale_sample', 'untrusted_source', 'scope_mismatch', 'empty_result', 'schema_drift', 'access_denied', 'ambiguous_match', 'invalid_data'));
