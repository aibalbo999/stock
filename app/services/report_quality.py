from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from importlib.util import find_spec

from app.core.config import get_settings
from app.core.time import now_taipei
from app.db.session import session_scope
from app.models.schemas import NewsDocument, ReportRequest, ReportResponse
from app.rag.reranker import RagReranker
from app.rag.vector_store import VectorStore
from app.services.candidate_confidence import format_confidence_score
from app.services.entity_mapping import EntityMapper
from app.services.leading_signals import LeadingSignalAnalyzer
from app.services.llm_client import summarize_llm_attempts
from app.services.persistence import (
    FinancialMetricRepository,
    MarketRepository,
    MonthlyRevenueRepository,
    ValuationMetricRepository,
)
from app.services.report_orchestrator import build_quality_recovery_plan
from app.services.source_quality import summarize_source_credibility


STALE_MARKET_SOURCE_MARKER = "cached-stale"
LATEST_ONLY_MARKET_SOURCE_MARKER = "latest-only"


def should_recover_market_data_quality(quality_gate: dict | None) -> bool:
    if not isinstance(quality_gate, dict):
        return False
    metrics = quality_gate.get("metrics") or {}
    issue_text = "；".join(
        [
            *[str(item) for item in quality_gate.get("blockers") or []],
            *[str(item) for item in quality_gate.get("warnings") or []],
            *[str(item) for item in quality_gate.get("remediation_actions") or []],
        ]
    )
    market_coverage = metrics.get("market_coverage")
    market_latest_trade_date_coverage = metrics.get("market_latest_trade_date_coverage")
    return bool(
        (market_coverage is not None and float(market_coverage or 0) < 1)
        or int(metrics.get("market_stale_count") or 0)
        or int(metrics.get("market_latest_only_count") or 0)
        or int(metrics.get("market_older_than_database_latest_count") or 0)
        or (
            market_latest_trade_date_coverage is not None
            and float(market_latest_trade_date_coverage or 0) < 0.8
        )
        or any(term in issue_text for term in ["股價資料覆蓋率", "股價日期不一致", "資料庫最新交易日股價"])
    )


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
        candidate_support.get("exploration_supported_ratio", candidate_support.get("supported_ratio")) or 0
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
    market_fresh_coverage = max(0, market_count - market_stale_count) / promoted_count if promoted_count else 0
    monthly_fresh_coverage = (
        max(0, monthly_revenue_count - monthly_revenue_stale_count) / promoted_count if promoted_count else 0
    )
    valuation_fresh_coverage = max(0, valuation_count - valuation_stale_count) / promoted_count if promoted_count else 0
    leading_signal_coverage = leading_signal_count / promoted_count if promoted_count and leading_signal_count is not None else None
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
        is_financial_subtopic = any(term in lower_name for term in ["財務", "估值", "股價", "營收", "現金流"])
        if is_financial_subtopic and market_count > 0 and monthly_revenue_count > 0 and valuation_count > 0 and financial_metrics_count > 0:
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
    timestamp_coverage = float(source_quality.get("timestamp_coverage") or 0) if source_quality else 0
    recent_coverage = float(source_quality.get("recent_coverage") or 0) if source_quality else 0
    source_lookback_days = int(source_quality.get("lookback_days") or 90) if source_quality else 90
    high_credibility_ratio = source_quality.get("high_credibility_ratio")
    low_credibility_ratio = source_quality.get("low_credibility_ratio")
    rag_status = rag_status or {}
    rag_embedding_status = rag_status.get("embedding_status") or {}
    rag_reranker_status = rag_status.get("reranker_status") or {}
    rag_reranker_provider = str(
        rag_reranker_status.get("normalized_provider") or rag_reranker_status.get("provider") or ""
    ).lower().replace("-", "_")
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
            observations.append(f"主題拆解仍有 {weak_subtopic_count} 個子題可持續追蹤，已由多來源資料覆蓋主要結論")
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
        if high_credibility_ratio is not None and source_count >= 8 and float(high_credibility_ratio) < 0.35:
            warnings.append("高可信來源比例偏低，正式結論需補官方文件或主流財經新聞")
        if low_credibility_ratio is not None and source_count >= 8 and float(low_credibility_ratio) > 0.35:
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
    if promoted_count and market_latest_trade_date_coverage is not None and market_latest_trade_date_coverage < 0.8:
        warnings.append("股價日期不一致，最新可取得交易日未覆蓋多數股票")
    if promoted_count and market_older_than_database_latest_count:
        older_ratio = market_older_than_database_latest_count / promoted_count
        message = "部分股票未取得資料庫最新交易日股價，報告僅能使用最新可取得收盤價"
        if older_ratio >= 0.5:
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
            observations.append("月營收資料含官方最新救援來源，連續成長趨勢需等待完整月營收歷史覆核")
        if financial_metrics_latest_only_ticker_count:
            observations.append("財務資料含官方最新季報救援來源，五年財務趨勢需等待完整歷史財報覆核")
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
    if llm_status:
        llm_attempt_summary = llm_status.get("attempt_summary") or {}
        if llm_fallback:
            warnings.append("LLM 補充分析未啟用或呼叫失敗，個股結論需視為規則引擎草稿")
        elif llm_attempt_summary.get("success_after_failure"):
            observations.append("LLM 補充分析已完成，但曾經重試或切換備援模型；模型穩定性需持續觀察")
        else:
            observations.append("LLM 補充分析已完成，且仍受來源與白名單驗證約束")
    if rag_status:
        if rag_status.get("use_chroma") and not rag_status.get("chroma_available"):
            warnings.append("RAG 向量庫套件不可用，檢索已退回本輪資料與關鍵字排序")
        if (
            rag_status.get("use_chroma")
            and rag_embedding_status.get("custom_embedding_requested")
            and not rag_embedding_status.get("custom_embedding_enabled")
        ):
            if rag_embedding_status.get("chroma_default_fallback_allowed"):
                warnings.append("RAG 自訂 embedding 未啟用，已退回 Chroma 預設模型，繁中檢索信心需下修")
            else:
                warnings.append("RAG 自訂 embedding 未啟用，已停用持久化向量庫並退回關鍵字檢索")
        if (
            rag_reranker_status
            and rag_reranker_provider in {"keyword", "hybrid"}
        ):
            warnings.append("RAG reranker 目前僅使用關鍵字排序，尚未啟用模型級重排序，來源排序信心需人工覆核")
        elif (
            rag_reranker_status
            and rag_reranker_status.get("keyword_fallback")
            and not rag_reranker_status.get("model_reranker_ready")
        ):
            warnings.append("RAG reranker auto 模式已退回關鍵字排序，模型級重排序尚未可用，來源排序信心需人工覆核")
        elif (
            rag_reranker_status
            and rag_reranker_provider not in {"", "none", "disabled", "off"}
            and not rag_reranker_status.get("model_reranker_ready", rag_reranker_status.get("available"))
        ):
            warnings.append("RAG reranker 未啟用或推論失敗，檢索排序信心需人工覆核")

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
            "market_older_than_database_latest_count": int(market_older_than_database_latest_count or 0),
            "leading_signal_coverage": leading_signal_coverage,
            "company_filing_coverage": company_filing_coverage,
            "llm_analysis_status": "fallback" if llm_fallback else "enabled" if llm_status else None,
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


