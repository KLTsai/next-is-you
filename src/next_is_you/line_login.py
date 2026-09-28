"""LINE Login authorization-code exchange and ID-token verification."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlencode


class LineLoginError(RuntimeError):
    """LINE rejected the Login exchange or returned an invalid response."""


@dataclass(frozen=True, slots=True)
class VerifiedLineIdentity:
    subject: str
    user_access_token: str = field(repr=False)


class LineOAuthClient(Protocol):
    async def verify_login(
        self,
        *,
        code: str,
        redirect_uri: str,
        channel_id: str,
        channel_secret: str,
        nonce: str,
    ) -> VerifiedLineIdentity: ...


class WorkersLineOAuthClient:
    """Use the Cloudflare Workers fetch API for the two server-side LINE calls."""

    def __init__(self, fetcher=None):
        self._fetcher = fetcher

    async def verify_login(
        self,
        *,
        code: str,
        redirect_uri: str,
        channel_id: str,
        channel_secret: str,
        nonce: str,
    ) -> VerifiedLineIdentity:
        token_response = await self._fetch(
            "https://api.line.me/oauth2/v2.1/token",
            {
                "method": "POST",
                "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                "body": urlencode(
                    {
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": redirect_uri,
                        "client_id": channel_id,
                        "client_secret": channel_secret,
                    }
                ),
            },
        )
        if not token_response.ok:
            raise LineLoginError("LINE token exchange failed")
        token_payload = json.loads(await token_response.text())
        id_token = token_payload.get("id_token")
        access_token = token_payload.get("access_token")
        if not isinstance(id_token, str) or not id_token:
            raise LineLoginError("LINE did not return an ID token")
        if not isinstance(access_token, str) or not access_token:
            raise LineLoginError("LINE did not return a user access token")

        verify_response = await self._fetch(
            "https://api.line.me/oauth2/v2.1/verify",
            {
                "method": "POST",
                "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                "body": urlencode(
                    {"id_token": id_token, "client_id": channel_id, "nonce": nonce}
                ),
            },
        )
        if not verify_response.ok:
            raise LineLoginError("LINE ID token verification failed")
        verified_payload: dict[str, Any] = json.loads(await verify_response.text())
        subject = verified_payload.get("sub")
        verified_nonce = verified_payload.get("nonce")
        if not isinstance(subject, str) or not subject:
            raise LineLoginError("LINE verified token has no subject")
        if not isinstance(verified_nonce, str) or verified_nonce != nonce:
            raise LineLoginError("LINE verified token nonce does not match")
        return VerifiedLineIdentity(subject=subject, user_access_token=access_token)

    async def _fetch(self, url: str, options: dict[str, Any]):
        if self._fetcher is not None:
            return await self._fetcher(url, options)
        from js import fetch
        from js import Object
        from pyodide.ffi import to_js

        return await fetch(url, to_js(options, dict_converter=Object.fromEntries))
