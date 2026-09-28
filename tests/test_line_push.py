import asyncio
import json

import pytest

from next_is_you.line_messaging import (
    LINE_PUSH_URL,
    LinePushClient,
    LinePushHttpResponse,
)

RECIPIENT_USER_ID = "U0123456789abcdef0123456789abcdef"


class FakeTransport:
    def __init__(self, response=None, error=None):
        self.response = response or LinePushHttpResponse(status_code=200)
        self.error = error
        self.requests = []

    async def post(self, url, *, headers, body):
        self.requests.append((url, headers, body))
        if self.error:
            raise self.error
        return self.response


def test_push_sends_one_selected_recipient_and_reuses_exact_retry_key():
    async def scenario():
        transport = FakeTransport()
        client = LinePushClient("server-only-token", transport)
        retry_key = "550e8400-e29b-41d4-a716-446655440000"

        first = await client.push_text(RECIPIENT_USER_ID, "看診提醒 08", retry_key=retry_key)
        second = await client.push_text(RECIPIENT_USER_ID, "看診提醒 08", retry_key=retry_key)

        assert first.outcome == "accepted"
        assert second.outcome == "accepted"
        assert first.accepted is True
        assert [request[0] for request in transport.requests] == [LINE_PUSH_URL, LINE_PUSH_URL]
        assert transport.requests[0] == transport.requests[1]
        _, headers, body = transport.requests[0]
        assert headers == {
            "Authorization": "Bearer server-only-token",
            "Content-Type": "application/json",
            "X-Line-Retry-Key": retry_key,
        }
        assert json.loads(body) == {
            "to": RECIPIENT_USER_ID,
            "messages": [{"type": "text", "text": "看診提醒 08"}],
        }
        assert "server-only-token" not in repr(first)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("status_code", "outcome", "accepted"),
    [
        (200, "accepted", True),
        (409, "accepted", True),
        (429, "failed", False),
        (500, "unknown", False),
    ],
)
def test_push_maps_line_status_without_claiming_handset_delivery(status_code, outcome, accepted):
    async def scenario():
        client = LinePushClient(
            "server-only-token",
            FakeTransport(LinePushHttpResponse(status_code=status_code)),
        )

        result = await client.push_text(
            RECIPIENT_USER_ID,
            "看診提醒",
            retry_key="550e8400-e29b-41d4-a716-446655440000",
        )

        assert result.outcome == outcome
        assert result.accepted is accepted
        assert not hasattr(result, "delivered")

    asyncio.run(scenario())


def test_push_transport_exception_is_unknown_and_is_not_retried():
    async def scenario():
        transport = FakeTransport(error=TimeoutError("connection timed out"))
        result = await LinePushClient("server-only-token", transport).push_text(
            RECIPIENT_USER_ID,
            "看診提醒",
            retry_key="550e8400-e29b-41d4-a716-446655440000",
        )

        assert result.outcome == "unknown"
        assert result.status_code is None
        assert len(transport.requests) == 1
        assert "server-only-token" not in repr(result)

    asyncio.run(scenario())


def test_push_rejects_invalid_retry_key_before_transport_call():
    async def scenario():
        transport = FakeTransport()

        with pytest.raises(ValueError, match="UUID"):
            await LinePushClient("server-only-token", transport).push_text(
                RECIPIENT_USER_ID,
                "看診提醒",
                retry_key="not-a-uuid",
            )

        assert transport.requests == []

    asyncio.run(scenario())


def test_push_rejects_group_or_room_ids_before_transport_call():
    async def scenario():
        transport = FakeTransport()
        client = LinePushClient("server-only-token", transport)

        for target in ("Cgroup-id", "Rroom-id"):
            with pytest.raises(ValueError, match="individual LINE user ID"):
                await client.push_text(
                    target,
                    "看診提醒",
                    retry_key="550e8400-e29b-41d4-a716-446655440000",
                )

        assert transport.requests == []

    asyncio.run(scenario())
