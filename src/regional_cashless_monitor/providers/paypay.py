"""PayPay「あなたのまちを応援プロジェクト」の解析。"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlsplit

from regional_cashless_monitor.models import Campaign, FetchDiagnostic, TargetMatch
from regional_cashless_monitor.providers.base import CampaignProvider
from regional_cashless_monitor.providers.common import (
    Tag,
    canonical_url,
    element_text,
    extract_best_date_range,
    extract_date_range,
    extract_reward,
    soup_from_html,
    title_and_description,
)
from regional_cashless_monitor.targets import match_target, normalize_text

LIST_URL = "https://paypay.ne.jp/event/support-local/"
# 詳細ページは /event/{campaign-slug}/。過去には support-local 配下の
# URLもあったため、両方を受け入れる。
DETAIL_PATH_RE = re.compile(r"^/event/(?!support-local/?$)(?:support-local/)?[^/]+/?$")


class PayPayProvider(CampaignProvider):
    provider = "paypay"
    provider_label = "PayPay"
    list_urls = (LIST_URL,)

    @staticmethod
    def _listing_items(raw_html: str) -> list[tuple[str, str, str, TargetMatch]]:
        soup = soup_from_html(raw_html)
        category = ""
        items: list[tuple[str, str, str, TargetMatch]] = []
        seen: set[str] = set()

        # 見出しとカードを文書順に読む。県見出しは対象判定に混ぜない。
        # そうしないと「岩手県 > 遠野市」を県全域と誤通知する。
        for element in soup.find_all(["h3", "h4", "h5", "a"]):
            if element.name in {"h3", "h4", "h5"}:
                heading = element_text(element)
                if "ポイント還元キャンペーン" in heading:
                    category = "point"
                elif element.name in {"h3", "h4"} or "プレミアム" in heading:
                    # 地域が変わっても、次の種別見出しまで前カテゴリを引きずらない。
                    category = "other"
                continue

            if category != "point" or not isinstance(element, Tag):
                continue
            href = str(element.get("href") or "")
            url = canonical_url(LIST_URL, href)
            if urlsplit(url).netloc != "paypay.ne.jp" or not DETAIL_PATH_RE.match(urlsplit(url).path):
                continue
            if url in seen:
                continue

            title = element_text(element)
            target = match_target(title)
            if not target:
                continue

            context = element_text(element.parent if isinstance(element.parent, Tag) else element)
            # 日付が親要素に無い場合は、カードの外枠まで少しずつ広げる。
            ancestor = element.parent
            for _ in range(4):
                if extract_date_range(context)[0] or not isinstance(ancestor, Tag):
                    break
                ancestor = ancestor.parent
                if isinstance(ancestor, Tag):
                    context = element_text(ancestor)
            items.append((url, title, context, target))
            seen.add(url)
        return items

    def fetch_campaigns(self, *, today: date | None = None):
        raw_html = self.client.get_text(LIST_URL)
        if "各自治体のキャンペーン" not in normalize_text(raw_html):
            raise RuntimeError("PayPay一覧の目印『各自治体のキャンペーン』が見つかりません")

        items = self._listing_items(raw_html)
        campaigns: list[Campaign] = []
        for url, listing_title, listing_context, target in items:
            start, end, period = extract_date_range(listing_context)
            reward = extract_reward(listing_context)
            title = listing_title
            description = ""

            # 一覧だけで開始日を取得できなかった時だけ詳細ページを読む。
            if not start:
                detail_soup = soup_from_html(self.client.get_text(url))
                detail_title, description = title_and_description(detail_soup)
                title = detail_title or title
                start, end, period = extract_best_date_range(
                    detail_soup, listing_context, title, description
                )
                reward = reward or extract_reward(title, description, element_text(detail_soup.body)[:6000])
            if not start:
                continue

            status_match = re.search(r"開催(?:予定|中)|終了", listing_context)
            campaigns.append(
                Campaign(
                    provider=self.provider,
                    provider_label=self.provider_label,
                    title=title,
                    url=url,
                    source_url=LIST_URL,
                    target=target,
                    start_date=start,
                    end_date=end,
                    reward_text=reward,
                    period_text=period,
                    status_text=status_match.group(0) if status_match else None,
                )
            )

        diagnostic = FetchDiagnostic(
            provider=self.provider,
            url=LIST_URL,
            ok=True,
            discovered_links=len(items),
            parsed_campaigns=len(campaigns),
            detail="公式一覧を解析しました",
        )
        return campaigns, [diagnostic]
