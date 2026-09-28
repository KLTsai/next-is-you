"""Server-owned official hospital links for the organizer visit projection."""

from __future__ import annotations

from types import MappingProxyType


_PROGRESS_LINKS = MappingProxyType({
    "ntuh-main": "https://registration.ntuh.gov.tw/WebReg/WebReg/ClinicCurrentLightNo?vHospCode=T0",
    "shin-kong-taipei": "https://reg.skh.org.tw/",
})


def progress_link(hospital: str) -> str | None:
    """Return the fixed HTTPS source link for a supported hospital, if any."""
    url = _PROGRESS_LINKS.get(hospital)
    if url is None or not url.startswith("https://"):
        return None
    return url
