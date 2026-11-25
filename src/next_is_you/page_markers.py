"""Words that show a hospital answered with a check or a refusal, not its page.

Shared by every hospital reader, so a marker added for one is seen by all.
"""

from __future__ import annotations

from typing import Literal

_CHALLENGE_MARKERS = (
    "captcha",
    "challenge",
    "robot check",
    "驗證碼",
    "安全驗證",
    "機器人驗證",
)
_DENIAL_MARKERS = ("access denied", "forbidden", "拒絕存取", "無權限")


def page_status(text: str) -> Literal["challenge", "denied"] | None:
    """Name a challenge or denial page from its casefolded text, else None."""
    if any(marker in text for marker in _CHALLENGE_MARKERS):
        return "challenge"
    if any(marker in text for marker in _DENIAL_MARKERS):
        return "denied"
    return None
