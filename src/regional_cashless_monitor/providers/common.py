"""4社に共通するHTTP取得、URL整理、日付・還元率抽出。"""

from __future__ import annotations

import html
import logging
import re
import ssl
import time
import urllib.error
import urllib.request
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from regional_cashless_monitor.targets import normalize_text

LOGGER = logging.getLogger(__name__)

FULL_DATE_RE = re.compile(
    r"(?P<year>20\d{2})\s*[年./-]\s*(?P<month>\d{1,2})\s*[月./-]\s*(?P<day>\d{1,2})\s*日?"
)
SHORT_DATE_RE = re.compile(
    r"(?<!\d)(?P<month>\d{1,2})\s*[月./-]\s*(?P<day>\d{1,2})\s*日?"
)
RANGE_MARK_RE = re.compile(r"[~〜～－―ー]\s*")
FROM_MARK_RE = re.compile(r"(?:から|より)\s*")
REWARD_PATTERNS = (
    re.compile(r"最大\s*\d+(?:\.\d+)?\s*[%％]\s*(?:分)?(?:還元|戻)") ,
    re.compile(r"\d+(?:\.\d+)?\s*[%％]\s*(?:分)?(?:還元|戻)") ,
    re.compile(r"最大\s*[\d,]+\s*(?:円相当|ポイント|Pontaポイント)") ,
)

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


class HtmlNode:
    """監視に必要な範囲だけを持つ、軽量なHTMLノード。"""

    def __init__(self, name: str, attrs: dict[str, str] | None = None, parent=None):
        self.name = name.lower()
        self.attrs = attrs or {}
        self.parent: HtmlNode | None = parent
        self.children: list[HtmlNode | str] = []

    def get(self, key: str, default=None):
        return self.attrs.get(key, default)

    def __getitem__(self, key: str):
        return self.attrs[key]

    def get_text(self, separator: str = " ", strip: bool = True) -> str:
        parts: list[str] = []

        def visit(node: HtmlNode):
            for child in node.children:
                if isinstance(child, str):
                    parts.append(child)
                else:
                    visit(child)

        visit(self)
        if strip:
            parts = [part.strip() for part in parts if part.strip()]
        return separator.join(parts)

    def _walk(self):
        for child in self.children:
            if isinstance(child, HtmlNode):
                yield child
                yield from child._walk()

    def find_all(self, names=None, **attrs):
        if isinstance(names, str):
            allowed_names = {names.lower()}
        elif names:
            allowed_names = {str(name).lower() for name in names}
        else:
            allowed_names = None
        results = []
        for node in self._walk():
            if allowed_names is not None and node.name not in allowed_names:
                continue
            matched = True
            for key, expected in attrs.items():
                actual = node.attrs.get(key)
                if expected is True and actual is None:
                    matched = False
                elif expected is not True and actual != expected:
                    matched = False
            if matched:
                results.append(node)
        return results

    def find(self, tag_name: str, **attrs):
        results = self.find_all(tag_name, **attrs)
        return results[0] if results else None

    def find_next_sibling(self):
        if not self.parent:
            return None
        passed_self = False
        for child in self.parent.children:
            if child is self:
                passed_self = True
                continue
            if passed_self and isinstance(child, HtmlNode):
                return child
        return None

    @property
    def body(self):
        return self.find("body")


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("document")
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = HtmlNode(tag, {key: value or "" for key, value in attrs}, self.current)
        self.current.children.append(node)
        if tag.lower() not in VOID_ELEMENTS:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        node = HtmlNode(tag, {key: value or "" for key, value in attrs}, self.current)
        self.current.children.append(node)

    def handle_endtag(self, tag):
        target = tag.lower()
        node = self.current
        while node.parent is not None:
            if node.name == target:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


Tag = HtmlNode
BeautifulSoup = HtmlNode


