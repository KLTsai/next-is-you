"""Today's Cloudflare usage against the Workers Free plan's daily limits.

Free limits are per account and reset at 00:00 UTC, so Staging and Production
add up. The script reads today's UTC totals from the GraphQL Analytics API,
projects each to the full day at the rate so far, and prints a Markdown table
with the Free limit and the projected percentage.

Exit status:
    0  every projection is at or below 50% of its Free limit
    1  at least one projection is above 50%
    2  the check could not run (missing settings, HTTP or GraphQL error)

A dataset the account does not have enabled is reported as "not available" and
its measures are left out; the other measures are still checked.

Environment:
    CLOUDFLARE_ANALYTICS_TOKEN  API token with Account Analytics Read only
    CLOUDFLARE_ACCOUNT_ID       the account whose usage is read

Usage:
    python3 scripts/cloudflare_usage.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, TextIO

ENDPOINT = "https://api.cloudflare.com/client/v4/graphql"
THRESHOLD_PERCENT = 50
SECONDS_PER_DAY = 24 * 60 * 60

Post = Callable[[str, dict], dict]


@dataclass(frozen=True)
class Measure:
    label: str
    dataset: str
    field: str
    limit: int
    decimals: int = 0


# Free plan daily limits, from
# https://developers.cloudflare.com/workers/platform/limits/,
# https://developers.cloudflare.com/durable-objects/platform/pricing/ and
# https://developers.cloudflare.com/d1/platform/pricing/.
MEASURES = (
    Measure("Worker requests", "workersInvocationsAdaptive", "requests", 100_000),
    Measure(
        "Durable Object requests",
        "durableObjectsInvocationsAdaptiveGroups",
        "requests",
        100_000,
    ),
    Measure(
        "Durable Object duration (GB-s)",
        "durableObjectsPeriodicGroups",
        "duration",
        13_000,
        decimals=1,
    ),
    Measure(
        "Durable Object rows read",
        "durableObjectsPeriodicGroups",
        "rowsRead",
        5_000_000,
    ),
    Measure(
        "Durable Object rows written",
        "durableObjectsPeriodicGroups",
        "rowsWritten",
        100_000,
    ),
    Measure("D1 rows read", "d1AnalyticsAdaptiveGroups", "rowsRead", 5_000_000),
    Measure("D1 rows written", "d1AnalyticsAdaptiveGroups", "rowsWritten", 100_000),
)

DATASETS = tuple(dict.fromkeys(measure.dataset for measure in MEASURES))


class CheckFailed(Exception):
    """The check could not run; the message says why."""


def settings_query() -> str:
    fields = " ".join(f"{name} {{ enabled }}" for name in DATASETS)
    return (
        "query ($account: string!) { viewer { accounts(filter: {accountTag: $account})"
        f" {{ settings {{ {fields} }} }} }} }}"
    )


def usage_query(datasets: list[str]) -> str:
    parts = []
    for name in datasets:
        fields = " ".join(m.field for m in MEASURES if m.dataset == name)
        parts.append(
            f"{name}(limit: 10000, filter: {{date: $date}}) {{ sum {{ {fields} }} }}"
        )
    return (
        "query ($account: string!, $date: Date!) { viewer {"
        f" accounts(filter: {{accountTag: $account}}) {{ {' '.join(parts)} }} }} }}"
    )


def account_data(response: dict) -> dict:
    errors = response.get("errors")
    if errors:
        messages = "; ".join(str(error.get("message", error)) for error in errors)
        raise CheckFailed(f"GraphQL error: {messages}")
    accounts = ((response.get("data") or {}).get("viewer") or {}).get("accounts")
    if not accounts:
        raise CheckFailed("GraphQL returned no account; check CLOUDFLARE_ACCOUNT_ID.")
    return accounts[0]


def http_post(token: str) -> Post:
    def post(query: str, variables: dict) -> dict:
        request = urllib.request.Request(
            ENDPOINT,
            data=json.dumps({"query": query, "variables": variables}).encode(),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as reply:
                return json.load(reply)
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")[:500]
            raise CheckFailed(f"HTTP {error.code} from {ENDPOINT}: {body}") from error
        except urllib.error.URLError as error:
            raise CheckFailed(f"Could not reach {ENDPOINT}: {error.reason}") from error

    return post


def number(value: float, decimals: int) -> str:
    return f"{value:,.{decimals}f}"


def check(account: str, now: datetime, post: Post) -> tuple[list[str], bool]:
    """Returns the report lines and whether any projection is over the line."""
    day = now.astimezone(timezone.utc)
    midnight = day.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = max((day - midnight).total_seconds(), 1.0)
    date = midnight.date().isoformat()

    settings = account_data(post(settings_query(), {"account": account}))["settings"]
    enabled = [name for name in DATASETS if (settings.get(name) or {}).get("enabled")]
    totals: dict[str, dict] = {}
    if enabled:
        data = account_data(
            post(usage_query(enabled), {"account": account, "date": date})
        )
        for name in enabled:
            sums: dict[str, float] = {}
            for group in data.get(name) or []:
                for field, value in (group.get("sum") or {}).items():
                    sums[field] = sums.get(field, 0) + (value or 0)
            totals[name] = sums

    hours, rest = divmod(int(elapsed), 3600)
    lines = [
        f"## Cloudflare usage for {date} (UTC)",
        "",
        f"{hours} h {rest // 60:02d} min of the UTC day have passed"
        f" ({elapsed / SECONDS_PER_DAY:.0%}). Projections assume the rest of the"
        f" day runs at the same rate. The check fails above {THRESHOLD_PERCENT}%.",
        "",
        "| Measure | Used today | Projected for the day | Free limit"
        " | Projected % of limit | Status |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    over = False
    for measure in MEASURES:
        if measure.dataset not in totals:
            lines.append(
                f"| {measure.label} | - | - | {measure.limit:,} | - |"
                f" not available: `{measure.dataset}` is not enabled on this account |"
            )
            continue
        used = totals[measure.dataset].get(measure.field, 0)
        projected = used * SECONDS_PER_DAY / elapsed
        percent = projected * 100 / measure.limit
        status = "ok"
        if percent > THRESHOLD_PERCENT:
            status = f"**over {THRESHOLD_PERCENT}%**"
            over = True
        lines.append(
            f"| {measure.label} | {number(used, measure.decimals)}"
            f" | {number(projected, measure.decimals)} | {measure.limit:,}"
            f" | {percent:.1f}% | {status} |"
        )
    return lines, over


def main(
    env: Mapping[str, str] | None = None,
    now: datetime | None = None,
    post: Post | None = None,
    out: TextIO | None = None,
) -> int:
    env = os.environ if env is None else env
    now = datetime.now(timezone.utc) if now is None else now
    out = sys.stdout if out is None else out
    try:
        token = env.get("CLOUDFLARE_ANALYTICS_TOKEN", "")
        account = env.get("CLOUDFLARE_ACCOUNT_ID", "")
        missing = [
            name
            for name, value in (
                ("CLOUDFLARE_ANALYTICS_TOKEN", token),
                ("CLOUDFLARE_ACCOUNT_ID", account),
            )
            if not value
        ]
        if missing:
            raise CheckFailed(f"Not set: {', '.join(missing)}.")
        lines, over = check(account, now, post or http_post(token))
    except CheckFailed as error:
        print(f"Cloudflare usage check could not run: {error}", file=out)
        return 2
    print("\n".join(lines), file=out)
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
