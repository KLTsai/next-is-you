---
status: accepted
---

# Staging has its own LINE provider

ADR 0001 let Staging share production's LINE Login channel (`2011753957`), each environment registering its own callback. That was fine while neither environment could send. Once Staging is made live as the full trial environment (#129), it sends real LINE messages, and the family must be able to tell a test reminder from a real one.

We decided on 2026-11-19, in the #129 grilling, that Staging has its own LINE provider, with its own Official Account, Login channel and Messaging API channel. Staging's Login channel stays in Developing mode with testers registered; production's is Published. This replaces the shared-channel clause in ADR 0001's consequences.

## Consequences

- A person's LINE user ID is per provider, so the same person has different IDs on Staging and production. The organizer allowlist, the captain's LINE ID and every recipient are set separately per environment, and nothing can be copied from one to the other.
- Each official account has its own monthly message quota.
- Going back to one shared provider would orphan every Staging recipient and allowlist entry.
