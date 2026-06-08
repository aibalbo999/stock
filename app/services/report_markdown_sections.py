from __future__ import annotations

from typing import Any

from app.core.time import now_taipei
from app.models.schemas import (
    FinancialMetric,
    MarketSnapshot,
    MonthlyRevenue,
    NewsDocument,
    ReportRequest,
    ValuationMetric,
)
from app.services.leading_signals import LeadingSignal
from app.services.llm_client import LLMResult
from app.services.report_models import ReportContext, ReportSection
from app.services.report_renderer import ReportMarkdownRenderer


def render_markdown(
    generator: Any,
    request: ReportRequest,
    documents: list[NewsDocument],
    findings,
    tickers: list[str],
    llm_result: LLMResult,
    market_snapshots: list[MarketSnapshot],
    monthly_revenues: list[MonthlyRevenue],
    financial_metrics: list[FinancialMetric] | None = None,
    valuation_metrics: list[ValuationMetric] | None = None,
    leading_signals: dict[str, LeadingSignal] | None = None,
) -> str:
    leading_signals = _sanitize_leading_signals(
        generator,
        leading_signals or {},
        financial_metrics,
    )
    ordered_tickers = generator._ordered_tickers_for_reading(
        request,
        tickers,
        documents,
        findings,
        market_snapshots,
        monthly_revenues,
        financial_metrics,
        valuation_metrics,
        leading_signals,
    )
    sections = build_sections(
        generator,
        request,
        ordered_tickers,
        documents,
        findings,
        llm_result,
        market_snapshots,
        monthly_revenues,
        financial_metrics,
        valuation_metrics,
        leading_signals,
    )
    context = ReportContext(
        title=f"{request.topic} 自動分析報告",
        topic=request.topic,
        generated_at=now_taipei(),
        sections=sections,
    )
    return ReportMarkdownRenderer().render(context)


def _sanitize_leading_signals(
    generator: Any,
    leading_signals: dict[str, LeadingSignal],
    financial_metrics: list[FinancialMetric] | None,
) -> dict[str, LeadingSignal]:
    if not financial_metrics:
        return leading_signals
    metrics_by_ticker = generator._group_financial_metrics(financial_metrics)
    return {
        ticker: generator._sanitize_leading_signal_for_profitability(
            signal,
            generator._has_negative_profitability(metrics_by_ticker.get(ticker, [])),
        )
        for ticker, signal in leading_signals.items()
    }


def build_sections(
    generator: Any,
    request: ReportRequest,
    ordered_tickers: list[str],
    documents: list[NewsDocument],
    findings,
    llm_result: LLMResult,
    market_snapshots: list[MarketSnapshot],
    monthly_revenues: list[MonthlyRevenue],
    financial_metrics: list[FinancialMetric] | None = None,
    valuation_metrics: list[ValuationMetric] | None = None,
    leading_signals: dict[str, LeadingSignal] | None = None,
) -> list[ReportSection]:
    leading_signals = leading_signals or {}
    return [
        ReportSection(
            title="一頁摘要",
            body=generator._render_executive_snapshot(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
        ),
        ReportSection(
            title="可信度檢查",
            body=generator._render_credibility_check(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
        ),
        ReportSection(
            title="時間口徑說明",
            body=generator._render_time_scope_note(
                request,
                market_snapshots,
                monthly_revenues,
                valuation_metrics,
            ),
        ),
        ReportSection(title="判斷準則說明", body=generator._render_decision_criteria_note(request)),
        ReportSection(
            title="下一步行動",
            body=generator._render_action_checklist(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
        ),
        ReportSection(
            title="監控清單",
            body=generator._render_monitoring_checklist(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
        ),
        ReportSection(
            title="自動補強任務",
            body=generator._render_follow_up_actions(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
        ),
        ReportSection(title="先看結論", body=generator._summary(findings)),
        ReportSection(title="候選公司審計", body=generator._render_candidate_audit(ordered_tickers)),
        ReportSection(
            title="資料完整度",
            body=generator._render_data_quality(
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
                request=request,
            ),
        ),
        ReportSection(title="來源覆蓋", body=generator._render_source_coverage(request, ordered_tickers, documents)),
        ReportSection(title="近況訊號檢查", body=generator._render_leading_signal_check(ordered_tickers, leading_signals)),
        ReportSection(
            title="早期潛力雷達",
            body=generator._render_early_potential_radar(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                leading_signals,
                financial_metrics,
                valuation_metrics,
            ),
        ),
        ReportSection(
            title="資金控管建議",
            body=generator._render_beginner_portfolio_plan(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
        ),
        ReportSection(
            title="投資建議",
            body=generator._render_investment_recommendations(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
        ),
        ReportSection(
            title="個股比較矩陣",
            body=generator._render_company_comparison_matrix(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
        ),
        ReportSection(
            title="投資理由地圖",
            body=generator._render_investment_thesis_map(
                request,
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
        ),
        ReportSection(
            title="二次綜合篩選",
            body=generator._render_final_potential_screen(
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
                request=request,
            ),
        ),
        ReportSection(
            title="評分明細",
            body=generator._render_score_breakdown(
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                leading_signals,
            ),
        ),
        ReportSection(title="基本面月營收檢查", body=generator._render_revenue_check(ordered_tickers, monthly_revenues)),
        ReportSection(
            title="個別公司分析",
            body=generator._render_company_analysis(
                ordered_tickers,
                documents,
                findings,
                market_snapshots,
                monthly_revenues,
                financial_metrics,
                valuation_metrics,
                request=request,
                leading_signals=leading_signals,
            ),
        ),
        ReportSection(title="主要風險與瓶頸", body=generator._render_risk_overview(findings, ordered_tickers)),
        ReportSection(title="分析範圍", body=generator._render_scope(ordered_tickers, market_snapshots, monthly_revenues)),
        ReportSection(
            title="附錄：AI 補充與資料來源",
            body=generator._render_appendix(llm_result, documents, market_snapshots, tickers=ordered_tickers),
        ),
    ]