class OfficialPageClient:
    """公式サイトへ負荷を掛けすぎない、再試行付きのHTTPクライアント。"""

    def __init__(self, *, contact: str | None = None, timeout_seconds: int = 25):
        suffix = f" contact={contact}" if contact else ""
        self.timeout_seconds = timeout_seconds
        self.headers = {
            "User-Agent": (
                "regional-cashless-monitor/1.0 "
                "(+https://github.com/nekoromme/regional-cashless-monitor; "
                f"twice-daily official-page check;{suffix})"
            ),
            "Accept-Language": "ja,en;q=0.5",
            "Accept": "text/html,application/xhtml+xml",
        }

    def get_text(self, url: str) -> str:
        def download(context: ssl.SSLContext | None = None) -> tuple[bytes, int, str]:
            request = urllib.request.Request(url, headers=self.headers, method="GET")
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
                context=context,
            ) as response:
                return (
                    response.read(),
                    int(getattr(response, "status", 200)),
                    response.headers.get_content_charset() or "utf-8",
                )

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                try:
                    content, status, charset = download()
                except urllib.error.URLError as exc:
                    # d払い公式は2026年8月時点で古いTLS再ネゴシエーションを要求する。
                    # 証明書・ホスト名検証は残し、その互換オプションだけを限定的に許可する。
                    if "UNSAFE_LEGACY_RENEGOTIATION_DISABLED" not in str(exc):
                        raise
                    context = ssl.create_default_context()
                    context.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
                    content, status, charset = download(context)
                if len(content) < 500:
                    snippet = re.sub(
                        r"\s+",
                        " ",
                        content.decode(charset, errors="replace")[:400],
                    )
                    raise RuntimeError(
                        f"本文が短すぎます: status={status}, bytes={len(content)}, "
                        f"先頭={snippet!r}"
                    )
                try:
                    return content.decode(charset)
                except (LookupError, UnicodeDecodeError):
                    return content.decode("utf-8", errors="replace")
            except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"公式ページを3回取得できません: {url}: {last_error}")


def canonical_url(base_url: str, href: str) -> str:
    absolute = urljoin(base_url, html.unescape(href).strip())
    parts = urlsplit(absolute)
    path = re.sub(r"/{2,}", "/", parts.path)
    if path and not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path += "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def soup_from_html(raw_html: str) -> BeautifulSoup:
    parser = _TreeBuilder()
    parser.feed(raw_html)
    parser.close()
    return parser.root


def element_text(element: Tag | None) -> str:
    if element is None:
        return ""
    parts = [element.get_text(" ", strip=True)]
    for image in element.find_all("img", alt=True):
        parts.append(str(image.get("alt") or ""))
    return normalize_text(" ".join(parts))


def title_and_description(soup: BeautifulSoup) -> tuple[str, str]:
    """関連記事を避け、ページ自身の見出しと概要だけを返す。"""

    candidates: list[str] = []
    title_nodes = (
        soup.find("h1"),
        soup.find("meta", property="og:title"),
        soup.find("title"),
    )
    for tag in title_nodes:
        if not tag:
            continue
        value = str(tag.get("content") or "") if tag.name == "meta" else element_text(tag)
        value = normalize_text(value)
        if value and value not in candidates:
            candidates.append(value)
    title = candidates[0] if candidates else ""

    descriptions: list[str] = []
    for tag in (
        soup.find("meta", name="description"),
        soup.find("meta", property="og:description"),
    ):
        value = normalize_text(str(tag.get("content") or "")) if tag else ""
        if value and value not in descriptions:
            descriptions.append(value)

    # au PAYなどは記事の最初の段落に自治体名と期間がまとまっている。
    for paragraph in soup.find_all("p")[:5]:
        value = element_text(paragraph)
        if 20 <= len(value) <= 1000 and value not in descriptions:
            descriptions.append(value)
            break
    return title, normalize_text(" ".join(descriptions))


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_date_range(text: str) -> tuple[date | None, date | None, str | None]:
    """日本語の期間表記から開始日と終了日を抽出する。

    `2026/10/1 ～ 11/30` のように終了年が省略される表記にも対応する。
    """

    cleaned = normalize_text(text)
    full_matches = list(FULL_DATE_RE.finditer(cleaned))
    if not full_matches:
        return None, None, None

    first = full_matches[0]
    start = _safe_date(
        int(first.group("year")), int(first.group("month")), int(first.group("day"))
    )
    if start is None:
        return None, None, None

    # 文中の無関係な「公開日」「関連記事の日付」を終了日と誤認しないよう、
    # 開始日の直後に範囲記号（～）か「から／より」がある時だけ終了日を読む。
    end: date | None = None
    end_match_end = first.end()
    tail = cleaned[first.end() :]
    marker_candidates = [
        match
        for match in (RANGE_MARK_RE.search(tail[:80]), FROM_MARK_RE.search(tail[:80]))
        if match is not None
    ]
    range_marker = min(marker_candidates, key=lambda item: item.start()) if marker_candidates else None
    if range_marker:
        after_marker = tail[range_marker.end() : range_marker.end() + 80]
        full_end = FULL_DATE_RE.search(after_marker)
        if full_end:
            end = _safe_date(
                int(full_end.group("year")),
                int(full_end.group("month")),
                int(full_end.group("day")),
            )
            end_match_end = first.end() + range_marker.end() + full_end.end()
        else:
            short = SHORT_DATE_RE.search(after_marker)
            if short:
                end_year = start.year
                end_month = int(short.group("month"))
                if end_month < start.month:
                    end_year += 1
                end = _safe_date(end_year, end_month, int(short.group("day")))
                end_match_end = first.end() + range_marker.end() + short.end()

    # 公式ページ側の本文結合が崩れても、開始日より前の終了日は採用しない。
    if end is not None and end < start:
        end = None

    period = cleaned[max(0, first.start() - 30) : min(len(cleaned), end_match_end + 30)]
    return start, end, period or None


