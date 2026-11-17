"""Server-owned official hospital links for the organizer visit projection.

The link itself lives in each hospital's registry entry; this module only
resolves a stored hospital id to it and refuses anything that is not a fixed
HTTPS link.
"""

from __future__ import annotations

from next_is_you import hospital_registry


def progress_link(hospital: str) -> str | None:
    """Return the fixed HTTPS source link for a registered hospital, if any."""
    entry = hospital_registry.HOSPITAL_REGISTRY.get(hospital)
    if entry is None or not entry.official_link.startswith("https://"):
        return None
    return entry.official_link
