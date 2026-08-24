"""4社の取得、重複防止、通知、異常監視をまとめる。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from regional_cashless_monitor.models import Campaign, FetchDiagnostic
from regional_cashless_monitor.services.calendar import GoogleCalendarWriter
from regional_cashless_monitor.services.discord import DiscordNotifier
from regional_cashless_monitor.state import save_state

LOGGER = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")
HEALTH_ALERT_THRESHOLD = 3


@dataclass(slots=True)
class RunSummary:
    mode: str
    detected_campaigns: int = 0
    new_campaigns: int = 0
    updated_campaigns: int = 0
    expired_suppressed: int = 0
    discord_notifications: int = 0
    calendar_updates: int = 0
    provider_results: dict[str, dict] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "detected_campaigns": self.detected_campaigns,
            "new_campaigns": self.new_campaigns,
            "updated_campaigns": self.updated_campaigns,
            "expired_suppressed": self.expired_suppressed,
            "discord_notifications": self.discord_notifications,
            "calendar_updates": self.calendar_updates,
            "provider_results": self.provider_results,
            "errors": self.errors,
        }


class JsonlAuditLog:
    """後から誤通知や拾い漏れを切り分けるための1行1JSONログ。"""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **details: object) -> None:
        record = {
            "timestamp": datetime.now(JST).isoformat(),
            "event": event,
            **details,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _changed_fields(record: dict, campaign: Campaign) -> list[str]:
    mapping = (
        ("title", campaign.title, "名称"),
        ("start_date", campaign.start_date.isoformat(), "開始日"),
        ("end_date", campaign.end_date.isoformat() if campaign.end_date else None, "終了日"),
        ("reward_text", campaign.reward_text, "還元内容"),
        ("status_text", campaign.status_text, "開催状況"),
    )
    return [label for key, new_value, label in mapping if record.get(key) != new_value]


def _merge_record(record: dict, campaign: Campaign, now: datetime) -> None:
    record.update(
        {
            "provider": campaign.provider,
            "provider_label": campaign.provider_label,
            "title": campaign.title,
            "url": campaign.url,
            "source_url": campaign.source_url,
            "target": {
                "key": campaign.target.key,
                "label": campaign.target.label,
                "kind": campaign.target.kind,
            },
            "start_date": campaign.start_date.isoformat(),
            "end_date": campaign.end_date.isoformat() if campaign.end_date else None,
            "reward_text": campaign.reward_text,
            "period_text": campaign.period_text,
            "status_text": campaign.status_text,
            "fingerprint": campaign.fingerprint,
            "last_seen_at": now.isoformat(),
        }
    )


def _is_expired(campaign: Campaign, today: date) -> bool:
    return campaign.status_text == "終了" or (
        campaign.end_date is not None and campaign.end_date < today
    )


def _update_health(
    *,
    state: dict,
    diagnostic: FetchDiagnostic,
    notifier: DiscordNotifier,
    audit: JsonlAuditLog,
    now: datetime,
    allow_notifications: bool,
) -> None:
    key = f"{diagnostic.provider}|{diagnostic.url}"
    health = state["source_health"].setdefault(
        key,
        {
            "consecutive_failures": 0,
            "alert_sent": False,
            "last_error": None,
            "last_success_at": None,
        },
    )
    previous_failures = int(health.get("consecutive_failures", 0))
    alert_sent = bool(health.get("alert_sent", False))
    if diagnostic.ok:
        if (
            previous_failures >= HEALTH_ALERT_THRESHOLD
            and alert_sent
            and allow_notifications
            and notifier.enabled
        ):
            notifier.send_recovery(diagnostic.provider, diagnostic.url)
        health.update(
            {
                "consecutive_failures": 0,
                "alert_sent": False,
                "last_error": None,
                "last_success_at": now.isoformat(),
            }
        )
        audit.write(
            "source_ok",
            provider=diagnostic.provider,
            url=diagnostic.url,
            links=diagnostic.discovered_links,
            campaigns=diagnostic.parsed_campaigns,
        )
        return

    failures = previous_failures + 1
    health.update(
        {
            "consecutive_failures": failures,
            "last_error": diagnostic.detail,
            "last_failure_at": now.isoformat(),
        }
    )
    if (
        failures >= HEALTH_ALERT_THRESHOLD
        and not alert_sent
        and allow_notifications
        and notifier.enabled
    ):
        notifier.send_health_alert(
            diagnostic.provider, diagnostic.url, failures, diagnostic.detail
        )
        health["alert_sent"] = True
    audit.write(
        "source_error",
        provider=diagnostic.provider,
        url=diagnostic.url,
        failures=failures,
        detail=diagnostic.detail,
    )


def run_monitor(
    *,
    mode: str,
    state: dict,
    state_path: Path,
    providers: list,
    notifier: DiscordNotifier,
    calendar: GoogleCalendarWriter,
    audit: JsonlAuditLog,
    now: datetime | None = None,
) -> RunSummary:
    if mode not in {"auto", "baseline", "run", "dry-run"}:
        raise ValueError(f"未対応のmodeです: {mode}")
    now = now or datetime.now(JST)
    today = now.astimezone(JST).date()
    summary = RunSummary(mode=mode)

    effective_mode = mode
    if mode == "auto" and not state.get("armed"):
        effective_mode = "baseline"
        summary.mode = "baseline(auto)"
    elif mode == "auto":
        effective_mode = "run"
    if effective_mode == "run" and not state.get("armed"):
        raise RuntimeError("状態が未初期化です。先にautoまたはbaselineを1回実行してください")

    campaigns: list[Campaign] = []
    diagnostics: list[FetchDiagnostic] = []
    for provider in providers:
        try:
            found, provider_diagnostics = provider.fetch_campaigns(today=today)
            # 同じURLが一覧の複数ページに出ても、1回だけ処理する。
            unique = {campaign.campaign_id: campaign for campaign in found}
            found = list(unique.values())
            campaigns.extend(found)
            diagnostics.extend(provider_diagnostics)
            summary.provider_results[provider.provider] = {
                "status": "ok",
                "campaigns": len(found),
            }
            audit.write(
                "provider_complete",
                provider=provider.provider,
                campaigns=len(found),
                titles=[campaign.title for campaign in found],
            )
        except Exception as exc:
            detail = repr(exc)
            summary.errors.append(f"{provider.provider}: {detail}")
            summary.provider_results[provider.provider] = {
                "status": "error",
                "error": detail,
            }
            diagnostics.append(
                FetchDiagnostic(
                    provider=provider.provider,
                    url=provider.list_urls[0],
                    ok=False,
                    discovered_links=0,
                    parsed_campaigns=0,
                    detail=detail,
                )
            )
            audit.write("provider_failed", provider=provider.provider, error=detail)

    summary.detected_campaigns = len(campaigns)

    if mode == "dry-run":
        for diagnostic in diagnostics:
            audit.write(
                "dry_run_source",
                provider=diagnostic.provider,
                url=diagnostic.url,
                ok=diagnostic.ok,
                detail=diagnostic.detail,
            )
        for campaign in campaigns:
            audit.write(
                "dry_run_campaign",
                provider=campaign.provider,
                target=campaign.target.label,
                title=campaign.title,
                start_date=campaign.start_date.isoformat(),
                end_date=campaign.end_date.isoformat() if campaign.end_date else None,
                url=campaign.url,
            )
        return summary

    allow_notifications = effective_mode == "run" and bool(state.get("armed"))
    for diagnostic in diagnostics:
        _update_health(
            state=state,
            diagnostic=diagnostic,
            notifier=notifier,
            audit=audit,
            now=now,
            allow_notifications=allow_notifications,
        )
    # この後のDiscordやCalendarが失敗しても、取得失敗回数は失わない。
    save_state(state_path, state)

    if effective_mode == "baseline":
        # 4社の一部しか読めない状態で初期化すると、復旧した社の既存案件を
        # 新着として通知してしまう。全社成功するまでarmedにしない。
        if summary.errors:
            audit.write("baseline_aborted", errors=summary.errors)
            return summary
        # baselineは取得できた現在の一覧を正として作り直す。解析修正後に
        # 過去の誤検出が状態ファイルへ残り続けるのを防ぐ。
        state["campaigns"] = {}
        for campaign in campaigns:
            record = state["campaigns"].setdefault(
                campaign.campaign_id, campaign.as_state_record(now)
            )
            _merge_record(record, campaign, now)
            record["notified"] = True
            record["last_notified_fingerprint"] = campaign.fingerprint
            record["calendar_fingerprint"] = campaign.fingerprint
        state["armed"] = True
        state["baseline_at"] = now.isoformat()
        save_state(state_path, state)
        audit.write("baseline_complete", campaigns=len(campaigns))
        return summary

    for campaign in campaigns:
        record = state["campaigns"].get(campaign.campaign_id)
        is_new = record is None
        changed_fields = [] if is_new else _changed_fields(record, campaign)
        if is_new:
            summary.new_campaigns += 1
            record = campaign.as_state_record(now)
            state["campaigns"][campaign.campaign_id] = record
        else:
            _merge_record(record, campaign, now)

        if _is_expired(campaign, today):
            summary.expired_suppressed += 1
            record["notified"] = True
            record["last_notified_fingerprint"] = campaign.fingerprint
            record["calendar_fingerprint"] = campaign.fingerprint
            audit.write(
                "expired_suppressed",
                campaign_id=campaign.campaign_id,
                title=campaign.title,
            )
            continue

        needs_notification = record.get("last_notified_fingerprint") != campaign.fingerprint
        needs_calendar = record.get("calendar_fingerprint") != campaign.fingerprint
        if needs_notification and notifier.enabled:
            notifier.send_campaign(
                campaign,
                detected_at=now,
                is_update=not is_new and bool(record.get("notified")),
                changed_fields=changed_fields,
            )
            record["notified"] = True
            record["last_notified_fingerprint"] = campaign.fingerprint
            summary.discord_notifications += 1
            if not is_new:
                summary.updated_campaigns += 1
            audit.write(
                "discord_notified",
                campaign_id=campaign.campaign_id,
                is_update=not is_new,
                changed_fields=changed_fields,
            )
            # Calendarだけ失敗した時にDiscordを重ねて送らないよう、ここで確定保存。
            save_state(state_path, state)
        elif needs_notification:
            # Secretをまだ登録していなくても監視と状態保存は続ける。
            # Webhook追加後の実行で、未通知の案件だけを改めて送る。
            audit.write(
                "discord_deferred",
                campaign_id=campaign.campaign_id,
                reason="DISCORD_WEBHOOK_URL未設定",
            )

        if needs_calendar and calendar.enabled:
            event_id = calendar.upsert_campaign(campaign)
            record["calendar_event_id"] = event_id
            record["calendar_fingerprint"] = campaign.fingerprint
            summary.calendar_updates += 1
            audit.write(
                "calendar_updated",
                campaign_id=campaign.campaign_id,
                event_id=event_id,
                date=campaign.start_date.isoformat(),
            )
            save_state(state_path, state)
        elif needs_calendar:
            # Googleサービスアカウントを使わず、外部のカレンダー同期から
            # state/state.jsonを読む構成でも監視本体を失敗させない。
            audit.write(
                "calendar_deferred",
                campaign_id=campaign.campaign_id,
                reason="Google Calendar直接連携未設定",
            )

    save_state(state_path, state)
    return summary
