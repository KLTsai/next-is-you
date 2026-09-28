import pytest

from next_is_you.auth import (
    AuthError,
    SESSION_TTL_SECONDS,
    csrf_cookie_options,
    issue_login_transaction,
    issue_session,
    login_transaction_cookie_options,
    require_csrf,
    session_cookie_options,
    verify_login_transaction,
    verify_session,
)


SECRET = "local-test-secret-with-at-least-32-bytes"


def test_signed_session_round_trips_identity_role_expiry_and_csrf():
    issued = issue_session("line-user-1", "organizer", SECRET, now=1_000)
    verified = verify_session(issued.value, SECRET, now=1_001)

    assert verified.subject == "line-user-1"
    assert verified.role == "organizer"
    assert verified.expires_at == 1_000 + SESSION_TTL_SECONDS
    assert verified.csrf_token == issued.csrf_token


def test_session_rejects_tampering_expiry_and_unknown_roles():
    issued = issue_session("line-user-1", "organizer", SECRET, now=1_000)

    with pytest.raises(AuthError):
        verify_session(issued.value + "x", SECRET, now=1_001)
    with pytest.raises(AuthError):
        verify_session(issued.value, SECRET, now=1_000 + SESSION_TTL_SECONDS)
    with pytest.raises(AuthError):
        issue_session("line-user-1", "admin", SECRET, now=1_000)
    with pytest.raises(AuthError):
        verify_session(
            _signed_payload(
                {
                    "csrf": "x",
                    "exp": 2_000,
                    "purpose": "session",
                    "role": [],
                    "sub": "u",
                    "v": 1,
                }
            ),
            SECRET,
            now=1_001,
        )


@pytest.mark.parametrize("secret", ["", "short"])
def test_session_rejects_missing_or_weak_signing_secrets(secret):
    with pytest.raises(AuthError):
        issue_session("line-user-1", "organizer", secret, now=1_000)


def test_csrf_token_must_match_signed_session_claim():
    issued = issue_session("line-user-1", "organizer", SECRET, now=1_000)
    verified = verify_session(issued.value, SECRET, now=1_001)

    require_csrf(verified, issued.csrf_token)
    with pytest.raises(AuthError):
        require_csrf(verified, "attacker-token")


def test_login_transaction_signs_single_attempt_state_and_nonce():
    issued = issue_login_transaction(SECRET, now=1_000)
    verified = verify_login_transaction(
        issued.value, SECRET, returned_state=issued.state, now=1_001
    )

    assert verified.state == issued.state
    assert verified.nonce == issued.nonce
    assert verified.expires_at > 1_001


def test_login_transaction_rejects_wrong_state_expiry_and_tampering():
    issued = issue_login_transaction(SECRET, now=1_000)

    with pytest.raises(AuthError):
        verify_login_transaction(
            issued.value, SECRET, returned_state="wrong", now=1_001
        )
    with pytest.raises(AuthError):
        verify_login_transaction(
            issued.value, SECRET, returned_state=issued.state, now=issued.expires_at
        )
    with pytest.raises(AuthError):
        verify_login_transaction(
            issued.value + "x", SECRET, returned_state=issued.state, now=1_001
        )


def _signed_payload(payload):
    import base64
    import hashlib
    import hmac
    import json

    body = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    signature = hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{body}.{encoded_signature}"


def test_session_and_login_cookie_options_are_secure_and_scoped():
    session = session_cookie_options(max_age=600)
    transaction = login_transaction_cookie_options(max_age=300)

    assert session == {
        "max_age": 600,
        "path": "/",
        "secure": True,
        "httponly": True,
        "samesite": "lax",
    }
    assert transaction == session | {"max_age": 300}
    assert csrf_cookie_options(max_age=600) == session | {"httponly": False}
