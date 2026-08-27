from datetime import date

from regional_cashless_monitor.providers.common import (
    extract_date_range,
    has_regional_benefit,
    is_store_or_facility_offer,
)
from regional_cashless_monitor.targets import match_target


def test_named_cities_and_aliases() -> None:
    assert match_target("岩手県奥州市で最大20％還元").label == "奥州市（水沢）"
    assert match_target("登米市の対象店舗（佐沼を含む）").label == "登米市（佐沼）"
    assert match_target("仙台市青葉区のお店").label == "仙台市"
    assert match_target("仙台で最大20％還元").label == "仙台市"


def test_prefecture_wide_campaign_matches() -> None:
    assert match_target("岩手県 第3弾").label == "岩手県"
    assert match_target("神奈川県内の対象店舗で最大20％還元").label == "神奈川県"
    assert match_target("千葉県で最大10％還元").label == "千葉県"


def test_unlisted_city_does_not_become_prefecture_wide() -> None:
    assert match_target("岩手県 遠野市の対象店舗で最大20％還元") is None
    assert match_target("東京都杉並区で最大20％還元") is None
    assert match_target("埼玉県 朝霞市 第2弾") is None


def test_store_or_facility_location_is_not_a_regional_target() -> None:
    assert match_target(
        "au PAY、千葉県 船橋FACEの対象店舗で使える最大30％割引クーポン"
    ) is None
    assert match_target("イオンモール盛岡南の対象店舗で最大20％還元") is None
    assert match_target("仙台PARCOでポイント還元") is None


def test_store_or_facility_offer_wording_is_blocked() -> None:
    assert is_store_or_facility_offer(
        "船橋FACEの対象店舗で使える最大30％割引クーポンをプレゼント"
    )
    assert is_store_or_facility_offer("一関店限定で10％還元")
    assert not is_store_or_facility_offer(
        "一関市の対象店舗で楽天ペイを使うと最大20％還元"
    )


def test_date_range_with_omitted_end_year() -> None:
    start, end, _ = extract_date_range("開催予定 2026/10/1 〜 11/30")
    assert start == date(2026, 10, 1)
    assert end == date(2026, 11, 30)


def test_date_range_crosses_new_year() -> None:
    start, end, _ = extract_date_range("2026/12/15～1/31")
    assert start == date(2026, 12, 15)
    assert end == date(2027, 1, 31)


def test_japanese_full_dates() -> None:
    start, end, _ = extract_date_range(
        "キャンペーン期間 2026年8月7日（金）0:00～2026年8月30日（日）23:59"
    )
    assert start == date(2026, 8, 7)
    assert end == date(2026, 8, 30)


def test_unrelated_dates_do_not_become_a_fake_range() -> None:
    start, end, _ = extract_date_range(
        "2026年8月17日開始。関連記事は2026年7月7日に公開しました。"
    )
    assert start == date(2026, 8, 17)
    assert end is None


def test_japanese_kara_range() -> None:
    start, end, _ = extract_date_range("2026年10月1日から10月31日まで")
    assert start == date(2026, 10, 1)
    assert end == date(2026, 10, 31)


def test_related_voucher_text_does_not_hide_a_point_campaign() -> None:
    assert has_regional_benefit(
        "岩手県で最大20％還元",
        "関連記事: 一関市プレミアム商品券",
    )
    assert not has_regional_benefit("一関市プレミアム商品券を販売します")
