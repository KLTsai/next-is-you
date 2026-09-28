"""Signed short-lived sessions and LINE Login transaction primitives."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any


SESSION_TTL_SECONDS = 4 * 60 * 60
LOGIN_TRANSACTION_TTL_SECONDS = 10 * 60
SESSION_COOKIE_NAME = "__Host-ny_session"
CSRF_COOKIE_NAME = "__Host-ny_csrf"
LOGIN_TRANSACTION_COOKIE_NAME = "__Host-ny_oauth"
_ALLOWED_ROLES = frozenset({"organizer", "recipient"})
_MAX_TOKEN_LENGTH = 4096


class AuthError(ValueError):
    """Authentication material is invalid or expired."""


@dataclass(frozen=True, slots=True)
class SignedSession:
    value: str
    csrf_token: str
    expires_at: int


@dataclass(frozen=True, slots=True)
class SessionClaims:
    subject: str
    role: str
    csrf_token: str
    expires_at: int


@dataclass(frozen=True, slots=True)
class LoginTransaction:
    value: str
    state: str
    nonce: str
    expires_at: int
    flow: str = "organizer"
    invitation_hash: str | None = None


def issue_session(
    subject: str,
    role: str,
    secret: str | bytes,
    *,
    now: int,
    ttl_seconds: int = SESSION_TTL_SECONDS,
) -> SignedSession:
    key = _secret_bytes(secret)
    if not isinstance(subject, str) or not subject or len(subject) > 256:
        raise AuthError("session subject is invalid")
    if not isinstance(role, str) or role not in _ALLOWED_ROLES:
        raise AuthError("session role is invalid")
    if ttl_seconds < 1 or ttl_seconds > SESSION_TTL_SECONDS:
        raise AuthError("session lifetime is outside the allowed range")
    csrf_token = secrets.token_urlsafe(32)
    expires_at = now + ttl_seconds
    value = _sign(
        {
            "csrf": csrf_token,
            "exp": expires_at,
            "purpose": "session",
            "role": role,
            "sub": subject,
            "v": 1,
        },
        key,
    )
    return SignedSession(value, csrf_token, expires_at)


def verify_session(
    value: str,
    secret: str | bytes,
    *,
    now: int,
) -> SessionClaims:
    payload = _verify(value, secret)
    if payload.get("purpose") != "session" or payload.get("v") != 1:
        raise AuthError("session purpose is invalid")
    subject = payload.get("sub")
    role = payload.get("role")
    csrf_token = payload.get("csrf")
    expires_at = payload.get("exp")
    if not isinstance(subject, str) or not subject or len(subject) > 256:
        raise AuthError("session subject is invalid")
    if not isinstance(role, str) or role not in _ALLOWED_ROLES:
        raise AuthError("session role is invalid")
    if not isinstance(csrf_token, str) or not csrf_token:
        raise AuthError("session CSRF claim is invalid")
    if (
        isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or expires_at <= now
    ):
        raise AuthError("session has expired")
    return SessionClaims(subject, role, csrf_token, expires_at)


def require_csrf(claims: SessionClaims, submitted_token: str | None) -> None:
    if not submitted_token or not hmac.compare_digest(
        claims.csrf_token, submitted_token
    ):
        raise AuthError("CSRF token is invalid")


def issue_login_transaction(
    secret: str | bytes,
    *,
    now: int,
    ttl_seconds: int = LOGIN_TRANSACTION_TTL_SECONDS,
    flow: str = "organizer",
    invitation_hash: str | None = None,
) -> LoginTransaction:
    key = _secret_bytes(secret)
    if ttl_seconds < 1 or ttl_seconds > LOGIN_TRANSACTION_TTL_SECONDS:
        raise AuthError("login transaction lifetime is outside the allowed range")
    if flow not in {"organizer", "recipient"}:
        raise AuthError("login flow is invalid")
    if (flow == "recipient") != bool(invitation_hash):
        raise AuthError("recipient login requires an invitation")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    expires_at = now + ttl_seconds
    value = _sign(
        {
            "exp": expires_at,
            "flow": flow,
            "invitation": invitation_hash,
            "nonce": nonce,
            "purpose": "login",
            "state": state,
            "v": 1,
        },
        key,
    )
    return LoginTransaction(value, state, nonce, expires_at, flow, invitation_hash)


def verify_login_transaction(
    value: str,
    secret: str | bytes,
    *,
    returned_state: str,
    now: int,
) -> LoginTransaction:
    payload = _verify(value, secret)
    state = payload.get("state")
    nonce = payload.get("nonce")
    expires_at = payload.get("exp")
    flow = payload.get("flow", "organizer")
    invitation_hash = payload.get("invitation")
    if payload.get("purpose") != "login" or payload.get("v") != 1:
        raise AuthError("login transaction purpose is invalid")
    if (
        not isinstance(state, str)
        or not state
        or not isinstance(returned_state, str)
        or not hmac.compare_digest(state, returned_state)
    ):
        raise AuthError("login state does not match")
    if not isinstance(nonce, str) or not nonce:
        raise AuthError("login nonce is invalid")
    if flow not in {"organizer", "recipient"}:
        raise AuthError("login flow is invalid")
    if flow == "recipient" and (
        not isinstance(invitation_hash, str) or not invitation_hash
    ):
        raise AuthError("recipient login invitation is invalid")
    if flow == "organizer" and invitation_hash is not None:
        raise AuthError("organizer login cannot carry an invitation")
    if (
        isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or expires_at <= now
    ):
        raise AuthError("login transaction has expired")
    return LoginTransaction(value, state, nonce, expires_at, flow, invitation_hash)


def session_cookie_options(*, max_age: int = SESSION_TTL_SECONDS) -> dict[str, Any]:
    return {
        "max_age": max_age,
        "path": "/",
        "secure": True,
        "httponly": True,
        "samesite": "lax",
    }


def csrf_cookie_options(*, max_age: int = SESSION_TTL_SECONDS) -> dict[str, Any]:
    return {
        "max_age": max_age,
        "path": "/",
        "secure": True,
        "httponly": False,
        "samesite": "lax",
    }


def login_transaction_cookie_options(
    *, max_age: int = LOGIN_TRANSACTION_TTL_SECONDS
) -> dict[str, Any]:
    return session_cookie_options(max_age=max_age)


def _secret_bytes(secret: str | bytes) -> bytes:
    key = secret.encode("utf-8") if isinstance(secret, str) else secret
    if not isinstance(key, bytes) or len(key) < 32:
        raise AuthError("signing secret must contain at least 32 bytes")
    return key


def _sign(payload: dict[str, Any], secret: bytes) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded_body = _b64encode(body)
    signature = hmac.new(secret, encoded_body.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_body}.{_b64encode(signature)}"


def _verify(value: str, secret: str | bytes) -> dict[str, Any]:
    key = _secret_bytes(secret)
    if not isinstance(value, str) or len(value) > _MAX_TOKEN_LENGTH:
        raise AuthError("signed token is invalid")
    parts = value.split(".")
    if len(parts) != 2:
        raise AuthError("signed token is malformed")
    encoded_body, encoded_signature = parts
    try:
        signature = _b64decode(encoded_signature)
        expected = hmac.new(key, encoded_body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise AuthError("signed token signature is invalid")
        payload = json.loads(_b64decode(encoded_body))
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        if isinstance(error, AuthError):
            raise
        raise AuthError("signed token is malformed") from error
    if not isinstance(payload, dict):
        raise AuthError("signed token payload is invalid")
    return payload


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if not value or any(
        char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_="
        for char in value
    ):
        raise AuthError("base64url value is malformed")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
