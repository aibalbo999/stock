from __future__ import annotations

from datetime import date

from app.db.session import session_scope
from app.models.schemas import NewsDocument, ReportRequest
from app.services.entity_mapping import EntityMapper
from app.services.leading_signals import LeadingSignalAnalyzer
from app.services.market_repositories import (
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    ValuationMetricRepository,
)
from app.services.report_orchestrator import build_quality_recovery_plan
from app.services.report_quality_recovery import (
    quality_remediation_actions,
    should_recover_market_data_quality as should_recover_market_data_quality,
)
from app.services.report_quality_runtime import (
    rag_runtime_status,
    summarize_llm_status,
)
from app.services.report_quality_llm_rules import llm_quality_notes
from app.services.report_quality_rag_rules import (
    normalized_rag_reranker_provider,
    rag_quality_warnings,
)
from app.services.report_quality_sources import (
    LATEST_ONLY_MARKET_SOURCE_MARKER,
    STALE_MARKET_SOURCE_MARKER,
    date_lag_days as _date_lag_days,
    date_to_text as _date_to_text,
    is_latest_only_market_data_source,
    is_stale_market_data_source,
    latest_only_financial_metric_ticker_count as _latest_only_financial_metric_ticker_count,
    latest_only_market_data_count as _latest_only_market_data_count,
    market_provider_summary,
    market_trade_date_summary,
    stale_financial_metric_ticker_count as _stale_financial_metric_ticker_count,
    stale_market_data_count as _stale_market_data_count,
    summarize_document_source_quality,
)
from app.services.report_quality_markdown import (
    _first_matching_field as _first_matching_field,
    _first_matching_value as _first_matching_value,
    _format_confidence_score as _format_confidence_score,
    _format_llm_observability as _format_llm_observability,
    _format_llm_status as _format_llm_status,
    _format_market_provider_summary as _format_market_provider_summary,
    _format_optional_int as _format_optional_int,
    _format_optional_number as _format_optional_number,
    _format_optional_percent as _format_optional_percent,
    _format_plan_quality as _format_plan_quality,
    _format_rag_status as _format_rag_status,
    _investor_friendly_issue as _investor_friendly_issue,
    _markdown_section as _markdown_section,
    _parse_amount as _parse_amount,
    _parse_confidence_value as _parse_confidence_value,
    _parse_int as _parse_int,
    _parse_llm_status as _parse_llm_status,
    _parse_optional_int as _parse_optional_int,
    _parse_optional_percent as _parse_optional_percent,
    _parse_percent as _parse_percent,
    _parse_plan_quality_score as _parse_plan_quality_score,
    _parse_plan_quality_status as _parse_plan_quality_status,
    _parse_stale_metric_count as _parse_stale_metric_count,
    _split_issue_field as _split_issue_field,
    attach_quality_gate_to_report as attach_quality_gate_to_report,
    parse_quality_gate_from_markdown as parse_quality_gate_from_markdown,
    remove_quality_gate_sections as remove_quality_gate_sections,
    render_quality_action_guard_markdown as render_quality_action_guard_markdown,
    render_quality_gate_markdown as render_quality_gate_markdown,
)

__all__ = [
    "LATEST_ONLY_MARKET_SOURCE_MARKER",
    "STALE_MARKET_SOURCE_MARKER",
    "is_latest_only_market_data_source",
    "is_stale_market_data_source",
    "market_provider_summary",
    "market_trade_date_summary",
    "summarize_document_source_quality",
]


