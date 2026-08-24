"""Google Calendarへキャンペーン開始日だけを登録する。"""

from __future__ import annotations

import base64
import json
import logging
from datetime import timedelta

from regional_cashless_monitor.models import Campaign

LOGGER = logging.getLogger(__name__)
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


def _decode_service_account(raw_value: str) -> dict:
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        try:
            return json.loads(base64.b64decode(raw_value).decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(
                "GOOGLE_SERVICE_ACCOUNT_JSONをJSONまたはBase64として解釈できません"
            ) from exc


class GoogleCalendarWriter:
    def __init__(self, service_account_json: str | None, calendar_id: str | None):
        self.calendar_id = calendar_id
        self.service = None
        self._http_error_class = None
        if not service_account_json or not calendar_id:
            return
        # dry-runや単体テストではGoogle部品を読み込まない。設定された時だけ必要。
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError

        credentials = Credentials.from_service_account_info(
            _decode_service_account(service_account_json), scopes=[CALENDAR_SCOPE]
        )
        self.service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        self._http_error_class = HttpError

    @property
    def enabled(self) -> bool:
        return self.service is not None and bool(self.calendar_id)

    @staticmethod
    def event_id(campaign: Campaign) -> str:
        # URL由来IDなので、公式側で開始日が変わっても同じ予定を移動・更新できる。
        return f"cashless{campaign.campaign_id[:32]}"

    def upsert_campaign(self, campaign: Campaign) -> str:
        if not self.enabled:
            raise RuntimeError(
                "GOOGLE_SERVICE_ACCOUNT_JSONまたはGOOGLE_CALENDAR_IDが未設定です"
            )

        event_id = self.event_id(campaign)
        next_day = campaign.start_date + timedelta(days=1)
        end_text = campaign.end_date.strftime("%Y/%m/%d") if campaign.end_date else "未定"
        lines = [
            f"決済: {campaign.provider_label}",
            f"対象: {campaign.target.label}",
            f"キャンペーン終了日: {end_text}",
            f"還元内容: {campaign.reward_text or '公式ページで要確認'}",
            f"公式ページ: {campaign.url}",
            "※カレンダー上は開始日の1日だけ表示しています。",
        ]
        body = {
            "id": event_id,
            "summary": f"【地域還元開始】{campaign.target.label}・{campaign.provider_label}",
            "description": "\n".join(lines),
            "start": {"date": campaign.start_date.isoformat()},
            "end": {"date": next_day.isoformat()},
            "source": {"title": f"{campaign.provider_label}公式", "url": campaign.url},
        }
        try:
            self.service.events().insert(
                calendarId=self.calendar_id,
                body=body,
                sendUpdates="none",
            ).execute()
        except Exception as exc:
            if self._http_error_class is None or not isinstance(exc, self._http_error_class):
                raise
            if exc.resp.status != 409:
                raise
            self.service.events().update(
                calendarId=self.calendar_id,
                eventId=event_id,
                body=body,
                sendUpdates="none",
            ).execute()
        LOGGER.info("Google Calendarを更新: %s", event_id)
        return event_id