def extract_best_date_range(soup: BeautifulSoup, *extra_texts: str):
    """期間ラベル周辺を優先し、公開日を開始日と誤認しにくくする。"""

    candidates: list[tuple[str, int]] = [
        (normalize_text(value), 20) for value in extra_texts if value
    ]

    for parent in soup.find_all(["h2", "h3", "h4", "dt", "th", "p", "div"]):
        label_text = element_text(parent)
        if not re.search(r"キャンペーン期間|実施期間|開催期間|^期間$", label_text):
            continue
        if parent:
            candidates.append(
                (element_text(parent.parent if isinstance(parent.parent, Tag) else parent), 50)
            )
            sibling = parent.find_next_sibling()
            if isinstance(sibling, Tag):
                candidates.append((element_text(sibling), 60))

    _, description = title_and_description(soup)
    if description:
        candidates.append((description, 40))
    body = element_text(soup.body)
    if body:
        candidates.append((body[:12000], 0))

    best = (None, None, None)
    best_score = -1
    for candidate, priority in candidates:
        start, end, period = extract_date_range(candidate)
        if not start:
            continue
        score = priority + (2 if end else 0)
        score += 1 if any(mark in candidate for mark in ("～", "〜", "~")) else 0
        if score > best_score:
            best = (start, end, period)
            best_score = score
    return best


def extract_reward(*texts: str) -> str | None:
    combined = normalize_text(" ".join(texts))
    for pattern in REWARD_PATTERNS:
        match = pattern.search(combined)
        if match:
            return match.group(0).replace("%", "％")
    return None


def has_regional_benefit(*texts: str) -> bool:
    # タイトル、概要、本文を別々に判定する。本文下部の関連記事に
    # 「プレミアム商品券」があっても、明確なポイント還元記事を落とさない。
    benefit_terms = (
        "還元",
        "戻って",
        "ポイント進呈",
        "ポイントがもらえる",
        "ポイント付与",
    )
    blocked_terms = ("プレミアム商品券", "自治体マイナポイント")
    for text in texts:
        candidate = normalize_text(text)
        if any(blocked in candidate for blocked in blocked_terms):
            continue
        if any(term in candidate for term in benefit_terms):
            return True
    return False


def discover_links(
    raw_html: str,
    *,
    base_url: str,
    allowed_host: str,
    path_pattern: re.Pattern[str],
    limit: int = 100,
) -> list[tuple[str, str]]:
    """通常リンクと埋め込みJSONの両方からキャンペーンURLを探す。"""

    soup = soup_from_html(raw_html)
    found: dict[str, str] = {}
    for anchor in soup.find_all("a", href=True):
        url = canonical_url(base_url, str(anchor["href"]))
        parts = urlsplit(url)
        if parts.netloc == allowed_host and path_pattern.search(parts.path):
            # au PAYの検索ページは親要素が記事一覧全体になることがある。
            # リンク自身に記事名があるなら、それだけをカード文脈として使う。
            anchor_text = element_text(anchor)
            context = anchor_text
            if len(anchor_text) < 10:
                context = element_text(
                    anchor.parent if isinstance(anchor.parent, Tag) else anchor
                )
            found.setdefault(url, context)

    # JavaScriptでカードを描くページ向け。HTML内のURL文字列も補助的に拾う。
    unescaped = html.unescape(raw_html).replace("\\/", "/")
    for match in re.finditer(r"(?:https?://[^\"'<> ]+|/[^\"'<> ]+)", unescaped):
        token = match.group(0).rstrip("\\,;)")
        url = canonical_url(base_url, token)
        parts = urlsplit(url)
        if parts.netloc == allowed_host and path_pattern.search(parts.path):
            found.setdefault(url, "")
        if len(found) >= limit:
            break
    return list(found.items())[:limit]
