from __future__ import annotations

from typing import Any


class DiscoveredPipelineCandidateMixin:
    @staticmethod
    def _promoted_tickers_from_candidates(candidates: list[dict]) -> list[str]:
        return [
            str(candidate.get("ticker"))
            for candidate in candidates
            if candidate.get("ticker") and candidate.get("status") == "evidence_supported"
        ]

    def _revalidate_candidates(
        self,
        payload: Any,
        service: Any,
        plan: Any,
        source_audit: dict,
        candidate_payload: list[dict],
        documents: list,
    ) -> tuple[dict | None, list[dict], list]:
        candidate_filing_ingestion = None
        if not self.should_revalidate_candidate_filings_func(candidate_payload):
            return candidate_filing_ingestion, candidate_payload, documents
        candidate_tickers = self.candidate_filing_revalidation_tickers_func(
            candidate_payload, payload
        )
        candidate_filing_ingestion = self.company_filing_timeout_result_func(
            candidate_tickers,
            RuntimeError("skipped during synchronous deep analysis; queued as follow-up"),
            "candidate MOPS annual report discovery",
        )
        candidate_filing_documents = self._latest_company_filing_news_documents(
            candidate_tickers,
            limit_per_ticker=2,
        )
        if not candidate_filing_documents:
            return candidate_filing_ingestion, candidate_payload, documents

        documents = self.dedupe_documents_func([*documents, *candidate_filing_documents])
        revalidated_candidates = service.validate_candidates(plan, documents)
        candidate_payload = [candidate.model_dump() for candidate in revalidated_candidates]
        source_audit["candidate_support"] = self.summarize_candidate_support_func(
            revalidated_candidates
        )
        source_audit["candidate_filing_revalidation"] = {
            "attempted": True,
            "stored_count": candidate_filing_ingestion.get("stored_count", 0),
            "document_count": len(candidate_filing_documents),
            "promoted_after_revalidation": [
                candidate["ticker"]
                for candidate in candidate_payload
                if candidate["status"] == "evidence_supported"
            ],
            "requested_tickers": candidate_tickers,
        }
        return candidate_filing_ingestion, candidate_payload, documents

    def _promoted_company_filing_ingestion(self, promoted_tickers: list[str]) -> dict:
        if promoted_tickers:
            return self.company_filing_timeout_result_func(
                promoted_tickers,
                RuntimeError("skipped during synchronous deep analysis; queued as follow-up"),
                "promoted MOPS annual report discovery",
            )
        return {
            "requested_tickers": [],
            "stored_count": 0,
            "per_ticker_results": [],
            "gap_summary": {"blocked_tickers": [], "retryable_tickers": []},
            "errors": [],
            "source": "Company filing discovery skipped: no promoted candidates",
        }

    def _latest_company_filing_news_documents(
        self,
        tickers: list[str],
        *,
        limit_per_ticker: int,
    ) -> list:
        with self.session_scope_factory() as session:
            return [
                self.company_filing_repository_cls.to_news_document(document)
                for document in self.company_filing_repository_cls(session).latest_by_tickers(
                    tickers,
                    limit_per_ticker=limit_per_ticker,
                )
            ]


__all__ = ["DiscoveredPipelineCandidateMixin"]
