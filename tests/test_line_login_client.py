import asyncio
import json
from urllib.parse import parse_qs

import pytest

from next_is_you.line_login import (
    LineLoginError,
    VerifiedLineIdentity,
    WorkersLineOAuthClient,
)


class FakeResponse:
    def __init__(self, payload, *, ok=True):
        self.ok = ok
        self.payload = payload

    async def text(self):
        return json.dumps(self.payload)


def test_line_client_exchanges_code_then_verifies_id_token_and_nonce():
    async def scenario():
        requests = []
        responses = [
            FakeResponse(
                {"id_token": "fake-id-token", "access_token": "short-lived-user-token"}
            ),
            FakeResponse({"sub": "line-subject", "nonce": "expected-nonce"}),
        ]

        async def fake_fetch(url, options):
            requests.append((url, options))
            return responses.pop(0)

        subject = await WorkersLineOAuthClient(fake_fetch).verify_login(
            code="authorization-code",
            redirect_uri="https://family.example/auth/line/callback",
            channel_id="channel-123",
            channel_secret="channel-secret",
            nonce="expected-nonce",
        )

        assert subject == VerifiedLineIdentity("line-subject", "short-lived-user-token")
        assert [url for url, _ in requests] == [
            "https://api.line.me/oauth2/v2.1/token",
            "https://api.line.me/oauth2/v2.1/verify",
        ]
        token_request = parse_qs(requests[0][1]["body"])
        assert token_request == {
            "grant_type": ["authorization_code"],
            "code": ["authorization-code"],
            "redirect_uri": ["https://family.example/auth/line/callback"],
            "client_id": ["channel-123"],
            "client_secret": ["channel-secret"],
        }
        verify_request = parse_qs(requests[1][1]["body"])
        assert verify_request == {
            "id_token": ["fake-id-token"],
            "client_id": ["channel-123"],
            "nonce": ["expected-nonce"],
        }
        assert all(options["method"] == "POST" for _, options in requests)
        assert all(
            options["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
            for _, options in requests
        )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "payload",
    [
        {"sub": "line-subject", "nonce": "wrong-nonce"},
        {"sub": "line-subject"},
        {"nonce": "expected-nonce"},
    ],
)
def test_line_client_rejects_verified_payload_without_matching_subject_and_nonce(
    payload,
):
    async def scenario():
        responses = [
            FakeResponse(
                {"id_token": "fake-id-token", "access_token": "short-lived-user-token"}
            ),
            FakeResponse(payload),
        ]

        async def fake_fetch(_url, _options):
            return responses.pop(0)

        with pytest.raises(LineLoginError):
            await WorkersLineOAuthClient(fake_fetch).verify_login(
                code="authorization-code",
                redirect_uri="https://family.example/auth/line/callback",
                channel_id="channel-123",
                channel_secret="channel-secret",
                nonce="expected-nonce",
            )

    asyncio.run(scenario())


def test_line_client_does_not_attempt_verification_when_code_exchange_fails():
    async def scenario():
        requests = []

        async def fake_fetch(url, _options):
            requests.append(url)
            return FakeResponse({"error": "invalid_grant"}, ok=False)

        with pytest.raises(LineLoginError):
            await WorkersLineOAuthClient(fake_fetch).verify_login(
                code="invalid-code",
                redirect_uri="https://family.example/auth/line/callback",
                channel_id="channel-123",
                channel_secret="channel-secret",
                nonce="expected-nonce",
            )

        assert requests == ["https://api.line.me/oauth2/v2.1/token"]

    asyncio.run(scenario())