def quality_remediation_actions(blockers: list[str], warnings: list[str]) -> list[str]:
    issue_text = "；".join([*blockers, *warnings])
    actions = []
    rules = [
        (
            ("沒有通過證據驗證",),
            "重新執行主題拆解，要求 AI 補查公司與主題的直接證據後再產生正式股票。",
        ),
        (
            ("候選公司證據覆蓋率低於 25%", "候選公司證據覆蓋率低於 60%"),
            "保留已升格的正式股票，對弱證據候選補抓公司新聞、法說會與供應鏈資料後再做二次篩選。",
        ),
        (
            ("低信心證據公司",),
            "對低信心正式股票補抓近期、有日期且不同發布者的公司來源，未補齊前不得產生買入建議。",
        ),
        (
            ("AI 動態資料來源入庫篇數過少", "AI 動態資料來源偏少"),
            "增加查詢子題、拉長回溯天數或開啟深度分析，至少補足 12 篇以上可追溯來源。",
        ),
        (
            ("來源時間戳覆蓋率", "缺少發布日期"),
            "優先改用有發布日期的來源，無日期資料只作背景參考，不納入關鍵風險或估值推論。",
        ),
        (
            ("資料來源發布者過於單一", "資料來源多樣性偏低"),
            "補入不同發布者與國際資料源，避免單一媒體或單一市場觀點主導結論。",
        ),
        (
            ("高可信來源比例偏低", "投資網誌或社群型來源比例偏高"),
            "優先補官方公告、交易所資料、法說會與主流財經新聞；投資網誌僅作輔助訊號，不可作為配置理由。",
        ),
        (
            ("來源比例偏低", "近期資料比例偏低"),
            "補抓最近期間資料，確認產能、訂單、法規與目前估值假設仍然有效。",
        ),
        (
            ("AI 拆解任務品質",),
            "請 AI 重新拆解分析任務，補齊缺漏的產業子題、風險瓶頸、估值與個股研究任務。",
        ),
        (
            ("完全缺少相關來源", "來源或資料意圖不足"),
            "針對缺來源或弱來源子題自動補抓資料；補足後重新驗證子題覆蓋，再重跑分析。",
        ),
        (
            ("股價資料覆蓋率", "股價日期不一致", "資料庫最新交易日股價"),
            "刷新股價與市值資料，缺資料股票不得產生買入或加碼建議。",
        ),
        (
            ("月營收資料覆蓋",),
            "補齊月營收資料，並把缺資料股票的成長判斷降為低信心。",
        ),
        (
            ("五年財務資料不足",),
            "補齊近五年財務指標，未補齊前不得給出高信心財務體質結論。",
        ),
        (
            ("估值資料覆蓋",),
            "補齊同業估值、P/E 與 DCF 假設，估值缺口未補齊前只保留觀察結論。",
        ),
        (
            ("快取救援",),
            "重新刷新股價、月營收、五年財務與估值資料；快取救援資料只能作暫時參考，不可單獨支撐配置決策。",
        ),
        (
            ("官方最新救援資料",),
            "補齊完整歷史股價、月營收、五年財務與估值資料；官方最新救援資料只能確認近況，不可推論長期趨勢。",
        ),
        (
            ("公司公開文件覆蓋", "高品質公司公開文件"),
            "補抓或人工匯入年報、法說會與官方 IR 文件；未補齊前不得把個股列為可投入資金標的。",
        ),
        (
            ("近況訊號覆蓋", "領先訊號覆蓋"),
            "補齊股價歷史、成交量、月營收與估值資料，避免只靠新聞排序目前情境升值與降值標的。",
        ),
        (
            ("LLM 補充分析",),
            "檢查 LLM API key、供應商狀態與重試策略；模型恢復後重新產生報告並保留事實核查。",
        ),
        (
            ("RAG 自訂 embedding", "RAG 向量庫", "RAG reranker"),
            "檢查 RAG embedding、向量庫與 reranker 設定；恢復後重新產生報告並重新核對來源歸屬。",
        ),
    ]
    for keywords, action in rules:
        if any(keyword in issue_text for keyword in keywords):
            actions.append(action)
    if issue_text and not actions:
        actions.append("先補齊品質警示所列資料缺口，再重新執行完整分析。")
    return _dedupe(actions)


