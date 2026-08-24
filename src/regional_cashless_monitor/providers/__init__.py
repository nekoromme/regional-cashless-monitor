"""決済サービス別の公式ページ取得部品。"""

from regional_cashless_monitor.providers.au_pay import AuPayProvider
from regional_cashless_monitor.providers.dpay import DPayProvider
from regional_cashless_monitor.providers.paypay import PayPayProvider
from regional_cashless_monitor.providers.rakuten_pay import RakutenPayProvider


def default_providers(*, contact: str | None = None):
    """通常運用する4社を固定順で返す。"""

    return [
        PayPayProvider(contact=contact),
        RakutenPayProvider(contact=contact),
        DPayProvider(contact=contact),
        AuPayProvider(contact=contact),
    ]


__all__ = [
    "AuPayProvider",
    "DPayProvider",
    "PayPayProvider",
    "RakutenPayProvider",
    "default_providers",
]