def build_report_quality_gate(
    source_audit: dict,
    promoted_tickers: list[str],
    market_count: int,
    monthly_revenue_count: int,
    financial_metrics_count: int,
    valuation_count: int,
    investor_capital: int | None = None,
    cash_reserve_pct: float | None = None,
    source_quality: dict | None = None,
    plan_quality: dict | None = None,
    leading_signal_count: int | None = None,
    llm_status: dict | None = None,
    company_filing_sufficient_count: int | None = None,
    market_stale_count: int = 0,
    monthly_revenue_stale_count: int = 0,
    financial_metrics_stale_ticker_count: int = 0,
    valuation_stale_count: int = 0,
    market_latest_only_count: int = 0,
    monthly_revenue_latest_only_count: int = 0,
    financial_metrics_latest_only_ticker_count: int = 0,
    valuation_latest_only_count: int = 0,
    rag_status: dict | None = None,
    market_provider_summary: dict | None = None,
    market_latest_trade_date: date | str | None = None,
    market_latest_trade_date_coverage: float | None = None,
    market_database_latest_trade_date: date | str | None = None,
    market_older_than_database_latest_count: int = 0,
    market_max_trade_date_lag_days: int | None = None,
) -> dict:
    candidate_support = source_audit.get("candidate_support") or {}
    dynamic_sources = source_audit.get("dynamic_queries") or {}
    promoted_count = len(promoted_tickers)
    source_count = max(
        int(dynamic_sources.get("stored_count") or 0),
        int(source_audit.get("total_stored_count") or 0),
    )
    source_quality = source_quality or {}
    plan_quality = plan_quality or source_audit.get("plan_quality") or {}
    exploration_supported_ratio = float(
        candidate_support.get(
            "exploration_supported_ratio", candidate_support.get("supported_ratio")
        )
        or 0
    )
    formal_supported_ratio = float(
        candidate_support.get(
            "formal_supported_ratio",
            1.0 if promoted_count else exploration_supported_ratio,
        )
        or 0
    )
    formal_confidence_avg = candidate_support.get("formal_confidence_avg")
    formal_confidence_min = candidate_support.get("formal_confidence_min")
    formal_low_confidence_count = int(candidate_support.get("formal_low_confidence_count") or 0)
    market_coverage = market_count / promoted_count if promoted_count else 0
    monthly_coverage = monthly_revenue_count / promoted_count if promoted_count else 0
    valuation_coverage = valuation_count / promoted_count if promoted_count else 0
    market_fresh_coverage = (
        max(0, market_count - market_stale_count) / promoted_count if promoted_count else 0
    )
    monthly_fresh_coverage = (
        max(0, monthly_revenue_count - monthly_revenue_stale_count) / promoted_count
        if promoted_count
        else 0
    )
    valuation_fresh_coverage = (
        max(0, valuation_count - valuation_stale_count) / promoted_count if promoted_count else 0
    )
    leading_signal_coverage = (
        leading_signal_count / promoted_count
        if promoted_count and leading_signal_count is not None
        else None
    )
    company_filing_coverage = (
        company_filing_sufficient_count / promoted_count
        if promoted_count and company_filing_sufficient_count is not None
        else None
    )
    llm_status = llm_status or {}
    llm_fallback = bool(llm_status.get("fallback")) if llm_status else None
    source_relevance = source_audit.get("source_relevance") or {}
    subtopic_readiness = source_relevance.get("subtopic_readiness") or {}
    missing_subtopic_count = int(source_relevance.get("missing_subtopic_count") or 0)
    weak_subtopic_count = int(source_relevance.get("weak_subtopic_count") or 0)
    adjusted_missing_subtopics = []
    adjusted_weak_subtopics = []
    for name, readiness in subtopic_readiness.items():
        status = str((readiness or {}).get("status") or "")
        if status not in {"missing", "weak"}:
            continue
        lower_name = str(name).lower()
        is_financial_subtopic = any(
            term in lower_name for term in ["財務", "估值", "股價", "營收", "現金流"]
        )
        if (
            is_financial_subtopic
            and market_count > 0
            and monthly_revenue_count > 0
            and valuation_count > 0
            and financial_metrics_count > 0
        ):
            continue
        if status == "missing":
            adjusted_missing_subtopics.append(name)
        else:
            adjusted_weak_subtopics.append(name)
    if adjusted_missing_subtopics:
        missing_subtopic_count = len(adjusted_missing_subtopics)
    if adjusted_weak_subtopics:
        weak_subtopic_count = len(adjusted_weak_subtopics)
    unique_publishers = int(source_quality.get("unique_publisher_count") or 0)
    timestamp_coverage = (
        float(source_quality.get("timestamp_coverage") or 0) if source_quality else 0
    )
    recent_coverage = float(source_quality.get("recent_coverage") or 0) if source_quality else 0
    source_lookback_days = int(source_quality.get("lookback_days") or 90) if source_quality else 90
    high_credibility_ratio = source_quality.get("high_credibility_ratio")
    low_credibility_ratio = source_quality.get("low_credibility_ratio")
    rag_status = rag_status or {}
    llm_observability = (llm_status or {}).get("observability") or {}
    rag_embedding_status = rag_status.get("embedding_status") or {}
    rag_reranker_status = rag_status.get("reranker_status") or {}
    rag_reranker_provider = normalized_rag_reranker_provider(rag_reranker_status)
    rag_retrieval_status = rag_status.get("retrieval_status") or {}
    market_provider_summary = market_provider_summary or {}
    stale_market_dataset_count = (
        int(market_stale_count)
        + int(monthly_revenue_stale_count)
        + int(financial_metrics_stale_ticker_count)
        + int(valuation_stale_count)
    )
    latest_only_market_dataset_count = (
        int(market_latest_only_count)
        + int(monthly_revenue_latest_only_count)
        + int(financial_metrics_latest_only_ticker_count)
        + int(valuation_latest_only_count)
    )

    blockers = []
    warnings = []
    observations = []
    if promoted_count == 0:
        blockers.append("沒有通過證據驗證的正式分析股票")
    if promoted_count == 0 and exploration_supported_ratio < 0.6:
        blockers.append("候選公司證據覆蓋率低於 60%")
    elif promoted_count and formal_supported_ratio < 1:
        blockers.append("正式分析股票仍含弱證據公司")
    elif promoted_count and formal_low_confidence_count:
        blockers.append("正式分析股票含低信心證據公司")
    elif promoted_count and exploration_supported_ratio < 0.6:
        observations.append("AI 初始候選清單較廣，已由二次篩選收斂為正式分析股票")
    if source_count < 8:
        blockers.append("AI 動態資料來源入庫篇數過少")
    elif source_count < 12:
        warnings.append("AI 動態資料來源偏少")
    if missing_subtopic_count:
        blockers.append(f"AI 拆解子題仍有 {missing_subtopic_count} 個完全缺少相關來源")
    if weak_subtopic_count:
        if not missing_subtopic_count and source_count >= 100 and unique_publishers >= 20:
            observations.append(
                f"主題拆解仍有 {weak_subtopic_count} 個子題可持續追蹤，已由多來源資料覆蓋主要結論"
            )
        else:
            warnings.append(f"AI 拆解子題仍有 {weak_subtopic_count} 個來源或資料意圖不足")
    if source_quality:
        if timestamp_coverage < 0.5:
            blockers.append("來源時間戳覆蓋率低於 50%")
        elif timestamp_coverage < 0.8:
            warnings.append("部分來源缺少發布日期，事實核查信心需下修")
        if source_count >= 8 and unique_publishers < 2:
            blockers.append("資料來源發布者過於單一")
        elif source_count >= 8 and unique_publishers < 3:
            warnings.append("資料來源多樣性偏低")
        if source_count >= 8 and recent_coverage < 0.4:
            warnings.append(f"近 {source_lookback_days} 天來源比例偏低，可能混入過舊產業假設")
        if (
            high_credibility_ratio is not None
            and source_count >= 8
            and float(high_credibility_ratio) < 0.35
        ):
            warnings.append("高可信來源比例偏低，正式結論需補官方文件或主流財經新聞")
        if (
            low_credibility_ratio is not None
            and source_count >= 8
            and float(low_credibility_ratio) > 0.35
        ):
            warnings.append("投資網誌或社群型來源比例偏高，不能直接支撐高可信投資理由")
    if plan_quality:
        plan_status = str(plan_quality.get("status") or "unknown")
        plan_score = int(plan_quality.get("score") or 0)
        missing = plan_quality.get("missing") or []
        missing_summary = "、".join(str(item) for item in missing[:3])
        if plan_status == "insufficient" or plan_score < 55:
            detail = f"：{missing_summary}" if missing_summary else ""
            blockers.append(f"AI 拆解任務品質不足{detail}")
        elif plan_status == "caution" or plan_score < 80:
            detail = f"：{missing_summary}" if missing_summary else ""
            warnings.append(f"AI 拆解任務仍有缺口{detail}")
    if promoted_count and market_coverage < 0.5:
        blockers.append("股價資料覆蓋率低於 50%")
    elif promoted_count and market_coverage < 1:
        warnings.append("部分股票缺少最新股價資料")
    market_trade_date_lag_days = (
        market_max_trade_date_lag_days
        if market_max_trade_date_lag_days is not None
        else _date_lag_days(
            market_latest_trade_date,
            market_database_latest_trade_date,
        )
    )
    market_trade_date_warning_suppressed = bool(
        promoted_count
        and market_coverage >= 1
        and not market_stale_count
        and not market_latest_only_count
        and market_trade_date_lag_days is not None
        and market_trade_date_lag_days <= 1
    )
    if (
        promoted_count
        and market_latest_trade_date_coverage is not None
        and market_latest_trade_date_coverage < 0.8
    ):
        if market_trade_date_warning_suppressed:
            observations.append("股價日期略有差異，系統已使用各股票最新可取得收盤資料")
        else:
            warnings.append("股價日期不一致，最新可取得交易日未覆蓋多數股票")
    if promoted_count and market_older_than_database_latest_count:
        older_ratio = market_older_than_database_latest_count / promoted_count
        message = "部分股票未取得資料庫最新交易日股價，報告僅能使用最新可取得收盤價"
        if market_trade_date_warning_suppressed:
            observations.append(message)
        elif older_ratio >= 0.5:
            warnings.append(message)
        else:
            observations.append(message)
    if promoted_count and monthly_coverage < 0.5:
        warnings.append("月營收資料覆蓋偏低")
    if promoted_count and financial_metrics_count < promoted_count * 8:
        warnings.append("五年財務資料不足，個股財務判斷信心需下修")
    if promoted_count and valuation_coverage < 0.5:
        warnings.append("估值資料覆蓋偏低")
    if stale_market_dataset_count:
        warnings.append("部分市場或財務資料使用快取救援，需刷新確認最新資料")
        if market_stale_count:
            observations.append("股價資料含快取救援來源，價格與成交量解讀需以刷新後資料覆核")
        if monthly_revenue_stale_count:
            observations.append("月營收資料含快取救援來源，成長率判斷需以最新公告覆核")
        if financial_metrics_stale_ticker_count:
            observations.append("五年財務資料含快取救援來源，財務體質結論需以最新財報覆核")
        if valuation_stale_count:
            observations.append("估值資料含快取救援來源，目前估值結論需以刷新後資料覆核")
    if latest_only_market_dataset_count:
        warnings.append("部分市場或財務資料只使用官方最新救援資料，不能代表完整歷史趨勢")
        if market_latest_only_count:
            observations.append("股價資料含官方最新救援來源，動能與區間漲跌需等待完整歷史資料覆核")
        if monthly_revenue_latest_only_count:
            observations.append(
                "月營收資料含官方最新救援來源，連續成長趨勢需等待完整月營收歷史覆核"
            )
        if financial_metrics_latest_only_ticker_count:
            observations.append(
                "財務資料含官方最新季報救援來源，五年財務趨勢需等待完整歷史財報覆核"
            )
        if valuation_latest_only_count:
            observations.append("估值資料含官方最新救援來源，同業估值比較需等待完整估值歷史覆核")
    if promoted_count and leading_signal_coverage is not None:
        if leading_signal_coverage < 0.5:
            warnings.append("近況訊號覆蓋偏低，目前情境升值/降值排序信心需下修")
        elif leading_signal_coverage < 1:
            observations.append("部分股票近況訊號不足，系統已降低排序信心")
    if promoted_count and company_filing_coverage is not None:
        if company_filing_coverage < 0.5:
            warnings.append("公司公開文件覆蓋率低於 50%，正式投入前需補年報或法說會")
        elif company_filing_coverage < 1:
            warnings.append("部分股票缺少高品質公司公開文件")
    llm_warnings, llm_observations = llm_quality_notes(llm_status)
    warnings.extend(llm_warnings)
    observations.extend(llm_observations)
    warnings.extend(rag_quality_warnings(rag_status))

    status = "ready"
    if blockers:
        status = "insufficient"
    elif warnings:
        status = "caution"
    if status == "insufficient":
        action_policy = "research_only"
        max_deployable_multiplier = 0.0
        action_label = "僅供研究，不允許投入資金"
    elif status == "caution":
        action_policy = "manual_review_required"
        max_deployable_multiplier = 0.25
        action_label = "需人工覆核，最多只可動用可投入資金的 25%"
    else:
        action_policy = "actionable"
        max_deployable_multiplier = 1.0
        action_label = "品質門檻通過，可進入個股研究；是否投入仍以後續投資建議與風險控管為準"
    deployable_amount = None
    if investor_capital is not None and cash_reserve_pct is not None:
        deployable_base = max(0, int(investor_capital * (1 - cash_reserve_pct)))
        deployable_amount = int(deployable_base * max_deployable_multiplier)
    remediation_actions = quality_remediation_actions(blockers, warnings)
    quality_gate = {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "observations": observations,
        "remediation_actions": remediation_actions,
        "action_policy": {
            "policy": action_policy,
            "label": action_label,
            "max_deployable_multiplier": max_deployable_multiplier,
            "max_deployable_amount": deployable_amount,
        },
        "metrics": {
            "promoted_count": promoted_count,
            "candidate_supported_ratio": formal_supported_ratio,
            "exploration_candidate_supported_ratio": exploration_supported_ratio,
            "formal_confidence_avg": formal_confidence_avg,
            "formal_confidence_min": formal_confidence_min,
            "formal_low_confidence_count": formal_low_confidence_count,
            "dynamic_source_count": source_count,
            "missing_subtopic_count": missing_subtopic_count,
            "weak_subtopic_count": weak_subtopic_count,
            "market_coverage": market_coverage,
            "monthly_revenue_coverage": monthly_coverage,
            "financial_metrics_count": financial_metrics_count,
            "valuation_coverage": valuation_coverage,
            "market_fresh_coverage": market_fresh_coverage,
            "monthly_revenue_fresh_coverage": monthly_fresh_coverage,
            "valuation_fresh_coverage": valuation_fresh_coverage,
            "market_stale_count": market_stale_count,
            "monthly_revenue_stale_count": monthly_revenue_stale_count,
            "financial_metrics_stale_ticker_count": financial_metrics_stale_ticker_count,
            "valuation_stale_count": valuation_stale_count,
            "stale_market_dataset_count": stale_market_dataset_count,
            "market_latest_only_count": market_latest_only_count,
            "monthly_revenue_latest_only_count": monthly_revenue_latest_only_count,
            "financial_metrics_latest_only_ticker_count": financial_metrics_latest_only_ticker_count,
            "valuation_latest_only_count": valuation_latest_only_count,
            "latest_only_market_dataset_count": latest_only_market_dataset_count,
            "market_latest_trade_date": _date_to_text(market_latest_trade_date),
            "market_latest_trade_date_coverage": market_latest_trade_date_coverage,
            "market_database_latest_trade_date": _date_to_text(market_database_latest_trade_date),
            "market_older_than_database_latest_count": int(
                market_older_than_database_latest_count or 0
            ),
            "market_trade_date_lag_days": market_trade_date_lag_days,
            "market_trade_date_warning_suppressed": market_trade_date_warning_suppressed,
            "leading_signal_coverage": leading_signal_coverage,
            "company_filing_coverage": company_filing_coverage,
            "llm_analysis_status": "fallback"
            if llm_fallback
            else "enabled"
            if llm_status
            else None,
            "llm_model": llm_status.get("model"),
            "llm_key_index": llm_status.get("key_index"),
            "llm_provider": llm_status.get("provider"),
            "llm_attempt_count": (llm_status.get("attempt_summary") or {}).get("attempt_count"),
            "llm_failed_attempt_count": (llm_status.get("attempt_summary") or {}).get(
                "failed_attempt_count"
            ),
            "llm_success_after_failure": (llm_status.get("attempt_summary") or {}).get(
                "success_after_failure"
            ),
            "llm_retry_used": (llm_status.get("attempt_summary") or {}).get("retry_used"),
            "llm_fallback_path_used": (llm_status.get("attempt_summary") or {}).get(
                "fallback_path_used"
            ),
            "llm_provider_fallback_used": (llm_status.get("attempt_summary") or {}).get(
                "provider_fallback_used"
            ),
            "llm_model_fallback_used": (llm_status.get("attempt_summary") or {}).get(
                "model_fallback_used"
            ),
            "llm_final_outcome": (llm_status.get("attempt_summary") or {}).get("final_outcome"),
            "llm_primary_failure_category": (llm_status.get("attempt_summary") or {}).get(
                "primary_failure_category"
            ),
            "llm_retryable_failure_count": (llm_status.get("attempt_summary") or {}).get(
                "retryable_failure_count"
            ),
            "llm_latency_ms": llm_observability.get("latency_ms"),
            "llm_input_token_estimate": llm_observability.get("input_token_estimate"),
            "llm_output_token_estimate": llm_observability.get("output_token_estimate"),
            "llm_total_token_estimate": llm_observability.get("total_token_estimate"),
            "llm_estimated_cost_usd": llm_observability.get("estimated_cost_usd"),
            "llm_cost_tracking_mode": llm_observability.get("cost_tracking_mode"),
            "llm_external_trace_provider": llm_observability.get("external_trace_provider"),
            "rag_retrieval_mode": rag_status.get("retrieval_mode"),
            "rag_retrieval_strategy": rag_retrieval_status.get("strategy"),
            "rag_hybrid_search_enabled": rag_retrieval_status.get("hybrid_search_enabled"),
            "rag_bm25_enabled": rag_retrieval_status.get("bm25_enabled"),
            "rag_keyword_corpus_limit": rag_retrieval_status.get("keyword_corpus_limit"),
            "rag_vector_weight": rag_retrieval_status.get("vector_weight"),
            "rag_keyword_weight": rag_retrieval_status.get("keyword_weight"),
            "rag_rerank_top_k": rag_retrieval_status.get("rerank_top_k"),
            "rag_use_chroma": rag_status.get("use_chroma"),
            "rag_chroma_available": rag_status.get("chroma_available"),
            "rag_persistent_collection_enabled": rag_status.get("persistent_collection_enabled"),
            "rag_embedding_provider": rag_embedding_status.get("provider"),
            "rag_embedding_enabled": rag_embedding_status.get("custom_embedding_enabled"),
            "rag_embedding_fallback_reason": rag_embedding_status.get("fallback_reason"),
            "rag_reranker_provider": rag_reranker_status.get("provider"),
            "rag_reranker_execution_mode": rag_reranker_status.get("execution_mode"),
            "rag_reranker_available": rag_reranker_status.get("available"),
            "rag_reranker_model_ready": (
                rag_reranker_status.get("model_reranker_ready")
                if "model_reranker_ready" in rag_reranker_status
                else (
                    None
                    if rag_reranker_provider in {"", "none", "disabled", "off"}
                    else bool(rag_reranker_status.get("available"))
                    and rag_reranker_provider not in {"keyword", "hybrid"}
                )
            ),
            "rag_reranker_quality_tier": rag_reranker_status.get("quality_tier"),
            "rag_reranker_keyword_fallback": rag_reranker_status.get("keyword_fallback"),
            "rag_reranker_model_gap": rag_reranker_status.get("model_reranker_gap"),
            "rag_reranker_fallback_reason": rag_reranker_status.get("fallback_reason"),
            "market_provider_summary": market_provider_summary,
            "source_unique_publishers": source_quality.get("unique_publisher_count"),
            "source_timestamp_coverage": source_quality.get("timestamp_coverage"),
            "source_recent_coverage": source_quality.get("recent_coverage"),
            "source_lookback_days": source_quality.get("lookback_days"),
            "source_high_credibility_ratio": source_quality.get("high_credibility_ratio"),
            "source_low_credibility_ratio": source_quality.get("low_credibility_ratio"),
            "source_average_credibility": source_quality.get("average_credibility"),
            "discovery_plan_status": plan_quality.get("status") if plan_quality else None,
            "discovery_plan_score": plan_quality.get("score") if plan_quality else None,
        },
        "recommendation": (
            "資料品質不足，請先視為研究草稿，不應作為買賣依據。"
            if status == "insufficient"
            else "資料大致可用，但仍需人工確認警示項。"
            if status == "caution"
            else "資料品質達到本系統產出投資建議的基本門檻。"
        ),
    }
    quality_gate["self_healing"] = build_quality_recovery_plan(
        blockers=blockers,
        warnings=warnings,
        metrics=quality_gate["metrics"],
        promoted_tickers=promoted_tickers,
    )
    return quality_gate


