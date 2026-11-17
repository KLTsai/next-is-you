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
  `HospitalEntry` holding the reader type, the official progress-page link,
  the display name and the supported departments. The entry's capability is
  derived from the reader type, never filled in.
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
much to offer. Nobody declares it: it is derived from the entry's `reader_type`
(no reader means `UNSUPPORTED`; a reader with `list_clinics` means
`FULL_SCHEDULE`; any other reader means `CURRENT_NUMBER_ONLY`), without building
a reader or touching transport. Decide which tier a hospital is in from what its
public source exposes:

| Capability | The source exposes | User experience |
|---|---|---|
| `FULL_SCHEDULE` | The day's roster for a department and session (which doctors and rooms are consulting) **and** the current called number | Cascading picker: choose department and date, pick a doctor from a live dropdown, type only the appointment number |
| `CURRENT_NUMBER_ONLY` | Only the current called number for an identified clinic, no roster | Manual entry, labelled with the hospital's clinic-code parts, and no clinic schedule request. A draft can be saved for any future day. Start is allowed on the visit day only (the backend decides), and admits the visit only when the Start read confirms the clinic; the refusals are `start_on_visit_day_only`, `hospital_cannot_find_clinic` and `hospital_page_unreachable`, each leaving the draft unchanged and sending the family nothing. The daily recheck skips these drafts |
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

A hospital may be registered as `UNSUPPORTED` with no reader while its source is
still being evidenced; reads for it fail closed and it is offered to no one.

## Steps to add one

1. **Evidence the source first** (its own ticket, for example #44). Capture the
   request contract and a real sample; verify identity and freshness. You can
   validate a captured sample offline with `source_samples.py` before writing any
   transport.
2. **Add the `Hospital` value** in `domain.py` if it is not already there.
3. **Write the reader module**, for example `shin_kong_reader.py`, implementing
   `HospitalReader` (`observe` and `observe_for_start`). For a `FULL_SCHEDULE`
   source also implement `ScheduleReader.list_clinics` so the picker can offer a
   doctor/room dropdown. Keep every hospital specific inside it. Honor the
   invariants below.
4. **Register it** in `HOSPITAL_REGISTRY` with its `display_name`,
   `reader_type` (for example `ShinKongReader`, built as
   `reader_type(deps.storage, deps.fetch)` unless you pass `build_reader`),
   `official_link`, departments and clinic-code labels.
5. **Add fixture-driven tests** for the reader. The registry contract test in
   `tests/test_hospital_registry.py` runs against every registered hospital, so
   a new entry is checked automatically. Make no live request in tests.

The catalog and roster endpoints already serve a newly registered hospital from
the backend; wiring the setup UI to consume them (the cascading picker and
graceful degradation) is tracked in #47.

## The contract

Until #95 lands, a new hospital touches these places. After #95 only the reader
module and the registry entry remain.

1. The reader module (`src/next_is_you/<hospital>_reader.py`).
2. `HOSPITAL_REGISTRY` in `hospital_registry.py` (reader type, display name,
   official link, departments, clinic-code labels).
3. The `Hospital` enum in `domain.py`.
4. The `hospital` CHECK constraint in `migrations/0001_initial.sql`, which needs
   a table rebuild migration to extend. #95 removes this.
5. The frontend hospital type and any frontend hospital knowledge, until the
   frontend change in #97 lands.

The registry contract test (`tests/test_hospital_registry.py`, class
`TestRegistryContract`) runs for every registered hospital. It checks that the
capability derives from the reader type, that every supported hospital offers a
department, that the official link is fixed HTTPS, and that the hospital id can
be stored with a visit. Later tickets add assertions to it; do not skip it for a
new hospital.

Rules every hospital follows:

- **Reader boundary.** A hospital's reader is the only place that knows its
  clinic schedule rules (end date, release time, publication rhythm), its clinic
  identity (how a draft's clinic code maps to a schedule row), its status
  vocabulary (cancelled, full, substitute) and its source access. Shared code
  knows a clinic only as a date, a session, a display label, labelled detail
  fields and an opaque clinic code it never parses. Use only what the hospital
  publicly states; an unstated rule is reported as unknown, never estimated.
- **Detail fields.** A reader must not drop a published field that helps a person
  confirm the clinic (room, location, clinic type, substitute doctor, status).
- **Label and details.** Each `ClinicOption` carries a non-empty `label` (the
  dropdown text, written by the reader) and an ordered `details` list of
  `(name, value)` pairs, which the setup form lists once the clinic is chosen.
  Build the label with `clinic_label(room, doctor, session_name)` so a hospital
  without room numbers gets no empty segment. The registry contract test asserts
  every option has a label; a new full-schedule hospital adds a roster fixture
  to it.
- **Family messages.** Messages are identical across hospitals and no reader
  affects their text.
- **Official link.** It lives in the registry entry and is fixed, server-owned,
  HTTPS-only (NIY-016) and never taken from a caller.
- **Retire, never delete.** To retire a hospital, remove its reader and keep its
  registry entry. It then derives as unsupported, shows as 尚未支援, and its
  stored visits fail closed. Deleting the entry would orphan stored visits.

### Source access rules

These come from `README.md` (Disclaimer and source access) and apply to every
reader: only pages any visitor can open, at a low rate, and only the clinic a
draft names; no bypass of a login, CAPTCHA, consent button, identity check or
block, with an honest client identity; no raw storage or republication, and a
link to the hospital's official page; stop reading a hospital that refuses
access; prefer official open data where the hospital publishes it.

### Record the hospital's terms before work starts

Before any reader work, record the hospital's terms of use and `robots.txt`
verbatim in the hospital's research or evidence ticket. Then classify:

- An explicit rule against automated access, or against storing content in any
  form, needs the captain's decision before the hospital is added.
- A plain no-reproduction line is recorded and does not block.
- The statutory 第4條 sentence is recorded and does not block.
- A `robots.txt` entry that names AI training crawlers does not apply to the
  reader, which is not one and identifies itself honestly. Record it anyway.

The law research behind this is `research/automated-access-taiwan-law.md`
(source research by a non-lawyer, not legal advice).

### Clinic schedule feasibility questions

In addition to the questions above, answer for each hospital:

1. How does it publish its clinic schedule (a page, a date-based form, a PDF, or
   not at all), and how far ahead does it cover?
2. Does it state a clinic schedule release time (門診表公布時間) publicly? If
   not, the reader reports it as unknown.

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
