"""Single-recipient LINE Messaging API push transport."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Protocol


LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_BOT_INFO_URL = "https://api.line.me/v2/bot/info"
LINE_USER_ID_PATTERN = re.compile(r"^U[0-9a-f]{32}$")


@dataclass(frozen=True, slots=True)
class LinePushHttpResponse:
    status_code: int
    request_id: str | None = None
    accepted_request_id: str | None = None


class LinePushTransport(Protocol):
    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: str,
    ) -> LinePushHttpResponse: ...


@dataclass(frozen=True, slots=True)
class LinePushResult:
    outcome: str
    status_code: int | None
    request_id: str | None = None
    accepted_request_id: str | None = None

    @property
    def accepted(self) -> bool:
        return self.outcome == "accepted"


@dataclass(frozen=True, slots=True)
class FriendshipResult:
    is_friend: bool | None


class LineFriendshipClient(Protocol):
    async def check_friendship(self, user_access_token: str) -> FriendshipResult: ...


class WorkersLineFriendshipClient:
    """Check friendship during enrollment with the transient LINE user token."""

    def __init__(self, fetcher=None) -> None:
        self._fetcher = fetcher

    async def check_friendship(self, user_access_token: str) -> FriendshipResult:
        if not user_access_token:
            raise ValueError("user_access_token is required")
        try:
            response = await self._fetch(
                "https://api.line.me/friendship/v1/status",
                {
                    "method": "GET",
                    "headers": {"Authorization": f"Bearer {user_access_token}"},
                },
            )
            if not response.ok:
                return FriendshipResult(None)
            payload = json.loads(await response.text())
            value = payload.get("friendFlag")
            return FriendshipResult(value if isinstance(value, bool) else None)
        except Exception:
            return FriendshipResult(None)

    async def _fetch(self, url: str, options: dict[str, object]):
        if self._fetcher is not None:
            return await self._fetcher(url, options)
        from js import Object
        from js import fetch
        from pyodide.ffi import to_js

        return await fetch(url, to_js(options, dict_converter=Object.fromEntries))


class LineBotInfoClient(Protocol):
    async def basic_id(self, channel_access_token: str) -> str | None: ...


class WorkersLineBotInfoClient:
    """Name the Official Account a channel access token belongs to.

    Answers the account's basic ID (for example "@123abcde"), or None when LINE
    does not answer with one, which never counts as a match.
    """

    def __init__(self, fetcher=None) -> None:
        self._fetcher = fetcher

    async def basic_id(self, channel_access_token: str) -> str | None:
        try:
            response = await self._fetch(
                LINE_BOT_INFO_URL,
                {
                    "method": "GET",
                    "headers": {"Authorization": f"Bearer {channel_access_token}"},
                },
            )
            if not response.ok:
                return None
            value = json.loads(await response.text()).get("basicId")
            return value if isinstance(value, str) and value else None
        except Exception:
            return None

    async def _fetch(self, url: str, options: dict[str, object]):
        if self._fetcher is not None:
            return await self._fetcher(url, options)
        from js import Object
        from js import fetch
        from pyodide.ffi import to_js

        return await fetch(url, to_js(options, dict_converter=Object.fromEntries))


class WorkersLinePushTransport:
    """Send a single HTTP request with the Cloudflare Workers fetch API."""

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: str,
    ) -> LinePushHttpResponse:
        from js import Object
        from js import fetch
        from pyodide.ffi import to_js

        response = await fetch(
            url,
            to_js(
                {"method": "POST", "headers": headers, "body": body},
                dict_converter=Object.fromEntries,
            ),
        )
        return LinePushHttpResponse(
            status_code=int(response.status),
            request_id=_read_header(response, "x-line-request-id"),
            accepted_request_id=_read_header(response, "x-line-accepted-request-id"),
        )


class LinePushClient:
    """Build one deterministic push request and report only API acceptance."""

    def __init__(
        self,
        channel_access_token: str,
        transport: LinePushTransport | None = None,
    ) -> None:
        if not channel_access_token:
            raise ValueError("LINE channel access token is required")
        self._channel_access_token = channel_access_token
        self._transport = transport or WorkersLinePushTransport()

    async def push_text(
        self,
        recipient_id: str,
        text: str,
        *,
        retry_key: str,
    ) -> LinePushResult:
        try:
            uuid.UUID(retry_key)
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("retry_key must be a UUID") from error
        if not isinstance(recipient_id, str) or not LINE_USER_ID_PATTERN.fullmatch(
            recipient_id
        ):
            raise ValueError("recipient_id must be an individual LINE user ID")
        if not text:
            raise ValueError("text is required")

        body = json.dumps(
            {"to": recipient_id, "messages": [{"type": "text", "text": text}]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        headers = {
            "Authorization": f"Bearer {self._channel_access_token}",
            "Content-Type": "application/json",
            "X-Line-Retry-Key": retry_key,
        }
        try:
            response = await self._transport.post(
                LINE_PUSH_URL,
                headers=headers,
                body=body,
            )
        except Exception:
            # A transport error does not prove whether LINE accepted the request.
            return LinePushResult(outcome="unknown", status_code=None)

        if 200 <= response.status_code < 300:
            outcome = "accepted"
        elif response.status_code == 409:
            outcome = "accepted"
        elif response.status_code >= 500:
            outcome = "unknown"
        else:
            outcome = "failed"
        return LinePushResult(
            outcome=outcome,
            status_code=response.status_code,
            request_id=response.request_id,
            accepted_request_id=response.accepted_request_id,
        )


def _read_header(response, name: str) -> str | None:
    value = response.headers.get(name)
    return str(value) if value is not None else None
