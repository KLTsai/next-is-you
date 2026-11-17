"""Server-owned official hospital links for the organizer visit projection.

The links live in the hospital registry entry. This module only applies the
NIY-016 rule when reading one: a registered hospital's fixed link, HTTPS only,
and never a value supplied by a caller.
"""

from __future__ import annotations

from next_is_you.hospital_registry import HOSPITAL_REGISTRY


def progress_link(hospital: str) -> str | None:
    """Return the fixed HTTPS source link for a registered hospital, if any."""
    for registered, entry in HOSPITAL_REGISTRY.items():
        if registered == hospital:
            url = entry.progress_url
            if url is None or not url.startswith("https://"):
                return None
            return url
    return None
