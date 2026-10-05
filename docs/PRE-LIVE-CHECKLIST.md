# Pre-live checklist

These gates are not proven by local synthetic tests and must be completed before
enabling real reminders:

Use [Issue #18 held HTTPS setup](HTTPS-SERVICE.md) for provisioning, deployment
acceptance, and hold/stop and rollback procedures. This checklist owns the gates
for enabling real reminders.

- [ ] **Hospital sources:** confirm each hospital permits the access method, verify
  live clinic/date/session identity and current-number meaning, measure freshness,
  and exercise timeout, denial, challenge, ambiguity, and schema-change handling.
- [ ] **LINE:** verify production Login, organizer allowlist and callback settings,
  friendship and consent behavior, token handling, retry-key behavior, and real
  handset delivery with authorized test accounts. An accepted API response is not
  proof of handset delivery.
- [ ] **Cloudflare Free:** verify deployed Worker, D1, SQLite Durable Object, Cron,
  and asset bindings; measure CPU and quota headroom; exercise backup/restore and
  the recovery hold against the deployed platform. Local bindings do not prove
  deployed serialization or limits.
- [ ] **Data retention:** verify production timestamps, Taipei cutoff behavior,
  48-hour cleanup scheduling, cascade deletion, and recipient withdrawal against
  deployed storage and operational backups. Confirm backup retention separately.
- [ ] **Production configuration:** check secrets, organizer allowlist, HTTPS
  callback, and test-mode exclusion in the deployment environment without exposing
  values in logs or repository files.
