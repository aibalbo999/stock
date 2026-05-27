from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import date, datetime
from hashlib import sha1
from pathlib import Path
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.models.schemas import NewsDocument, Source


class NewsSourceConfig(BaseModel):
    name: str
    url: str
    enabled: bool = True
    publisher: Optional[str] = None
    category: str = "news"
    scope: str = "universal"
    topics: list[str] = Field(default_factory=list)

    def matches_topic(self, topic: str | None) -> bool:
        if not self.enabled:
            return False
        if self.scope == "universal":
            return True
        if not topic:
            return False
        normalized_topic = topic.casefold()
        terms = [self.category, self.name, self.publisher or "", *self.topics]
        return any(term.casefold() in normalized_topic for term in terms if term)


class NewsSourceStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_settings().news_sources_path

    def load(self) -> list[NewsSourceConfig]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return [NewsSourceConfig.model_validate(item) for item in payload.get("sources", [])]

    def enabled_sources(self) -> list[NewsSourceConfig]:
        return [source for source in self.load() if source.enabled]

    def sources_for_topic(self, topic: str | None) -> list[NewsSourceConfig]:
        return [source for source in self.load() if source.matches_topic(topic)]


class NewsFetcher:
    async def fetch_url(self, url: str, publisher: str | None = None) -> NewsDocument:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url)
            response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        title = self._title(soup) or url
        text = self._article_text(soup)
        return NewsDocument(
            id=sha1(url.encode("utf-8")).hexdigest(),
            title=title,
            text=text,
            source=Source(
                title=title,
                url=url,
                publisher=publisher,
                published_at=self._published_date(soup),
                fetched_at=datetime.utcnow(),
            ),
        )

    @staticmethod
    def from_manual_text(
        title: str,
        text: str,
        publisher: str = "manual",
        published_at: date | None = None,
        url: str | None = None,
    ) -> NewsDocument:
        digest = sha1(f"{title}:{text[:80]}".encode("utf-8")).hexdigest()
        return NewsDocument(
            id=digest,
            title=title,
            text=text,
            source=Source(title=title, url=url, publisher=publisher, published_at=published_at),
        )

    async def fetch_feed(
        self,
        url: str,
        publisher: str | None = None,
        limit: int = 10,
    ) -> list[NewsDocument]:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        return self.parse_feed(response.text, feed_url=url, publisher=publisher, limit=limit)

    def parse_feed(
        self,
        xml_text: str,
        feed_url: str,
        publisher: str | None = None,
        limit: int = 10,
    ) -> list[NewsDocument]:
        root = ET.fromstring(xml_text)
        items = list(root.findall(".//item"))
        if items:
            return [self._rss_item_to_document(item, publisher, feed_url) for item in items[:limit]]
        entries = list(root.findall(".//{http://www.w3.org/2005/Atom}entry"))
        return [self._atom_entry_to_document(entry, publisher, feed_url) for entry in entries[:limit]]

    @staticmethod
    def _title(soup: BeautifulSoup) -> str | None:
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        heading = soup.find("h1")
        return heading.get_text(strip=True) if heading else None

    @staticmethod
    def _article_text(soup: BeautifulSoup) -> str:
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        article = soup.find("article") or soup.body or soup
        return "\n".join(part.strip() for part in article.get_text("\n").splitlines() if part.strip())

    @staticmethod
    def _published_date(soup: BeautifulSoup) -> date | None:
        selectors = [
            ("meta", {"property": "article:published_time"}),
            ("meta", {"name": "pubdate"}),
            ("meta", {"name": "date"}),
        ]
        for name, attrs in selectors:
            tag = soup.find(name, attrs=attrs)
            content = tag.get("content") if tag else None
            if not content:
                continue
            try:
                return datetime.fromisoformat(content.replace("Z", "+00:00")).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _rss_item_to_document(item: ET.Element, publisher: str | None, feed_url: str) -> NewsDocument:
        title = NewsFetcher._child_text(item, "title") or "untitled"
        link = NewsFetcher._child_text(item, "link")
        description = NewsFetcher._child_text(item, "description") or ""
        published_at = NewsFetcher._parse_date(NewsFetcher._child_text(item, "pubDate"))
        item_publisher = NewsFetcher._child_text(item, "source") or publisher or feed_url
        return NewsFetcher.from_manual_text(
            title=title,
            text=BeautifulSoup(description, "html.parser").get_text(" ", strip=True) or title,
            publisher=item_publisher,
            published_at=published_at,
            url=link,
        )

    @staticmethod
    def _atom_entry_to_document(entry: ET.Element, publisher: str | None, feed_url: str) -> NewsDocument:
        namespace = "{http://www.w3.org/2005/Atom}"
        title = NewsFetcher._child_text(entry, f"{namespace}title") or "untitled"
        summary = NewsFetcher._child_text(entry, f"{namespace}summary") or NewsFetcher._child_text(
            entry,
            f"{namespace}content",
        ) or ""
        link_element = entry.find(f"{namespace}link")
        link = link_element.get("href") if link_element is not None else None
        published_at = NewsFetcher._parse_date(
            NewsFetcher._child_text(entry, f"{namespace}published")
            or NewsFetcher._child_text(entry, f"{namespace}updated")
        )
        return NewsFetcher.from_manual_text(
            title=title,
            text=BeautifulSoup(summary, "html.parser").get_text(" ", strip=True) or title,
            publisher=publisher or feed_url,
            published_at=published_at,
            url=link,
        )

    @staticmethod
    def _child_text(element: ET.Element, tag: str) -> str | None:
        child = element.find(tag)
        if child is None or child.text is None:
            return None
        return child.text.strip()

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return parsedate_to_datetime(value).date()
        except (TypeError, ValueError):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
            except ValueError:
                return None