def _peer_valuation_summary(valuations) -> dict[str, float | None]:
    pe_values = [
        valuation.pe_ratio
        for valuation in valuations
        if valuation.pe_ratio is not None and valuation.pe_ratio > 0
    ]
    pb_values = [
        valuation.pb_ratio
        for valuation in valuations
        if valuation.pb_ratio is not None and valuation.pb_ratio > 0
    ]
    return {
        "pe_avg": sum(pe_values) / len(pe_values) if pe_values else None,
        "pb_avg": sum(pb_values) / len(pb_values) if pb_values else None,
    }


def build_quality_gate_for_request(
    request: ReportRequest,
    documents: list[NewsDocument] | None = None,
    source_count: int | None = None,
    llm_result: object | None = None,
    company_filing_sufficient_count: int | None = None,
    candidate_support: dict | None = None,
    plan_quality: dict | None = None,
) -> dict:
    tickers = list(dict.fromkeys(request.tickers))
    if not tickers:
        tickers = EntityMapper().filter_allowed_tickers(request.tickers)
    source_count = len(documents or []) if source_count is None else source_count
    source_quality = (
        summarize_document_source_quality(documents or [], request.lookback_days)
        if documents
        else None
    )
    source_audit = {
        "candidate_support": candidate_support
        or {
            "total": len(tickers),
            "supported": len(tickers),
            "unsupported": 0,
            "supported_ratio": 1.0 if tickers else 0.0,
        },
        "dynamic_queries": {"stored_count": source_count},
    }
    with session_scope() as session:
        snapshots = MarketRepository(session).latest_by_tickers(tickers)
        monthly_revenues = MonthlyRevenueRepository(session).latest_by_tickers(tickers)
        financial_metrics = FinancialMetricRepository(session).by_tickers(tickers)
        valuations = ValuationMetricRepository(session).latest_by_tickers(tickers)
        market_count = len(snapshots)
        monthly_revenue_count = len(monthly_revenues)
        financial_metrics_count = len(financial_metrics)
        valuation_count = len(valuations)
        market_stale_count = _stale_market_data_count(snapshots)
        monthly_revenue_stale_count = _stale_market_data_count(monthly_revenues)
        financial_metrics_stale_ticker_count = _stale_financial_metric_ticker_count(
            financial_metrics
        )
        valuation_stale_count = _stale_market_data_count(valuations)
        market_latest_only_count = _latest_only_market_data_count(snapshots)
        monthly_revenue_latest_only_count = _latest_only_market_data_count(monthly_revenues)
        financial_metrics_latest_only_ticker_count = _latest_only_financial_metric_ticker_count(
            financial_metrics
        )
        valuation_latest_only_count = _latest_only_market_data_count(valuations)
        market_repository = MarketRepository(session)
        latest_trade_date = (
            market_repository.latest_trade_date()
            if callable(getattr(market_repository, "latest_trade_date", None))
            else None
        )
        market_date_summary = market_trade_date_summary(
            snapshots,
            tickers,
            latest_trade_date,
        )
        price_histories = market_repository.history_by_tickers(tickers, limit=90)
        revenue_histories = MonthlyRevenueRepository(session).history_by_tickers(tickers, limit=18)
    valuation_map = {valuation.ticker: valuation for valuation in valuations}
    peer_summary = _peer_valuation_summary(valuations)
    leading_signals = LeadingSignalAnalyzer().build(
        tickers, price_histories, revenue_histories, valuation_map, peer_summary
    )
    leading_signal_count = sum(1 for signal in leading_signals.values() if signal.has_signal_data)
    return build_report_quality_gate(
        source_audit,
        tickers,
        market_count=market_count,
        monthly_revenue_count=monthly_revenue_count,
        financial_metrics_count=financial_metrics_count,
        valuation_count=valuation_count,
        investor_capital=request.investor_capital,
        cash_reserve_pct=request.cash_reserve_pct,
        source_quality=source_quality,
        plan_quality=plan_quality,
        leading_signal_count=leading_signal_count,
        llm_status=summarize_llm_status(llm_result),
        company_filing_sufficient_count=company_filing_sufficient_count,
        market_stale_count=market_stale_count,
        monthly_revenue_stale_count=monthly_revenue_stale_count,
        financial_metrics_stale_ticker_count=financial_metrics_stale_ticker_count,
        valuation_stale_count=valuation_stale_count,
        market_latest_only_count=market_latest_only_count,
        monthly_revenue_latest_only_count=monthly_revenue_latest_only_count,
        financial_metrics_latest_only_ticker_count=financial_metrics_latest_only_ticker_count,
        valuation_latest_only_count=valuation_latest_only_count,
        rag_status=rag_runtime_status(),
        market_provider_summary=market_provider_summary(
            snapshots,
            monthly_revenues,
            financial_metrics,
            valuations,
        ),
        market_latest_trade_date=market_date_summary["latest_trade_date"],
        market_latest_trade_date_coverage=market_date_summary["latest_trade_date_coverage"],
        market_database_latest_trade_date=market_date_summary["database_latest_trade_date"],
        market_older_than_database_latest_count=market_date_summary[
            "older_than_database_latest_count"
        ],
        market_max_trade_date_lag_days=market_date_summary["max_trade_date_lag_days"],
    )
