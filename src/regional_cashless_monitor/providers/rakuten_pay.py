"""楽天ペイ公式キャンペーン一覧の解析。"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin

from regional_cashless_monitor.models import Campaign, FetchDiagnostic
from regional_cashless_monitor.providers.base import CampaignProvider
from regional_cashless_monitor.providers.common import (
    discover_links,
    element_text,
    extract_best_date_range,
    extract_reward,
    has_regional_benefit,
    soup_from_html,
    title_and_description,
)
from regional_cashless_monitor.targets import match_target

LIST_URL = "https://common-service.payment.rakuten.co.jp/campaigns/"
OLD_DETAIL_PATH_RE = re.compile(r"^/campaign/20\d{2}/[^/]+/?$")
NEW_DETAIL_PATH_RE = re.compile(r"^/campaigns/[^/?#]+/?$")


class RakutenPayProvider(CampaignProvider):
    provider = "rakuten_pay"
    provider_label = "楽天ペイ"
    list_urls = (LIST_URL,)

    def fetch_campaigns(self, *, today: date | None = None):
        raw_html = self.client.get_text(LIST_URL)
        links = discover_links(
            raw_html,
            base_url=LIST_URL,
            allowed_host="common-service.payment.rakuten.co.jp",
            path_pattern=NEW_DETAIL_PATH_RE,
            limit=100,
        )
        old_links = discover_links(
            raw_html,
            base_url=LIST_URL,
            allowed_host="pay.rakuten.co.jp",
            path_pattern=OLD_DETAIL_PATH_RE,
            limit=100,
        )
        known = {url for url, _ in links}
        links.extend(item for item in old_links if item[0] not in known)
        if not links:
            soup = soup_from_html(raw_html)
            scripts = [
                str(script.get("src") or "inline")
                for script in soup.find_all("script")
            ]
            endpoint_hints = []
            for match in re.finditer(
                r"(?:https?:)?//[^\"'<>\s]+|/[A-Za-z0-9_./?=&%-]*(?:api|campaign|media)[A-Za-z0-9_./?=&%-]*",
                raw_html,
                flags=re.IGNORECASE,
            ):
                value = match.group(0).rstrip("\\,;)")
                if value not in endpoint_hints:
                    endpoint_hints.append(value)
            script_hints = []
            html_data_hints = []
            for node in soup.find_all():
                for key, value in node.attrs.items():
                    if key.startswith("data-") and value:
                        html_data_hints.append(f"{node.name}.{key}={value}")
            for script_src in scripts:
                if script_src == "inline" or "media" not in script_src.lower():
                    continue
                script_url = urljoin(LIST_URL, script_src)
                try:
                    javascript = self.client.get_text(script_url)
                except Exception as exc:
                    script_hints.append(f"{script_url}: {exc!r}")
                    continue
                values = []
                for match in re.finditer(
                    r"[\"'`](https?://[^\"'`]+|/[^\"'`]{2,240})[\"'`]",
                    javascript,
                ):
                    value = match.group(1)
                    lowered = value.lower()
                    if any(word in lowered for word in ("api", "media", "content", "search", "json")):
                        if value not in values:
                            values.append(value)
                script_hints.append(f"{script_url}: {values[-80:]}")
            raise RuntimeError(
                "楽天ペイ一覧からキャンペーンURLを1件も取得できません。"
                f" script={scripts[-20:]}, hints={endpoint_hints[-40:]}, "
                f"html_data={html_data_hints[-80:]}, script_hints={script_hints[-20:]}"
            )

        campaigns: list[Campaign] = []
        for url, listing_context in links:
            listing_target = match_target(listing_context)
            # カード本文が読める時は、対象外カードの詳細取得を省いて公式サイトの負荷を減らす。
            if (
                listing_context
                and not listing_target
                and len(listing_context) >= 20
                and ("キャンペーン" in listing_context or has_regional_benefit(listing_context))
            ):
                continue

            detail_soup = soup_from_html(self.client.get_text(url))
            title, description = title_and_description(detail_soup)
            target = listing_target or match_target(title, description)
            leading_body = element_text(detail_soup.body)[:8000]
            if not target or not has_regional_benefit(title, description, leading_body):
                continue
            start, end, period = extract_best_date_range(
                detail_soup, listing_context, title, description
            )
            if not start:
                continue
            campaigns.append(
                Campaign(
                    provider=self.provider,
                    provider_label=self.provider_label,
                    title=title or listing_context,
                    url=url,
                    source_url=LIST_URL,
                    target=target,
                    start_date=start,
                    end_date=end,
                    reward_text=extract_reward(title, description, leading_body),
                    period_text=period,
                    status_text=None,
                )
            )

        diagnostic = FetchDiagnostic(
            provider=self.provider,
            url=LIST_URL,
            ok=True,
            discovered_links=len(links),
            parsed_campaigns=len(campaigns),
            detail="公式キャンペーン一覧と対象詳細を解析しました",
        )
        return campaigns, [diagnostic]
