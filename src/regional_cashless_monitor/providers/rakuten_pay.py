"""楽天ペイ公式キャンペーン一覧の解析。"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from urllib.parse import urlsplit

from regional_cashless_monitor.models import Campaign, FetchDiagnostic
from regional_cashless_monitor.providers.base import CampaignProvider
from regional_cashless_monitor.providers.common import (
    canonical_url,
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

LIST_URL = "https://common-service.payment.rakuten.co.jp/campaigns/"
DATA_URL = (
    "https://common-service.payment.rakuten.co.jp/ptcms/campaign-medias/"
    "common-campaign-list.json"
)
OLD_DETAIL_PATH_RE = re.compile(r"^/campaign/20\d{2}/[^/]+/?$")
NEW_DETAIL_PATH_RE = re.compile(r"^/campaigns/[^/?#]+/?$")


class RakutenPayProvider(CampaignProvider):
    provider = "rakuten_pay"
    provider_label = "楽天ペイ"
    list_urls = (LIST_URL,)

    @staticmethod
    def _links_from_api(payload: object) -> list[tuple[str, str]]:
        """公開JSONを再帰的に読み、詳細URLと同じカード内の文言を組にする。"""

        found: dict[str, str] = {}

        def walk(value: object, inherited: tuple[str, ...] = ()) -> None:
            if isinstance(value, dict):
                # 公式画面と同じく、ゲスト非表示のカードは監視対象にしない。
                if value.get("showForGuest") is False:
                    return
                local = tuple(
                    str(item)
                    for item in value.values()
                    if isinstance(item, (str, int, float))
                )
                context_parts = (inherited + local)[-30:]
                context = " ".join(context_parts)[:5000]
                for item in local:
                    if not (item.startswith(("http://", "https://", "/"))):
                        continue
                    url = canonical_url(LIST_URL, item)
                    parts = urlsplit(url)
                    is_new = (
                        parts.netloc == "common-service.payment.rakuten.co.jp"
                        and NEW_DETAIL_PATH_RE.match(parts.path)
                    )
                    is_old = (
                        parts.netloc == "pay.rakuten.co.jp"
                        and OLD_DETAIL_PATH_RE.match(parts.path)
                    )
                    if is_new or is_old:
                        found.setdefault(url, context)
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        walk(child, context_parts)
            elif isinstance(value, list):
                for child in value:
                    walk(child, inherited)

        walk(payload)
        return list(found.items())

    def fetch_campaigns(self, *, today: date | None = None):
        # 旧URLはmeta refreshだけになった。現在の公式一覧が使う公開JSONを直接読む。
        raw_html = self.client.get_text(LIST_URL)
        data_raw = self.client.get_text(DATA_URL)
        try:
            payload = json.loads(data_raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"楽天ペイ公式キャンペーンJSONを解釈できません: {exc}") from exc

        links = self._links_from_api(payload)
        # HTML直書きへ戻った場合にも対応する。
        page_new = discover_links(
            raw_html,
            base_url=LIST_URL,
            allowed_host="common-service.payment.rakuten.co.jp",
            path_pattern=NEW_DETAIL_PATH_RE,
            limit=100,
        )
        page_old = discover_links(
            raw_html,
            base_url=LIST_URL,
            allowed_host="pay.rakuten.co.jp",
            path_pattern=OLD_DETAIL_PATH_RE,
            limit=100,
        )
        known = {url for url, _ in links}
        links.extend(item for item in page_new + page_old if item[0] not in known)
        if not links:
            raise RuntimeError(
                "楽天ペイ公式JSONからキャンペーンURLを1件も取得できません。"
                f" JSON先頭={data_raw[:1000]!r}"
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
            if (
                not target
                or is_store_or_facility_offer(title, description)
                or not has_regional_benefit(title, description)
            ):
                continue
            start, end, period = extract_best_date_range(
                detail_soup, title, description, listing_context
            )
            if not start:
                continue
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
            url=DATA_URL,
            ok=True,
            discovered_links=len(links),
            parsed_campaigns=len(campaigns),
            detail="公式キャンペーン一覧と対象詳細を解析しました",
        )
        return campaigns, [diagnostic]