def _dedupe(items: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def summarize_document_source_quality(documents: list[NewsDocument], lookback_days: int) -> dict:
    total = len(documents)
    if not total:
        return {
            "total_documents": 0,
            "unique_publisher_count": 0,
            "timestamped_count": 0,
            "timestamp_coverage": 0,
            "recent_count": 0,
            "recent_coverage": 0,
            "lookback_days": lookback_days,
            "publisher_sample": [],
            "average_credibility": None,
            "high_credibility_count": 0,
            "low_credibility_count": 0,
            "high_credibility_ratio": None,
            "low_credibility_ratio": None,
            "credibility_tier_counts": {},
        }
    cutoff = now_taipei().date() - timedelta(days=max(1, lookback_days))
    publishers = {
        _normalize_publisher(document.source.publisher or document.source.url or document.source.title)
        for document in documents
        if _normalize_publisher(document.source.publisher or document.source.url or document.source.title)
    }
    published_dates = [
        _source_date(document.source.published_at)
        for document in documents
        if _source_date(document.source.published_at) is not None
    ]
    recent_count = sum(1 for published_at in published_dates if published_at >= cutoff)
    return {
        "total_documents": total,
        "unique_publisher_count": len(publishers),
        "timestamped_count": len(published_dates),
        "timestamp_coverage": len(published_dates) / total,
        "recent_count": recent_count,
        "recent_coverage": recent_count / total,
        "lookback_days": lookback_days,
        "publisher_sample": sorted(publishers)[:5],
        **_source_credibility_quality(documents),
    }


def _source_credibility_quality(documents: list[NewsDocument]) -> dict:
    credibility = summarize_source_credibility(documents)
    return {
        "average_credibility": credibility["average_weight"],
        "high_credibility_count": credibility["high_credibility_count"],
        "low_credibility_count": credibility["low_credibility_count"],
        "high_credibility_ratio": credibility["high_credibility_ratio"],
        "low_credibility_ratio": credibility["low_credibility_ratio"],
        "credibility_tier_counts": credibility["tier_counts"],
    }


def _source_date(value: date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


def _date_to_text(value: date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _normalize_publisher(value: str | None) -> str:
    return (value or "").strip()


def is_stale_market_data_source(source: object) -> bool:
    return STALE_MARKET_SOURCE_MARKER in str(source or "").lower()


def is_latest_only_market_data_source(source: object) -> bool:
    return LATEST_ONLY_MARKET_SOURCE_MARKER in str(source or "").lower()


def _is_stale_market_data(row: object) -> bool:
    return is_stale_market_data_source(getattr(row, "source", ""))


def _is_latest_only_market_data(row: object) -> bool:
    return is_latest_only_market_data_source(getattr(row, "source", ""))


def _stale_market_data_count(rows: list[object]) -> int:
    return sum(1 for row in rows if _is_stale_market_data(row))


def _stale_financial_metric_ticker_count(metrics: list[object]) -> int:
    return len({str(getattr(metric, "ticker", "")) for metric in metrics if _is_stale_market_data(metric)})


def _latest_only_market_data_count(rows: list[object]) -> int:
    return sum(1 for row in rows if _is_latest_only_market_data(row))


def _latest_only_financial_metric_ticker_count(metrics: list[object]) -> int:
    return len({str(getattr(metric, "ticker", "")) for metric in metrics if _is_latest_only_market_data(metric)})


def market_trade_date_summary(
    snapshots: list[object],
    promoted_tickers: list[str],
    database_latest_trade_date: date | None = None,
) -> dict:
    ticker_dates = {
        str(getattr(snapshot, "ticker", "")): getattr(snapshot, "trade_date", None)
        for snapshot in snapshots
        if getattr(snapshot, "ticker", None) and getattr(snapshot, "trade_date", None)
    }
    dates = list(ticker_dates.values())
    if not dates:
        return {
            "latest_trade_date": None,
            "latest_trade_date_coverage": None,
            "database_latest_trade_date": database_latest_trade_date,
            "older_than_database_latest_count": 0,
        }
    latest_trade_date = max(dates)
    latest_count = sum(1 for value in dates if value == latest_trade_date)
    promoted_count = len(promoted_tickers)
    database_latest_trade_date = database_latest_trade_date or latest_trade_date
    older_than_database_latest_count = sum(
        1
        for ticker in promoted_tickers
        if ticker_dates.get(ticker) is not None and ticker_dates[ticker] < database_latest_trade_date
    )
    return {
        "latest_trade_date": latest_trade_date,
        "latest_trade_date_coverage": latest_count / promoted_count if promoted_count else None,
        "database_latest_trade_date": database_latest_trade_date,
        "older_than_database_latest_count": older_than_database_latest_count,
    }


def _peer_valuation_summary(valuations) -> dict[str, float | None]:
    pe_values = [valuation.pe_ratio for valuation in valuations if valuation.pe_ratio is not None and valuation.pe_ratio > 0]
    pb_values = [valuation.pb_ratio for valuation in valuations if valuation.pb_ratio is not None and valuation.pb_ratio > 0]
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
    source_quality = summarize_document_source_quality(documents or [], request.lookback_days) if documents else None
    source_audit = {
        "candidate_support": candidate_support or {
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
        financial_metrics_stale_ticker_count = _stale_financial_metric_ticker_count(financial_metrics)
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
    leading_signals = LeadingSignalAnalyzer().build(tickers, price_histories, revenue_histories, valuation_map, peer_summary)
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
        market_older_than_database_latest_count=market_date_summary["older_than_database_latest_count"],
    )


def summarize_llm_status(llm_result: object | None) -> dict | None:
    if llm_result is None:
        return None
    attempts = getattr(llm_result, "attempts", ())
    return {
        "fallback": bool(getattr(llm_result, "fallback", False)),
        "model": getattr(llm_result, "model", None),
        "key_index": getattr(llm_result, "key_index", None),
        "provider": getattr(llm_result, "provider", None),
        "attempt_summary": summarize_llm_attempts(attempts),
        "attempts": list(attempts[-10:]) if isinstance(attempts, (tuple, list)) else [],
    }


def rag_runtime_status() -> dict:
    settings = get_settings()
    embedding_status = VectorStore.runtime_embedding_provider_status(settings)
    retrieval_status = VectorStore.retrieval_runtime_status(settings)
    chroma_available = _module_available("chromadb")
    persistent_collection_enabled = _rag_persistent_collection_enabled(
        settings,
        embedding_status,
        chroma_available,
    )
    reranker_status = RagReranker().status()
    return {
        "use_chroma": bool(settings.use_chroma),
        "chroma_available": chroma_available,
        "persistent_collection_enabled": persistent_collection_enabled,
        "retrieval_mode": "chroma_hybrid" if persistent_collection_enabled else "memory_hybrid",
        "retrieval_status": retrieval_status,
        "embedding_status": embedding_status,
        "reranker_status": reranker_status,
    }


def _rag_persistent_collection_enabled(settings, embedding_status: dict, chroma_available: bool) -> bool:
    if not settings.use_chroma:
        return False
    if not chroma_available:
        return False
    if not embedding_status.get("custom_embedding_requested"):
        return True
    if embedding_status.get("custom_embedding_enabled"):
        return True
    return bool(settings.rag_allow_chroma_default_embedding_fallback)


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def market_provider_summary(
    snapshots: list[object],
    monthly_revenues: list[object],
    financial_metrics: list[object],
    valuations: list[object],
) -> dict:
    return {
        "price_history": _market_source_summary("股價", snapshots),
        "monthly_revenue": _market_source_summary("月營收", monthly_revenues),
        "financial_metrics": _market_source_summary("五年財務", financial_metrics),
        "valuation": _market_source_summary("估值", valuations),
    }


def _market_source_summary(label: str, rows: list[object]) -> dict:
    sources = _unique_market_sources(rows)
    return {
        "label": label,
        "row_count": len(rows),
        "sources": sources,
        "providers": _market_provider_names(sources),
        "stale_count": _stale_market_data_count(rows),
        "latest_only_count": _latest_only_market_data_count(rows),
    }


def _unique_market_sources(rows: list[object]) -> list[str]:
    sources: list[str] = []
    for row in rows:
        source = str(getattr(row, "source", "") or "").strip()
        if source and source not in sources:
            sources.append(source)
    return sources


def _market_provider_names(sources: list[str]) -> list[str]:
    providers: list[str] = []
    for source in sources:
        provider = _market_provider_name(source)
        if provider and provider not in providers:
            providers.append(provider)
    return providers


def _market_provider_name(source: str) -> str:
    normalized = source.lower()
    if "fugle" in normalized:
        return "Fugle"
    if "finmind" in normalized:
        return "FinMind"
    if "twse openapi" in normalized:
        return "TWSE OpenAPI"
    if "tpex openapi" in normalized:
        return "TPEx OpenAPI"
    if STALE_MARKET_SOURCE_MARKER in normalized:
        return "Redis cached-stale"
    return source.split()[0] if source else ""


def render_quality_gate_markdown(quality_gate: dict) -> str:
    labels = {
        "ready": "資料品質可用",
        "caution": "需謹慎判讀",
        "insufficient": "資料不足",
    }
    metrics = quality_gate.get("metrics") or {}
    action_policy = quality_gate.get("action_policy") or {}
    lines = [
        "## 報告品質門檻",
        f"- 狀態：{labels.get(quality_gate.get('status'), quality_gate.get('status', 'unknown'))}",
        f"- 系統判斷：{quality_gate.get('recommendation', '目前無足夠數據判斷。')}",
        f"- 投資行動狀態：{action_policy.get('label', '目前無足夠數據判斷。')}",
        f"- 正式分析股票：{metrics.get('promoted_count', 0)} 檔",
        f"- 候選公司證據覆蓋率：{float(metrics.get('candidate_supported_ratio') or 0):.0%}",
        f"- 探索候選覆蓋率：{float(metrics.get('exploration_candidate_supported_ratio') or 0):.0%}",
        f"- 正式股票證據信心：平均 {_format_confidence_score(metrics.get('formal_confidence_avg'))} / "
        f"最低 {_format_confidence_score(metrics.get('formal_confidence_min'))}",
        f"- 自動搜尋來源入庫：{metrics.get('dynamic_source_count', 0)} 篇",
        f"- 來源發布者數：{_format_optional_int(metrics.get('source_unique_publishers'))}",
        f"- 來源時間戳覆蓋率：{_format_optional_percent(metrics.get('source_timestamp_coverage'))}",
        f"- 近 {int(metrics.get('source_lookback_days') or 90)} 天來源比例：{_format_optional_percent(metrics.get('source_recent_coverage'))}",
        f"- 高可信來源比例：{_format_optional_percent(metrics.get('source_high_credibility_ratio'))}",
        f"- 投資網誌/社群型來源比例：{_format_optional_percent(metrics.get('source_low_credibility_ratio'))}",
        f"- 拆解任務品質：{_format_plan_quality(metrics)}",
        f"- 模型補充分析：{_format_llm_status(metrics)}",
        f"- 資料檢索狀態：{_format_rag_status(metrics)}",
        f"- 市場資料來源：{_format_market_provider_summary(metrics)}",
        f"- 股價資料覆蓋率：{float(metrics.get('market_coverage') or 0):.0%}",
        "- 股價最新可取得交易日："
        f"{metrics.get('market_latest_trade_date') or '尚無'}"
        f"（同日覆蓋率 {_format_optional_percent(metrics.get('market_latest_trade_date_coverage'))}；"
        f"資料庫最新交易日 {metrics.get('market_database_latest_trade_date') or '尚無'}；"
        f"落後資料庫最新日 {int(metrics.get('market_older_than_database_latest_count') or 0)} 檔）",
        f"- 月營收資料覆蓋率：{float(metrics.get('monthly_revenue_coverage') or 0):.0%}",
        f"- 估值資料覆蓋率：{float(metrics.get('valuation_coverage') or 0):.0%}",
        "- 快取救援資料："
        f"股價 {int(metrics.get('market_stale_count') or 0)} 檔、"
        f"月營收 {int(metrics.get('monthly_revenue_stale_count') or 0)} 檔、"
        f"五年財務 {int(metrics.get('financial_metrics_stale_ticker_count') or 0)} 檔、"
        f"估值 {int(metrics.get('valuation_stale_count') or 0)} 檔",
        "- 官方最新救援資料："
        f"股價 {int(metrics.get('market_latest_only_count') or 0)} 檔、"
        f"月營收 {int(metrics.get('monthly_revenue_latest_only_count') or 0)} 檔、"
        f"五年財務 {int(metrics.get('financial_metrics_latest_only_ticker_count') or 0)} 檔、"
        f"估值 {int(metrics.get('valuation_latest_only_count') or 0)} 檔",
        f"- 近況訊號覆蓋率：{_format_optional_percent(metrics.get('leading_signal_coverage'))}",
        f"- 公司公開文件覆蓋率：{_format_optional_percent(metrics.get('company_filing_coverage'))}",
    ]
    if action_policy.get("max_deployable_amount") is not None:
        lines.append(
            f"- 品質門檻研究額度上限：約 {int(action_policy['max_deployable_amount']):,} 元"
            "（不是本次配置或買進指令；本次是否投入仍以投資建議與資金控管為準）"
        )
    blockers = quality_gate.get("blockers") or []
    warnings = quality_gate.get("warnings") or []
    observations = quality_gate.get("observations") or []
    if blockers:
        lines.append("- 阻擋項：" + "；".join(_investor_friendly_issue(item) for item in blockers))
    if warnings:
        lines.append("- 警示項：" + "；".join(_investor_friendly_issue(item) for item in warnings))
    if observations:
        lines.append("- 觀察項：" + "；".join(_investor_friendly_issue(item) for item in observations))
    remediation_actions = quality_gate.get("remediation_actions") or []
    if remediation_actions:
        lines.append("- 建議補強：" + "；".join(_investor_friendly_issue(action) for action in remediation_actions))
    self_healing = quality_gate.get("self_healing") or {}
    self_healing_actions = self_healing.get("actions") or []
    if self_healing_actions:
        action_labels = "、".join(
            str(action.get("action_type") or action.get("tool") or "補強任務")
            for action in self_healing_actions[:8]
            if isinstance(action, dict)
        )
        lines.append(
            f"- 自癒補強計畫：{self_healing.get('status', 'planned')}；"
            f"{len(self_healing_actions)} 個任務（{action_labels}）"
        )
    if not blockers and not warnings:
        lines.append("- 阻擋/警示：無")
    return "\n".join(lines)


def _format_optional_int(value: object) -> str:
    return "未評估" if value is None else str(value)


def _format_optional_number(value: object) -> str:
    if value is None:
        return "未評估"
    number = float(value)
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def _format_confidence_score(value: object) -> str:
    return format_confidence_score(float(value)) if value is not None else "信心分數未匯入品質門檻"


def _format_optional_percent(value: object) -> str:
    return "未評估" if value is None else f"{float(value or 0):.0%}"


def _format_plan_quality(metrics: dict) -> str:
    status = metrics.get("discovery_plan_status")
    score = metrics.get("discovery_plan_score")
    if status is None and score is None:
        return "未評估"
    labels = {
        "ready": "完整",
        "caution": "需補強",
        "insufficient": "不足",
    }
    label = labels.get(str(status), str(status or "unknown"))
    return f"{label}（{int(score or 0)} 分）"


def _format_llm_status(metrics: dict) -> str:
    status = metrics.get("llm_analysis_status")
    if status == "enabled":
        model = metrics.get("llm_model") or "unknown"
        provider = metrics.get("llm_provider")
        provider_text = f"，provider：{provider}" if provider else ""
        recovery_bits = []
        if metrics.get("llm_retry_used"):
            recovery_bits.append("曾重試")
        if metrics.get("llm_model_fallback_used"):
            recovery_bits.append("已切換備援模型")
        elif metrics.get("llm_provider_fallback_used"):
            recovery_bits.append("已切換備援供應商")
        recovery_text = f"，{ '、'.join(recovery_bits) }" if recovery_bits else ""
        return f"已啟用（模型：{model}{provider_text}{recovery_text}）"
    if status == "fallback":
        reason = metrics.get("llm_primary_failure_category")
        reason_text = f"；主要原因：{reason}" if reason else ""
        return f"未啟用或呼叫失敗，已改用資料規則判讀{reason_text}"
    return "未評估"


def _format_rag_status(metrics: dict) -> str:
    if metrics.get("rag_retrieval_mode") is None and metrics.get("rag_reranker_execution_mode") is None:
        return "未評估"
    retrieval_labels = {
        "chroma_hybrid": "向量庫 + 關鍵字混合檢索",
        "memory_hybrid": "本輪資料 + 關鍵字檢索",
    }
    reranker_labels = {
        "keyword": "關鍵字排序 fallback",
        "cross_encoder": "cross-encoder 重排序",
        "cohere_api": "Cohere API 重排序",
        "llm_rerank": "LLM 模型重排序",
        "input_order": "原排序",
        "input_order_fallback": "重排序 fallback",
    }
    retrieval = retrieval_labels.get(
        str(metrics.get("rag_retrieval_mode") or ""),
        str(metrics.get("rag_retrieval_mode") or "未評估"),
    )
    reranker = reranker_labels.get(
        str(metrics.get("rag_reranker_execution_mode") or ""),
        str(metrics.get("rag_reranker_execution_mode") or "未評估"),
    )
    embedding_fallback = metrics.get("rag_embedding_fallback_reason")
    reranker_fallback = metrics.get("rag_reranker_fallback_reason")
    reranker_gap = metrics.get("rag_reranker_model_gap")
    fallback_notes = []
    if embedding_fallback and embedding_fallback != "chroma_default_requested":
        fallback_notes.append(f"embedding：{embedding_fallback}")
    if reranker_fallback:
        fallback_notes.append(f"reranker：{reranker_fallback}")
    elif reranker_gap:
        fallback_notes.append(f"reranker：{reranker_gap}")
    suffix = "；" + "、".join(fallback_notes) if fallback_notes else ""
    bm25_note = ""
    if metrics.get("rag_bm25_enabled") is True:
        corpus_limit = metrics.get("rag_keyword_corpus_limit")
        if corpus_limit is not None:
            bm25_note = f"，BM25 keyword corpus {int(corpus_limit):,} 筆"
        else:
            bm25_note = "，BM25 關鍵字檢索啟用"
    elif metrics.get("rag_hybrid_search_enabled") is False:
        bm25_note = "，BM25 關鍵字檢索未啟用"
    return f"{retrieval}，{reranker}{bm25_note}{suffix}"


def _format_market_provider_summary(metrics: dict) -> str:
    summary = metrics.get("market_provider_summary") or {}
    if not summary:
        return "未評估"
    parts = []
    for key in ("price_history", "monthly_revenue", "financial_metrics", "valuation"):
        item = summary.get(key) or {}
        label = item.get("label") or key
        providers = item.get("providers") or []
        provider_text = "、".join(str(provider) for provider in providers) if providers else "未入庫"
        stale_count = int(item.get("stale_count") or 0)
        latest_only_count = int(item.get("latest_only_count") or 0)
        notes = []
        if stale_count:
            notes.append(f"含快取救援 {stale_count} 筆")
        if latest_only_count:
            notes.append(f"含官方最新救援 {latest_only_count} 筆")
        if notes:
            provider_text = f"{provider_text}（{'；'.join(notes)}）"
        parts.append(f"{label} {provider_text}")
    return "；".join(parts)


def _investor_friendly_issue(item: object) -> str:
    text = str(item)
    replacements = {
        "LLM 補充分析未啟用或呼叫失敗，個股結論需視為規則引擎草稿": (
            "模型補充分析未啟用或呼叫失敗，個股結論主要由資料規則產生，需人工覆核"
        ),
        "LLM 補充分析已完成，且仍受來源與白名單驗證約束": (
            "模型補充分析已完成，仍只採用可追溯來源與白名單公司"
        ),
        "LLM 補充分析已完成，但曾經重試或切換備援模型；模型穩定性需持續觀察": (
            "模型補充分析已完成，但曾經重試或切換備援模型；模型連線穩定性需持續觀察"
        ),
        "AI 動態資料來源": "自動搜尋資料來源",
        "AI 拆解": "主題拆解",
        "LLM 補充分析": "模型補充分析",
        "檢查 LLM API key、供應商狀態與重試策略；模型恢復後重新產生報告並保留事實核查。": (
            "請系統管理者恢復模型補充分析，恢復後重新產生報告並保留事實核查。"
        ),
        "LLM API key": "模型連線設定",
        "官方 IR 文件": "官方投資人關係文件",
        "規則引擎草稿": "資料規則草稿",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def parse_quality_gate_from_markdown(markdown: str) -> dict | None:
    section = _markdown_section(markdown, "報告品質門檻")
    if not section:
        return None
    fields: dict[str, str] = {}
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("- ") or "：" not in line:
            continue
        key, value = line[2:].split("：", 1)
        fields[key.strip()] = value.strip()

    status_map = {
        "資料品質可用": "ready",
        "需謹慎判讀": "caution",
        "資料不足": "insufficient",
    }
    action_label = fields.get("投資行動狀態", "目前無足夠數據判斷。")
    dynamic_source_field = fields.get("自動搜尋來源入庫") or fields.get("AI 動態來源入庫")
    llm_field = fields.get("模型補充分析") or fields.get("LLM 補充分析")
    recent_source_field = _first_matching_value(fields, r"近\s*\d+\s*天來源比例") or fields.get("近期資料比例")
    return {
        "status": status_map.get(fields.get("狀態", ""), "unknown"),
        "blockers": _split_issue_field(fields.get("阻擋項")),
        "warnings": _split_issue_field(fields.get("警示項")),
        "observations": _split_issue_field(fields.get("觀察項")),
        "remediation_actions": _split_issue_field(fields.get("建議補強")),
        "action_policy": {
            "label": action_label,
            "max_deployable_amount": _parse_amount(
                fields.get("品質門檻研究額度上限")
                or fields.get("品質通過後研究資金上限")
                or fields.get("本輪品質門檻後可投入上限")
            ),
        },
        "metrics": {
            "promoted_count": _parse_int(fields.get("正式分析股票")),
            "candidate_supported_ratio": _parse_percent(fields.get("候選公司證據覆蓋率")),
            "exploration_candidate_supported_ratio": _parse_percent(fields.get("探索候選覆蓋率")),
            "formal_confidence_avg": _parse_confidence_value(fields.get("正式股票證據信心"), "平均"),
            "formal_confidence_min": _parse_confidence_value(fields.get("正式股票證據信心"), "最低"),
            "dynamic_source_count": _parse_int(dynamic_source_field),
            "source_unique_publishers": _parse_optional_int(fields.get("來源發布者數")),
            "source_timestamp_coverage": _parse_optional_percent(fields.get("來源時間戳覆蓋率")),
            "source_recent_coverage": _parse_optional_percent(recent_source_field),
            "source_lookback_days": _parse_int(_first_matching_field(fields, r"近\s*(\d+)\s*天來源比例")),
            "discovery_plan_status": _parse_plan_quality_status(fields.get("拆解任務品質")),
            "discovery_plan_score": _parse_plan_quality_score(fields.get("拆解任務品質")),
            "llm_analysis_status": _parse_llm_status(llm_field),
            "market_coverage": _parse_percent(fields.get("股價資料覆蓋率")),
            "monthly_revenue_coverage": _parse_percent(fields.get("月營收資料覆蓋率")),
            "valuation_coverage": _parse_percent(fields.get("估值資料覆蓋率")),
            "market_stale_count": _parse_stale_metric_count(fields.get("快取救援資料"), "股價"),
            "monthly_revenue_stale_count": _parse_stale_metric_count(fields.get("快取救援資料"), "月營收"),
            "financial_metrics_stale_ticker_count": _parse_stale_metric_count(fields.get("快取救援資料"), "五年財務"),
            "valuation_stale_count": _parse_stale_metric_count(fields.get("快取救援資料"), "估值"),
            "leading_signal_coverage": _parse_optional_percent(
                fields.get("近況訊號覆蓋率") or fields.get("領先訊號覆蓋率")
            ),
            "company_filing_coverage": _parse_optional_percent(fields.get("公司公開文件覆蓋率")),
        },
        "recommendation": fields.get("系統判斷", "目前無足夠數據判斷。"),
    }


def _markdown_section(markdown: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)", markdown, flags=re.S | re.M)
    return (match.group("body").strip() if match else "")


def _split_issue_field(value: str | None) -> list[str]:
    if not value or value == "無":
        return []
    return [item.strip() for item in value.split("；") if item.strip()]


def _first_matching_field(fields: dict[str, str], pattern: str) -> str | None:
    for key in fields:
        match = re.search(pattern, key)
        if match:
            return match.group(1) if match.groups() else key
    return None


def _first_matching_value(fields: dict[str, str], pattern: str) -> str | None:
    for key, value in fields.items():
        if re.search(pattern, key):
            return value
    return None


def _parse_int(value: str | None) -> int:
    if not value:
        return 0
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else 0


def _parse_optional_int(value: str | None) -> int | None:
    if not value or value == "未評估":
        return None
    return _parse_int(value)


def _parse_stale_metric_count(value: str | None, label: str) -> int:
    if not value:
        return 0
    match = re.search(rf"{re.escape(label)}\s*(\d+)\s*檔", value)
    return int(match.group(1)) if match else 0


def _parse_percent(value: str | None) -> float:
    parsed = _parse_optional_percent(value)
    return parsed if parsed is not None else 0


def _parse_optional_percent(value: str | None) -> float | None:
    if not value or value == "未評估":
        return None
    match = re.search(r"(-?\d+(?:\.\d+)?)%", value)
    return float(match.group(1)) / 100 if match else None


def _parse_confidence_value(value: str | None, label: str) -> float | None:
    if not value or "未評估" in value:
        return None
    match = re.search(rf"{re.escape(label)}\s*(?:高|中|低)?\s*(\d+(?:\.\d+)?)", value)
    return float(match.group(1)) if match else None


def _parse_plan_quality_status(value: str | None) -> str | None:
    if not value or value == "未評估":
        return None
    if "完整" in value:
        return "ready"
    if "需補強" in value:
        return "caution"
    if "不足" in value:
        return "insufficient"
    return "unknown"


def _parse_plan_quality_score(value: str | None) -> int | None:
    if not value or value == "未評估":
        return None
    match = re.search(r"(\d+)\s*分", value)
    return int(match.group(1)) if match else None


def _parse_llm_status(value: str | None) -> str | None:
    if not value or value == "未評估":
        return None
    if "退回規則引擎" in value or "呼叫失敗" in value:
        return "fallback"
    if "已啟用" in value:
        return "enabled"
    return None


def _parse_amount(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None


def render_quality_action_guard_markdown(quality_gate: dict) -> str:
    status = quality_gate.get("status")
    if status == "ready":
        return ""
    action_policy = quality_gate.get("action_policy") or {}
    amount = action_policy.get("max_deployable_amount")
    amount_line = (
        f"- 品質門檻後本輪研究資金上限：{int(amount):,} 元；此數字不是買進指令，且優先於後續摘要或表格中的一般資金上限。"
        if amount is not None
        else "- 品質門檻後本輪研究資金上限以本段限制為準，優先於後續摘要或表格中的一般資金上限。"
    )
    if status == "insufficient":
        return "\n".join(
            [
                "## 投資行動限制",
                "- 本次報告品質狀態為「資料不足」。",
                amount_line,
                "- 所有個股結論自動降級為「觀察 / 補資料」，不得視為買入清單。",
                "- 若報告其他章節出現目前情境升值分或可研究字樣，僅代表研究線索，不代表可投入資金。",
                "- 下一步應先補齊阻擋項，再重新執行分析。",
            ]
        )
    return "\n".join(
        [
            "## 投資行動限制",
            "- 本次報告品質狀態為「需謹慎判讀」。",
            amount_line,
            "- 可保留觀察名單，但不應直接轉成買入或加碼指令。",
            "- 需先人工覆核警示項，確認資料缺口不影響核心投資假設。",
        ]
    )


def remove_quality_gate_sections(markdown: str) -> str:
    return re.sub(
        r"\n*## (報告品質門檻|投資行動限制)\n.*?(?=\n## |\Z)",
        "",
        markdown,
        flags=re.S,
    ).strip()


def attach_quality_gate_to_report(response: ReportResponse, quality_gate: dict) -> ReportResponse:
    quality_section = render_quality_gate_markdown(quality_gate)
    action_guard = render_quality_action_guard_markdown(quality_gate)
    inserted_sections = quality_section if not action_guard else f"{quality_section}\n\n{action_guard}"
    markdown = remove_quality_gate_sections(response.markdown)
    first_section = markdown.find("\n## ")
    if first_section == -1:
        markdown = f"{markdown.rstrip()}\n\n{inserted_sections}"
    else:
        markdown = f"{markdown[:first_section].rstrip()}\n\n{inserted_sections}\n{markdown[first_section:]}"
    return response.model_copy(update={"markdown": markdown, "quality_gate": quality_gate})
