from __future__ import annotations

from typing import Any


class CandidateCompatibilityMixin:
    """Legacy candidate/revalidation delegates for app.api.main imports."""

    api_services: Any
    candidate_revalidation_module: Any

    def sufficient_company_filing_tickers(self, tickers: list[str]) -> set[str]:
        return self.api_services.candidate_revalidation().sufficient_company_filing_tickers(tickers)

    def count_sufficient_company_filings(self, tickers: list[str]) -> int:
        return len(self.sufficient_company_filing_tickers(tickers))

    def apply_company_filing_gate_to_candidate_payload(
        self,
        candidates: list[dict],
        *,
        sufficient_tickers_provider: Any | None = None,
    ) -> list[dict]:
        return self.candidate_revalidation_module.apply_company_filing_gate_to_candidate_payload(
            candidates,
            sufficient_tickers_provider=sufficient_tickers_provider
            or self.sufficient_company_filing_tickers,
        )

    def revalidate_candidate_whitelist(
        self,
        run_payload: dict,
        fallback_candidates: list[dict],
        limit: int = 500,
    ) -> dict:
        return self.api_services.candidate_revalidation().revalidate_candidate_whitelist(
            run_payload,
            fallback_candidates,
            limit,
        )

    def preserve_previous_supported_candidates(
        self,
        current_candidates: list[dict],
        previous_candidates: list[dict],
    ) -> list[dict]:
        return self.candidate_revalidation_module.preserve_previous_supported_candidates(
            current_candidates,
            previous_candidates,
        )

    def mark_unavailable_candidates_after_revalidation(
        self,
        candidates: list[dict],
        document_count: int,
    ) -> list[dict]:
        return self.candidate_revalidation_module.mark_unavailable_candidates_after_revalidation(
            candidates,
            document_count,
        )

    def candidate_revalidation_queries(
        self,
        plan: Any,
        topic: str = "",
        limit: int = 80,
    ) -> list[str]:
        return self.candidate_revalidation_module.candidate_revalidation_queries(plan, topic, limit)

    def collect_revalidation_documents(self, repository: Any, queries: list[str], limit: int) -> list:
        return self.candidate_revalidation_module.collect_revalidation_documents(
            repository,
            queries,
            limit,
        )

    def dedupe_documents(self, documents: list) -> list:
        return self.candidate_revalidation_module.dedupe_documents(documents)

    def persist_candidate_entity_matches(
        self,
        plan: Any,
        candidates: list,
        documents: list,
    ) -> dict:
        return self.api_services.candidate_revalidation().persist_candidate_entity_matches(
            plan,
            candidates,
            documents,
        )

    def dedupe_strings(self, values: list[str], limit: int) -> list[str]:
        return self.candidate_revalidation_module.dedupe_strings(values, limit)
