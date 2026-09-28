import asyncio
import json

import pytest

from next_is_you.line_messaging import WorkersLineFriendshipClient


class FakeResponse:
    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self.ok = 200 <= status < 300
        self.payload = payload

    async def text(self) -> str:
        return json.dumps(self.payload)


@pytest.mark.parametrize(
    ("status", "payload", "expected"),
    [
        (200, {"friendFlag": True}, True),
        (200, {"friendFlag": False}, False),
        (200, {}, None),
        (401, {"message": "invalid token"}, None),
    ],
)
def test_friendship_check_uses_transient_profile_scope_token(status, payload, expected):
    async def scenario():
        requests = []

        async def fake_fetch(url, options):
            requests.append((url, options))
            return FakeResponse(status, payload)

        token = "transient-profile-scope-user-token"
        result = await WorkersLineFriendshipClient(fake_fetch).check_friendship(token)

        assert result.is_friend is expected
        assert requests == [
            (
                "https://api.line.me/friendship/v1/status",
                {"method": "GET", "headers": {"Authorization": f"Bearer {token}"}},
            )
        ]
        assert token not in repr(result)

    asyncio.run(scenario())
