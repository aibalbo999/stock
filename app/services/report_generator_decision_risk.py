from __future__ import annotations

from app.models.schemas import NewsDocument, ReportRequest
from app.services import report_decision_narrative, report_decision_rules, report_risk_overview
from app.services.leading_signals import LeadingSignal


class ReportGeneratorDecisionRiskMixin:
    @classmethod
    def _sort_decision_contexts(cls, contexts: list[dict]) -> list[dict]:
        return report_decision_rules.sort_decision_contexts(contexts)

    @classmethod
    def _decision_sort_key(cls, context: dict) -> tuple:
        return report_decision_rules.decision_sort_key(context)

    @staticmethod
    def _decision_rank(decision: str | None) -> int:
        return report_decision_rules.decision_rank(decision)

    @staticmethod
    def _context_current_price(context: dict) -> float:
        return report_decision_rules.context_current_price(context)

    @staticmethod
    def _recheck_trigger_text(context: dict, downside_gate: int | None = None) -> str:
        return report_decision_rules.recheck_trigger_text(context, downside_gate)

    @staticmethod
    def _avoid_trigger_text(context: dict, downside_gate: int | None = None) -> str:
        return report_decision_rules.avoid_trigger_text(context, downside_gate)

    @staticmethod
    def _monitor_frequency(context: dict) -> str:
        return report_decision_rules.monitor_frequency(context)

    @staticmethod
    def _risk_warning_reason(estimate: dict) -> str:
        return report_decision_rules.risk_warning_reason(estimate)

    def _company_risk_summary(self, related_findings) -> str:
        return report_risk_overview.company_risk_summary(related_findings, whitelist=self.whitelist)

    def _sanitized_risk_topic_for_finding(self, finding) -> str:
        return report_risk_overview.sanitized_risk_topic_for_finding(finding, self.whitelist)

    def _sanitize_risk_topic(self, topic: str, tickers: list[str] | None = None) -> str:
        return report_risk_overview.sanitize_risk_topic(topic, tickers, whitelist=self.whitelist)

    def _companies_allow_ai_infra_risk(self, tickers: list[str]) -> bool:
        return report_risk_overview.companies_allow_ai_infra_risk(tickers, self.whitelist)

    def _company_allows_ai_infra_risk(self, ticker: str) -> bool:
        return report_risk_overview.company_allows_ai_infra_risk(ticker, self.whitelist)

    @staticmethod
    def _is_ai_infra_specific_risk_term(term: str) -> bool:
        return report_risk_overview.is_ai_infra_specific_risk_term(term)

    @staticmethod
    def _finding_scope_companies(finding, scope_tickers: set[str] | None = None) -> list:
        return report_risk_overview.finding_scope_companies(finding, scope_tickers)

    def _risk_findings_for_scope(self, findings, tickers: list[str] | None = None) -> list:
        return report_risk_overview.risk_findings_for_scope(findings, tickers)

    def _render_risk_overview(self, findings, tickers: list[str] | None = None) -> str:
        return report_risk_overview.render_risk_overview(findings, tickers, whitelist=self.whitelist)

    @staticmethod
    def _related_findings(ticker: str, findings) -> list:
        return report_risk_overview.related_findings(ticker, findings)

    @staticmethod
    def _summary(findings) -> str:
        return report_risk_overview.findings_summary(findings)

    @staticmethod
    def _decision_reason(
        rating: str,
        estimate: dict,
        quality: dict,
        related_findings,
        related_documents: list[NewsDocument],
        downside_gate: int,
        request: ReportRequest,
        leading_signal: LeadingSignal | None = None,
    ) -> str:
        return report_decision_narrative.decision_reason(
            rating,
            estimate,
            quality,
            related_findings,
            related_documents,
            downside_gate,
            request,
            leading_signal,
        )

    @staticmethod
    def _structural_bottleneck_reason(related_findings) -> str:
        return report_decision_narrative.structural_bottleneck_reason(related_findings)
