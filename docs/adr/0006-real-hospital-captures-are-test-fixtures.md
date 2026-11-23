---
status: accepted
---

# Real hospital captures are test fixtures

The NTUH detail-page fixtures were built by hand from the list card, not from a real detail page, so hundreds of green tests proved nothing about the real page: a real clinic schedule page later measured 6.9 million characters against the reader's 3.5 million cap (#202). We decided on 2026-11-23, in the #202 grilling, that pages captured from a hospital's public site are committed as test fixtures as captured, and replay tests read them.

The repository rule "use synthetic local data" protects people: organizers, recipients and patients. A captured public page names doctors and lists patient numbers, but it identifies no patient, and the doctors' names are already published by the hospital on the same public page. Replacing doctor names with stand-ins was considered and rejected: the reader matches a card by room and doctor, so every capture of a day would need the same stand-ins, and anyone tracing a problem would have to translate between the stand-ins and the live site.

## Consequences

- Expected values in a replay test are read off the page as a person sees it (current light and its flag, highest called, a number's state), or checked against the capture's analysis notes. They are never copied from the parser's output.
- A capture holds no cookies, session tokens or anything a request sent; only the page the hospital served.
- The repository is public, so a committed capture stays in its history.
