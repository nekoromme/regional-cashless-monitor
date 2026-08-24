"""監視内で受け渡すデータ型。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class TargetMatch:
    """監視対象として一致した自治体。"""

    key: str
    label: str
    kind: str


@dataclass(frozen=True, slots=True)
class Campaign:
    """公式ページから取り出した1件の地域キャンペーン。"""

    provider: str
    provider_label: str
    title: str
    url: str
    source_url: str
    target: TargetMatch
    start_date: date
    end_date: date | None = None
    reward_text: str | None = None
    period_text: str | None = None
    status_text: str | None = None

    @property
    def campaign_id(self) -> str:
        """URLが同じ案件は同一とみなす、重複防止用ID。"""

        raw = f"{self.provider}|{self.url}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @property
    def fingerprint(self) -> str:
        """日付や還元率の変更を検知するための指紋。"""

        payload = {
            "title": self.title,
            "target": self.target.key,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "reward_text": self.reward_text,
            "status_text": self.status_text,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def as_state_record(self, now: datetime) -> dict:
        data = asdict(self)
        data["start_date"] = self.start_date.isoformat()
        data["end_date"] = self.end_date.isoformat() if self.end_date else None
        data["fingerprint"] = self.fingerprint
        data["first_seen_at"] = now.isoformat()
        data["last_seen_at"] = now.isoformat()
        data["notified"] = False
        data["calendar_event_id"] = None
        return data


@dataclass(frozen=True, slots=True)
class FetchDiagnostic:
    """1つの公式一覧ページを正常に読めたか。"""

    provider: str
    url: str
    ok: bool
    discovered_links: int
    parsed_campaigns: int
    detail: str
