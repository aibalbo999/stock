from __future__ import annotations

from collections.abc import Callable

from app.models.schemas import MarketSnapshot, MonthlyRevenue, NewsDocument
from app.services import report_appendix, report_prompt_builder
from app.services.llm_client import LLMResult


class ReportGeneratorPromptAppendixMixin:
    def _appendix_documents_for_tickers(
        self,
        documents: list[NewsDocument],
        tickers: list[str] | None,
    ) -> list[NewsDocument]:
        return report_appendix.appendix_documents_for_tickers(
            documents,
            tickers,
            document_match_resolver=self._document_matches,
        )

    def _render_appendix(
        self,
        llm_result: LLMResult,
        documents: list[NewsDocument],
        market_snapshots: list[MarketSnapshot],
        tickers: list[str] | None = None,
    ) -> str:
        return report_appendix.render_appendix(
            llm_result,
            documents,
            market_snapshots,
            tickers=tickers,
            document_match_resolver=self._document_matches,
            claim_ticker_resolver=lambda claim: self.mapper.match_text(claim),
        )

    @staticmethod
    def _format_evidence(documents: list[NewsDocument]) -> str:
        return report_prompt_builder.format_evidence_digest(documents)

    @staticmethod
    def _format_llm_evidence(
        documents: list[NewsDocument],
        ticker_label_resolver: Callable[[NewsDocument], list[str]] | None = None,
    ) -> str:
        return report_prompt_builder.format_llm_evidence(documents, ticker_label_resolver)

    @staticmethod
    def _format_market_data(
        snapshots: list[MarketSnapshot],
        monthly_revenues: list[MonthlyRevenue] | None = None,
    ) -> str:
        return report_prompt_builder.format_market_data(snapshots, monthly_revenues)

    @staticmethod
    def _model_status(result: LLMResult) -> str:
        return report_appendix.model_status(result)
