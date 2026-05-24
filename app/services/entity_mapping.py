from __future__ import annotations

from app.models.schemas import EntityMatch, NewsDocument
from app.services.whitelist import SupplyChainWhitelist


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
                    if alias and alias.lower() in lowered:
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
        return self.match_text(f"{document.title}\n{document.text}")

    def filter_allowed_tickers(self, tickers: list[str]) -> list[str]:
        allowed = self.whitelist.allowed_tickers()
        return [ticker for ticker in tickers if ticker in allowed]
