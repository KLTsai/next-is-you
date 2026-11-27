"""Screens use the words agreed in GLOSSARY.md (#139).

No source the browser receives may say 管理者, 監控, 停止提醒, 看診提醒, 成員 or
這一診, and 提醒 stays only where it names the whole service. LINE message
wording lives in the backend and is not scanned.

Fixture/mock evidence: reads source files only, no network.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
LOGIN_ERROR_PAGE = ROOT / "src" / "next_is_you" / "login_error_page.py"

# The uses of 提醒 that name the whole service, not one visit or one message.
KEPT_SERVICE_WIDE_USES = (
    "家人候診提醒",  # product name
    "目前無法使用提醒服務",
    "提醒不代表叫號確認",  # footer
    "登入以管理家人提醒",  # login heading
)
FORBIDDEN_WORDS = (
    "管理者",
    "監控",
    "停止提醒",
    "看診提醒",
    "成員",
    "這一診",
    "提醒",
)


def screen_source_files() -> list[Path]:
    pages = sorted(FRONTEND.glob("*.html"))
    scripts = sorted(path for path in (FRONTEND / "src").rglob("*") if path.is_file())
    assert pages, "no frontend page found; the scan would pass vacuously"
    assert scripts, "no frontend source found; the scan would pass vacuously"
    return [*pages, *scripts, LOGIN_ERROR_PAGE]


def old_words(files: list[Path]) -> list[str]:
    """Return "file:line word" for each forbidden word outside the kept uses."""
    found = []
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            for kept in KEPT_SERVICE_WIDE_USES:
                line = line.replace(kept, "")
            found += [
                f"{path.name}:{number} {word}"
                for word in FORBIDDEN_WORDS
                if word in line
            ]
    return found


def test_screens_use_the_agreed_words():
    assert old_words(screen_source_files()) == []


@pytest.mark.parametrize("kept", KEPT_SERVICE_WIDE_USES)
def test_each_kept_use_is_still_on_a_screen(kept):
    """A kept use nobody shows any more must leave the allow list."""
    assert any(
        kept in path.read_text(encoding="utf-8") for path in screen_source_files()
    )


@pytest.mark.parametrize("word", FORBIDDEN_WORDS)
def test_scan_fails_when_a_forbidden_word_is_added(word, tmp_path):
    planted = tmp_path / "main.ts"
    planted.write_text(f'const text = "家人候診提醒 {word}";\n', encoding="utf-8")
    assert f"main.ts:1 {word}" in old_words([planted])
