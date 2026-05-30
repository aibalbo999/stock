from __future__ import annotations

import re

from app.models.schemas import EntityMatch, NewsDocument
from app.services.whitelist import SupplyChainWhitelist


def company_filing_owner_ticker(document: NewsDocument) -> str | None:
    if not document.id.startswith("filing-"):
        return None
    head = "\n".join(document.text.splitlines()[:8])
    explicit = re.search(r"股票代號[：:]\s*(\d{4,6})", head)
    if explicit:
        return explicit.group(1)
    first_line = next((line.strip() for line in document.text.splitlines() if line.strip()), "")
    first = re.match(r"(\d{4,6})(?:\s|$)", first_line)
    return first.group(1) if first else None


class EntityMapper:
    def __init__(self, whitelist: SupplyChainWhitelist | None = None) -> None:
        self.whitelist = whitelist or SupplyChainWhitelist()

    def match_text(self, text: str) -> list[EntityMatch]:
        matches: dict[tuple[str, str], EntityMatch] = {}
        lowered = text.lower()
        for segment in self.whitelist.segments:
            for company in segment.companies:
                aliases = [company.ticker, company.name, *company.aliases]
                for alias in aliases:
                    if alias and self._alias_matches(lowered, alias):
                        matches[(company.ticker, segment.id)] = EntityMatch(
                            ticker=company.ticker,
                            name=company.name,
                            segment_id=segment.id,
                            segment_name=segment.name,
                            matched_alias=alias,
                        )
                        break
        return list(matches.values())

    def match_document(self, document: NewsDocument) -> list[EntityMatch]:
        text = f"{document.title}\n{document.text}"
        matches = self.match_text(text)
        owner_ticker = company_filing_owner_ticker(document)
        if owner_ticker:
            matches = [match for match in matches if match.ticker == owner_ticker]
        if not self._looks_like_release_notes(document):
            return matches
        lowered = text.lower()
        return [
            match
            for match in matches
            if self._document_has_named_company_alias(match.ticker, lowered)
        ]

    def filter_allowed_tickers(self, tickers: list[str]) -> list[str]:
        allowed = self.whitelist.allowed_tickers()
        return [ticker for ticker in tickers if ticker in allowed]

    @staticmethod
    def _alias_matches(lowered_text: str, alias: str) -> bool:
        lowered_alias = alias.lower()
        if lowered_alias.isdigit():
            return bool(re.search(rf"(?<!\d){re.escape(lowered_alias)}(?!\d)", lowered_text))
        return lowered_alias in lowered_text

    @staticmethod
    def _looks_like_release_notes(document: NewsDocument) -> bool:
        haystack = " ".join(
            [
                document.title,
                document.source.title or "",
                document.source.publisher or "",
                document.source.url or "",
            ]
        ).lower()
        release_markers = (
            "google cloud release notes",
            "release notes",
            "changelog",
            "版本資訊",
            "更新日誌",
        )
        return any(marker in haystack for marker in release_markers)

    def _document_has_named_company_alias(self, ticker: str, lowered_text: str) -> bool:
        for segment in self.whitelist.segments:
            for company in segment.companies:
                if company.ticker != ticker:
                    continue
                aliases = [company.name, *company.aliases]
                return any(
                    alias and not alias.isdigit() and alias.lower() in lowered_text
                    for alias in aliases
                )
        return False
