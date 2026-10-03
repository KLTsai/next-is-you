"""Same-origin application shell and API for local and held Worker runtimes."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
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
from next_is_you.domain import ClinicSession, Hospital
from next_is_you.progress_links import progress_link
from next_is_you.line_login import LineOAuthClient, WorkersLineOAuthClient
from next_is_you.line_messaging import (
    LineFriendshipClient,
    WorkersLineFriendshipClient,
)
from next_is_you.persistence import CloudflareD1Store, VisitRepository, iso_utc

# Wrangler discovers the Durable Object class from this imported module export.
from next_is_you.send_gate import SystemSendGate, local_test_mode  # noqa: F401

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
        def text_setting(local_name: str, runtime_name: str) -> str:
            value = values.get(local_name, values.get(runtime_name, ""))
            return value if isinstance(value, str) and value.strip() else ""

        raw_subjects = values.get(
            "organizer_subjects", values.get("ORGANIZER_LINE_SUBJECTS", "")
        )
        if isinstance(raw_subjects, str):
            subjects = frozenset(
                part.strip() for part in raw_subjects.split(",") if part.strip()
            )
        elif isinstance(raw_subjects, (list, tuple, set, frozenset)):
            subjects = frozenset(
                subject.strip()
                for subject in raw_subjects
                if isinstance(subject, str) and subject.strip()
            )
        else:
            subjects = frozenset()
        return cls(
            channel_id=text_setting("line_login_channel_id", "LINE_LOGIN_CHANNEL_ID"),
            channel_secret=text_setting(
                "line_login_channel_secret", "LINE_LOGIN_CHANNEL_SECRET"
            ),
            redirect_uri=text_setting(
                "line_login_redirect_uri", "LINE_LOGIN_REDIRECT_URI"
            ),
            session_secret=text_setting("session_secret", "SESSION_SIGNING_SECRET"),
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
                and callback.path == "/auth/line/callback"
                and not callback.query
                and not callback.fragment
                and (callback.port is None or callback.port > 0)
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
    send_gate: Any | None = None,
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
    app.state.send_gate = send_gate
    app.state.clock = clock

    @app.get("/api/healthz")
    async def health_check(request: Request) -> dict[str, str]:
        env = request.scope.get("env")
        mode = (
            "local-test"
            if local_test_mode(env)
            else "held-service"
            if env is not None
            else "local-development"
        )
        return {"status": "ok", "mode": mode}

    @app.get("/auth/line")
    async def line_login(request: Request) -> Response:
        config = _login_settings(request)
        now = int(request.app.state.clock())
        invitation = request.query_params.get("invite")
        identity = _identity_repository(request)
        if invitation:
            if not config.ready or identity is None:
                return JSONResponse(
                    {"detail": "Recipient invitations are unavailable"}, status_code=503
                )
            if not await identity.invitation_is_valid(invitation, _now(request)):
                return JSONResponse(
                    {"detail": "Invitation is invalid or expired"}, status_code=410
                )
            transaction = issue_login_transaction(
                config.session_secret,
                now=now,
                flow="recipient",
                invitation_hash=hash_invitation(invitation),
            )
        else:
            if not config.organizer_login_ready:
                return JSONResponse(
                    {"detail": "Organizer LINE Login is not configured"},
                    status_code=503,
                )
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
            **login_transaction_cookie_options(max_age=transaction.expires_at - now),
        )
        return response

    @app.get("/auth/line/callback", name="line_login_callback")
    async def line_login_callback(request: Request) -> Response:
        config = _login_settings(request)
        if not config.ready:
            return JSONResponse(
                {"detail": "LINE Login is not configured"}, status_code=503
            )
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
            response = JSONResponse(
                {"detail": "LINE Login could not be verified"}, status_code=401
            )
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
            response = JSONResponse(
                {"detail": "LINE Login could not be verified"}, status_code=401
            )
            _clear_login_cookie(response)
            return response

        if transaction.flow == "recipient":
            repository = _identity_repository(request)
            if repository is None or transaction.invitation_hash is None:
                response = JSONResponse(
                    {"detail": "Recipient invitations are unavailable"}, status_code=503
                )
                _clear_login_cookie(response)
                return response
            friendship = _friendship_client(request)
            if friendship is None:
                response = JSONResponse(
                    {"detail": "Friendship verification is unavailable"},
                    status_code=503,
                )
                _clear_login_cookie(response)
                return response
            friendship_result = await friendship.check_friendship(
                identity.user_access_token
            )
            if friendship_result.is_friend is None:
                response = JSONResponse(
                    {"detail": "Friendship could not be verified"}, status_code=503
                )
                _clear_login_cookie(response)
                return response
            if not friendship_result.is_friend:
                response = JSONResponse(
                    {"detail": "Add the official account before enrolling"},
                    status_code=409,
                )
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
                response = JSONResponse(
                    {"detail": "Invitation is invalid, expired, or already used"},
                    status_code=410,
                )
                _clear_login_cookie(response)
                return response
            subject = identity.subject
            role = "recipient"
            destination = "/recipient/consent"
        else:
            if identity.subject not in config.organizer_subjects:
                response = JSONResponse(
                    {"detail": "This LINE account is not authorized"}, status_code=403
                )
                _clear_login_cookie(response)
                return response
            subject = identity.subject
            role = "organizer"
            destination = "/"

        try:
            session = issue_session(subject, role, config.session_secret, now=now)
        except AuthError:
            response = JSONResponse(
                {"detail": "LINE Login is not configured"}, status_code=503
            )
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
            return JSONResponse(
                {"detail": "Invitations are unavailable"}, status_code=503
            )
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

    @app.get("/api/organizer/recipients")
    async def organizer_recipients(request: Request) -> Response:
        _, denied = await _authorized(request, "organizer", csrf=False)
        if denied:
            return denied
        repository = _visit_repository(request)
        if repository is None:
            return _api_error("service_unavailable", 503)
        rows = await repository.eligible_recipients()
        return JSONResponse({"recipients": [dict(row) for row in rows]})

    @app.get("/api/organizer/visits")
    async def organizer_visits(request: Request) -> Response:
        _, denied = await _authorized(request, "organizer", csrf=False)
        if denied:
            return denied
        repository = _visit_repository(request)
        if repository is None:
            return _api_error("service_unavailable", 503)
        rows = await repository.organizer_visits()
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            visit_id = str(row["id"])
            state = str(row["state"])
            item = grouped.setdefault(
                visit_id,
                {
                    "id": visit_id,
                    "hospital": str(row["hospital"]),
                    "date": str(row["visit_date"]),
                    "department_code": str(row["department_code"]),
                    "clinic_code": str(row["clinic_code"]),
                    "session": str(row["clinic_session"]),
                    "state": state,
                    "observation": {
                        "current_number": row["near_last_current_number"],
                        "checked_at": row["latest_observed_at"],
                    },
                    "source_read": {
                        "status": str(row["latest_source_read_status"]),
                        "reason": str(row["latest_source_read_reason"]),
                    },
                    "notification": {
                        "count": int(row["notification_count"] or 0),
                        "accepted": int(row["accepted_count"] or 0),
                        "issues": int(row["issue_count"] or 0),
                    },
                    "recipients": [],
                },
            )
            item["patient_number"] = int(row["patient_number"])
            source_url = progress_link(str(row["hospital"]))
            if source_url is not None:
                item["source_url"] = source_url
            if row["recipient_id"] is not None:
                item["recipients"].append(
                    {
                        "id": str(row["recipient_id"]),
                        "display_name": str(row["display_name"]),
                    }
                )
        return JSONResponse({"visits": list(grouped.values())})

    @app.post("/api/organizer/visits", status_code=201)
    async def create_organizer_visit(request: Request) -> Response:
        _, denied = await _authorized(request, "organizer", csrf=True)
        if denied:
            return denied
        body = await _organizer_body(request)
        if body is None:
            return _api_error("invalid_request", 400)
        parsed = _visit_input(body)
        repository = _visit_repository(request)
        if parsed is None:
            return _api_error("invalid_request", 400)
        if repository is None:
            return _api_error("service_unavailable", 503)
        visit_id = str(uuid.uuid4())
        try:
            created = await repository.create_organizer_draft(
                visit_id=visit_id, now=_now(request), **parsed
            )
        except Exception:
            return _api_error("ineligible_recipients", 409)
        if not created:
            return _api_error("ineligible_recipients", 409)
        return JSONResponse({"id": visit_id, "state": "draft"}, status_code=201)

    @app.patch("/api/organizer/visits/{visit_id}")
    async def update_organizer_visit(visit_id: str, request: Request) -> Response:
        _, denied = await _authorized(request, "organizer", csrf=True)
        if denied:
            return denied
        body = await _organizer_body(request)
        parsed = _visit_input(body) if body is not None else None
        if parsed is None:
            return _api_error("invalid_request", 400)
        gate = _send_gate(request)
        if gate is None:
            return _api_error("service_unavailable", 503)
        rpc_request = json.dumps(
            {
                "visit_id": visit_id,
                "hospital": parsed["hospital"],
                "visit_day": parsed["visit_day"].isoformat(),
                "department_code": parsed["department_code"],
                "clinic_code": parsed["clinic_code"],
                "clinic_session": parsed["clinic_session"],
                "patient_number": parsed["patient_number"],
                "recipient_ids": list(parsed["recipient_ids"]),
                "now": iso_utc(_now(request)),
            },
            separators=(",", ":"),
        )
        if not await gate.update_draft_rpc(rpc_request):
            return _api_error("invalid_lifecycle_state", 409)
        return JSONResponse({"id": visit_id, "state": "draft"})

    @app.get("/api/organizer/visits/{visit_id}/correction")
    async def organizer_visit_correction(visit_id: str, request: Request) -> Response:
        _, denied = await _authorized(request, "organizer", csrf=True)
        if denied:
            return denied
        repository = _visit_repository(request)
        if repository is None:
            return _api_error("service_unavailable", 503)
        visit = await repository.get_visit(visit_id)
        if visit is None:
            return _api_error("visit_not_found", 404)
        if visit["state"] not in {"draft", "stopped", "expired"}:
            return _api_error("invalid_lifecycle_state", 409)
        return JSONResponse({"patient_number": int(visit["patient_number"])})

    @app.post("/api/organizer/visits/{visit_id}/start")
    async def start_organizer_visit(visit_id: str, request: Request) -> Response:
        _, denied = await _authorized(request, "organizer", csrf=True)
        if denied:
            return denied
        gate = _send_gate(request)
        if gate is None:
            return _api_error("service_unavailable", 503)
        result = await gate.start_visit(visit_id, iso_utc(_now(request)))
        if "error" in result:
            errors = {
                "visit_not_found": ("visit_not_found", 404),
                "invalid_lifecycle_state": ("invalid_lifecycle_state", 409),
                "observation_unavailable": ("observation_unavailable", 503),
                "observation_stale": ("observation_stale", 409),
                "observation_scope_mismatch": ("observation_scope_mismatch", 409),
                "observation_untrusted": ("observation_untrusted", 409),
                "observation_invalid": ("observation_invalid", 409),
                "ineligible_recipients": ("ineligible_recipients", 409),
                "scheduler_held": ("scheduler_held", 503),
            }
            code, status = errors.get(result["error"], ("service_unavailable", 503))
            return _api_error(code, status)
        return JSONResponse(result)

    @app.post("/api/organizer/visits/{visit_id}/stop")
    async def stop_organizer_visit(visit_id: str, request: Request) -> Response:
        _, denied = await _authorized(request, "organizer", csrf=True)
        if denied:
            return denied
        gate = _send_gate(request)
        if gate is None:
            return _api_error("service_unavailable", 503)
        state = await gate.stop_visit(visit_id, iso_utc(_now(request)))
        if state is None:
            return _api_error("visit_not_found", 404)
        if state == "invalid_lifecycle_state":
            return _api_error("invalid_lifecycle_state", 409)
        if state == "scheduler_held":
            return _api_error("scheduler_held", 503)
        return JSONResponse({"state": state})

    @app.post("/api/organizer/visits/{visit_id}/correct")
    async def correct_organizer_visit(visit_id: str, request: Request) -> Response:
        _, denied = await _authorized(request, "organizer", csrf=True)
        if denied:
            return denied
        body = await _organizer_body(request)
        parsed = _visit_input(body) if body is not None else None
        gate = _send_gate(request)
        if parsed is None:
            return _api_error("invalid_request", 400)
        if gate is None:
            return _api_error("service_unavailable", 503)
        rpc_request = json.dumps(
            {
                "visit_id": visit_id,
                "hospital": parsed["hospital"],
                "visit_day": parsed["visit_day"].isoformat(),
                "department_code": parsed["department_code"],
                "clinic_code": parsed["clinic_code"],
                "clinic_session": parsed["clinic_session"],
                "patient_number": parsed["patient_number"],
                "recipient_ids": list(parsed["recipient_ids"]),
            },
            separators=(",", ":"),
        )
        corrected = await gate.correct_stopped_visit_rpc(rpc_request)
        if not corrected:
            return _api_error("invalid_lifecycle_state", 409)
        return JSONResponse({"id": visit_id, "state": "draft"})

    @app.post("/api/recipient/opt-in")
    async def opt_in_recipient(request: Request) -> Response:
        claims, denied = await _authorized(
            request, "recipient", csrf=True, allow_pending=True
        )
        if denied:
            return denied
        repository = _identity_repository(request)
        if repository is None:
            return JSONResponse(
                {"detail": "Recipient controls are unavailable"}, status_code=503
            )
        if not await repository.opt_in(claims.subject, _now(request)):
            return JSONResponse(
                {"detail": "Recipient consent is already set or unavailable"},
                status_code=409,
            )
        return Response(status_code=204)

    @app.post("/api/recipient/withdraw")
    async def withdraw_recipient(request: Request) -> Response:
        claims, denied = await _authorized(request, "recipient", csrf=True)
        if denied:
            return denied
        identity = _identity_repository(request)
        visits = _visit_repository(request)
        if identity is None or visits is None:
            return JSONResponse(
                {"detail": "Recipient controls are unavailable"}, status_code=503
            )
        recipient_id = await identity.recipient_id(claims.subject, active=True)
        if recipient_id is None:
            return Response(status_code=204)
        gate = _send_gate(request)
        if gate is None:
            return JSONResponse(
                {"detail": "Recipient send ordering is unavailable"}, status_code=503
            )
        await gate.withdraw_recipient(recipient_id, iso_utc(_now(request)))
        return Response(status_code=204)

    @app.post("/api/visits/{visit_id}/recipients/{recipient_id}")
    async def select_recipient(
        visit_id: str, recipient_id: str, request: Request
    ) -> Response:
        _, denied = await _authorized(request, "organizer", csrf=True)
        if denied:
            return denied
        identity = _identity_repository(request)
        gate = _send_gate(request)
        if identity is None or gate is None:
            return JSONResponse(
                {"detail": "Recipient eligibility checks are unavailable"},
                status_code=503,
            )
        subject = await identity.recipient_subject(recipient_id)
        if subject is None:
            return JSONResponse(
                {"detail": "Recipient is not opted in"}, status_code=409
            )
        now = _now(request)
        if not await gate.add_visit_recipient(visit_id, recipient_id, now):
            return JSONResponse(
                {"detail": "Recipient could not be selected for this visit"},
                status_code=409,
            )
        return Response(status_code=204)

    @app.post("/api/visits/{visit_id}/stop")
    async def stop_visit(visit_id: str, request: Request) -> Response:
        _, denied = await _authorized(request, "organizer", csrf=True)
        if denied:
            return denied
        gate = _send_gate(request)
        if gate is None:
            return JSONResponse(
                {"detail": "Visit send ordering is unavailable"}, status_code=503
            )
        state = await gate.stop_visit(visit_id, iso_utc(_now(request)))
        if state is None:
            return _api_error("visit_not_found", 404)
        if state == "invalid_lifecycle_state":
            return _api_error("invalid_lifecycle_state", 409)
        return JSONResponse({"state": state})

    @app.delete("/api/visits/{visit_id}/recipients/{recipient_id}", status_code=204)
    async def remove_visit_recipient(
        visit_id: str, recipient_id: str, request: Request
    ) -> Response:
        _, denied = await _authorized(request, "organizer", csrf=True)
        if denied:
            return denied
        gate = _send_gate(request)
        if gate is None:
            return JSONResponse(
                {"detail": "Recipient send ordering is unavailable"}, status_code=503
            )
        removed = await gate.remove_visit_recipient(
            visit_id, recipient_id, iso_utc(_now(request))
        )
        if not removed:
            return JSONResponse(
                {"detail": "Recipient was not selected for this visit"}, status_code=404
            )
        return Response(status_code=204)

    @app.get("/api/organizer/scheduler/status")
    async def scheduler_status(request: Request) -> Response:
        _, denied = await _authorized(request, "organizer", csrf=False)
        if denied:
            return denied
        gate = _send_gate(request)
        if gate is None:
            return _api_error("service_unavailable", 503)
        return JSONResponse(await gate.scheduler_status())

    @app.post("/api/organizer/scheduler/recovery-hold", status_code=204)
    async def hold_scheduler_for_reconciliation(request: Request) -> Response:
        _, denied = await _authorized(request, "organizer", csrf=True)
        if denied:
            return denied
        gate = _send_gate(request)
        if gate is None:
            return JSONResponse(
                {"detail": "Scheduler recovery gate is unavailable"}, status_code=503
            )
        await gate.hold_for_reconciliation()
        return Response(status_code=204)

    @app.post("/api/organizer/scheduler/resume", status_code=204)
    async def resume_scheduler_after_reconciliation(request: Request) -> Response:
        _, denied = await _authorized(request, "organizer", csrf=True)
        if denied:
            return denied
        try:
            body = await request.json()
        except Exception:
            body = None
        if not isinstance(body, Mapping) or body.get("reconciled") is not True:
            return JSONResponse(
                {"detail": "Explicit reconciliation confirmation is required"},
                status_code=400,
            )
        gate = _send_gate(request)
        if gate is None:
            return JSONResponse(
                {"detail": "Scheduler recovery gate is unavailable"}, status_code=503
            )
        if not await gate.resume_after_reconciliation(True):
            return JSONResponse({"detail": "Scheduler remains held"}, status_code=409)
        return Response(status_code=204)

    @app.post("/__niy006_test/{operation}")
    async def local_scheduler_test_control(
        operation: str, request: Request
    ) -> Response:
        env = request.scope.get("env")
        if not local_test_mode(env):
            return Response(status_code=404)
        gate = _send_gate(request)
        if gate is None:
            return JSONResponse(
                {"detail": "Local test gate is unavailable"}, status_code=503
            )
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, Mapping):
            return JSONResponse({"detail": "Invalid test request"}, status_code=400)
        if operation == "organizer-session":
            settings = _login_settings(request)
            session = issue_session(
                "niy006-synthetic-organizer",
                "organizer",
                settings.session_secret,
                now=int(request.app.state.clock()),
            )
            response = JSONResponse({"issued": True})
            response.set_cookie(
                SESSION_COOKIE_NAME,
                session.value,
                **session_cookie_options(
                    max_age=session.expires_at - int(request.app.state.clock())
                ),
            )
            response.set_cookie(
                CSRF_COOKIE_NAME,
                session.csrf_token,
                **csrf_cookie_options(
                    max_age=session.expires_at - int(request.app.state.clock())
                ),
            )
            return response
        if operation == "seed":
            seeded = await gate.seed_test_visit(
                str(body["visit_id"]),
                str(body["recipient_id"]),
                str(body["visit_day"]),
                int(body["patient_number"]),
                str(body["now"]),
            )
            return JSONResponse({"seeded": seeded}, status_code=201 if seeded else 409)
        if operation == "observation":
            current = body.get("current_number")
            configured = await gate.set_test_observation(
                int(current) if current is not None else None,
                body.get("trustworthy") is True,
            )
            return JSONResponse({"configured": configured})
        if operation == "stop":
            state = await gate.stop_visit(str(body["visit_id"]), str(body["now"]))
            return JSONResponse({"state": state})
        if operation == "remove":
            removed = await gate.remove_visit_recipient(
                str(body["visit_id"]),
                str(body["recipient_id"]),
                str(body["now"]),
            )
            return JSONResponse({"removed": removed})
        if operation == "withdraw":
            withdrawn = await gate.withdraw_recipient(
                str(body["recipient_id"]), str(body["now"])
            )
            return JSONResponse({"withdrawn": withdrawn})
        if operation == "hold":
            await gate.hold_for_reconciliation()
            return JSONResponse({"held": True})
        if operation == "line-mode":
            await gate.set_test_line_mode(str(body["mode"]))
            return Response(status_code=204)
        if operation == "wait-request":
            await gate.wait_test_request_started()
            return Response(status_code=204)
        if operation == "release-request":
            await gate.release_test_request()
            return Response(status_code=204)
        if operation == "tick":
            return JSONResponse(await gate.scheduled_tick(str(body["now"])))
        if operation == "snapshot":
            return JSONResponse(await gate.test_snapshot())
        if operation == "correct-watch":
            corrected = await gate.correct_test_watch(
                str(body["visit_id"]),
                str(body["visit_day"]),
                int(body["patient_number"]),
                str(body["now"]),
            )
            return JSONResponse({"corrected": corrected})
        if operation == "restore-shaped":
            return JSONResponse({"restored": await gate.restore_test_state()})
        return Response(status_code=404)

    @app.get("/{path:path}")
    async def serve_static_asset(path: str, request: Request) -> Response:
        """Proxy non-API requests to Workers Static Assets after the UI build."""
        env = request.scope.get("env")
        if env is None:
            asset_path = (STATIC_ASSET_ROOT / (path or "index.html")).resolve()
            if (
                not asset_path.is_relative_to(STATIC_ASSET_ROOT.resolve())
                or not asset_path.is_file()
            ):
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
    test_mode = local_test_mode(env)
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
    if test_mode and not values["SESSION_SIGNING_SECRET"]:
        values["SESSION_SIGNING_SECRET"] = "niy006-local-synthetic-session-secret-only"
    if test_mode:
        subjects = set(
            part.strip()
            for part in values["ORGANIZER_LINE_SUBJECTS"].split(",")
            if part.strip()
        )
        subjects.add("niy006-synthetic-organizer")
        values["ORGANIZER_LINE_SUBJECTS"] = ",".join(subjects)
    settings = LineLoginSettings.from_mapping(values)
    if env is not None and not test_mode:
        # Cookies and callback must return to the same HTTPS origin. Do not trust
        # forwarded headers or redirect a misconfigured deployment elsewhere.
        try:
            callback = urlsplit(settings.redirect_uri)
            same_origin = (
                callback.scheme == request.url.scheme == "https"
                and callback.hostname == request.url.hostname
                and (callback.port or 443) == (request.url.port or 443)
            )
        except ValueError:
            same_origin = False
        if not same_origin:
            settings = replace(settings, redirect_uri="")
    return settings


async def _organizer_body(request: Request) -> Mapping[str, Any] | None:
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, Mapping) else None


def _visit_input(body: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        if set(body) - {
            "hospital",
            "date",
            "department_code",
            "clinic_code",
            "session",
            "patient_number",
            "recipient_ids",
        }:
            return None
        hospital = Hospital(str(body["hospital"])).value
        clinic_session = ClinicSession(str(body["session"])).value
        visit_day = date.fromisoformat(str(body["date"]))
        department_code = _bounded_code(body["department_code"])
        clinic_code = _bounded_code(body["clinic_code"])
        patient_number = body["patient_number"]
        recipient_ids = body["recipient_ids"]
        if (
            isinstance(patient_number, bool)
            or not isinstance(patient_number, int)
            or patient_number < 1
        ):
            return None
        if (
            not isinstance(recipient_ids, list)
            or not recipient_ids
            or len(recipient_ids) > 50
        ):
            return None
        if any(
            not isinstance(value, str) or not value or len(value) > 128
            for value in recipient_ids
        ):
            return None
        return {
            "hospital": hospital,
            "visit_day": visit_day,
            "department_code": department_code,
            "clinic_code": clinic_code,
            "clinic_session": clinic_session,
            "patient_number": patient_number,
            "recipient_ids": tuple(recipient_ids),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _bounded_code(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 64 or not value.strip():
        raise ValueError("invalid clinic code")
    return value.strip()


def _api_error(code: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status_code)


def _binding(env: Any, name: str) -> str:
    value = _binding_value(env, name, "")
    return value if isinstance(value, str) else ""


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


def _send_gate(request: Request) -> Any | None:
    configured = request.app.state.send_gate
    if configured is not None:
        return configured
    env = request.scope.get("env")
    namespace = _binding_value(env, "SEND_GATE")
    if namespace is None:
        return None
    get_by_name = getattr(namespace, "getByName", None)
    if get_by_name is None:
        return None
    return get_by_name("next-is-you-system")


def _binding_value(env: Any, name: str, default: Any = None) -> Any:
    if isinstance(env, Mapping):
        return env.get(name, default)
    return getattr(env, name, default) if env is not None else default


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
    if not local_test_mode(request.scope.get("env")) and not config.ready:
        return None, JSONResponse(
            {"detail": "LINE Login is not configured"}, status_code=503
        )
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
            return None, JSONResponse(
                {"detail": "Recipient identity is unavailable"}, status_code=503
            )
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
    response.delete_cookie(
        SESSION_COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax"
    )
    response.delete_cookie(
        CSRF_COOKIE_NAME, path="/", secure=True, httponly=False, samesite="lax"
    )


app = create_app()

if asgi is not None:
    ASGIEntrypoint = asgi.entrypoint(app)

    class Default(ASGIEntrypoint):
        async def scheduled(self, controller, env, ctx):
            gate = self.env.SEND_GATE.getByName("next-is-you-system")
            await gate.scheduled_tick()
