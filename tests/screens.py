"""Browser sizes every browser test uses (issue #208).

Family members always open the product on a phone, so the pages they open are
tested on PHONE only. Organizer pages are tested on every entry of SCREENS.
"""

from __future__ import annotations

SCREENS = {
    "desktop": {"viewport": {"width": 1280, "height": 900}},
    "phone": {
        "viewport": {"width": 390, "height": 844},
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True,
    },
}
PHONE = SCREENS["phone"]
