"""既存SecretがDiscordとGoogle Calendarへ接続できるか、送信せず確認する。"""

from __future__ import annotations

import json
import os
import urllib.request

from regional_cashless_monitor.services.calendar import GoogleCalendarWriter


def validate_discord() -> None:
    """Webhook情報をGETするだけで検証する。Discordへ投稿はしない。"""

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL") or ""
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URLが未設定です")
    request = urllib.request.Request(
        webhook_url,
        headers={"User-Agent": "regional-cashless-monitor/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        # 例外文字列にはWebhook URLが含まれる場合があるため、型名だけを残す。
        raise RuntimeError(
            f"Discord Webhookへ接続できません: {type(exc).__name__}"
        ) from None
    if not isinstance(payload, dict) or not payload.get("id"):
        raise RuntimeError("Discord Webhookの応答形式が想定外です")
    print("Discord Webhook: 読み取り検証OK（試験投稿なし）")


def validate_calendar() -> None:
    """登録先カレンダーの参照権限を、予定を作らず確認する。"""

    writer = GoogleCalendarWriter(
        os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or None,
        os.getenv("GOOGLE_CALENDAR_ID") or None,
    )
    if not writer.enabled:
        raise RuntimeError("Google Calendar用Secretが未設定です")
    try:
        writer.service.calendars().get(calendarId=writer.calendar_id).execute()
    except Exception as exc:
        # Googleの例外にもカレンダーIDが入ることがあるため、詳細は公開ログへ出さない。
        raise RuntimeError(
            f"Google Calendarを参照できません: {type(exc).__name__}"
        ) from None
    print("Google Calendar: 読み取り検証OK（予定作成なし）")


if __name__ == "__main__":
    validate_discord()
    validate_calendar()
