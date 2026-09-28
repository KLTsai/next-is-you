"""Cloudflare Python Worker entrypoint for the local application."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from next_is_you.auth import (
    AuthError,
    CSRF_COOKIE_NAME,
    LOGIN_TRANSACTION_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    csrf_cookie_options,
    issue_login_transaction,
    issue_session,
    login_transaction_cookie_options,
    require_csrf,
    session_cookie_options,
    verify_login_transaction,
    verify_session,
)
from next_is_you.identity import IdentityRepository, hash_invitation
from next_is_you.line_login import LineOAuthClient, WorkersLineOAuthClient
from next_is_you.line_messaging import (
    LineFriendshipClient,
    WorkersLineFriendshipClient,
)
from next_is_you.persistence import CloudflareD1Store, VisitRepository, iso_utc

try:
    from workers import asgi
except ModuleNotFoundError as error:
    if error.name != "js":
        raise
    asgi = None

STATIC_ASSET_ROOT = Path(__file__).resolve().parents[1] / "dist"


LINE_AUTHORIZE_URL = "https://access.line.me/oauth2/v2.1/authorize"


@dataclass(frozen=True, slots=True)
class LineLoginSettings:
    channel_id: str
    channel_secret: str
    redirect_uri: str
    session_secret: str
    organizer_subjects: frozenset[str]

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "LineLoginSettings":
        raw_subjects = values.get("organizer_subjects", values.get("ORGANIZER_LINE_SUBJECTS", ""))
        if isinstance(raw_subjects, str):
            subjects = frozenset(part.strip() for part in raw_subjects.split(",") if part.strip())
        else:
            subjects = frozenset(str(subject).strip() for subject in raw_subjects if str(subject).strip())
        return cls(
            channel_id=str(values.get("line_login_channel_id", values.get("LINE_LOGIN_CHANNEL_ID", ""))),
            channel_secret=str(values.get("line_login_channel_secret", values.get("LINE_LOGIN_CHANNEL_SECRET", ""))),
            redirect_uri=str(values.get("line_login_redirect_uri", values.get("LINE_LOGIN_REDIRECT_URI", ""))),
            session_secret=str(values.get("session_secret", values.get("SESSION_SIGNING_SECRET", ""))),
            organizer_subjects=subjects,
        )

    @property
    def ready(self) -> bool:
        try:
            callback = urlsplit(self.redirect_uri)
            callback_is_secure = (
                callback.scheme == "https"
                and callback.hostname is not None
                and callback.username is None
                and callback.password is None
                and not callback.fragment
            )
        except ValueError:
            callback_is_secure = False
        return bool(
            self.channel_id
            and self.channel_secret
            and callback_is_secure
            and len(self.session_secret.encode("utf-8")) >= 32
        )

    @property
    def organizer_login_ready(self) -> bool:
        return self.ready and bool(self.organizer_subjects)


def create_app(
    *,
    settings: LineLoginSettings | Mapping[str, Any] | None = None,
    line_client: LineOAuthClient | None = None,
    friendship_client: LineFriendshipClient | None = None,
    identity_repository: IdentityRepository | None = None,
    visit_repository: VisitRepository | None = None,
    clock: Callable[[], int | float] = time.time,
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None)
    app.state.line_login_settings = (
        settings
        if isinstance(settings, LineLoginSettings) or settings is None
        else LineLoginSettings.from_mapping(settings)
    )
    app.state.line_oauth_client = line_client or WorkersLineOAuthClient()
    app.state.friendship_client = friendship_client
    app.state.identity_repository = identity_repository
    app.state.visit_repository = visit_repository
    app.state.clock = clock

    @app.get("/api/healthz")
    async def health_check() -> dict[str, str]:
        return {"status": "ok", "mode": "local-development"}

    @app.get("/auth/line")
    async def line_login(request: Request) -> Response:
        config = _login_settings(request)
        now = int(request.app.state.clock())
        invitation = request.query_params.get("invite")
        identity = _identity_repository(request)
        if invitation:
            if not config.ready or identity is None:
                return JSONResponse({"detail": "Recipient invitations are unavailable"}, status_code=503)
            if not await identity.invitation_is_valid(invitation, _now(request)):
                return JSONResponse({"detail": "Invitation is invalid or expired"}, status_code=410)
            transaction = issue_login_transaction(
                config.session_secret,
                now=now,
                flow="recipient",
                invitation_hash=hash_invitation(invitation),
            )
        else:
            if not config.organizer_login_ready:
                return JSONResponse({"detail": "Organizer LINE Login is not configured"}, status_code=503)
            transaction = issue_login_transaction(config.session_secret, now=now)
        query = urlencode(
            {
                "response_type": "code",
                "client_id": config.channel_id,
                "redirect_uri": config.redirect_uri,
                "state": transaction.state,
                "scope": "openid profile" if invitation else "openid",
                "nonce": transaction.nonce,
            }
        )
        response = RedirectResponse(f"{LINE_AUTHORIZE_URL}?{query}", status_code=302)
        response.set_cookie(
            LOGIN_TRANSACTION_COOKIE_NAME,
            transaction.value,
            **login_transaction_cookie_options(
                max_age=transaction.expires_at - now
            ),
        )
        return response

    @app.get("/auth/line/callback", name="line_login_callback")
    async def line_login_callback(request: Request) -> Response:
        config = _login_settings(request)
        if not config.ready:
            return JSONResponse({"detail": "LINE Login is not configured"}, status_code=503)
        state_cookie = request.cookies.get(LOGIN_TRANSACTION_COOKIE_NAME)
        returned_state = request.query_params.get("state", "")
        code = request.query_params.get("code", "")
        now = int(request.app.state.clock())
        try:
            if not state_cookie or not code or request.query_params.get("error"):
                raise AuthError("login response is incomplete")
            transaction = verify_login_transaction(
                state_cookie,
                config.session_secret,
                returned_state=returned_state,
                now=now,
            )
        except AuthError:
            response = JSONResponse({"detail": "LINE Login could not be verified"}, status_code=401)
            _clear_login_cookie(response)
            return response

        try:
            identity = await request.app.state.line_oauth_client.verify_login(
                code=code,
                redirect_uri=config.redirect_uri,
                channel_id=config.channel_id,
                channel_secret=config.channel_secret,
                nonce=transaction.nonce,
            )
        except Exception:
            response = JSONResponse({"detail": "LINE Login could not be verified"}, status_code=401)
            _clear_login_cookie(response)
            return response

        if transaction.flow == "recipient":
            repository = _identity_repository(request)
            if repository is None or transaction.invitation_hash is None:
                response = JSONResponse({"detail": "Recipient invitations are unavailable"}, status_code=503)
                _clear_login_cookie(response)
                return response
            friendship = _friendship_client(request)
            if friendship is None:
                response = JSONResponse({"detail": "Friendship verification is unavailable"}, status_code=503)
                _clear_login_cookie(response)
                return response
            friendship_result = await friendship.check_friendship(identity.user_access_token)
            if friendship_result.is_friend is None:
                response = JSONResponse({"detail": "Friendship could not be verified"}, status_code=503)
                _clear_login_cookie(response)
                return response
            if not friendship_result.is_friend:
                response = JSONResponse({"detail": "Add the official account before enrolling"}, status_code=409)
                _clear_login_cookie(response)
                return response
            enrolled_at = _now(request)
            accepted = await repository.accept_invitation(
                token_hash=transaction.invitation_hash,
                line_subject=identity.subject,
                display_name="LINE recipient",
                now=enrolled_at,
                friendship_checked_at=enrolled_at,
            )
            if not accepted:
                response = JSONResponse({"detail": "Invitation is invalid, expired, or already used"}, status_code=410)
                _clear_login_cookie(response)
                return response
            subject = identity.subject
            role = "recipient"
            destination = "/recipient/consent"
        else:
            if identity.subject not in config.organizer_subjects:
                response = JSONResponse({"detail": "This LINE account is not authorized"}, status_code=403)
                _clear_login_cookie(response)
                return response
            subject = identity.subject
            role = "organizer"
            destination = "/"

        try:
            session = issue_session(subject, role, config.session_secret, now=now)
        except AuthError:
            response = JSONResponse({"detail": "LINE Login is not configured"}, status_code=503)
            _clear_login_cookie(response)
            return response
        response = RedirectResponse(destination, status_code=303)
        response.set_cookie(
            SESSION_COOKIE_NAME,
            session.value,
            **session_cookie_options(max_age=session.expires_at - now),
        )
        response.set_cookie(
            CSRF_COOKIE_NAME,
            session.csrf_token,
            **csrf_cookie_options(max_age=session.expires_at - now),
        )
        _clear_login_cookie(response)
        return response

    @app.post("/auth/logout", status_code=204)
    async def logout(request: Request) -> Response:
        config = _login_settings(request)
        try:
            claims = verify_session(
                request.cookies.get(SESSION_COOKIE_NAME, ""),
                config.session_secret,
                now=int(request.app.state.clock()),
            )
            require_csrf(claims, request.headers.get("x-csrf-token"))
        except AuthError:
            return Response(status_code=403)
        response = Response(status_code=204)
        _clear_session_cookies(response)
        return response

    @app.post("/api/organizer/invitations")
    async def create_recipient_invitation(request: Request) -> Response:
        claims, denied = await _authorized(request, "organizer", csrf=True)
        if denied:
            return denied
        repository = _identity_repository(request)
        if repository is None:
            return JSONResponse({"detail": "Invitations are unavailable"}, status_code=503)
        invitation = await repository.create_invitation(claims.subject, _now(request))
        parsed_redirect = urlsplit(_login_settings(request).redirect_uri)
        origin = f"{parsed_redirect.scheme}://{parsed_redirect.netloc}"
        return JSONResponse(
            {
                "invitation_url": f"{origin}/auth/line?invite={invitation.token}",
                "expires_at": iso_utc(invitation.expires_at),
            },
            status_code=201,
        )

    @app.post("/api/recipient/opt-in")
    async def opt_in_recipient(request: Request) -> Response:
        claims, denied = await _authorized(request, "recipient", csrf=True, allow_pending=True)
        if denied:
            return denied
        repository = _identity_repository(request)
        if repository is None:
            return JSONResponse({"detail": "Recipient controls are unavailable"}, status_code=503)
        if not await repository.opt_in(claims.subject, _now(request)):
            return JSONResponse({"detail": "Recipient consent is already set or unavailable"}, status_code=409)
        return Response(status_code=204)

    @app.post("/api/recipient/withdraw")
    async def withdraw_recipient(request: Request) -> Response:
        claims, denied = await _authorized(request, "recipient", csrf=True)
        if denied:
            return denied
        identity = _identity_repository(request)
        visits = _visit_repository(request)
        if identity is None or visits is None:
            return JSONResponse({"detail": "Recipient controls are unavailable"}, status_code=503)
        recipient_id = await identity.recipient_id(claims.subject, active=True)
        if recipient_id is None:
            return Response(status_code=204)
        await visits.withdraw_recipient(recipient_id)
        return Response(status_code=204)

    @app.post("/api/visits/{visit_id}/recipients/{recipient_id}")
    async def select_recipient(visit_id: str, recipient_id: str, request: Request) -> Response:
        _, denied = await _authorized(request, "organizer", csrf=True)
        if denied:
            return denied
        identity = _identity_repository(request)
        visits = _visit_repository(request)
        if identity is None or visits is None:
            return JSONResponse({"detail": "Recipient eligibility checks are unavailable"}, status_code=503)
        subject = await identity.recipient_subject(recipient_id)
        if subject is None:
            return JSONResponse({"detail": "Recipient is not opted in"}, status_code=409)
        now = _now(request)
        if not await visits.add_recipient(visit_id, recipient_id, now):
            return JSONResponse({"detail": "Recipient could not be selected for this visit"}, status_code=409)
        return Response(status_code=204)

    @app.get("/{path:path}")
    async def serve_static_asset(path: str, request: Request) -> Response:
        """Proxy non-API requests to Workers Static Assets after the UI build."""
        env = request.scope.get("env")
        if env is None:
            asset_path = (STATIC_ASSET_ROOT / (path or "index.html")).resolve()
            if not asset_path.is_relative_to(STATIC_ASSET_ROOT.resolve()) or not asset_path.is_file():
                return Response(status_code=404)
            return FileResponse(asset_path)

        asset_path = path or "index.html"
        asset_response = await env.ASSETS.fetch(f"https://assets.local/{asset_path}")
        return Response(
            content=await asset_response.bytes(),
            status_code=asset_response.status,
            headers=asset_response.headers,
        )

    return app


def _login_settings(request: Request) -> LineLoginSettings:
    configured = request.app.state.line_login_settings
    if configured is not None:
        return configured
    env = request.scope.get("env")
    values = {
        name: _binding(env, name)
        for name in (
            "LINE_LOGIN_CHANNEL_ID",
            "LINE_LOGIN_CHANNEL_SECRET",
            "LINE_LOGIN_REDIRECT_URI",
            "SESSION_SIGNING_SECRET",
            "ORGANIZER_LINE_SUBJECTS",
        )
    }
    return LineLoginSettings.from_mapping(values)


def _binding(env: Any, name: str) -> str:
    if env is None:
        return ""
    if isinstance(env, Mapping):
        return str(env.get(name, ""))
    return str(getattr(env, name, ""))


def _now(request: Request) -> datetime:
    return datetime.fromtimestamp(float(request.app.state.clock()), timezone.utc)


def _store(request: Request) -> CloudflareD1Store | None:
    env = request.scope.get("env")
    if isinstance(env, Mapping):
        binding = env.get("DB")
    else:
        binding = getattr(env, "DB", None) if env is not None else None
    if binding is None:
        return None
    return CloudflareD1Store(binding)


def _identity_repository(request: Request) -> IdentityRepository | None:
    configured = request.app.state.identity_repository
    if configured is not None:
        return configured
    store = _store(request)
    return IdentityRepository(store) if store is not None else None


def _visit_repository(request: Request) -> VisitRepository | None:
    configured = request.app.state.visit_repository
    if configured is not None:
        return configured
    store = _store(request)
    return VisitRepository(store) if store is not None else None


def _friendship_client(request: Request) -> LineFriendshipClient | None:
    configured = request.app.state.friendship_client
    return configured if configured is not None else WorkersLineFriendshipClient()


async def _authorized(
    request: Request,
    role: str,
    *,
    csrf: bool,
    allow_pending: bool = False,
):
    config = _login_settings(request)
    try:
        claims = verify_session(
            request.cookies.get(SESSION_COOKIE_NAME, ""),
            config.session_secret,
            now=int(request.app.state.clock()),
        )
    except AuthError:
        return None, Response(status_code=401)
    if claims.role != role:
        return None, Response(status_code=403)
    if csrf:
        try:
            require_csrf(claims, request.headers.get("x-csrf-token"))
        except AuthError:
            return None, Response(status_code=403)
    if role == "organizer":
        if claims.subject not in config.organizer_subjects:
            return None, Response(status_code=403)
    else:
        identity = _identity_repository(request)
        if identity is None:
            return None, JSONResponse({"detail": "Recipient identity is unavailable"}, status_code=503)
        active = await identity.recipient_is_active(claims.subject)
        pending = allow_pending and await identity.recipient_is_pending(claims.subject)
        if not active and not pending:
            return None, Response(status_code=403)
    return claims, None


def _clear_login_cookie(response: Response) -> None:
    response.delete_cookie(
        LOGIN_TRANSACTION_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/", secure=True, httponly=False, samesite="lax")


app = create_app()

if asgi is not None:
    Default = asgi.entrypoint(app)
