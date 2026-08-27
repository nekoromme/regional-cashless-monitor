"""d払い「街のお店を応援」公式一覧の解析。"""

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
    is_store_or_facility_offer,
    soup_from_html,
    title_and_description,
)
from regional_cashless_monitor.targets import match_target

LIST_URL = "https://service.smt.docomo.ne.jp/keitai_payment/campaign/dpay_ouen/"
DETAIL_PATH_RE = re.compile(r"^/keitai_payment/campaign/dpay_ouen/(?!archive|index)[^/]+(?:/index\.html|/)?$")


class DPayProvider(CampaignProvider):
    provider = "dpay"
    provider_label = "d払い"
    list_urls = (LIST_URL,)

    def fetch_campaigns(self, *, today: date | None = None):
        raw_html = self.client.get_text(LIST_URL)
        if "街のお店を応援" not in raw_html:
            raise RuntimeError("d払い一覧の目印『街のお店を応援』が見つかりません")
        links = discover_links(
            raw_html,
            base_url=LIST_URL,
            allowed_host="service.smt.docomo.ne.jp",
            path_pattern=DETAIL_PATH_RE,
            limit=100,
        )
        if not links:
            raise RuntimeError("d払い一覧からキャンペーンURLを1件も取得できません")

        campaigns: list[Campaign] = []
        for url, listing_context in links:
            listing_target = match_target(listing_context)
            if (
                listing_context
                and not listing_target
                and len(listing_context) >= 20
                and ("キャンペーン" in listing_context or has_regional_benefit(listing_context))
            ):
                continue
            detail_soup = soup_from_html(self.client.get_text(url))
            title, description = title_and_description(detail_soup)
            leading_body = element_text(detail_soup.body)[:10000]
            target = listing_target or match_target(title, description)
            if (
                not target
                or is_store_or_facility_offer(title, description)
                or not has_regional_benefit(title, description)
            ):
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
                    status_text="終了" if "このキャンペーンは終了" in leading_body[:1500] else None,
                )
            )

        diagnostic = FetchDiagnostic(
            provider=self.provider,
            url=LIST_URL,
            ok=True,
            discovered_links=len(links),
            parsed_campaigns=len(campaigns),
            detail="街のお店を応援一覧と対象詳細を解析しました",
        )
        return campaigns, [diagnostic]
