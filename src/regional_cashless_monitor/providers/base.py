"""決済サービス別Providerの共通処理。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from regional_cashless_monitor.models import Campaign, FetchDiagnostic
from regional_cashless_monitor.providers.common import OfficialPageClient


class CampaignProvider(ABC):
    provider: str
    provider_label: str
    list_urls: tuple[str, ...]

    def __init__(self, *, contact: str | None = None, client: OfficialPageClient | None = None):
        self.client = client or OfficialPageClient(contact=contact)

    @abstractmethod
    def fetch_campaigns(self, *, today: date | None = None) -> tuple[list[Campaign], list[FetchDiagnostic]]:
        raise NotImplementedError
