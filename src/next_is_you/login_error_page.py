"""One shared Traditional Chinese page for LINE sign-in and invitation failures."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from fastapi.responses import HTMLResponse


@dataclass(frozen=True)
class LoginFailure:
    status: int
    cause: str
    next_step: str


UNAVAILABLE = LoginFailure(503, "LINE 登入目前無法使用。", "請稍後再試，或聯絡管理者。")
INVITATION_INVALID = LoginFailure(
    410,
    "這個邀請連結已失效、過期，或已經被使用過。",
    "請聯絡管理者重新發送邀請連結。",
)
NOT_VERIFIED = LoginFailure(
    401,
    "無法確認你的 LINE 登入。",
    "請重新開啟邀請連結再試一次；如果你是管理者，請重新開啟管理者登入頁。",
)
FRIENDSHIP_UNVERIFIABLE = LoginFailure(
    503,
    "暫時無法確認你是否已加入官方帳號。",
    "請稍後再開啟邀請連結重試。",
)
FRIENDSHIP_MISSING = LoginFailure(
    409,
    "你還沒有加入官方帳號為好友。",
    "請加入官方帳號為好友後，再開啟一次邀請連結。",
)
NOT_MANAGER = LoginFailure(
    403,
    "這個 LINE 帳號不是管理者。",
    "如果你是受邀的家人，請使用管理者給你的邀請連結。",
)


def login_error_page(failure: LoginFailure) -> HTMLResponse:
    body = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex">
<title>無法完成登入 - 家人候診提醒</title>
<style>
body{{margin:0;background:#f4f7f6;color:#1d2b29;font:16px/1.6 system-ui,-apple-system,"Noto Sans TC",sans-serif}}
main{{max-width:32rem;margin:0 auto;padding:2.5rem 1.25rem}}
.panel{{background:#fff;border:1px solid #d5dfdc;border-radius:12px;padding:1.5rem}}
h1{{margin:0 0 .75rem;font-size:1.25rem}}
p{{margin:.5rem 0}}
</style>
</head>
<body>
<main>
<section class="panel" aria-labelledby="login-error-heading">
<h1 id="login-error-heading">無法完成登入</h1>
<p>{escape(failure.cause)}</p>
<p>{escape(failure.next_step)}</p>
</section>
</main>
</body>
</html>
"""
    return HTMLResponse(
        body, status_code=failure.status, headers={"cache-control": "no-store"}
    )
