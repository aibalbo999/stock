from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.models.schemas import ReportRequest
from app.services.report_execution import report_execution_summary
from app.services.report_generator import ReportGenerator
from app.services.report_quality import attach_quality_gate_to_report, build_quality_gate_for_request


class ReportBuildService:
    def __init__(
        self,
        report_generator_cls=ReportGenerator,
        build_quality_gate_for_request_func: Callable = build_quality_gate_for_request,
        attach_quality_gate_to_report_func: Callable = attach_quality_gate_to_report,
        report_execution_summary_func: Callable[[object], dict] = report_execution_summary,
    ) -> None:
        self.report_generator_cls = report_generator_cls
        self.build_quality_gate_for_request_func = build_quality_gate_for_request_func
        self.attach_quality_gate_to_report_func = attach_quality_gate_to_report_func
        self.report_execution_summary_func = report_execution_summary_func

    def build(
        self,
        request: ReportRequest,
        *,
        whitelist: Any | None = None,
        documents: list | None = None,
        source_count: int | None = None,
        company_filing_sufficient_count: int | None = None,
        candidate_support: dict | None = None,
        plan_quality: dict | None = None,
    ) -> dict:
        generator = self._generator(whitelist)
        if documents is None:
            response = generator.generate(request)
        else:
            response = generator.generate(request, documents=documents)
        quality_gate = self._quality_gate(
            request,
            generator,
            source_count=self._effective_source_count(source_count, generator),
            company_filing_sufficient_count=company_filing_sufficient_count,
            candidate_support=candidate_support,
            plan_quality=plan_quality,
        )
        response = self.attach_quality_gate_to_report_func(response, quality_gate)
        report_execution = self.report_execution_summary_func(generator)
        return {
            "response": response,
            "quality_gate": quality_gate,
            "generator": generator,
            "report_execution": report_execution,
            "evidence_count": len(getattr(generator, "last_evidence_documents", None) or []),
        }

    def _generator(self, whitelist: Any | None) -> object:
        if whitelist is None:
            return self.report_generator_cls()
        return self.report_generator_cls(whitelist=whitelist)

    def _effective_source_count(self, source_count: int | None, generator: object) -> int | None:
        if source_count is None:
            return None
        evidence_count = len(getattr(generator, "last_evidence_documents", None) or [])
        return max(source_count, evidence_count)

    def _quality_gate(
        self,
        request: ReportRequest,
        generator: object,
        *,
        source_count: int | None,
        company_filing_sufficient_count: int | None,
        candidate_support: dict | None,
        plan_quality: dict | None,
    ) -> dict:
        kwargs = {
            "documents": getattr(generator, "last_evidence_documents", None),
            "llm_result": getattr(generator, "last_llm_result", None),
        }
        if source_count is not None:
            kwargs["source_count"] = source_count
        if company_filing_sufficient_count is not None:
            kwargs["company_filing_sufficient_count"] = company_filing_sufficient_count
        if candidate_support is not None:
            kwargs["candidate_support"] = candidate_support
        if plan_quality is not None:
            kwargs["plan_quality"] = plan_quality
        return self.build_quality_gate_for_request_func(request, **kwargs)
