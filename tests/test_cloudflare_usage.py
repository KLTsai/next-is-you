"""The daily Cloudflare usage check in `scripts/cloudflare_usage.py`.

Evidence: fixture/mock. The GraphQL endpoint is replaced by canned responses
shaped like the live Analytics API; nothing here touches the network.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "cloudflare_usage", ROOT / "scripts" / "cloudflare_usage.py"
)
cloudflare_usage = importlib.util.module_from_spec(_spec)
sys.modules["cloudflare_usage"] = cloudflare_usage
_spec.loader.exec_module(cloudflare_usage)

ENV = {"CLOUDFLARE_ANALYTICS_TOKEN": "test-token", "CLOUDFLARE_ACCOUNT_ID": "acct"}
# 06:00 UTC: a quarter of the day has passed, so projections are four times usage.
SIX_AM = datetime(2026, 11, 24, 6, 0, tzinfo=timezone.utc)

ALL_ENABLED = {
    "workersInvocationsAdaptive": {"enabled": True},
    "durableObjectsInvocationsAdaptiveGroups": {"enabled": True},
    "durableObjectsPeriodicGroups": {"enabled": True},
    "d1AnalyticsAdaptiveGroups": {"enabled": True},
}

# Two Workers (Production and Staging) and two databases, as on the account.
QUIET_DAY = {
    "workersInvocationsAdaptive": [
        {"sum": {"requests": 448}},
        {"sum": {"requests": 319}},
    ],
    "durableObjectsInvocationsAdaptiveGroups": [
        {"sum": {"requests": 454}},
        {"sum": {"requests": 549}},
    ],
    "durableObjectsPeriodicGroups": [
        {"sum": {"duration": 31.4, "rowsRead": 455, "rowsWritten": 3}},
        {"sum": {"duration": 15.1, "rowsRead": 446, "rowsWritten": 0}},
    ],
    "d1AnalyticsAdaptiveGroups": [
        {"sum": {"rowsRead": 8551, "rowsWritten": 393}},
        {"sum": {"rowsRead": 1229, "rowsWritten": 71}},
    ],
}


ALL_FIELDS = {
    "workersInvocationsAdaptive": ["requests", "errors"],
    "durableObjectsInvocationsAdaptiveGroups": ["requests"],
    "durableObjectsPeriodicGroups": ["duration", "rowsRead", "rowsWritten"],
    "d1AnalyticsAdaptiveGroups": ["rowsRead", "rowsWritten"],
}


class FakeGraphQL:
    """Answers the settings query and the usage query from canned data."""

    def __init__(self, settings=None, usage=None, errors=None, fields=None):
        self.settings = ALL_ENABLED if settings is None else settings
        self.usage = QUIET_DAY if usage is None else usage
        # The fields each dataset's `sum` offers; by default every field used.
        self.fields = ALL_FIELDS if fields is None else fields
        self.errors = errors
        self.calls = []

    def __call__(self, query, variables):
        self.calls.append((query, variables))
        if self.errors is not None:
            return {"data": None, "errors": self.errors}
        if "settings" in query:
            account = {"settings": self.settings}
            types = {
                f"fields_{name}": {"fields": [{"name": field} for field in fields]}
                for name, fields in self.fields.items()
            }
            return {"data": {"viewer": {"accounts": [account]}, **types}}
        else:
            account = {
                name: groups for name, groups in self.usage.items() if name in query
            }
        return {"data": {"viewer": {"accounts": [account]}}, "errors": None}


def run(post, now=SIX_AM, env=ENV):
    out = io.StringIO()
    code = cloudflare_usage.main(env=env, now=now, post=post, out=out)
    return code, out.getvalue()


def row(report, measure):
    for line in report.splitlines():
        if line.startswith(f"| {measure} |"):
            return [cell.strip() for cell in line.strip("|").split("|")]
    raise AssertionError(f"no row for {measure!r} in:\n{report}")


def test_totals_add_both_workers_and_project_to_the_full_day():
    code, report = run(FakeGraphQL())

    assert code == 0
    # 448 + 319 = 767 so far; a quarter of the day gone, so 3,068 projected.
    assert row(report, "Worker requests") == [
        "Worker requests",
        "767",
        "3,068",
        "100,000",
        "3.1%",
        "ok",
    ]
    assert row(report, "D1 rows read") == [
        "D1 rows read",
        "9,780",
        "39,120",
        "5,000,000",
        "0.8%",
        "ok",
    ]
    assert row(report, "Durable Object duration (GB-s)") == [
        "Durable Object duration (GB-s)",
        "46.5",
        "186.0",
        "13,000",
        "1.4%",
        "ok",
    ]
    assert "2026-11-24" in report


def test_a_projection_above_half_a_limit_fails_the_check():
    # 25,001 Worker requests by 06:00 projects to 100,004: over 50% of 100,000.
    busy = dict(QUIET_DAY, workersInvocationsAdaptive=[{"sum": {"requests": 25_001}}])

    code, report = run(FakeGraphQL(usage=busy))

    assert code == 1
    assert row(report, "Worker requests")[-2:] == ["100.0%", "**over 50%**"]
    assert row(report, "D1 rows read")[-1] == "ok"


def test_a_projection_of_exactly_half_a_limit_passes():
    # 12,500 by 06:00 projects to exactly 50,000.
    edge = dict(QUIET_DAY, workersInvocationsAdaptive=[{"sum": {"requests": 12_500}}])

    code, report = run(FakeGraphQL(usage=edge))

    assert code == 0
    assert row(report, "Worker requests")[-2:] == ["50.0%", "ok"]


def test_projection_uses_the_time_passed_since_midnight_utc():
    # 18:00 in Taiwan is 10:00 UTC: 600 requests in 10 hours is 1,440 a day.
    taiwan = timezone(timedelta(hours=8))
    fake = FakeGraphQL(
        usage=dict(QUIET_DAY, workersInvocationsAdaptive=[{"sum": {"requests": 600}}])
    )

    code, report = run(fake, now=datetime(2026, 11, 24, 18, 0, tzinfo=taiwan))

    assert code == 0
    assert row(report, "Worker requests")[1:3] == ["600", "1,440"]
    assert fake.calls[-1][1] == {"account": "acct", "date": "2026-11-24"}


def test_a_dataset_not_enabled_is_reported_and_the_rest_still_checked():
    settings = dict(ALL_ENABLED, durableObjectsPeriodicGroups={"enabled": False})
    busy = dict(
        QUIET_DAY,
        d1AnalyticsAdaptiveGroups=[{"sum": {"rowsRead": 0, "rowsWritten": 30_000}}],
    )
    fake = FakeGraphQL(settings=settings, usage=busy)

    code, report = run(fake)

    assert code == 1
    for measure in (
        "Durable Object duration (GB-s)",
        "Durable Object rows read",
        "Durable Object rows written",
    ):
        cells = row(report, measure)
        assert cells[1:3] == ["-", "-"]
        assert cells[-1].startswith("not available")
    assert row(report, "Worker requests")[-1] == "ok"
    assert row(report, "D1 rows written")[-1] == "**over 50%**"
    # The disabled dataset is not queried, so it cannot fail the whole request.
    assert "durableObjectsPeriodicGroups(" not in fake.calls[-1][0]


def test_a_dataset_not_enabled_alone_does_not_fail_the_check():
    settings = dict(ALL_ENABLED, durableObjectsPeriodicGroups={"enabled": False})

    code, report = run(FakeGraphQL(settings=settings))

    assert code == 0
    assert "not available" in report


def test_a_field_missing_from_a_dataset_is_reported_and_not_queried():
    fields = dict(ALL_FIELDS, durableObjectsPeriodicGroups=["rowsRead", "rowsWritten"])
    fake = FakeGraphQL(fields=fields)

    code, report = run(fake)

    assert code == 0
    cells = row(report, "Durable Object duration (GB-s)")
    assert cells[1:3] == ["-", "-"]
    assert cells[-1].startswith("not available")
    assert row(report, "Durable Object rows read")[1] == "901"
    usage_query = fake.calls[-1][0]
    assert "rowsRead" in usage_query
    assert "duration" not in usage_query


def test_a_graphql_error_means_the_check_could_not_run():
    fake = FakeGraphQL(errors=[{"message": "not authorized for that account"}])

    code, report = run(fake)

    assert code == 2
    assert "could not run" in report
    assert "not authorized for that account" in report


def test_missing_settings_mean_the_check_could_not_run():
    fake = FakeGraphQL()

    code, report = run(fake, env={"CLOUDFLARE_ACCOUNT_ID": "acct"})

    assert code == 2
    assert "CLOUDFLARE_ANALYTICS_TOKEN" in report
    assert fake.calls == []
