from __future__ import annotations

from app.db.session import session_scope
from app.models.schemas import NewsDocument
from app.services import (
    report_company_filing_checks,
    report_document_matching,
    report_source_coverage,
)


class ReportGeneratorDocumentMixin:
    @staticmethod
    def _is_international_source(document: NewsDocument) -> bool:
        return report_source_coverage.is_international_source(document)

    def _document_matches(self, document: NewsDocument) -> list:
        cache = getattr(self, "_document_match_cache", None)
        if cache is None:
            cache = {}
            self._document_match_cache = cache
        return report_document_matching.document_matches(
            document,
            mapper=self.mapper,
            whitelist=self.whitelist,
            cache=cache,
        )

    def _document_metadata_matches(self, document: NewsDocument) -> list:
        return report_document_matching.document_metadata_matches(document, self.whitelist)

    def _related_documents(self, ticker: str, documents: list[NewsDocument]) -> list[NewsDocument]:
        return report_document_matching.related_documents(
            ticker,
            documents,
            document_match_resolver=self._document_matches,
        )

    def _document_company_labels(self, document: NewsDocument) -> list[str]:
        return report_document_matching.document_company_labels(
            document,
            document_match_resolver=self._document_matches,
        )

    def _candidate_audit_evidence_counts(self) -> dict[str, dict[str, int]]:
        return report_document_matching.candidate_audit_evidence_counts(
            self.whitelist.candidate_audit()
        )

    @staticmethod
    def _publisher_count(documents: list[NewsDocument]) -> int:
        return report_document_matching.publisher_count(documents)

    def _company_filing_missing(self, ticker: str, documents: list[NewsDocument]) -> list[str]:
        return report_company_filing_checks.company_filing_missing(
            ticker,
            documents,
            whitelist=self.whitelist,
            session_scope_func=session_scope,
        )

    @staticmethod
    def _filing_type_label(document_type: str) -> str:
        return report_company_filing_checks.filing_type_label(document_type)

    @staticmethod
    def _company_filing_documents_from_db(ticker: str):
        return report_company_filing_checks.company_filing_documents_from_db(
            ticker,
            session_scope_func=session_scope,
        )

    @staticmethod
    def _is_company_filing_document(ticker: str, document: NewsDocument) -> bool:
        return report_company_filing_checks.is_company_filing_document(ticker, document)

    @staticmethod
    def _news_document_filing_type(document: NewsDocument) -> str | None:
        return report_company_filing_checks.news_document_filing_type(document)
