from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from regional_cashless_monitor.models import Campaign, FetchDiagnostic, TargetMatch
from regional_cashless_monitor.monitor import JsonlAuditLog, run_monitor
from regional_cashless_monitor.state import EMPTY_STATE

JST = ZoneInfo("Asia/Tokyo")
NOW = datetime(2026, 8, 24, 9, 0, tzinfo=JST)


def make_campaign(*, start: date = date(2026, 10, 1), end: date | None = date(2026, 10, 31)):
    return Campaign(
        provider="paypay",
        provider_label="PayPay",
        title="一関市で最大20％還元",
        url="https://example.test/campaign/ichinoseki/",
        source_url="https://example.test/list/",
        target=TargetMatch("ichinoseki", "一関市", "city"),
        start_date=start,
        end_date=end,
        reward_text="最大20％還元",
    )


class FakeProvider:
    provider = "paypay"
    list_urls = ("https://example.test/list/",)

    def __init__(self, campaign: Campaign):
        self.campaign = campaign

    def fetch_campaigns(self, *, today=None):
        return [self.campaign], [
            FetchDiagnostic("paypay", self.list_urls[0], True, 1, 1, "test")
        ]


class FakeNotifier:
    enabled = True

    def __init__(self):
        self.campaign_calls = []
        self.health_calls = []

    def send_campaign(self, campaign, *, detected_at, is_update, changed_fields=None):
        self.campaign_calls.append((campaign, is_update, changed_fields))
        return "message-id"

    def send_health_alert(self, provider, source, failures, detail):
        self.health_calls.append(("alert", provider, failures))

    def send_recovery(self, provider, source):
        self.health_calls.append(("recovery", provider))


class FakeCalendar:
    def __init__(self):
        self.calls = []

    def upsert_campaign(self, campaign):
        self.calls.append(campaign)
        return "event-id"


def run_once(tmp_path: Path, *, mode: str, state: dict, campaign: Campaign, notifier, calendar):
    return run_monitor(
        mode=mode,
        state=state,
        state_path=tmp_path / "state.json",
        providers=[FakeProvider(campaign)],
        notifier=notifier,
        calendar=calendar,
        audit=JsonlAuditLog(tmp_path / "logs" / "audit.jsonl"),
        now=NOW,
    )


def test_first_auto_run_is_silent_baseline(tmp_path: Path) -> None:
    state = deepcopy(EMPTY_STATE)
    notifier = FakeNotifier()
    calendar = FakeCalendar()
    summary = run_once(
        tmp_path,
        mode="auto",
        state=state,
        campaign=make_campaign(),
        notifier=notifier,
        calendar=calendar,
    )
    assert summary.mode == "baseline(auto)"
    assert state["armed"] is True
    assert notifier.campaign_calls == []
    assert calendar.calls == []


def test_new_campaign_notifies_and_adds_calendar_once(tmp_path: Path) -> None:
    state = deepcopy(EMPTY_STATE)
    state["armed"] = True
    notifier = FakeNotifier()
    calendar = FakeCalendar()
    first = run_once(
        tmp_path,
        mode="run",
        state=state,
        campaign=make_campaign(),
        notifier=notifier,
        calendar=calendar,
    )
    second = run_once(
        tmp_path,
        mode="run",
        state=state,
        campaign=make_campaign(),
        notifier=notifier,
        calendar=calendar,
    )
    assert first.discord_notifications == 1
    assert first.calendar_updates == 1
    assert second.discord_notifications == 0
    assert second.calendar_updates == 0
    assert len(notifier.campaign_calls) == 1
    assert len(calendar.calls) == 1


def test_date_change_is_update_and_moves_same_campaign(tmp_path: Path) -> None:
    state = deepcopy(EMPTY_STATE)
    state["armed"] = True
    notifier = FakeNotifier()
    calendar = FakeCalendar()
    run_once(
        tmp_path,
        mode="run",
        state=state,
        campaign=make_campaign(),
        notifier=notifier,
        calendar=calendar,
    )
    summary = run_once(
        tmp_path,
        mode="run",
        state=state,
        campaign=make_campaign(start=date(2026, 10, 2)),
        notifier=notifier,
        calendar=calendar,
    )
    assert summary.updated_campaigns == 1
    assert notifier.campaign_calls[-1][1] is True
    assert "開始日" in notifier.campaign_calls[-1][2]
    assert len(calendar.calls) == 2


def test_expired_campaign_is_suppressed(tmp_path: Path) -> None:
    state = deepcopy(EMPTY_STATE)
    state["armed"] = True
    notifier = FakeNotifier()
    calendar = FakeCalendar()
    summary = run_once(
        tmp_path,
        mode="run",
        state=state,
        campaign=make_campaign(start=date(2026, 7, 1), end=date(2026, 7, 31)),
        notifier=notifier,
        calendar=calendar,
    )
    assert summary.expired_suppressed == 1
    assert notifier.campaign_calls == []
    assert calendar.calls == []
