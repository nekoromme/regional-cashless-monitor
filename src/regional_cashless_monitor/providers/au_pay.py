"""au PAY公式メディアの自治体キャンペーン記事を解析。"""

from __future__ import annotations

import re
from datetime import date, timedelta

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

SEARCH_URL = (
    "https://media.aupay.wallet.auone.jp/articles/search"
    "?q%5Btitle_cont%5D=%E8%87%AA%E6%B2%BB%E4%BD%93%E3%82%AD%E3%83%A3%E3%83%B3%E3%83%9A%E3%83%BC%E3%83%B3"
)
LIST_URLS = tuple([SEARCH_URL] + [f"{SEARCH_URL}&page={page}" for page in (2, 3)])
DETAIL_PATH_RE = re.compile(r"^/articles/\d+/?$")


class AuPayProvider(CampaignProvider):
    provider = "au_pay"
    provider_label = "au PAY"
    list_urls = LIST_URLS

    def fetch_campaigns(self, *, today: date | None = None):
        all_links: dict[str, str] = {}
        diagnostics: list[FetchDiagnostic] = []
        for list_url in LIST_URLS:
            raw_html = self.client.get_text(list_url)
            links = discover_links(
                raw_html,
                base_url=list_url,
                allowed_host="media.aupay.wallet.auone.jp",
                path_pattern=DETAIL_PATH_RE,
                limit=40,
            )
            if not links:
                raise RuntimeError(f"au PAY検索結果から記事URLを取得できません: {list_url}")
            for url, context in links:
                all_links.setdefault(url, context)
            diagnostics.append(
                FetchDiagnostic(
                    provider=self.provider,
                    url=list_url,
                    ok=True,
                    discovered_links=len(links),
                    parsed_campaigns=0,
                    detail="自治体キャンペーン検索結果を解析しました",
                )
            )

        campaigns: list[Campaign] = []
        for url, listing_context in all_links.items():
            listing_target = match_target(listing_context)
            # 検索結果カードに十分な記事名がある場合、対象外地域は詳細を読まない。
            # 「詳細はこちら」のような短いリンクだけなら、取りこぼし防止で詳細を確認する。
            if listing_context and len(listing_context) >= 20 and not listing_target:
                continue

            detail_soup = soup_from_html(self.client.get_text(url))
            title, description = title_and_description(detail_soup)
            leading_body = element_text(detail_soup.body)[:8000]
            target = listing_target or match_target(title, description)
            if not target or not has_regional_benefit(title, description, leading_body):
                continue
            # 詳細ページを最優先する。一覧ページの親要素には別記事の日付が
            # 混ざることがあるため、カード文言は最後の補助候補にだけ使う。
            start, end, period = extract_best_date_range(
                detail_soup, title, description, listing_context
            )
            if not start:
                continue
            # 検索結果には前年の記事も残る。終了済み、または終了日不明で
            # 半年以上前に始まった記事は新着監視へ混ぜない。
            reference_day = today or date.today()
            if (end and end < reference_day) or (
                end is None and start < reference_day - timedelta(days=180)
            ):
                continue
            campaigns.append(
                Campaign(
                    provider=self.provider,
                    provider_label=self.provider_label,
                    title=title or listing_context,
                    url=url,
                    source_url=SEARCH_URL,
                    target=target,
                    start_date=start,
                    end_date=end,
                    reward_text=extract_reward(title, description, leading_body),
                    period_text=period,
                    status_text=None,
                )
            )

        # 各ページ診断へ、対象として解析できた総数を入れてログで見やすくする。
        diagnostics = [
            FetchDiagnostic(
                provider=item.provider,
                url=item.url,
                ok=item.ok,
                discovered_links=item.discovered_links,
                parsed_campaigns=len(campaigns),
                detail=item.detail,
            )
            for item in diagnostics
        ]
        return campaigns, diagnostics
