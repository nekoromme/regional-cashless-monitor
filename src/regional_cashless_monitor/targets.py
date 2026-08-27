"""監視する自治体名と表記揺れ。

県名は「県全域・都全域のキャンペーン」だけを対象にする。
たとえば「岩手県 遠野市」は岩手県全域とは扱わない。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from regional_cashless_monitor.models import TargetMatch


@dataclass(frozen=True, slots=True)
class NamedTarget:
    key: str
    label: str
    aliases: tuple[str, ...]


# 市名は長いもの・具体的なものから先に判定する。
CITY_TARGETS = (
    NamedTarget("ichinoseki", "一関市", ("一関市", "一関")),
    NamedTarget("oshu_mizusawa", "奥州市（水沢）", ("奥州市", "奥州", "水沢市", "水沢")),
    NamedTarget("kitakami", "北上市", ("北上市", "北上")),
    NamedTarget("hanamaki", "花巻市", ("花巻市", "花巻")),
    NamedTarget("morioka", "盛岡市", ("盛岡市", "盛岡")),
    NamedTarget("tome_sanuma", "登米市（佐沼）", ("登米市", "登米", "佐沼")),
    NamedTarget("kesennuma", "気仙沼市", ("気仙沼市", "気仙沼")),
    NamedTarget("osaki", "大崎市", ("大崎市", "大崎")),
    NamedTarget("ishinomaki", "石巻市", ("石巻市", "石巻")),
    NamedTarget(
        "sendai",
        "仙台市",
        (
            "仙台市",
            "仙台",
            "青葉区",
            "宮城野区",
            "若林区",
            "太白区",
            "泉区",
        ),
    ),
)

PREFECTURES = (
    "青森県",
    "岩手県",
    "宮城県",
    "秋田県",
    "山形県",
    "福島県",
    "茨城県",
    "栃木県",
    "群馬県",
    "埼玉県",
    "千葉県",
    "東京都",
    "神奈川県",
)


def normalize_text(value: str) -> str:
    """全角英数や改行をならして、表記差を小さくする。"""

    normalized = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"\s+", " ", normalized).strip()


def _is_prefecture_wide(text: str, prefecture: str) -> bool:
    """県名だけでなく、県全域だと分かる文言がある場合だけ許可する。

    県名は店舗・商業施設の所在地としても頻繁に書かれる。
    そのため「千葉県 船橋FACE」のように県名の後ろが空白というだけでは
    県キャンペーンにしない。過去の自治体キャンペーンで実際に使われた
    「県内」「県の対象店舗」「県で最大○％」「県にて20xx年」などを
    肯定材料にする。
    """

    location = text.find(prefecture)
    if location < 0:
        return False
    after = text[location + len(prefecture) :].lstrip()
    # 「岩手県 遠野市」「東京都杉並区」のような個別自治体は県全域ではない。
    if re.match(r"[^\s、,:：】)）]{1,12}[市区町村]", after):
        return False

    escaped = re.escape(prefecture)
    patterns = (
        # PayPay一覧などの短い「岩手県 第3弾」というカード名。
        rf"^{escaped}(?:\s*第\s*\d+\s*弾)?$",
        rf"{escaped}(?:内|全域)(?:の|で|にて|対象|$)",
        rf"{escaped}(?:の対象店舗|のお店|で最大|でお買い物|キャッシュレス)",
        rf"{escaped}にて\s*20\d{{2}}年",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _is_city_scope(text: str, target: NamedTarget) -> bool:
    """市名の省略形を店舗名の一部と取り違えないようにする。"""

    for alias in target.aliases:
        if alias not in text:
            continue
        # 正式な自治体名・区名は、それ自体が十分に強い地域表記。
        if alias.endswith(("市", "区")):
            return True

        escaped = re.escape(alias)
        # 「盛岡駅ビル」「仙台PARCO」「一関店」のような施設・店名は除外し、
        # 過去の自治体案件で使われる地域としてのつながりだけを許可する。
        patterns = (
            rf"^{escaped}$",
            rf"{escaped}(?:内|全域|地域|エリア)(?:の|で|にて|対象|$)",
            rf"{escaped}(?:の対象店舗|のお店|で最大|でお買い物|キャッシュレス)",
            rf"{escaped}にて\s*20\d{{2}}年",
            rf"{escaped}\s*第\s*\d+\s*弾",
        )
        if any(re.search(pattern, text) for pattern in patterns):
            return True
    return False


def match_target(*texts: str) -> TargetMatch | None:
    """見出し・概要から指定自治体を1件返す。

    公式ページの末尾には「ほかの岩手県キャンペーン」のような関連記事が
    混ざるため、呼び出し側は本文全体ではなくタイトルと冒頭説明だけを渡す。
    """

    combined = normalize_text(" ".join(text for text in texts if text))
    if not combined:
        return None

    for target in CITY_TARGETS:
        if _is_city_scope(combined, target):
            return TargetMatch(target.key, target.label, "city")

    for prefecture in PREFECTURES:
        if _is_prefecture_wide(combined, prefecture):
            key = "prefecture_" + prefecture.encode("punycode").decode("ascii")
            return TargetMatch(key, prefecture, "prefecture")

    return None
