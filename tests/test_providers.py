from datetime import date

from regional_cashless_monitor.providers.au_pay import AuPayProvider, LIST_URLS
from regional_cashless_monitor.providers.dpay import DPayProvider, LIST_URL as DPAY_LIST
from regional_cashless_monitor.providers.paypay import PayPayProvider
from regional_cashless_monitor.providers.rakuten_pay import (
    DATA_URL as RAKUTEN_DATA,
    LIST_URL as RAKUTEN_LIST,
    RakutenPayProvider,
)


class FakeClient:
    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.requested: list[str] = []

    def get_text(self, url: str) -> str:
        self.requested.append(url)
        return self.pages[url]


def test_paypay_only_reads_point_campaign_and_exact_scope() -> None:
    raw_html = """
    <html><body>
      <h2>各自治体のキャンペーン</h2>
      <h3>東北地方</h3><h4>岩手県</h4>
      <h5>ポイント還元キャンペーン</h5>
      <div><a href="/event/iwate-pref-20260901/">岩手県 第3弾</a>
        開催予定 2026/9/1 〜 9/30</div>
      <div><a href="/event/support-local/tono/">遠野市 第2弾</a>
        開催予定 2026/10/1 〜 11/30</div>
      <h5>プレミアム商品券（住民限定）</h5>
      <div><a href="/event/support-local/ichinoseki-voucher/">一関市</a>
        開催予定 2026/10/1 〜 12/31</div>
    </body></html>
    """
    provider = PayPayProvider(client=FakeClient({}))
    items = provider._listing_items(raw_html)
    assert [(title, target.label) for _, title, _, target in items] == [
        ("岩手県 第3弾", "岩手県")
    ]


def test_rakuten_detail_is_parsed() -> None:
    detail_url = "https://common-service.payment.rakuten.co.jp/campaigns/1001-ichinoseki/"
    pages = {
        RAKUTEN_LIST: "<html><body><h1>キャンペーン一覧</h1></body></html>",
        RAKUTEN_DATA: (
            '{"campaigns":[{"title":"一関市で最大20％還元",'
            f'"url":"{detail_url}"}},{{"title":"非公開",'
            '"showForGuest":false,"url":"https://common-service.payment.rakuten.co.jp/campaigns/hidden/"}]}'
        ),
        detail_url: """
          <html><head>
            <meta name="description" content="岩手県一関市の対象店舗で楽天ペイを使うと最大20％還元。2026年10月1日から10月31日まで。">
          </head><body>
            <h1>一関市で最大20％還元！</h1>
            <h2>キャンペーン期間</h2><p>2026年10月1日～2026年10月31日</p>
          </body></html>
        """,
    }
    provider = RakutenPayProvider(client=FakeClient(pages))
    campaigns, diagnostics = provider.fetch_campaigns(today=date(2026, 8, 24))
    assert len(campaigns) == 1
    assert campaigns[0].target.label == "一関市"
    assert campaigns[0].start_date == date(2026, 10, 1)
    assert campaigns[0].end_date == date(2026, 10, 31)
    assert campaigns[0].reward_text == "最大20％還元"
    assert diagnostics[0].discovered_links == 1


def test_dpay_detail_uses_oshu_for_mizusawa_scope() -> None:
    detail_url = (
        "https://service.smt.docomo.ne.jp/keitai_payment/campaign/"
        "dpay_ouen/oshu_01/"
    )
    pages = {
        DPAY_LIST: f"""
          <html><body><h1>街のお店を応援</h1>
          <a href="{detail_url}">詳しく見る</a></body></html>
        """,
        detail_url: """
          <html><head><meta name="description" content="奥州市の対象店舗でd払いのお支払い金額の20％分のポイントを進呈します。"></head>
          <body><h1>奥州市キャッシュレス決済ポイント還元キャンペーン</h1>
          <h2>キャンペーン期間</h2><p>2026.9.1～2026.9.30</p></body></html>
        """,
    }
    campaigns, _ = DPayProvider(client=FakeClient(pages)).fetch_campaigns()
    assert len(campaigns) == 1
    assert campaigns[0].target.label == "奥州市（水沢）"
    assert campaigns[0].start_date == date(2026, 9, 1)


def test_au_pay_reads_search_pages_and_ignores_unlisted_city() -> None:
    wanted = "https://media.aupay.wallet.auone.jp/articles/6001/"
    ignored = "https://media.aupay.wallet.auone.jp/articles/6002/"
    stale = "https://media.aupay.wallet.auone.jp/articles/5001/"
    pages = {}
    for index, list_url in enumerate(LIST_URLS):
        pages[list_url] = f"""
          <html><body>
            <div><a href="{wanted}">【自治体キャンペーン】宮城県 仙台市で最大20％還元</a></div>
            <div><a href="{ignored}">【自治体キャンペーン】岩手県 遠野市で最大20％還元</a></div>
            <div><a href="{stale}">【自治体キャンペーン】千葉県で最大10％還元（2025年8月1日～）</a></div>
            <div><a href="/articles/{7000 + index}/">一般キャンペーン</a></div>
          </body></html>
        """
    pages[wanted] = """
      <html><head><meta name="description" content="宮城県仙台市にて2026年10月1日から10月31日の間、au PAY残高に最大20％還元します。"></head>
      <body><h1>【自治体キャンペーン】宮城県 仙台市の対象店舗で最大20％還元</h1>
      <h2>実施期間</h2><p>2026年10月1日～2026年10月31日</p></body></html>
    """
    pages[stale] = """
      <html><head><meta name="description" content="千葉県で2025年8月1日から8月31日まで最大10％還元します。"></head>
      <body><h1>【自治体キャンペーン】千葉県で最大10％還元（2025年8月1日～）</h1></body></html>
    """
    # 対象外カードは一覧文だけで判定できるため、その詳細ページは用意しない。
    for index in range(3):
        pages[f"https://media.aupay.wallet.auone.jp/articles/{7000 + index}/"] = """
          <html><body><h1>一般キャンペーン</h1><p>全国のお店でクーポン</p></body></html>
        """

    campaigns, _ = AuPayProvider(client=FakeClient(pages)).fetch_campaigns(
        today=date(2026, 8, 24)
    )
    assert len(campaigns) == 1
    assert campaigns[0].target.label == "仙台市"
    assert campaigns[0].start_date == date(2026, 10, 1)
