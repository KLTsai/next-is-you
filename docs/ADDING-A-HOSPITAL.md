# Adding a hospital

This explains how the system reads more than one hospital, how to tell whether a
given hospital is feasible to add, and what work adding one involves. You do not
need to read the source to answer "can we support hospital X, and what would it
take".

## How the system is put together

The rest of the system never names a specific hospital. It reads every hospital
through one interface and one dispatcher:

- **`HospitalReader` (`src/next_is_you/domain.py`)** - the fixed interface:
  `observe` (a scheduled read) and `observe_for_start` (the Start read, which may
  reuse a recent good read). Every hospital is reached as one of these.
- **`hospital_registry` (`src/next_is_you/hospital_registry.py`)** - the one
  place that knows which hospitals exist. It maps each `Hospital` to a
  `HospitalEntry` holding the display name, the official progress-page link and
  the reader *type*. The capability is derived from that type, never declared.
  `RegistryHospitalReader` is the single reader the scheduler and Start are
  given; it looks up `scope.hospital` and delegates.
- **A per-hospital reader module** - for example `ntuh_reader.py`
  (`NtuhProgressReader`). This is where all of one hospital's specifics live:
  its URLs, request contract, the language its pages are pinned to, how its
  markup is parsed, how a clinic is matched, and how the watch is bounded. A new
  hospital is a new module of this shape (for example `shin_kong_reader.py`).
