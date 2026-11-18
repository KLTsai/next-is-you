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


_STYLE = """
:root{font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif;color:#26362f;background:#f4f7f6;--green:#28634f;--line:#dce5df}
*{box-sizing:border-box}
body{min-width:320px;min-height:100vh;margin:0}
a:focus-visible{outline:3px solid #87b9a2;outline-offset:3px}
.shell{width:min(100% - 36px,900px);margin:0 auto;padding:27px 0 30px}
.brand{display:flex;align-items:center;gap:16px;margin-bottom:27px;color:inherit;text-decoration:none}
.brand-mark{display:grid;width:44px;height:44px;place-items:center;border-radius:14px;color:#fff;background:var(--green);font-size:1.15rem;font-weight:800}
.brand strong{display:block;font-size:1.04rem;letter-spacing:.01em}
.eyebrow{display:block;margin:0 0 6px;color:#74857c;font-size:.7rem;font-weight:750;letter-spacing:.11em}
.panel{max-width:570px;margin:8vh auto 0;border:1px solid var(--line);border-radius:18px;padding:clamp(20px,5vw,34px);background:#fff;box-shadow:0 12px 36px rgb(35 58 46 / 5%)}
h1{margin:0 0 18px;font-size:clamp(1.5rem,4vw,2rem);color:#26362f}
.cause{margin:0 0 18px;color:#66766e;line-height:1.7}
.next-step{margin:0;border-radius:9px;padding:11px 13px;color:#6b4b18;background:#fff3d8;font-size:.88rem;line-height:1.5}
footer{padding:17px 3px 0;color:#738077;font-size:.8rem;line-height:1.55}
footer p{margin:0}
"""


def login_error_page(failure: LoginFailure) -> HTMLResponse:
    body = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#f4f7f6">
<meta name="robots" content="noindex">
<title>無法完成登入 - 家人候診提醒</title>
<style>{_STYLE}</style>
</head>
<body>
<main class="shell">
<a class="brand" href="/" aria-label="家人候診提醒首頁"><span class="brand-mark" aria-hidden="true">候</span><span><span class="eyebrow">FAMILY CARE</span><strong>家人候診提醒</strong></span></a>
<section class="panel" aria-labelledby="login-error-heading">
<span class="eyebrow">登入</span>
<h1 id="login-error-heading">無法完成登入</h1>
<p class="cause">{escape(failure.cause)}</p>
<p class="next-step" role="alert">{escape(failure.next_step)}</p>
</section>
<footer><p>院方網頁與診間現場資訊為準。提醒不代表叫號確認，也不預測候診時間。本服務非醫院官方服務。</p></footer>
</main>
</body>
</html>
"""
    return HTMLResponse(
        body, status_code=failure.status, headers={"cache-control": "no-store"}
    )
