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
  `HospitalEntry` holding a `SourceCapability` and a reader factory.
  `RegistryHospitalReader` is the single reader the scheduler and Start are
  given; it looks up `scope.hospital` and delegates.
- **A per-hospital reader module** - for example `ntuh_reader.py`
  (`NtuhProgressReader`). This is where all of one hospital's specifics live:
  its URLs, request contract, the language its pages are pinned to, how its
  markup is parsed, how a clinic is matched, and how the watch is bounded. A new
  hospital is a new module of this shape (for example `shin_kong_reader.py`).
- **`source_samples.py`** - offline parsers that turn a *captured* response
  sample into a normalized observation, with no transport. This is a
  source-verification tool (see Issue #44), **not** the live adapter layer. Do
  not add a live hospital here.

Adding a hospital is therefore: write one reader module, register one entry. No
other part of the system - the scheduler, the send gate, the frontend - changes.

## Is a hospital feasible? Pick its capability

Every hospital declares a `SourceCapability`, which the setup UI reads to decide
how much to offer. Decide which tier a hospital is in from what its public source
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

A hospital may be registered as `UNSUPPORTED` with no reader while its source is
still being evidenced; reads for it fail closed and it is offered to no one.

## Steps to add one

1. **Evidence the source first** (its own ticket, for example #44). Capture the
   request contract and a real sample; verify identity and freshness. You can
   validate a captured sample offline with `source_samples.py` before writing any
   transport.
2. **Add the `Hospital` value** in `domain.py` if it is not already there.
3. **Write the reader module**, for example `shin_kong_reader.py`, implementing
   `HospitalReader` (`observe` and `observe_for_start`). Keep every hospital
   specific inside it. Honor the invariants below.
4. **Register it** in `HOSPITAL_REGISTRY` with its `SourceCapability` and a
   factory `lambda deps: ShinKongReader(deps.storage, deps.fetch)`.
5. **Add fixture-driven tests** for the reader, and a registry test that the new
   hospital dispatches and reports the right capability. Make no live request in
   tests.

The frontend needs no change to read a newly registered hospital once the setup
UI consumes the registry (tracked in #47); until then the hospital list is still
frontend-side.

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