- **The setup endpoints** - `GET /api/organizer/hospitals` returns the catalog
  (each hospital's `display_name` and `capability`) straight from the registry,
  and `GET /api/organizer/hospitals/{hospital}/clinics?department=&date=`
  returns that day's roster through the gate. The frontend reads hospitals and
  clinics from these, so it holds no hospital names, URLs or source assumptions.
- **`ScheduleReader` (`domain`)** - the capability a `FULL_SCHEDULE` hospital
  adds on top of `HospitalReader`: `list_clinics(RosterQuery) -> ClinicRoster`,
  the day's consulting doctors and rooms for the picker. `RegistryHospitalReader`
  offers a roster only for `FULL_SCHEDULE` hospitals; everything else degrades to
  manual entry.
- **`source_samples.py`** - offline parsers that turn a *captured* response
  sample into a normalized observation, with no transport. This is a
  source-verification tool (see Issue #44), **not** the live adapter layer. Do
  not add a live hospital here.

Adding a hospital is therefore: write one reader module, register one entry. No
other part of the system - the scheduler, the send gate, the frontend - changes.

## Is a hospital feasible? Pick its capability

Every hospital has a `SourceCapability`, which the setup UI reads to decide how
much to offer. Nobody fills it in: `HospitalEntry.capability` is derived from the
entry's reader type. No reader means `UNSUPPORTED`; a reader that can list a
clinic schedule (it has `list_clinics`) means `FULL_SCHEDULE`; any other reader
means `CURRENT_NUMBER_ONLY`. It is known without building a reader or touching
transport. Decide which tier a hospital is in from what its public source
exposes:

| Capability | The source exposes | User experience |
|---|---|---|
| `FULL_SCHEDULE` | The day's roster for a department and session (which doctors and rooms are consulting) **and** the current called number | Cascading picker: choose department and date, pick a doctor from a live dropdown, type only the appointment number |
| `CURRENT_NUMBER_ONLY` | Only the current called number for an identified clinic, no roster | Manual entry with pre-submit validation |
| `UNSUPPORTED` | Neither, or nothing permitted/public | Not offered for automatic monitoring (manual-reminder path or excluded from the picker) |

Feasibility questions to answer before committing to a reader (this is the kind
of evidence Issue #17 produced for NTUH and Issue #44 is gathering for Shin
Kong):

1. **Is there a permitted public or authorized interface** carrying the current
   called/queue number for a clinic? If not, the hospital is `UNSUPPORTED`.
2. **Can a clinic be identified** from what the owner knows (department, doctor,
   room, session)? Matching must be exact and fail closed on ambiguity.
3. **Is the reading fresh**, and can you observe at least one real number change
   during a clinic session?
4. **Does the source also list the day's roster** for a department/session? If
   yes it can be `FULL_SCHEDULE`; if it only exposes a single clinic's number it
   is `CURRENT_NUMBER_ONLY`.

A hospital may be registered with no reader (it then derives as `UNSUPPORTED`)
while its source is still being evidenced; reads for it fail closed and it is
offered to no one.

Also ask, before work starts, how the hospital publishes its clinic schedule
(門診表: how many days ahead, in what rhythm, in what form) and whether it
publicly states a clinic schedule release time (門診表公布時間). Record only what
the hospital states; an unstated release time is unknown and is never estimated.

## Steps to add one

1. **Record the hospital's terms first** (see "The contract" below), then
   **evidence the source** (its own ticket, for example #44). Capture the
   request contract and a real sample; verify identity and freshness. You can
   validate a captured sample offline with `source_samples.py` before writing any
   transport.
2. **Add the `Hospital` value** in `domain.py` if it is not already there.
3. **Write the reader module**, for example `shin_kong_reader.py`, implementing
   `HospitalReader` (`observe` and `observe_for_start`), constructed as
   `ShinKongReader(storage, fetch)`. For a source that lists the clinic schedule
   also implement `ScheduleReader.list_clinics` so the picker can offer a
   doctor/room dropdown. Keep every hospital specific inside it. Honor the
   invariants below.
4. **Register it** in `HOSPITAL_REGISTRY` with its `display_name`, its fixed
   HTTPS `progress_url` and the reader type (`reader_type=ShinKongReader`). Do
   not set a capability; it is derived.
5. **Add fixture-driven tests** for the reader. The registry contract test
   (`tests/test_hospital_contract.py`) already runs every registered hospital
   through its assertions; add the hospital's synthetic fixtures, not a copy of
   those assertions. Make no live request in tests.

The catalog and roster endpoints already serve a newly registered hospital from
the backend; wiring the setup UI to consume them (the cascading picker and
graceful degradation) is tracked in #47.

## The contract

### Every place a new hospital touches (until #95 lands)

- The reader module (`src/next_is_you/<hospital>_reader.py`).
- One `HOSPITAL_REGISTRY` entry in `hospital_registry.py`, which also holds the
  official progress-page link.
- The `Hospital` enum in `domain.py`.
- The `hospital` CHECK constraint on `visits` in `migrations/0001_initial.sql`.
  It cannot be altered in place; a new id needs a migration that rebuilds the
  table holding every reminder (the outbound-events rebuild is prior art). #95
  removes this step.
- The frontend `Hospital` type (`frontend/src/organizer-api.d.ts`) until the
  frontend work in #97 makes it a plain string.

### Boundary rule

Each hospital's reader is the only place that knows its clinic schedule rules
(end date, release time, publication rhythm), its clinic identity (how a draft's
clinic code maps to a clinic schedule row), its status vocabulary (cancelled,
full, substitute) and its source access. Shared code (Start pre-flight, the daily
recheck, the API, the frontend) knows a clinic only as date, session, display
label, labelled detail fields and an opaque clinic code it never parses. Use only
what the hospital publicly states; an unstated rule is reported as unknown.

### Detail-field rule

A reader must not drop a published field that helps a person confirm the clinic
(room, location, clinic type, substitute doctor, status). Show what the hospital
publishes.

### Family messages

Family messages are identical across hospitals. No reader changes their text,
timing or recipients.

### Source access rules

These come from the README's "Disclaimer and source access" section and apply to
every reader:

- Only pages any visitor can open, at a low rate, and only the clinic a draft
  names.
- Never bypass a login, CAPTCHA, consent button, identity check or block; identify
  honestly instead of disguising the client.
- Keep no raw responses and republish nothing; link the organizer to the
  hospital's official page.
- Stop reading a hospital that refuses access, and prefer official open data
  where the hospital publishes it.

### Record the hospital's terms before work starts

Before any reader work, record the hospital's terms of use and its `robots.txt`
verbatim (with the date and URL) in its research note. Then classify:

- An explicit rule against automated access, or against storing content in any
  form, needs the captain's decision before the hospital is added. Do not start
  the reader until that decision is recorded.
- A plain "do not reproduce" line and the statutory 第4條 sentence (醫療機構網際網路資訊管理辦法
  第4條, a duty on hospitals to post a no-transcription statement) are recorded
  but do not block. They concern republication, which the reader does not do.
- A `robots.txt` entry naming AI training crawlers does not apply to the reader,
  which is not one and identifies itself honestly. Record it anyway.

The source research and its limits (not legal advice) are in
`research/automated-access-taiwan-law.md`.

### Retire, never delete

To retire a hospital keep its registry entry and remove its reader
(`reader_type=None`). It then derives as unsupported, stays visible as 尚未支援,
keeps its name and link for old reminders, and its stored visits fail closed.
Deleting the entry would orphan stored visits.

## Invariants every reader must honor

These are product-wide and are not yours to relax when adding a hospital:

- **Fail closed.** Zero or several matching clinics never produce a number.
  Timeout, stale, denied/challenged, and schema drift do not activate a draft or
  create a send. Return `ReadFailed` for an unusable read, `ReadSkipped` for a
  read that did not happen, `None` for no observation.
- **Untrusted source.** A usable read means fresh, exact and unambiguous - never
  that the number is verified against the room's physical light. No ETA is
  computed; the current number is never inferred from a next/highest number;
  missing is never treated as zero.
- **Minimal retention.** Keep only the matched clinic's transient read state;
  discard unrelated rows and raw responses. No raw patient responses are retained.
- **Freshness is read time**, taken from when the reader fetched, never from the
  page.

See `docs/NTUH-READER.md` for a worked example of all of this against a real
source.
