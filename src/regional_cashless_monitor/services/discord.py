"""Discord Webhook通知。"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from regional_cashless_monitor.models import Campaign

JST = ZoneInfo("Asia/Tokyo")


def _period(campaign: Campaign) -> str:
    start = campaign.start_date.strftime("%Y/%m/%d")
    end = campaign.end_date.strftime("%Y/%m/%d") if campaign.end_date else "終了日未定"
    return f"{start} ～ {end}"


class DiscordNotifier:
    def __init__(self, webhook_url: str | None, timeout_seconds: int = 20):
        self.webhook_url = webhook_url
        self.timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    def _post(self, payload: dict) -> str | None:
        if not self.webhook_url:
            raise RuntimeError("DISCORD_WEBHOOK_URLが未設定です")
        separator = "&" if "?" in self.webhook_url else "?"
        url = f"{self.webhook_url}{separator}{urllib.parse.urlencode({'wait': 'true'})}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "regional-cashless-monitor/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            content = response.read()
        if content:
            return str(json.loads(content.decode("utf-8")).get("id") or "") or None
        return None

    def send_campaign(
        self,
        campaign: Campaign,
        *,
        detected_at: datetime,
        is_update: bool,
        changed_fields: list[str] | None = None,
    ) -> str | None:
        title = "🔄 地域還元キャンペーンが更新" if is_update else "💰 地域還元キャンペーンを検知"
        colour = 0x3498DB if is_update else 0x2ECC71
        fields = [
            {"name": "決済", "value": campaign.provider_label, "inline": True},
            {"name": "対象地域", "value": campaign.target.label, "inline": True},
            {"name": "実施期間", "value": _period(campaign), "inline": False},
            {
                "name": "還元内容",
                "value": campaign.reward_text or "公式ページで要確認",
                "inline": True,
            },
            {
                "name": "検知日時",
                "value": detected_at.astimezone(JST).strftime("%Y/%m/%d %H:%M:%S"),
                "inline": True,
            },
        ]
        if is_update and changed_fields:
            fields.append(
                {"name": "変わった項目", "value": "、".join(changed_fields), "inline": False}
            )
        fields.extend(
            [
                {"name": "公式ページ", "value": f"[詳細を開く]({campaign.url})", "inline": False},
                {"name": "重複防止ID", "value": f"`{campaign.campaign_id[:12]}`", "inline": True},
            ]
        )
        return self._post(
            {
                "username": "地域キャッシュレス還元監視",
                "embeds": [
                    {
                        "title": title,
                        "description": campaign.title[:1000],
                        "color": colour,
                        "fields": fields,
                        "footer": {"text": "4社の公式キャンペーンページを1日2回監視"},
                    }
                ],
            }
        )

    def send_health_alert(self, provider: str, source: str, failures: int, detail: str):
        return self._post(
            {
                "username": "地域キャッシュレス還元監視",
                "embeds": [
                    {
                        "title": "⚠️ 地域還元監視が連続失敗",
                        "description": "キャンペーン情報ではなく、監視システム側の異常です。",
                        "color": 0xE74C3C,
                        "fields": [
                            {"name": "決済", "value": provider, "inline": True},
                            {"name": "連続失敗", "value": f"{failures}回", "inline": True},
                            {"name": "監視元", "value": source, "inline": False},
                            {"name": "原因", "value": detail[:1000], "inline": False},
                        ],
                    }
                ],
            }
        )

    def send_recovery(self, provider: str, source: str):
        return self._post(
            {
                "username": "地域キャッシュレス還元監視",
                "embeds": [
                    {
                        "title": "✅ 地域還元監視が復旧",
                        "description": f"{provider}\n{source}",
                        "color": 0x3498DB,
                    }
                ],
            }
        )
