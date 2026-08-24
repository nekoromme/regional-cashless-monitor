"""楽天ペイ公式キャンペーン一覧の解析。"""

from __future__ import annotations

import re
from datetime import date

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

LIST_URL = "https://pay.rakuten.co.jp/campaign/"
DETAIL_PATH_RE = re.compile(r"^/campaign/20\d{2}/[^/]+/?$")


class RakutenPayProvider(CampaignProvider):
    provider = "rakuten_pay"
    provider_label = "楽天ペイ"
    list_urls = (LIST_URL,)

    def fetch_campaigns(self, *, today: date | None = None):
        raw_html = self.client.get_text(LIST_URL)
        links = discover_links(
            raw_html,
            base_url=LIST_URL,
            allowed_host="pay.rakuten.co.jp",
            path_pattern=DETAIL_PATH_RE,
            limit=100,
        )
        if not links:
            raise RuntimeError("楽天ペイ一覧からキャンペーンURLを1件も取得できません")

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
