from __future__ import annotations

from typing import Any

from app.core.time import now_taipei
from app.models.schemas import NewsDocument, ReportRequest, ReportResponse
from app.services import report_prompt_builder
from app.services.source_quality import (
    filter_formal_evidence_documents,
    is_formal_evidence_document,
    remove_low_quality_investor_forum_lines,
)


def generate_report(
    generator: Any,
    request: ReportRequest,
    documents: list[NewsDocument] | None = None,
    *,
    execution_error_cls: type[Exception],
) -> ReportResponse:
    raw_evidence_docs = documents or generator._retrieve_evidence(request)
    evidence_docs = filter_formal_evidence_documents(raw_evidence_docs)
    generator.last_excluded_low_quality_documents = [
        document
        for document in raw_evidence_docs
        if not is_formal_evidence_document(document)
    ]
    generator.last_evidence_documents = list(evidence_docs)
    findings = generator.risk_analyzer.analyze_documents(evidence_docs)
    tickers = generator.mapper.filter_allowed_tickers(request.tickers)
    generator.last_filtered_tickers = tickers
    generator.last_dropped_tickers = [ticker for ticker in request.tickers if ticker not in set(tickers)]
    if generator.last_dropped_tickers:
        dropped_tickers = "、".join(generator.last_dropped_tickers)
        raise execution_error_cls(
            f"報告產生中止：以下指定股票未進入目前白名單：{dropped_tickers}。"
            "若這是 AI 主題探索或補強重跑，必須套用候選公司動態白名單，"
            "避免產出缺漏個股分析卻顯示成功的報告。"
        )
    market_snapshots = generator._latest_market_snapshots(tickers)
    monthly_revenues = generator._latest_monthly_revenues(tickers)
    financial_metrics = generator._financial_metrics(tickers)
    valuation_metrics = generator._latest_valuations(tickers)
    leading_signals = generator._leading_signals(tickers, valuation_metrics)

    graph_reasoning_context = generator._graph_reasoning_context(request, tickers)
    prompt = report_prompt_builder.build_report_prompt(
        whitelist_context=generator.whitelist.as_prompt_context(),
        graph_context=graph_reasoning_context,
        evidence_documents=evidence_docs,
        market_snapshots=market_snapshots,
        monthly_revenues=monthly_revenues,
        ticker_label_resolver=generator._document_company_labels,
    )
    llm_result = generator._generate_llm_supplement(prompt)
    generator.last_llm_result = llm_result
    markdown = generator._render_markdown(
        request,
        evidence_docs,
        findings,
        tickers,
        llm_result,
        market_snapshots,
        monthly_revenues,
        financial_metrics,
        valuation_metrics,
        leading_signals,
    )
    markdown = remove_low_quality_investor_forum_lines(markdown)
    generator._assert_report_integrity(markdown, generator.whitelist)
    return ReportResponse(
        title=f"{request.topic} 自動分析報告",
        generated_at=now_taipei(),
        markdown=markdown,
        findings=findings,
    )
