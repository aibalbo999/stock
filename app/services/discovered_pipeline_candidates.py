from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CandidateRevalidationStageResult:
    candidate_filing_ingestion: dict | None
    candidate_payload: list[dict]
    documents: list[Any]
    source_audit: dict
    promoted_tickers: list[str]
    company_filing_ingestion: dict

    def workflow_summary(self, *, resumed: bool = False) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "candidate_count": len(self.candidate_payload),
            "promoted_count": len(self.promoted_tickers),
            "candidate_filing_attempted": self.candidate_filing_ingestion is not None,
        }
        if resumed:
            summary["resumed"] = True
        return summary

    def checkpoint_updates(
        self,
        documents_payload_func: Callable[[list[Any]], list[dict]],
    ) -> dict[str, Any]:
        return {
            "source_documents": documents_payload_func(self.documents),
            "candidate_filing_ingestion": self.candidate_filing_ingestion,
            "company_filing_ingestion": self.company_filing_ingestion,
            "source_audit": self.source_audit,
            "candidate_whitelist": self.candidate_payload,
            "promoted_tickers": self.promoted_tickers,
        }


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

    def _finalize_candidate_revalidation_stage(
        self,
        *,
        candidate_filing_ingestion: dict | None,
        candidate_payload: list[dict],
        documents: list[Any],
        source_audit: dict,
    ) -> CandidateRevalidationStageResult:
        candidate_payload = self.apply_company_filing_gate_func(candidate_payload)
        source_audit["candidate_support"] = self.summarize_candidate_support_payload_func(
            candidate_payload
        )
        promoted_tickers = self._promoted_tickers_from_candidates(candidate_payload)
        company_filing_ingestion = self._promoted_company_filing_ingestion(promoted_tickers)
        documents = self.dedupe_documents_func(
            [
                *documents,
                *self._latest_company_filing_news_documents(
                    promoted_tickers,
                    limit_per_ticker=4,
                ),
            ]
        )
        return CandidateRevalidationStageResult(
            candidate_filing_ingestion=candidate_filing_ingestion,
            candidate_payload=candidate_payload,
            documents=documents,
            source_audit=source_audit,
            promoted_tickers=promoted_tickers,
            company_filing_ingestion=company_filing_ingestion,
        )

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


__all__ = ["CandidateRevalidationStageResult", "DiscoveredPipelineCandidateMixin"]
